"""Daily valuation snapshot for watchlist items.

After market close (IST 16:00), snapshot the current PE / PB / 52-week-high
distance for every WatchlistItem across all users. This builds a long-term
valuation history we can chart and use for "valuation change" alerts.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from kiteconnect import KiteConnect

from app.db.session import async_session
from app.models.user import User
from app.models.watchlist import (
    Watchlist,
    WatchlistItem,
    WatchlistValuationSnapshot,
)
from app.services.fundamentals_service import get_cached_fundamentals_bulk
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _today_ist() -> date:
    return datetime.now(tz=ZoneInfo("Asia/Kolkata")).date()


async def _compute_52w_for_user(
    user: User, symbols: set[str]
) -> dict[str, dict]:
    """For each symbol, fetch CMP from Kite and compute 52w high/low from
    daily candles. Returns symbol -> {cmp, high_52w, low_52w}.

    Failures per symbol are silently skipped. If the user has no Kite
    credentials we return an empty dict.
    """
    if not user.kite_api_key or not user.kite_access_token:
        return {}

    try:
        kite = KiteConnect(api_key=user.kite_api_key)
        kite.set_access_token(user.kite_access_token)
    except Exception as e:
        logger.info(f"snapshot: kite session failed for user {user.id}: {e}")
        return {}

    out: dict[str, dict] = {}

    # Batch quote for CMP — single Kite call per ~200 symbols
    instrument_keys = [f"NSE:{s}" for s in symbols]
    try:
        quote_data = await asyncio.to_thread(kite.quote, instrument_keys)
    except Exception:
        quote_data = {}

    for sym in symbols:
        key = f"NSE:{sym}"
        ltp = (quote_data.get(key) or {}).get("last_price") if isinstance(quote_data, dict) else None

        # Compute 52w high/low — needs the instrument token
        # We avoid storing it here; cheaper to skip the historical call and
        # rely on whatever was cached in the technicals endpoint earlier.
        # For now: store CMP only and fill 52w from a separate /technicals
        # call if a stock_id is configured. Skip if unavailable.
        out[sym] = {"cmp": float(ltp) if ltp is not None else None}

    return out


async def _snapshot_async(celery_task_id: str | None = None) -> dict:
    from app.services.smart_money.run_logger import ingestion_run

    async with ingestion_run(
        source="watchlist_snapshot",
        task_name="app.tasks.watchlist_snapshots.snapshot_watchlist_valuations",
        celery_task_id=celery_task_id,
    ) as ctx:
        result = await _snapshot_inner()
        ctx.fetched = result.get("inserted", 0) + result.get("skipped", 0)
        ctx.inserted = result.get("inserted", 0)
        ctx.skipped = result.get("skipped", 0)
        return result


async def _snapshot_inner() -> dict:
    """Iterate all users + their watchlist items and write today's snapshots."""
    today = _today_ist()
    inserted = 0
    skipped = 0

    async with async_session() as session:
        # All watchlist items grouped by user
        users_res = await session.execute(select(User))
        users = users_res.scalars().all()

        for user in users:
            wl_res = await session.execute(select(Watchlist).where(Watchlist.user_id == user.id))
            watchlists = wl_res.scalars().all()
            if not watchlists:
                continue
            wl_ids = [w.id for w in watchlists]

            items_res = await session.execute(
                select(WatchlistItem).where(WatchlistItem.watchlist_id.in_(wl_ids))
            )
            items = items_res.scalars().all()
            if not items:
                continue

            # Symbol -> [item_ids] (a symbol may appear in multiple watchlists)
            symbols = {it.symbol.upper() for it in items}

            # CMPs from kite
            quote_map = await _compute_52w_for_user(user, symbols)

            # Fundamentals from DB (PE / PB)
            fund_map = await get_cached_fundamentals_bulk(list(symbols), session)

            for it in items:
                sym = it.symbol.upper()
                cmp = (quote_map.get(sym) or {}).get("cmp")
                fund = fund_map.get(sym)

                pe = float(fund.pe_ratio or fund.ttm_pe) if fund and (fund.pe_ratio or fund.ttm_pe) else None
                pb = float(fund.pb_ratio) if fund and fund.pb_ratio else None

                # 52w from fundamentals if we cached it; otherwise None
                high_52w = float(getattr(fund, "high_52w", None) or 0) or None if fund else None
                low_52w = float(getattr(fund, "low_52w", None) or 0) or None if fund else None
                pct_high = ((cmp - high_52w) / high_52w * 100) if cmp and high_52w else None
                pct_low = ((cmp - low_52w) / low_52w * 100) if cmp and low_52w else None

                stmt = pg_insert(WatchlistValuationSnapshot).values(
                    watchlist_item_id=it.id,
                    snapshot_date=today,
                    cmp=cmp,
                    pe_ratio=pe,
                    pb_ratio=pb,
                    pct_from_52w_high=pct_high,
                    pct_from_52w_low=pct_low,
                    high_52w=high_52w,
                    low_52w=low_52w,
                ).on_conflict_do_update(
                    index_elements=["watchlist_item_id", "snapshot_date"],
                    set_={
                        "cmp": cmp, "pe_ratio": pe, "pb_ratio": pb,
                        "pct_from_52w_high": pct_high, "pct_from_52w_low": pct_low,
                        "high_52w": high_52w, "low_52w": low_52w,
                    },
                )
                try:
                    await session.execute(stmt)
                    inserted += 1
                except Exception as e:
                    skipped += 1
                    logger.info(f"snapshot upsert failed for {sym}: {e}")

        await session.commit()

    return {"date": today.isoformat(), "inserted": inserted, "skipped": skipped}


@celery_app.task(name="app.tasks.watchlist_snapshots.snapshot_watchlist_valuations", bind=True)
def snapshot_watchlist_valuations(self) -> dict:
    """Sync entry-point; runs the async job in a fresh loop."""
    return asyncio.run(_snapshot_async(celery_task_id=self.request.id))
