"""Pending-for-review alert evaluator.

A "monitored symbol" for a user = (any watchlist symbol) ∪ (any portfolio holding).

Triggers (any → create a pending alert if none exists for the same trigger_type):
- rule       Watch rule on a watchlist item evaluates true
- news       High-confidence headwind/tailwind classified for the symbol since last review
- valuation  PE crossed `pe_target` or PB drifted ≥10% wow
- verdict    AI verdict flipped vs the most recent prior decision
- sentiment  News sentiment score crossed ±30 from prior

A cleanup task auto-dismisses pending alerts for symbols that fall out of
the user's monitored set (no longer in any watchlist AND no longer held).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.investment_decision import InvestmentDecision
from app.models.news_sentiment import NewsSentimentCache
from app.models.review_alert import ReviewAlert
from app.models.user import User
from app.models.watchlist import (
    Watchlist,
    WatchlistItem,
    WatchlistJournalEntry,
    WatchlistValuationSnapshot,
)
from app.services.portfolio_cache import get_holdings as cached_holdings

logger = logging.getLogger(__name__)


async def _get_user_holdings(user: User) -> set[str]:
    if not user.kite_api_key or not user.kite_access_token:
        return set()
    try:
        rows = await cached_holdings(user)
    except Exception as e:
        logger.info(f"holdings fetch failed (review_alerts): {e}")
        return set()
    from app.services.portfolio_cache import holding_total_qty
    symbols = {(r.get("tradingsymbol") or "").upper() for r in rows if holding_total_qty(r) > 0}
    symbols.discard("")
    return symbols


async def get_monitored_symbols(user: User, db: AsyncSession) -> dict[str, dict]:
    """Return {symbol -> {source, watchlist_item_id?}} for the user's
    portfolio holdings ∪ all watchlist symbols.

    `source` is one of: "watchlist" | "holding" | "both".
    """
    # Watchlist symbols (with their item id for rule eval)
    res = await db.execute(
        select(WatchlistItem)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.user_id == user.id)
    )
    items = res.scalars().all()
    wl_map: dict[str, WatchlistItem] = {}
    for it in items:
        sym = (it.symbol or "").upper()
        if sym and sym not in wl_map:
            # Keep the first one if multiple watchlists hold the same symbol
            wl_map[sym] = it

    # Portfolio symbols
    held = await _get_user_holdings(user)

    out: dict[str, dict] = {}
    for sym, it in wl_map.items():
        out[sym] = {
            "source": "both" if sym in held else "watchlist",
            "watchlist_item_id": it.id,
            "exchange": it.exchange or "NSE",
            "lane": it.lane or "researching",
        }
    for sym in held:
        if sym in out:
            continue
        out[sym] = {
            "source": "holding",
            "watchlist_item_id": None,
            "exchange": "NSE",
            "lane": None,
        }
    return out


# ────────────────────────── helpers ──────────────────────────

async def _existing_pending(user_id: int, symbol: str, trigger_type: str, db: AsyncSession) -> ReviewAlert | None:
    res = await db.execute(
        select(ReviewAlert).where(
            ReviewAlert.user_id == user_id,
            ReviewAlert.symbol == symbol,
            ReviewAlert.trigger_type == trigger_type,
            ReviewAlert.status == "pending",
        )
    )
    return res.scalar_one_or_none()


async def _last_resolved_at(user_id: int, symbol: str, db: AsyncSession) -> datetime | None:
    res = await db.execute(
        select(ReviewAlert)
        .where(ReviewAlert.user_id == user_id, ReviewAlert.symbol == symbol)
        .where(ReviewAlert.status.in_(("applied", "dismissed")))
        .order_by(desc(ReviewAlert.resolved_at))
        .limit(1)
    )
    last = res.scalar_one_or_none()
    return last.resolved_at if last else None


async def _create_alert(
    db: AsyncSession,
    *,
    user_id: int,
    symbol: str,
    exchange: str,
    source: str,
    trigger_type: str,
    trigger_label: str,
    suggested_action: str | None = None,
    suggested_lane: str | None = None,
    payload: dict | None = None,
) -> bool:
    alert = ReviewAlert(
        user_id=user_id,
        symbol=symbol,
        exchange=exchange,
        source=source,
        trigger_type=trigger_type,
        trigger_label=trigger_label[:200],
        suggested_action=(suggested_action or None) and suggested_action[:60],
        suggested_lane=suggested_lane,
        payload=payload or {},
        status="pending",
    )
    try:
        db.add(alert)
        await db.flush()
        return True
    except Exception as e:
        logger.info(f"create alert failed (likely partial-unique): {e}")
        await db.rollback()
        return False


# ────────────────────────── trigger checks ──────────────────────────

# Canonical rule types (kept in sync with WatchRulePayload in api/watchlist.py).
# The aliases on the right exist so older rows authored before the validation
# tightening still evaluate correctly — there's no data migration since v1
# only writes canonical names.
SUPPORTED_RULE_TYPES = (
    "pct_from_52w_high",
    "pe",
    "pb",
    "single_day_drop",
    "price_below",
    # Legacy aliases for older rows authored before the v2 schema.
    "pe_below",
    "pe_above",
)
_RULE_TYPE_ALIASES: dict[str, str] = {
    "pct_from_peak": "pct_from_52w_high",
    "drawdown_pct":  "pct_from_52w_high",
    "pe_target":     "pe_below",
}

# Types that need the most-recent snapshot vs. the previous snapshot — i.e.
# day-over-day change. Without a `prev_snap`, these rules are skipped.
_DAY_CHANGE_TYPES = {"single_day_drop"}


def _compare(actual: float, op: str, value: float) -> bool:
    if op == "lte":
        return actual <= value
    if op == "gte":
        return actual >= value
    if op == "eq":
        return abs(actual - value) < 1e-9
    return False


async def _check_watch_rules(
    item: WatchlistItem,
    snapshot: WatchlistValuationSnapshot | None,
    db: AsyncSession,
    user_id: int,
    source: str,
    prev_snap: WatchlistValuationSnapshot | None = None,
) -> int:
    """Evaluate item.watch_rules against the latest valuation snapshot.

    `prev_snap` is the immediately-prior snapshot (yesterday's row, in
    practice). Used by `single_day_drop` to compute day-over-day change.
    """
    rules = item.watch_rules or []
    if not rules or not snapshot:
        return 0
    created = 0
    for r in rules:
        if not isinstance(r, dict):
            continue
        rtype = (r.get("type") or "").lower()
        rtype = _RULE_TYPE_ALIASES.get(rtype, rtype)
        rval = r.get("value")
        rop = (r.get("operator") or "").lower() or None
        try:
            rval_f = float(rval) if rval is not None else None
        except (TypeError, ValueError):
            rval_f = None
        fired = False
        label = r.get("label") or f"{rtype}={rval}"
        if rtype == "pct_from_52w_high" and snapshot.pct_from_52w_high is not None and rval_f is not None:
            # "−10% from peak" → trigger when pct_from_52w_high <= -10
            fired = snapshot.pct_from_52w_high <= rval_f
        elif rtype == "pe" and snapshot.pe_ratio is not None and rval_f is not None:
            fired = _compare(snapshot.pe_ratio, rop or "lte", rval_f)
        elif rtype == "pb" and snapshot.pb_ratio is not None and rval_f is not None:
            fired = _compare(snapshot.pb_ratio, rop or "lte", rval_f)
        # Legacy operator-baked-into-type variants
        elif rtype == "pe_below" and snapshot.pe_ratio is not None and rval_f is not None:
            fired = snapshot.pe_ratio <= rval_f
        elif rtype == "pe_above" and snapshot.pe_ratio is not None and rval_f is not None:
            fired = snapshot.pe_ratio >= rval_f
        elif rtype == "price_below" and snapshot.cmp is not None and rval_f is not None:
            fired = snapshot.cmp <= rval_f
        elif (
            rtype == "single_day_drop"
            and snapshot.cmp is not None
            and prev_snap is not None
            and prev_snap.cmp is not None
            and prev_snap.cmp > 0
            and rval_f is not None
        ):
            day_pct = (snapshot.cmp - prev_snap.cmp) / prev_snap.cmp * 100.0
            # Rule value is the threshold drop magnitude (positive percent).
            # Fire when actual drop is at least that big.
            fired = day_pct <= -abs(rval_f)
        if not fired:
            continue
        if await _existing_pending(user_id, item.symbol.upper(), "rule", db):
            continue
        ok = await _create_alert(
            db,
            user_id=user_id,
            symbol=item.symbol.upper(),
            exchange=item.exchange or "NSE",
            source=source,
            trigger_type="rule",
            trigger_label=f"Rule fired — {label}",
            suggested_action="Move to Awaiting Correction",
            suggested_lane="awaiting",
            payload={"rule": r, "snapshot": {
                "pct_from_52w_high": snapshot.pct_from_52w_high,
                "pe_ratio": snapshot.pe_ratio,
                "pb_ratio": snapshot.pb_ratio,
                "cmp": snapshot.cmp,
            }},
        )
        if ok:
            created += 1
    return created


async def _check_valuation(
    item: WatchlistItem | None, snapshot: WatchlistValuationSnapshot | None, prev_snapshots: list[WatchlistValuationSnapshot],
    db: AsyncSession, user_id: int, symbol: str, exchange: str, source: str,
) -> int:
    if not snapshot:
        return 0
    # PE crosses target
    pe_target = float(item.pe_target) if (item and item.pe_target is not None) else None
    if pe_target and snapshot.pe_ratio is not None:
        prev_pe = next((p.pe_ratio for p in prev_snapshots if p.pe_ratio is not None), None)
        crossed_down = prev_pe is not None and prev_pe > pe_target and snapshot.pe_ratio <= pe_target
        crossed_up = prev_pe is not None and prev_pe < pe_target and snapshot.pe_ratio >= pe_target
        if crossed_down or crossed_up:
            if not await _existing_pending(user_id, symbol, "valuation", db):
                ok = await _create_alert(
                    db,
                    user_id=user_id, symbol=symbol, exchange=exchange, source=source,
                    trigger_type="valuation",
                    trigger_label=f"PE crossed {pe_target:.0f}× target",
                    suggested_action="Move to Awaiting Correction" if crossed_down else "Re-evaluate",
                    suggested_lane="awaiting" if crossed_down else None,
                    payload={"pe_now": snapshot.pe_ratio, "pe_prev": prev_pe, "pe_target": pe_target},
                )
                return 1 if ok else 0
    # PB shifts ≥10% wow
    if snapshot.pb_ratio and prev_snapshots:
        week_old = next((p for p in prev_snapshots if p.snapshot_date <= snapshot.snapshot_date - timedelta(days=5)), None)
        if week_old and week_old.pb_ratio:
            delta = (snapshot.pb_ratio - week_old.pb_ratio) / week_old.pb_ratio * 100
            if abs(delta) >= 10 and not await _existing_pending(user_id, symbol, "valuation", db):
                ok = await _create_alert(
                    db,
                    user_id=user_id, symbol=symbol, exchange=exchange, source=source,
                    trigger_type="valuation",
                    trigger_label=f"PB moved {delta:+.0f}% week-over-week",
                    suggested_action="Re-evaluate",
                    suggested_lane=None,
                    payload={"pb_now": snapshot.pb_ratio, "pb_week_old": week_old.pb_ratio, "pct_delta": round(delta, 2)},
                )
                return 1 if ok else 0
    return 0


async def _check_verdict(
    user_id: int, symbol: str, exchange: str, source: str, since: datetime | None, db: AsyncSession,
) -> int:
    res = await db.execute(
        select(InvestmentDecision)
        .where(InvestmentDecision.user_id == user_id, InvestmentDecision.symbol == symbol)
        .order_by(desc(InvestmentDecision.created_at))
        .limit(2)
    )
    rows = list(res.scalars().all())
    if len(rows) < 2:
        return 0
    latest, prior = rows[0], rows[1]
    if since and latest.created_at and latest.created_at <= since:
        return 0
    if (latest.verdict or "") == (prior.verdict or ""):
        return 0
    if await _existing_pending(user_id, symbol, "verdict", db):
        return 0
    suggest_lane = {"INVEST": "researching", "AVOID": "exit", "WAIT": "awaiting"}.get(latest.verdict or "")
    ok = await _create_alert(
        db,
        user_id=user_id, symbol=symbol, exchange=exchange, source=source,
        trigger_type="verdict",
        trigger_label=f"AI verdict flipped: {prior.verdict} → {latest.verdict}",
        suggested_action=f"Move to {suggest_lane.title()}" if suggest_lane else "Re-evaluate",
        suggested_lane=suggest_lane,
        payload={"prev": prior.verdict, "now": latest.verdict, "confidence": latest.confidence},
    )
    return 1 if ok else 0


async def _check_sentiment(
    user_id: int, symbol: str, exchange: str, source: str, since: datetime | None, db: AsyncSession,
) -> int:
    res = await db.execute(
        select(NewsSentimentCache)
        .where(NewsSentimentCache.symbol == symbol)
        .order_by(desc(NewsSentimentCache.analyzed_at))
        .limit(2)
    )
    rows = list(res.scalars().all())
    if len(rows) < 2:
        return 0
    latest, prior = rows[0], rows[1]
    if since and latest.analyzed_at and latest.analyzed_at <= since:
        return 0
    if latest.score is None or prior.score is None:
        return 0
    delta = (latest.score or 0) - (prior.score or 0)
    if abs(delta) < 30:
        return 0
    if await _existing_pending(user_id, symbol, "sentiment", db):
        return 0
    ok = await _create_alert(
        db,
        user_id=user_id, symbol=symbol, exchange=exchange, source=source,
        trigger_type="sentiment",
        trigger_label=f"Sentiment shifted {delta:+.0f}: {prior.sentiment} → {latest.sentiment}",
        suggested_action="Re-evaluate",
        suggested_lane=None,
        payload={"prev_score": prior.score, "now_score": latest.score, "prev": prior.sentiment, "now": latest.sentiment},
    )
    return 1 if ok else 0


# ────────────────────────── main entry points ──────────────────────────

async def evaluate_alerts_for_user(user: User, db: AsyncSession) -> int:
    """Run all trigger checks for the user. Returns number of alerts created."""
    monitored = await get_monitored_symbols(user, db)
    if not monitored:
        return 0
    created_total = 0
    for sym, info in monitored.items():
        wl_item: WatchlistItem | None = None
        if info["watchlist_item_id"]:
            res = await db.execute(
                select(WatchlistItem).where(WatchlistItem.id == info["watchlist_item_id"])
            )
            wl_item = res.scalar_one_or_none()

        # Latest snapshot (newest first), and a small window for week-over-week comparisons
        snapshots: list[WatchlistValuationSnapshot] = []
        if wl_item:
            res = await db.execute(
                select(WatchlistValuationSnapshot)
                .where(WatchlistValuationSnapshot.watchlist_item_id == wl_item.id)
                .order_by(desc(WatchlistValuationSnapshot.snapshot_date))
                .limit(15)
            )
            snapshots = list(res.scalars().all())
        latest_snap = snapshots[0] if snapshots else None

        since = await _last_resolved_at(user.id, sym, db)

        # Run each check
        if wl_item:
            prev_snap = snapshots[1] if len(snapshots) > 1 else None
            created_total += await _check_watch_rules(
                wl_item, latest_snap, db, user.id, info["source"], prev_snap=prev_snap,
            )
        created_total += await _check_valuation(
            wl_item, latest_snap, snapshots[1:] if snapshots else [],
            db, user.id, sym, info["exchange"], info["source"],
        )
        created_total += await _check_verdict(
            user.id, sym, info["exchange"], info["source"], since, db
        )
        created_total += await _check_sentiment(
            user.id, sym, info["exchange"], info["source"], since, db
        )
        # news trigger relies on the news_inbox classifier output, but we
        # don't yet write classified items into a per-symbol DB table — skip
        # for now (TODO when news_inbox persists per-symbol classifications).
    if created_total:
        await db.commit()
    return created_total


async def cleanup_stale_alerts_for_user(user: User, db: AsyncSession) -> int:
    """Auto-dismiss pending alerts for symbols no longer in the monitored set."""
    monitored = await get_monitored_symbols(user, db)
    monitored_set = set(monitored.keys())
    if not monitored_set:
        # If empty, dismiss all pending for this user
        res = await db.execute(
            select(ReviewAlert).where(ReviewAlert.user_id == user.id, ReviewAlert.status == "pending")
        )
    else:
        res = await db.execute(
            select(ReviewAlert)
            .where(ReviewAlert.user_id == user.id, ReviewAlert.status == "pending")
            .where(~ReviewAlert.symbol.in_(monitored_set))
        )
    stale = res.scalars().all()
    if not stale:
        return 0
    now = datetime.now(tz=timezone.utc)
    for a in stale:
        a.status = "dismissed"
        a.resolved_at = now
        a.payload = {**(a.payload or {}), "auto_dismissed": True, "reason": "Symbol no longer in portfolio or any watchlist"}
    await db.commit()
    return len(stale)
