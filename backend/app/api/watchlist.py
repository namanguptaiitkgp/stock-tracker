import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes as sa_attributes

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.investment_decision import InvestmentDecision
from app.models.news_sentiment import NewsSentimentCache
from app.models.user import User
from app.models.review_alert import ReviewAlert
from app.models.watchlist import (
    Watchlist,
    WatchlistItem,
    WatchlistJournalEntry,
    WatchlistValuationSnapshot,
)
from app.services.fundamentals_service import (
    get_cached_fundamentals_bulk,
    refresh_fundamentals_bulk,
    serialize as serialize_fund,
)
from app.services.stock_resolver import parse_upload, resolve_and_match

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_TYPES = {
    "text/csv", "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "image/png", "image/jpeg", "image/jpg", "image/webp",
}
MAX_FILE_SIZE = 10 * 1024 * 1024


class CreateWatchlistRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateWatchlistRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class AddStockRequest(BaseModel):
    symbol: str
    name: str | None = None
    exchange: str = "NSE"
    reason: str | None = None


class BulkAddRequest(BaseModel):
    stocks: list[AddStockRequest]


class UploadResolveResponse(BaseModel):
    matched: list[dict]
    errors: list[dict]
    raw_extracted: list[str]


# --- Watchlist CRUD ---

