"""News endpoints — unified news inbox + opportunities (News Scan watchlist).

Aggregates RSS sources + BSE filings, classifies via Gemini, and serves to
the frontend with scope/source/keyword filtering.  Also manages the
"News Scan" watchlist for opportunity triage.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem
from app.models.daily_news_report import DailyNewsReport
from app.services.news.inbox_aggregator import (
    available_sources,
    clear_cache as clear_rss_cache,
    fetch_all_news,
    fetch_all_news_with_meta,
)
from app.services.news.inbox_classifier import (
    classify_headlines,
    clear_cache as clear_classifier_cache,
)
from app.services.news.sources.bse_filings import (
    clear_cache as clear_bse_cache,
    fetch_bse_filings,
)
from app.services.news_sentiment import fetch_google_news_custom
from app.services.portfolio_cache import get_holdings as cached_holdings

logger = logging.getLogger(__name__)
router = APIRouter()

async def _get_user_holdings(user: User) -> set[str]:
    if not user.kite_api_key or not user.kite_access_token:
        return set()
    try:
        rows = await cached_holdings(user)
    except Exception as e:
        logger.info(f"holdings fetch failed for inbox scope: {e}")
        return set()
    from app.services.portfolio_cache import holding_total_qty
    symbols = {(r.get("tradingsymbol") or "").upper() for r in rows if holding_total_qty(r) > 0}
    symbols.discard("")
    return symbols


async def _get_user_watched(user: User, db: AsyncSession) -> set[str]:
    result = await db.execute(
        select(WatchlistItem.symbol)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.user_id == user.id)
    )
    return {row[0].upper() for row in result.all() if row[0]}


def _pre_filter_by_symbols(items: list[dict], symbols: set[str]) -> list[dict]:
    """Fast title-based pre-filter BEFORE Gemini classification.

    Checks if any of the user's stock symbols appear in the headline text.
    This is intentionally loose (substring match) to avoid false negatives —
    Gemini will do the precise stock extraction on the smaller set.
    """
    if not symbols:
        return items
    lower_symbols = {s.lower() for s in symbols}
    out: list[dict] = []
    for it in items:
        title_lower = (it.get("title") or "").lower()
        if any(sym in title_lower for sym in lower_symbols):
            out.append(it)
            continue
        existing_stocks = it.get("stocks") or []
        if existing_stocks:
            item_syms = {(s.get("symbol") or "").upper() for s in existing_stocks}
            if item_syms & symbols:
                out.append(it)
    return out


def _apply_filters(
    items: list[dict],
    *,
    scope: str,
    watched: set[str],
    held: set[str],
    sources: Optional[list[str]],
    q: Optional[str],
    sentiment: Optional[str] = None,
) -> list[dict]:
    out: list[dict] = []
    my_stocks = watched | held
    for it in items:
        if scope == "watchlist":
            syms = {(s.get("symbol") or "").upper() for s in (it.get("stocks") or [])}
            if not (syms & watched):
                continue
        elif scope == "holdings":
            syms = {(s.get("symbol") or "").upper() for s in (it.get("stocks") or [])}
            if not (syms & held):
                continue
        elif scope == "mystocks":
            syms = {(s.get("symbol") or "").upper() for s in (it.get("stocks") or [])}
            if not (syms & my_stocks):
                continue
        elif scope.startswith("symbol:"):
            target = scope.split(":", 1)[1].upper()
            syms = {(s.get("symbol") or "").upper() for s in (it.get("stocks") or [])}
            if target not in syms:
                continue

        if sources and it.get("source") not in sources:
            continue

        if q and q.lower() not in it.get("title", "").lower():
            continue

        if sentiment and it.get("sentiment") != sentiment:
            continue

        out.append(it)
    return out


# ── Inbox endpoints ─────────────────────────────────────────────────


@router.get("/inbox")
async def get_inbox(
    scope: str = Query("all"),
    source: Optional[str] = Query(None, description="comma-separated source names"),
    q: Optional[str] = Query(None, description="keyword filter (substring match on title)"),
    sentiment: Optional[str] = Query(None, description="tailwind, headwind, or context"),
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sources_list = [s.strip() for s in source.split(",")] if source else None

    bse_only = sources_list == ["BSE Filings"]

    rss_meta: dict = {}
    if bse_only:
        items = await fetch_bse_filings(days=2)
    elif sources_list and "BSE Filings" in sources_list:
        (rss_items, rss_meta), bse_items = await asyncio.gather(
            fetch_all_news_with_meta(days=1),
            fetch_bse_filings(days=2),
        )
        items = bse_items + rss_items
    else:
        items, rss_meta = await fetch_all_news_with_meta(days=1)

    total_before = len(items)

    watched: set[str] = set()
    held: set[str] = set()
    if scope in ("watchlist", "mystocks"):
        watched = await _get_user_watched(user, db)
    if scope in ("holdings", "mystocks"):
        held = await _get_user_holdings(user)

    if scope in ("watchlist", "holdings", "mystocks"):
        user_symbols = watched | held
        items = _pre_filter_by_symbols(items, user_symbols)

    items = await classify_headlines(items, user.id, db)

    counts: dict[str, int] = {}
    for it in items:
        s = it.get("source") or "Unknown"
        counts[s] = counts.get(s, 0) + 1

    filtered = _apply_filters(
        items, scope=scope, watched=watched, held=held,
        sources=sources_list, q=q, sentiment=sentiment,
    )

    filtered.sort(key=lambda h: h.get("published_at") or "", reverse=True)
    filtered = filtered[:limit]

    return {
        "items": filtered,
        "total": len(filtered),
        "sources_available": available_sources(),
        "source_counts": counts,
        "scope": scope,
        "as_of": datetime.now(tz=timezone.utc).isoformat(),
        "fetched_at": rss_meta.get("fetched_at"),
        "next_refresh_at": rss_meta.get("next_refresh_at"),
        "ttl_seconds": rss_meta.get("ttl_seconds"),
        "pre_filtered": scope != "all",
        "headlines_classified": len(items),
        "headlines_total": total_before,
    }


class SearchRequest(BaseModel):
    q: str
    limit: int = 30


@router.post("/inbox/search")
async def search_inbox(
    body: SearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = (body.q or "").strip()
    if not q:
        return {"items": [], "total": 0, "query": q}

    raw = await fetch_google_news_custom(q, days=3)
    items: list[dict] = []
    for h in raw[:40]:
        items.append({
            "title": h.get("title", ""),
            "url": h.get("url", ""),
            "source": h.get("source") or "Google News",
            "published_at": h.get("date"),
        })
    items = await classify_headlines(items, user.id, db)
    items.sort(key=lambda h: h.get("published_at") or "", reverse=True)
    items = items[: body.limit]

    return {"items": items, "total": len(items), "query": q}


@router.post("/inbox/refresh")
async def refresh_inbox(_user: User = Depends(get_current_user)) -> dict:
    await clear_rss_cache()
    await clear_bse_cache()
    await clear_classifier_cache()
    return {"ok": True}


# ── Opportunities (News Scan watchlist) ──────────────────────────────


OPPORTUNITY_LOOKBACK_DAYS = 7


@router.get("/opportunities")
async def get_opportunities(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return enriched opportunities from the last 7 days of DailyNewsReports."""
    from app.services.market.fno_universe import get_fno_sets
    from app.models.fundamentals import StockFundamentals
    from app.services.fundamentals_service import get_fundamentals

    reports_result = await db.execute(
        select(DailyNewsReport)
        .where(DailyNewsReport.user_id == user.id)
        .order_by(DailyNewsReport.report_date.desc())
        .limit(OPPORTUNITY_LOOKBACK_DAYS)
    )
    reports = reports_result.scalars().all()
    if not reports:
        return {"items": [], "report_date": None}

    latest_report = reports[0]

    dismissed: set[str] = set()
    for r in reports:
        dismissed.update(r.dismissed_json or [])

    held = await _get_user_holdings(user)
    watched = await _get_user_watched(user, db)
    already_tracked = held | watched | dismissed

    nse_fno, bse_fno = await get_fno_sets()

    seen: set[str] = set()
    candidates = []
    for report in reports:
        companies = (report.result_json or {}).get("companies", [])
        for c in companies:
            sym = (c.get("symbol") or "").upper()
            if not sym or sym in already_tracked or sym in seen:
                continue
            seen.add(sym)
            score = c.get("score", 0)
            sentiment = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
            candidates.append({
                "symbol": sym,
                "name": c.get("name", sym),
                "score": score,
                "sentiment": sentiment,
                "summary": (c.get("summary") or "")[:200],
                "headline_count": c.get("headline_count", len(c.get("headlines", []))),
                "discovered_at": report.created_at.isoformat() if report.created_at else None,
                "report_id": report.id,
            })

    candidates.sort(key=lambda x: abs(x.get("score", 0)), reverse=True)
    candidates = candidates[:20]

    if not candidates:
        return {"items": [], "report_date": latest_report.report_date.isoformat()}

    syms = [c["symbol"] for c in candidates]
    fund_result = await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol.in_(syms))
    )
    fund_map = {f.symbol: f for f in fund_result.scalars().all()}

    missing = [s for s in syms if s not in fund_map]
    if missing:
        for ms in missing[:10]:
            try:
                rec = await get_fundamentals(ms, db, exchange="NSE", user_id=user.id)
                if rec:
                    fund_map[ms] = rec
            except Exception as e:
                logger.warning("opportunities: failed to fetch fundamentals for %s: %s", ms, e)

    # Pull StockAnalysis rows so we can emit valuation/peer/news sections
    # alongside each opportunity (same shape as today.py portfolio brief).
    from app.models.stock_analysis import StockAnalysis
    from app.models.stock_peers import StockPeer
    from sqlalchemy import func as sa_func

    sa_result = await db.execute(
        select(StockAnalysis).where(StockAnalysis.symbol.in_(syms))
    )
    analyses_by_symbol = {a.symbol: a for a in sa_result.scalars().all()}

    peer_age_result = await db.execute(
        select(StockPeer.symbol, sa_func.max(StockPeer.updated_at))
        .where(StockPeer.symbol.in_(syms))
        .group_by(StockPeer.symbol)
    )
    peer_age_by_symbol = {sym: ts for sym, ts in peer_age_result.all()}

    items = []
    for c in candidates:
        sym = c["symbol"]
        f = fund_map.get(sym)
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
                "source_count": sa.news_source_count or c["headline_count"],
                "qualitative": sa.news_qualitative,
                "sector": (f.sector if f else None),
                "last_run_at": sa.news_last_run_at.isoformat() if sa.news_last_run_at else None,
                # opportunity discovery date stands in for "newest_headline_at"
                # — the headline that surfaced this stock is the freshness anchor.
                "newest_headline_at": c["discovered_at"],
            }

        items.append({
            "symbol": sym,
            "name": (f.name if f and f.name else c["name"]) or sym,
            "exchange": "NSE",
            "score": c["score"],
            "sentiment": c["sentiment"],
            "summary": c["summary"],
            "headline_count": c["headline_count"],
            "discovered_at": c["discovered_at"],
            "has_nse_fno": sym in nse_fno,
            "has_bse_fno": sym in bse_fno,
            "sector": (f.sector if f else None),
            "industry": (f.industry if f else None),
            "cmp": float(f.cmp) if f and f.cmp else None,
            "market_cap": float(f.market_cap) if f and f.market_cap else None,
            "pe_ratio": float(f.pe_ratio) if f and f.pe_ratio else None,
            "day_change_pct": None,
            "report_id": c["report_id"],
            # 3-section grid data (same shape as today.py /brief holding items)
            "valuation_section": valuation_section,
            "peer_section": peer_section,
            "news_section": news_section,
        })

    # Fire peer warmup async for any opportunity-surfaced symbol still
    # missing peers. Idempotent. Covers users who hit /opportunities directly
    # without going through the morning pipeline path.
    try:
        from app.tasks.peer_warmup_task import warm_peers_for_symbol
        from app.models.stock_peers import StockPeer
        surfaced = [i["symbol"] for i in items]
        if surfaced:
            already_q = await db.execute(
                select(StockPeer.symbol).where(StockPeer.symbol.in_(surfaced))
            )
            already = {s for s, in already_q.all()}
            for sym in surfaced:
                if sym not in already:
                    warm_peers_for_symbol.delay(sym, user.id)
    except Exception as e:  # pragma: no cover — best-effort
        logger.warning("opportunities: peer warmup dispatch failed: %s", e)

    return {
        "items": items,
        "report_date": latest_report.report_date.isoformat(),
    }


