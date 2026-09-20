"""Intraday review-alert evaluator.

Runs every 15 minutes between 09:15-15:30 IST (Mon-Fri). For every user
that owns a watchlist item with at least one rule whose `check_frequency`
is `15min` or `hourly`, fetches a live Kite quote and evaluates the two
"fast" rule types — `single_day_drop` and `price_below` — against the LTP.

Slow rule types (`pe`, `pb`, `pct_from_52w_high`) are intentionally NOT
re-evaluated here: they're driven by `WatchlistValuationSnapshot` which
the daily 16:30 task writes once a day, so there's nothing new to check
intraday. The 16:40 daily eval handles them.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.session import async_session
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem
from app.services.portfolio_cache import get_quote
from app.services.review_alerts import _create_alert, _existing_pending  # noqa: F401
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

INTRADAY_TYPES = {"single_day_drop", "price_below"}
INTRADAY_FREQS = {"15min", "hourly"}
IST = ZoneInfo("Asia/Kolkata")


def _is_market_open() -> bool:
    now = datetime.now(tz=IST)
    if now.weekday() >= 5:  # Sat / Sun
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= minutes <= 15 * 60 + 30


async def _eval_user(user: User) -> int:
    """Returns alerts created for this user."""
    if not user.kite_api_key or not user.kite_access_token:
        return 0  # need a Kite session for live quotes

    async with async_session() as db:
        # Pull every WatchlistItem with at least one fast-frequency rule.
        items_q = (
            select(WatchlistItem)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_id == user.id)
        )
        items = list((await db.execute(items_q)).scalars().all())
        eligible: list[tuple[WatchlistItem, list[dict]]] = []
        for it in items:
            rules = it.watch_rules or []
            fast = [
                r for r in rules
                if isinstance(r, dict)
                and (r.get("type") or "") in INTRADAY_TYPES
                and (r.get("check_frequency") or "daily") in INTRADAY_FREQS
            ]
            if fast:
                eligible.append((it, fast))
        if not eligible:
            return 0

        instrument_keys = list({f"{(it.exchange or 'NSE')}:{it.symbol.upper()}" for it, _ in eligible})
        try:
            quotes = await get_quote(user, instrument_keys)
        except Exception as e:  # noqa: BLE001
            logger.warning("intraday quote fetch failed for user %s: %s", user.id, e)
            return 0

        created = 0
        for item, fast_rules in eligible:
            ikey = f"{(item.exchange or 'NSE')}:{item.symbol.upper()}"
            q = quotes.get(ikey, {}) if isinstance(quotes, dict) else {}
            ltp = q.get("last_price")
            ohlc = q.get("ohlc") or {}
            prev_close = ohlc.get("close")
            if ltp is None:
                continue

            for r in fast_rules:
                rtype = r.get("type")
                rval = r.get("value")
                try:
                    rval_f = float(rval) if rval is not None else None
                except (TypeError, ValueError):
                    rval_f = None
                if rval_f is None:
                    continue
                fired = False
                if rtype == "price_below":
                    fired = float(ltp) <= rval_f
                elif rtype == "single_day_drop" and prev_close and prev_close > 0:
                    day_pct = (float(ltp) - float(prev_close)) / float(prev_close) * 100.0
                    fired = day_pct <= -abs(rval_f)
                if not fired:
                    continue

                if await _existing_pending(user.id, item.symbol.upper(), "rule", db):
                    continue
                ok = await _create_alert(
                    db,
                    user_id=user.id,
                    symbol=item.symbol.upper(),
                    exchange=item.exchange or "NSE",
                    source="watchlist",
                    trigger_type="rule",
                    trigger_label=f"Rule fired (intraday) — {r.get('label') or rtype}",
                    suggested_action="Move to Awaiting Correction",
                    suggested_lane="awaiting",
                    payload={"rule": r, "live": {"ltp": ltp, "prev_close": prev_close}},
                )
                if ok:
                    created += 1
        if created:
            await db.commit()
        return created


async def _run(celery_task_id: str | None = None) -> dict:
    from app.services.smart_money.run_logger import ingestion_run

    async with ingestion_run(
        source="review_alerts_intraday",
        task_name="app.tasks.review_alerts_intraday.run_intraday_eval",
        celery_task_id=celery_task_id,
    ) as ctx:
        if not _is_market_open():
            ctx.meta["skipped"] = "market_closed"
            return {"skipped": True, "reason": "market_closed"}
        async with async_session() as db:
            owners = (await db.execute(select(Watchlist.user_id).distinct())).all()
            user_ids = [r[0] for r in owners]
            if not user_ids:
                return {"users": 0, "alerts_created": 0}
            users = list((await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all())
        total = 0
        for user in users:
            try:
                total += await _eval_user(user)
            except Exception:
                logger.exception("intraday eval failed for user_id=%s", user.id)
        logger.info("review-alerts-intraday: users=%d alerts_created=%d", len(users), total)
        ctx.fetched = len(users)
        ctx.inserted = total
        return {"users": len(users), "alerts_created": total}


@celery_app.task(name="app.tasks.review_alerts_intraday.run_intraday_eval", bind=True)
def run_intraday_eval(self) -> dict:
    return asyncio.run(_run(celery_task_id=self.request.id))