@router.get("/")
async def get_watchlists(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(select(Watchlist).where(Watchlist.user_id == user.id))
    watchlists = result.scalars().all()

    if not watchlists:
        default = Watchlist(user_id=user.id, name="Default", description="Default watchlist")
        db.add(default)
        await db.commit()
        await db.refresh(default)
        watchlists = [default]

    out = []
    for wl in watchlists:
        items_result = await db.execute(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
        )
        items = items_result.scalars().all()
        out.append({
            "id": wl.id,
            "name": wl.name,
            "description": wl.description,
            "is_system": wl.is_system,
            "stock_count": len(items),
            "stocks": [
                {
                    "id": item.id,
                    "symbol": item.symbol,
                    "name": item.name,
                    "exchange": item.exchange,
                }
                for item in items
            ],
        })

    return out


@router.post("/")
async def create_watchlist(
    body: CreateWatchlistRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    wl = Watchlist(user_id=user.id, name=body.name, description=body.description)
    db.add(wl)
    await db.commit()
    await db.refresh(wl)
    return {"id": wl.id, "name": wl.name, "description": wl.description, "stock_count": 0, "stocks": []}


@router.put("/{watchlist_id}")
async def update_watchlist(
    watchlist_id: int,
    body: UpdateWatchlistRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    wl = await _get_user_watchlist(watchlist_id, user.id, db)
    if body.name is not None:
        wl.name = body.name
    if body.description is not None:
        wl.description = body.description
    await db.commit()
    return {"id": wl.id, "name": wl.name, "description": wl.description}


@router.delete("/{watchlist_id}")
async def delete_watchlist(
    watchlist_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    wl = await _get_user_watchlist(watchlist_id, user.id, db)
    await db.delete(wl)
    await db.commit()
    return {"status": "deleted"}


# --- Aggregated all-watchlists view ---

# IMPORTANT: this route MUST be declared BEFORE the
# `/{watchlist_id}/detail` handler below. FastAPI matches routes in
# declaration order; if `/{watchlist_id}/detail` came first, the literal
# string "all" would be captured as a `watchlist_id` path param and the
# aggregated handler would never run.
@router.get("/all/detail")
async def get_all_watchlists_detail(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregated view across every watchlist the user owns.

    Returns one row per *distinct symbol* — when the same symbol lives in
    multiple watchlists, `memberships` lists all of them and `id` resolves
    to the most-recently-created WatchlistItem (so PATCHing journal /
    rules / lane on the response acts on a single coherent row).
    """
    from app.services.market.fno_universe import get_fno_sets

    # All watchlists owned by the user
    wls_res = await db.execute(
        select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.created_at)
    )
    watchlists_list = list(wls_res.scalars().all())
    if not watchlists_list:
        return {
            "id": None, "name": "All watchlists", "description": None,
            "stock_count": 0, "missing_fundamentals": 0, "stocks": [],
            "watchlists": [],
        }
    wl_ids = [w.id for w in watchlists_list]
    wl_by_id = {w.id: w for w in watchlists_list}

    # All items across those watchlists, newest-first so dedup keeps the freshest item id.
    items_res = await db.execute(
        select(WatchlistItem)
        .where(WatchlistItem.watchlist_id.in_(wl_ids))
        .order_by(WatchlistItem.created_at.desc())
    )
    all_items = list(items_res.scalars().all())

    # Build symbol -> primary item + membership list
    primary_by_symbol: dict[str, WatchlistItem] = {}
    memberships_rich: dict[str, list[dict]] = {}
    memberships_flat: dict[str, list[str]] = {}
    for it in all_items:
        sym = (it.symbol or "").upper()
        if not sym:
            continue
        if sym not in primary_by_symbol:
            primary_by_symbol[sym] = it
        wl = wl_by_id.get(it.watchlist_id)
        wl_name = wl.name if wl else "Unknown"
        memberships_rich.setdefault(sym, []).append({
            "name": wl_name,
            "watchlist_id": it.watchlist_id,
            "lane": it.lane or "researching",
            "item_id": it.id,
        })
        memberships_flat.setdefault(sym, []).append(wl_name)

    symbols = list(primary_by_symbol.keys())
    fundamentals_map = await get_cached_fundamentals_bulk(symbols, db) if symbols else {}
    nse_fno, bse_fno = await get_fno_sets()

    # Pending alerts per-symbol
    alerts_res = await db.execute(
        select(ReviewAlert)
        .where(ReviewAlert.user_id == user.id, ReviewAlert.status == "pending")
        .where(ReviewAlert.source.in_(("watchlist", "both")))
    )
    alerts_by_symbol: dict[str, list[dict]] = {}
    for alert in alerts_res.scalars().all():
        alerts_by_symbol.setdefault(alert.symbol.upper(), []).append({
            "id": alert.id,
            "trigger_type": alert.trigger_type,
            "trigger_label": alert.trigger_label,
            "suggested_action": alert.suggested_action,
            "suggested_lane": alert.suggested_lane,
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
        })

    # Batched verdict + sentiment lookups (DISTINCT ON keeps the latest per-symbol)
    decisions_by_symbol: dict[str, InvestmentDecision] = {}
    sentiments_by_symbol: dict[str, NewsSentimentCache] = {}
    if symbols:
        from sqlalchemy import desc as _desc
        d_res = await db.execute(
            select(InvestmentDecision)
            .where(InvestmentDecision.user_id == user.id, InvestmentDecision.symbol.in_(symbols))
            .order_by(InvestmentDecision.symbol, _desc(InvestmentDecision.created_at))
            .distinct(InvestmentDecision.symbol)
        )
        for d in d_res.scalars().all():
            decisions_by_symbol[d.symbol] = d
        s_res = await db.execute(
            select(NewsSentimentCache)
            .where(NewsSentimentCache.symbol.in_(symbols))
            .order_by(NewsSentimentCache.symbol, NewsSentimentCache.analyzed_at.desc())
            .distinct(NewsSentimentCache.symbol)
        )
        for s in s_res.scalars().all():
            sentiments_by_symbol[s.symbol] = s

    # Batch evaluate fundamental analysis once per (user, rule_set,
    # snapshot table) — avoids N+1 snapshot lookups per stock.
    from app.services import fundamental_analysis as fa_svc
    fa_map = await fa_svc.evaluate_batch(db, user.id, list(primary_by_symbol.keys()))

    # Pull StockAnalysis + peer-set age for the 3-section grid on
    # ResearchingCard (mirrors today.py portfolio-brief shape). Single
    # batched queries keep this O(1) DB round-trips.
    from app.models.stock_analysis import StockAnalysis
    from app.models.stock_peers import StockPeer
    from sqlalchemy import func as sa_func
    analyses_by_symbol: dict[str, StockAnalysis] = {}
    peer_age_by_symbol: dict[str, datetime] = {}
    if symbols:
        sa_res = await db.execute(
            select(StockAnalysis).where(StockAnalysis.symbol.in_(symbols))
        )
        analyses_by_symbol = {a.symbol: a for a in sa_res.scalars().all()}
        pa_res = await db.execute(
            select(StockPeer.symbol, sa_func.max(StockPeer.updated_at))
            .where(StockPeer.symbol.in_(symbols))
            .group_by(StockPeer.symbol)
        )
        peer_age_by_symbol = {sym: ts for sym, ts in pa_res.all()}

    stocks_out = []
    missing_fundamentals = 0
    for sym, item in primary_by_symbol.items():
        fund = fundamentals_map.get(sym)
        fund_data = serialize_fund(fund) if fund else None
        if fund_data is None:
            missing_fundamentals += 1
        verdict_rec = decisions_by_symbol.get(item.symbol)
        sent_rec = sentiments_by_symbol.get(item.symbol)
        fa_v = fa_map.get(sym.upper())
        sa = analyses_by_symbol.get(sym)

        valuation_section = None
        peer_section = None
        news_section = None
        if sa:
            valuation_section = {
                "verdict": sa.valuation_verdict,
                "score": float(sa.valuation_score) if sa.valuation_score is not None else None,
                "signals": sa.valuation_signals,
                "hard_failed": sa.valuation_hard_failed,
                "last_run_at": sa.valuation_last_run_at.isoformat() if sa.valuation_last_run_at else None,
            }
            peer_section = {
                "verdict": sa.peer_verdict,
                "metric_breakdown": sa.peer_metric_breakdown,
                "peer_summary": sa.peer_summary,
                "peer_count": sa.peer_count,
                "peer_set_weak": sa.peer_set_weak,
                "last_run_at": sa.peer_last_run_at.isoformat() if sa.peer_last_run_at else None,
                "peers_generated_at": (
                    peer_age_by_symbol[sym].isoformat()
                    if peer_age_by_symbol.get(sym) else None
                ),
            }
            news_section = {
                "verdict": sa.news_verdict,
                "stock_signals": sa.news_stock_signals,
                "source_count": sa.news_source_count,
                "qualitative": sa.news_qualitative,
                "sector": (fund.sector if fund else None),
                "last_run_at": sa.news_last_run_at.isoformat() if sa.news_last_run_at else None,
                # Latest analyzed_at on the per-symbol sentiment row is the
                # honest "freshness" anchor for this card.
                "newest_headline_at": (
                    sent_rec.analyzed_at.isoformat()
                    if sent_rec and sent_rec.analyzed_at else None
                ),
            }

        stocks_out.append({
            "id": item.id,
            "symbol": item.symbol,
            "name": item.name or (fund.name if fund else None),
            "exchange": item.exchange,
            "fundamentals": fund_data,
            "fundamental_analysis": (
                {
                    "verdict": fa_v.verdict, "score": fa_v.score,
                    "rules_passed": fa_v.rules_passed, "rules_failed": fa_v.rules_failed,
                    "rules_missing": fa_v.rules_missing,
                    "snapshot_fetched_at": fa_v.snapshot_fetched_at.isoformat() if fa_v.snapshot_fetched_at else None,
                }
                if fa_v else None
            ),
            "in_watchlists": memberships_flat.get(sym, []),
            "verdict": verdict_rec.verdict if verdict_rec else None,
            "verdict_confidence": verdict_rec.confidence if verdict_rec else None,
            "decision_json": (verdict_rec.result_json if verdict_rec else None),
            "decision_at": (
                verdict_rec.created_at.isoformat()
                if verdict_rec and verdict_rec.created_at
                else None
            ),
            "news_sentiment": sent_rec.sentiment if sent_rec else None,
            "news_score": sent_rec.score if sent_rec else None,
            "reason_tag": item.notes,
            "has_nse_fno": sym in nse_fno,
            "has_bse_fno": sym in bse_fno,
            "watching_since": item.created_at.isoformat() if item.created_at else None,
            "reason": item.reason,
            "pe_target": float(item.pe_target) if item.pe_target is not None else None,
            "price_target": float(item.price_target) if item.price_target is not None else None,
            "peer_symbols": item.peer_symbols or [],
            "watch_rules": item.watch_rules or [],
            "lane": item.lane or "researching",
            "memberships": memberships_rich.get(sym, []),
            "triggered_alerts": alerts_by_symbol.get(sym, []),
            # 3-section grid data (Price / Peers / News) — same shape
            # as today.py portfolio holding items.
            "valuation_section": valuation_section,
            "peer_section": peer_section,
            "news_section": news_section,
        })

    # On-demand peer warmup for symbols with no peers yet. Idempotent
    # (ensure_peers short-circuits when ≥2 stored peers exist). Fire and
    # forget — the API response returns immediately; peers materialize
    # within ~30-60s and the card picks them up on next reload.
    try:
        from app.tasks.peer_warmup_task import warm_peers_for_symbol
        for sym in symbols:
            if sym not in peer_age_by_symbol:
                warm_peers_for_symbol.delay(sym, user.id)
    except Exception as e:  # pragma: no cover — best-effort
        logger.warning("watchlist /all/detail: peer warmup dispatch failed: %s", e)

    return {
        "id": None,
        "name": "All watchlists",
        "description": None,
        "stock_count": len(stocks_out),
        "missing_fundamentals": missing_fundamentals,
        "stocks": stocks_out,
        # Caller uses this list to populate the watchlist picker dropdown.
        # stock_count is the number of items in that specific watchlist
        # (NOT distinct symbols across watchlists), so the picker can show
        # live counts without an extra round-trip.
        "watchlists": [
            {
                "id": w.id,
                "name": w.name,
                "description": w.description,
                "stock_count": sum(1 for it in all_items if it.watchlist_id == w.id),
            }
            for w in watchlists_list
        ],
    }


# --- Detailed watchlist with fundamentals ---

@router.get("/{watchlist_id}/detail")
async def get_watchlist_detail(
    watchlist_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.market.fno_universe import get_fno_sets

    wl = await _get_user_watchlist(watchlist_id, user.id, db)
    nse_fno, bse_fno = await get_fno_sets()

    items_result = await db.execute(
        select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
    )
    items = items_result.scalars().all()

    symbols = [item.symbol for item in items]
    # Fast path: read only from DB cache. User can click "Refresh" to fetch fresh.
    fundamentals_map = await get_cached_fundamentals_bulk(symbols, db) if symbols else {}

    # Get all user watchlists to compute memberships
    all_watchlists_result = await db.execute(
        select(Watchlist).where(Watchlist.user_id == user.id)
    )
    all_wls = all_watchlists_result.scalars().all()

    all_items_result = await db.execute(
        select(WatchlistItem).join(Watchlist).where(Watchlist.user_id == user.id)
    )
    all_items = all_items_result.scalars().all()

    # symbol -> list of watchlist names (legacy, kept for compat)
    memberships: dict[str, list[str]] = {}
    # symbol -> list of {name, lane} (richer)
    memberships_rich: dict[str, list[dict]] = {}
    wl_by_id = {w.id: w.name for w in all_wls}
    for it in all_items:
        memberships.setdefault(it.symbol, []).append(wl_by_id.get(it.watchlist_id, "Unknown"))
        memberships_rich.setdefault(it.symbol, []).append({
            "name": wl_by_id.get(it.watchlist_id, "Unknown"),
            "lane": it.lane or "researching",
        })

    # Pending review alerts per symbol (from review_alerts table)
    alerts_res = await db.execute(
        select(ReviewAlert)
        .where(ReviewAlert.user_id == user.id, ReviewAlert.status == "pending")
        .where(ReviewAlert.source.in_(("watchlist", "both")))
    )
    alerts_by_symbol: dict[str, list[dict]] = {}
    for alert in alerts_res.scalars().all():
        alerts_by_symbol.setdefault(alert.symbol.upper(), []).append({
            "id": alert.id,
            "trigger_type": alert.trigger_type,
            "trigger_label": alert.trigger_label,
            "suggested_action": alert.suggested_action,
            "suggested_lane": alert.suggested_lane,
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
        })

    # Batch evaluate fundamental analysis for every watchlist item.
    from app.services import fundamental_analysis as fa_svc
    fa_map = await fa_svc.evaluate_batch(db, user.id, [it.symbol for it in items])

    stocks_out = []
    missing_fundamentals = 0
    for item in items:
        fund = fundamentals_map.get(item.symbol.upper())
        fund_data = serialize_fund(fund) if fund else None
        if fund_data is None:
            missing_fundamentals += 1

        # Look up latest verdict
        verdict_result = await db.execute(
            select(InvestmentDecision)
            .where(InvestmentDecision.user_id == user.id, InvestmentDecision.symbol == item.symbol)
            .order_by(InvestmentDecision.created_at.desc())
            .limit(1)
        )
        verdict_rec = verdict_result.scalar_one_or_none()

        # Look up latest sentiment
        sent_result = await db.execute(
            select(NewsSentimentCache)
            .where(NewsSentimentCache.symbol == item.symbol)
            .order_by(NewsSentimentCache.analyzed_at.desc())
            .limit(1)
        )
        sent_rec = sent_result.scalar_one_or_none()

        symbol_u = (item.symbol or "").upper()
        fa_v = fa_map.get(symbol_u)
        stocks_out.append({
            "id": item.id,
            "symbol": item.symbol,
            "name": item.name or (fund.name if fund else None),
            "exchange": item.exchange,
            "fundamentals": fund_data,
            "fundamental_analysis": (
                {
                    "verdict": fa_v.verdict, "score": fa_v.score,
                    "rules_passed": fa_v.rules_passed, "rules_failed": fa_v.rules_failed,
                    "rules_missing": fa_v.rules_missing,
                    "snapshot_fetched_at": fa_v.snapshot_fetched_at.isoformat() if fa_v.snapshot_fetched_at else None,
                }
                if fa_v else None
            ),
            "in_watchlists": memberships.get(item.symbol, [wl.name]),
            "verdict": verdict_rec.verdict if verdict_rec else None,
            "verdict_confidence": verdict_rec.confidence if verdict_rec else None,
            # Full AI verdict payload for the Researching card's Fundamentals
            # section (summary + key_risks + action_items + valuation_view).
            "decision_json": (verdict_rec.result_json if verdict_rec else None),
            "decision_at": (
                verdict_rec.created_at.isoformat()
                if verdict_rec and verdict_rec.created_at
                else None
            ),
            "news_sentiment": sent_rec.sentiment if sent_rec else None,
            "news_score": sent_rec.score if sent_rec else None,
            "reason_tag": item.notes,
            "has_nse_fno": symbol_u in nse_fno,
            "has_bse_fno": symbol_u in bse_fno,
            # Researching-card fields
            "watching_since": item.created_at.isoformat() if item.created_at else None,
            "reason": item.reason,
            "pe_target": float(item.pe_target) if item.pe_target is not None else None,
            "price_target": float(item.price_target) if item.price_target is not None else None,
            "peer_symbols": item.peer_symbols or [],
            "watch_rules": item.watch_rules or [],
            "lane": item.lane or "researching",
            "memberships": memberships_rich.get(item.symbol, [{"name": wl.name, "lane": item.lane or "researching"}]),
            "triggered_alerts": alerts_by_symbol.get(item.symbol.upper(), []),
        })

    return {
        "id": wl.id,
        "name": wl.name,
        "description": wl.description,
        "stock_count": len(stocks_out),
        "missing_fundamentals": missing_fundamentals,
        "stocks": stocks_out,
    }


@router.post("/{watchlist_id}/refresh-fundamentals")
async def refresh_watchlist_fundamentals(
    watchlist_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    only_stale: bool = False,
) -> dict:
    wl = await _get_user_watchlist(watchlist_id, user.id, db)
    items_result = await db.execute(
        select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
    )
    symbols = [item.symbol for item in items_result.scalars().all()]
    return await refresh_fundamentals_bulk(symbols, db, only_stale=only_stale)


# --- Stock CRUD ---

@router.post("/{watchlist_id}/stocks")
async def add_stock(
    watchlist_id: int,
    body: AddStockRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    wl = await _get_user_watchlist(watchlist_id, user.id, db)

    existing = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id,
            WatchlistItem.symbol == body.symbol.upper(),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"{body.symbol} already in watchlist")

    item = WatchlistItem(
        watchlist_id=wl.id,
        symbol=body.symbol.upper(),
        name=body.name,
        exchange=body.exchange,
        notes=body.reason,
    )
    db.add(item)
    await db.commit()

    # Fire peer warmup async so the user's first stock-detail view shows
    # a fully populated peer set (Gemini + industry/sector fallback). Cheap
    # no-op when peers already exist (e.g. stock is a peer of another holding).
    try:
        from app.tasks.peer_warmup_task import warm_peers_for_symbol
        warm_peers_for_symbol.delay(item.symbol, user.id)
    except Exception as e:
        logger.warning(f"watchlist.add_stock: peer warmup dispatch failed for {item.symbol}: {e}")

    return {"status": "added", "symbol": item.symbol}


@router.post("/{watchlist_id}/stocks/bulk")
async def bulk_add_stocks(
    watchlist_id: int,
    body: BulkAddRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    wl = await _get_user_watchlist(watchlist_id, user.id, db)

    added = []
    skipped = []

    for stock in body.stocks:
        existing = await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.watchlist_id == wl.id,
                WatchlistItem.symbol == stock.symbol.upper(),
            )
        )
        if existing.scalar_one_or_none():
            skipped.append(stock.symbol.upper())
            continue

        item = WatchlistItem(
            watchlist_id=wl.id,
            symbol=stock.symbol.upper(),
            name=stock.name,
            exchange=stock.exchange,
            notes=stock.reason,
        )
        db.add(item)
        added.append(stock.symbol.upper())

    await db.commit()

    # Fire peer warmup for each newly added symbol (idempotent).
    if added:
        try:
            from app.tasks.peer_warmup_task import warm_peers_for_symbol
            for sym in added:
                warm_peers_for_symbol.delay(sym, user.id)
        except Exception as e:
            logger.warning(f"watchlist.bulk_add: peer warmup dispatch failed: {e}")

    return {"added": added, "skipped": skipped}


@router.delete("/{watchlist_id}/stocks/{item_id}")
async def remove_stock(
    watchlist_id: int,
    item_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    wl = await _get_user_watchlist(watchlist_id, user.id, db)
    result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.id == item_id,
            WatchlistItem.watchlist_id == wl.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Stock not found in watchlist")
    await db.delete(item)
    await db.commit()
    return {"status": "removed", "symbol": item.symbol}


# ────────── Researching-card item edits + journal + valuation history ──────────

class WatchRulePayload(BaseModel):
    """Validated shape for a single watch rule. Kept in sync with
    SUPPORTED_RULE_TYPES in services/review_alerts.py — see _check_watch_rules
    for firing semantics.

    `operator` is meaningful for `pe` and `pb` (where the user picks
    above/below explicitly); the other types have an implicit operator (e.g.
    `pct_from_52w_high` always means "fall by N% from peak", `single_day_drop`
    is "today's drop ≥ N%"). Missing operator is allowed and stored as null.

    `check_frequency` controls whether this rule is evaluated by the daily
    16:40 IST beat task only (`daily`) or also by the intraday beat task
    that runs every 15 min during market hours (`hourly`, `15min`). Only
    `single_day_drop` and `price_below` are evaluated intraday — slower
    fundamentals like `pe` / `pct_from_52w_high` always come from the daily
    snapshot regardless of the frequency picked.
    """

    type: Literal[
        "pct_from_52w_high",
        "pe",
        "pb",
        "single_day_drop",
        "price_below",
        # Legacy aliases — accepted on read so older rows keep firing, but
        # new clients should write the canonical names above.
        "pe_below",
        "pe_above",
    ]
    value: float
    operator: Literal["lte", "gte", "eq"] | None = None
    label: str | None = None
    check_frequency: Literal["daily", "hourly", "15min"] = "daily"


class WatchlistItemPatch(BaseModel):
    reason: str | None = None
    pe_target: float | None = None
    price_target: float | None = None
    peer_symbols: list[str] | None = None
    watch_rules: list[WatchRulePayload] | None = None
    lane: str | None = None
    notes: str | None = None


async def _get_user_item(item_id: int, user_id: int, db: AsyncSession) -> WatchlistItem:
    res = await db.execute(
        select(WatchlistItem)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(WatchlistItem.id == item_id, Watchlist.user_id == user_id)
    )
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return item


@router.patch("/items/{item_id}")
async def patch_watchlist_item(
    item_id: int,
    body: WatchlistItemPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await _get_user_item(item_id, user.id, db)
    if body.reason is not None: item.reason = body.reason
    if body.pe_target is not None: item.pe_target = body.pe_target
    if body.price_target is not None: item.price_target = body.price_target
    if body.peer_symbols is not None: item.peer_symbols = body.peer_symbols
    if body.watch_rules is not None:
        # Persist the validated dicts (drops any unknown keys clients try to sneak in).
        item.watch_rules = [r.model_dump() for r in body.watch_rules]
        # SQLAlchemy doesn't auto-detect mutations on JSON columns when the
        # caller assigns a brand-new list; flag the attr so the diff lands.
        sa_attributes.flag_modified(item, "watch_rules")
    if body.lane is not None: item.lane = body.lane
    if body.notes is not None: item.notes = body.notes
    await db.commit()
    return {"ok": True, "id": item.id}


class JournalEntryCreate(BaseModel):
    body: str


@router.get("/items/{item_id}/journal")
async def list_journal(
    item_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await _get_user_item(item_id, user.id, db)
    res = await db.execute(
        select(WatchlistJournalEntry)
        .where(WatchlistJournalEntry.watchlist_item_id == item_id)
        .order_by(WatchlistJournalEntry.created_at.desc())
        .limit(50)
    )
    rows = res.scalars().all()
    entries = [
        {
            "id": e.id,
            "body": e.body,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "kind": "journal",
        }
        for e in rows
    ]

    # Also surface the user's global StockNote for this symbol as a
    # synthetic journal entry, so notes added from the Stock Detail panel
    # appear on the Researching card too. Negative id keeps it distinct
    # from real journal rows; the frontend treats `kind="note"` as
    # read-only here (editing happens via /api/notes/{symbol}).
    from app.models.note import StockNote
    note_res = await db.execute(
        select(StockNote).where(
            StockNote.user_id == user.id,
            StockNote.symbol == item.symbol,
        )
    )
    note = note_res.scalar_one_or_none()
    if note and (note.content or "").strip():
        entries.insert(0, {
            "id": -note.id,
            "body": f"[Note] {note.content[:4000]}",
            "created_at": (note.updated_at or note.created_at).isoformat() if (note.updated_at or note.created_at) else None,
            "kind": "note",
        })
        # Re-sort newest first now that we've spliced the note in.
        entries.sort(key=lambda e: e["created_at"] or "", reverse=True)

    return {"entries": entries, "count": len(entries)}


@router.post("/items/{item_id}/journal")
async def add_journal(
    item_id: int,
    body: JournalEntryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_user_item(item_id, user.id, db)
    text = (body.body or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty journal entry")
    entry = WatchlistJournalEntry(
        watchlist_item_id=item_id, body=text[:4000], user_id=user.id
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {
        "id": entry.id,
        "body": entry.body,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@router.delete("/items/{item_id}/journal/{entry_id}")
async def delete_journal(
    item_id: int,
    entry_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_user_item(item_id, user.id, db)
    res = await db.execute(
        select(WatchlistJournalEntry).where(
            WatchlistJournalEntry.id == entry_id,
            WatchlistJournalEntry.watchlist_item_id == item_id,
        )
    )
    e = res.scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    await db.delete(e)
    await db.commit()
    return {"ok": True}


@router.get("/items/{item_id}/valuation-history")
async def valuation_history(
    item_id: int,
    days: int = 90,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Daily valuation snapshots (PE, PB, % from 52w high) — most recent first."""
    await _get_user_item(item_id, user.id, db)
    res = await db.execute(
        select(WatchlistValuationSnapshot)
        .where(WatchlistValuationSnapshot.watchlist_item_id == item_id)
        .order_by(WatchlistValuationSnapshot.snapshot_date.desc())
        .limit(max(1, min(days, 365)))
    )
    rows = res.scalars().all()
    return {
        "snapshots": [
            {
                "date": s.snapshot_date.isoformat(),
                "cmp": s.cmp,
                "pe_ratio": s.pe_ratio,
                "pb_ratio": s.pb_ratio,
                "pct_from_52w_high": s.pct_from_52w_high,
                "pct_from_52w_low": s.pct_from_52w_low,
                "high_52w": s.high_52w,
                "low_52w": s.low_52w,
            }
            for s in rows
        ],
    }


@router.post("/items/{item_id}/research")
async def aggressive_research(
    item_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggressive news research for a watchlist item — fetches headlines for the
    stock + named peers, sends to Gemini for a structured bullet-point analysis.
    The result is appended to the journal so the long-term view accumulates.
    """
    import asyncio
    import json
    from app.ai.gemini_client import call_gemini_with_rotation
    from app.ai.credential_rotation import NoCredentialsConfiguredError, AllCredentialsExhaustedError
    from app.services.news_sentiment import fetch_google_news_custom

    item = await _get_user_item(item_id, user.id, db)

    queries: list[tuple[str, str]] = [(item.symbol, f"{item.symbol} {item.name or ''}".strip())]
    for peer in (item.peer_symbols or []):
        if isinstance(peer, str) and peer.strip():
            queries.append((peer.strip().upper(), peer.strip()))

    fetches = await asyncio.gather(
        *(fetch_google_news_custom(q[1], days=7) for q in queries),
        return_exceptions=True,
    )

    by_symbol: dict[str, list[dict]] = {}
    for (sym, _), res in zip(queries, fetches):
        if isinstance(res, Exception) or not res:
            by_symbol[sym] = []
        else:
            by_symbol[sym] = res[:8]

    # Build prompt
    blocks: list[str] = []
    for sym, headlines in by_symbol.items():
        if not headlines:
            blocks.append(f"### {sym}\n(no headlines)")
            continue
        lines = [f"- [{h.get('date') or '?'}] {h.get('title')} ({h.get('source') or '?'})" for h in headlines]
        blocks.append(f"### {sym}\n" + "\n".join(lines))

    prompt = f"""You are an equity research analyst. The user is researching {item.symbol} ({item.name or ''}).
{f"Their thesis: {item.reason}" if item.reason else ""}

Below are recent headlines for {item.symbol} and its named peers. Synthesize a comprehensive analysis.

{chr(10).join(blocks)}

Return a JSON object only — no prose, no fences:
{{
  "thesis_check": "1-2 sentences: does the recent news support or challenge the user's thesis?",
  "tailwinds": ["bullet 1", "bullet 2", "..."],
  "headwinds": ["bullet 1", "..."],
  "peer_dynamics": ["bullet — how peers are doing relative to {item.symbol}", "..."],
  "watch_items": ["specific catalyst/event/data to watch over the next 4-8 weeks", "..."],
  "summary": "2-3 sentence executive summary"
}}

Rules:
- Use 3-5 bullets per array, max 8.
- Each bullet must be traceable to at least one headline above.
- Be specific — name the catalyst or risk.
"""

    raw = await call_gemini_with_rotation(user.id, db, prompt)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(cleaned)
    except Exception:
        raise HTTPException(status_code=502, detail="Gemini returned non-JSON response")

    # Append a journal entry summarising this research
    summary = parsed.get("summary") or parsed.get("thesis_check") or ""
    body_text = f"[Research · {item.symbol} + {len(queries)-1} peers]\n{summary}".strip()
    if body_text:
        entry = WatchlistJournalEntry(
            watchlist_item_id=item.id, body=body_text[:4000], user_id=user.id
        )
        db.add(entry)
        await db.commit()

    return {
        "symbol": item.symbol,
        "peers": [q[0] for q in queries[1:]],
        "headlines_by_symbol": by_symbol,
        "analysis": parsed,
    }


# --- Upload & Resolve ---

@router.post("/{watchlist_id}/upload")
async def upload_stocks(
    watchlist_id: int,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UploadResolveResponse:
    await _get_user_watchlist(watchlist_id, user.id, db)

    content_type = file.content_type or ""
    filename = file.filename or ""
    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    raw_names = await parse_upload(file_bytes, content_type, filename, user.id, db)

    if not raw_names:
        raise HTTPException(status_code=400, detail="Could not extract any stock names from the file")

    matched, errors = await resolve_and_match(raw_names, user.id, db)

    return UploadResolveResponse(matched=matched, errors=errors, raw_extracted=raw_names)


# --- Helpers ---

async def _get_user_watchlist(watchlist_id: int, user_id: int, db: AsyncSession) -> Watchlist:
    result = await db.execute(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user_id)
    )
    wl = result.scalar_one_or_none()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return wl