@router.get("/opportunities/{symbol}/headlines")
async def get_opportunity_headlines(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the news headlines that drove a particular opportunity's score."""
    symbol = symbol.upper().strip()

    reports = await db.execute(
        select(DailyNewsReport)
        .where(DailyNewsReport.user_id == user.id)
        .order_by(DailyNewsReport.report_date.desc())
        .limit(7)
    )
    for report in reports.scalars():
        companies = (report.result_json or {}).get("companies", [])
        for company in companies:
            if (company.get("symbol") or "").upper() == symbol:
                headlines = company.get("headlines", [])
                return {
                    "headlines": [
                        {
                            "title": h.get("title", ""),
                            "source": h.get("source", ""),
                            "sentiment": h.get("sentiment", "neutral"),
                            "url": h.get("url", ""),
                        }
                        for h in headlines[:5]
                    ],
                    "report_date": report.report_date.isoformat(),
                }

    return {"headlines": [], "report_date": None}


class TriageRequest(BaseModel):
    action: str  # "watchlist" | "not_interested"
    symbol: str
    target_watchlist_id: int | None = None
    report_id: int | None = None
    name: str | None = None
    notes: str | None = None


@router.post("/opportunities/triage")
async def triage_opportunity(
    body: TriageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Triage an opportunity: add to a user watchlist or dismiss."""
    symbol = body.symbol.upper().strip()

    if body.action == "watchlist":
        target_wl_id = body.target_watchlist_id
        if not target_wl_id:
            default_wl = (await db.execute(
                select(Watchlist).where(
                    Watchlist.user_id == user.id,
                    Watchlist.is_system == False,
                ).order_by(Watchlist.created_at)
            )).scalar_one_or_none()
            if not default_wl:
                default_wl = Watchlist(user_id=user.id, name="Default")
                db.add(default_wl)
                await db.flush()
            target_wl_id = default_wl.id

        existing = (await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.watchlist_id == target_wl_id,
                WatchlistItem.symbol == symbol,
            )
        )).scalar_one_or_none()

        if not existing:
            new_item = WatchlistItem(
                watchlist_id=target_wl_id,
                symbol=symbol,
                name=body.name,
                exchange="NSE",
                notes=body.notes,
                lane="researching",
            )
            db.add(new_item)

    if body.report_id:
        report = (await db.execute(
            select(DailyNewsReport).where(
                DailyNewsReport.id == body.report_id,
                DailyNewsReport.user_id == user.id,
            )
        )).scalar_one_or_none()
        if report:
            dismissed = list(report.dismissed_json or [])
            if symbol not in dismissed:
                dismissed.append(symbol)
                report.dismissed_json = dismissed

    await db.commit()

    action_label = "moved_to_watchlist" if body.action == "watchlist" else "dismissed"
    return {"ok": True, "action": action_label, "symbol": symbol}
