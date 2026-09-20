"""One-time backfill that generates peer sets for all portfolio + watchlist
symbols that don't have any.

Designed to drain the backlog of stocks created before the morning pipeline
started auto-generating peers (and to rescue stocks where the earlier
generation failed silently).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.fundamentals import StockFundamentals
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem
from app.services.peer_discovery import generate_peers, get_stored_peers

logger = logging.getLogger(__name__)

_CONCURRENCY = 3


async def _collect_target_symbols(user: User, db: AsyncSession) -> set[str]:
    """Union of holdings symbols + all watchlist symbols for this user."""
    symbols: set[str] = set()

    # Holdings (Kite-cached)
    try:
        from app.services.portfolio_cache import get_holdings
        holdings = await get_holdings(user)
        for h in holdings or []:
            sym = (h.get("tradingsymbol") or h.get("symbol") or "").upper().strip()
            if sym:
                symbols.add(sym)
    except Exception as e:
        logger.warning(f"peer_backfill: holdings fetch failed: {e}")

    # Watchlists
    wl_ids = [
        row.id for row in (
            await db.execute(select(Watchlist).where(Watchlist.user_id == user.id))
        ).scalars().all()
    ]
    if wl_ids:
        items = (await db.execute(
            select(WatchlistItem.symbol).where(WatchlistItem.watchlist_id.in_(wl_ids))
        )).scalars().all()
        for s in items:
            if s:
                symbols.add(s.upper().strip())

    return symbols


async def backfill_missing_peers(
    user: User,
    session_maker: async_sessionmaker[AsyncSession],
    *,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """Generate peers for any holding/watchlist symbol missing them.

    Uses its own session-maker so each generation runs in a fresh transaction
    (long-lived sessions during 50+ Gemini calls would hold locks unhealthily).

    Wrapped in an ingestion_run so the activity monitor (and Scheduled Jobs
    table) can see backfill progress + results.

    Returns a summary dict: {checked, generated, skipped_no_industry,
    skipped_already_has, failed}.
    """
    from app.services.smart_money.run_logger import ingestion_run
    async with ingestion_run(source="peer_backfill", task_name="peer_backfill") as ctx:
        result = await _backfill_inner(user, session_maker, db=db)
        if ctx:
            ctx.fetched = result.get("checked", 0)
            ctx.inserted = result.get("generated", 0)
            ctx.skipped = result.get("skipped_already_has", 0) + result.get("skipped_no_industry", 0)
            ctx.meta.update(result)
            if result.get("failed", 0) > 0:
                ctx.mark_partial(f"{result['failed']} symbols failed")
        return result


async def _backfill_inner(
    user: User,
    session_maker: async_sessionmaker[AsyncSession],
    *,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    # Use the caller's db only to read the target list; per-symbol generation
    # uses fresh sessions below.
    if db is None:
        async with session_maker() as bootstrap:
            target_symbols = await _collect_target_symbols(user, bootstrap)
    else:
        target_symbols = await _collect_target_symbols(user, db)

    logger.info(f"peer_backfill: {len(target_symbols)} candidate symbols")

    summary = {
        "checked": len(target_symbols),
        "generated": 0,
        "skipped_no_industry": 0,
        "skipped_already_has": 0,
        "failed": 0,
        "generated_for": [],
    }

    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _one(symbol: str) -> None:
        async with sem:
            async with session_maker() as sdb:
                try:
                    stored = await get_stored_peers(symbol, sdb)
                    if len(stored) >= 2:
                        summary["skipped_already_has"] += 1
                        return

                    fund = (await sdb.execute(
                        select(StockFundamentals).where(
                            StockFundamentals.symbol == symbol
                        )
                    )).scalar_one_or_none()

                    if not fund or not (fund.industry or fund.sector):
                        summary["skipped_no_industry"] += 1
                        return

                    await generate_peers(symbol, sdb, user)
                    summary["generated"] += 1
                    summary["generated_for"].append(symbol)
                    logger.info(f"peer_backfill: generated peers for {symbol}")
                except Exception as e:
                    summary["failed"] += 1
                    logger.warning(f"peer_backfill: {symbol} failed — {e}")

    await asyncio.gather(*[_one(s) for s in sorted(target_symbols)])

    # Chain: for every symbol where peer_backfill just generated peers, fire
    # refresh_stock_analysis so the dashboard's peer verdict picks up the new
    # peer set same-day. Without this, stock_analyses rows stay stale until
    # next morning_pipeline run (the ordering-bug fix the user flagged).
    generated_for: list[str] = summary.get("generated_for") or []
    if generated_for:
        from app.services.stock_card import refresh_stock_analysis as _refresh

        async def _chain_one(sym: str) -> None:
            async with sem:
                async with session_maker() as c_db:
                    try:
                        await _refresh(sym, c_db, user.id)
                        logger.info(f"peer_backfill chain: refreshed analysis for {sym}")
                    except Exception as e:
                        logger.warning(
                            f"peer_backfill chain: refresh failed for {sym} — "
                            f"{type(e).__name__}: {str(e)[:100]}"
                        )

        await asyncio.gather(*[_chain_one(s) for s in generated_for])

    return summary
