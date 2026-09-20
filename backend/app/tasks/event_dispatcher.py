"""Event-driven re-evaluation dispatcher.

Replaces the "refresh every holding every day" pattern with one that
fires only when *information* has changed. Reads ingestion_runs
completions since the last dispatch, identifies affected symbols, and
queues refresh_stock_analysis for holdings + watchlist overlaps.

State is kept in Redis (`event_dispatcher:last_run_at`) so the
dispatcher resumes from where it stopped across restarts.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()

# Sources we react to. Each one maps to a "which symbols changed?" lookup.
WATCHED_SOURCES = (
    "nse_corporate_announcements",
    "smart_money_rollup",
    "nse_insider",
)

LAST_RUN_KEY = "event_dispatcher:last_run_at"
MAX_REFRESH_PER_TICK = 8


@celery_app.task(
    name="app.tasks.event_dispatcher.run_event_dispatcher",
    queue="analysis",
    bind=True,
)
def run_event_dispatcher(self):
    logger.info("=== Event dispatcher tick ===")
    try:
        return asyncio.run(_dispatch())
    except Exception as e:
        logger.error(f"Event dispatcher failed: {e}", exc_info=True)
        return {"error": str(e)}


async def _dispatch() -> dict:
    import redis.asyncio as aioredis

    redis_url = settings.REDIS_URL
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        last_iso = await r.get(LAST_RUN_KEY)
    except Exception:
        last_iso = None
    now = datetime.now(timezone.utc)
    # Default lookback: 15 min on first tick so we don't dispatch a flood.
    last_dt = (
        datetime.fromisoformat(last_iso)
        if last_iso
        else now - timedelta(minutes=15)
    )

    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SM = async_sessionmaker(engine, expire_on_commit=False)
    affected: set[str] = set()

    try:
        async with SM() as db:
            from app.models.smart_money import IngestionRun
            from app.models.user import User
            from app.models.watchlist import Watchlist, WatchlistItem

            recent_runs = (await db.execute(
                select(IngestionRun).where(
                    IngestionRun.source.in_(WATCHED_SOURCES),
                    IngestionRun.status.in_(("success", "partial")),
                    IngestionRun.finished_at.isnot(None),
                    IngestionRun.finished_at > last_dt,
                )
            )).scalars().all()

            if not recent_runs:
                await r.set(LAST_RUN_KEY, now.isoformat())
                return {"affected": 0, "queued": 0, "tick": now.isoformat()}

            # For each source, figure out which symbols changed
            for run in recent_runs:
                affected |= await _symbols_for_source(db, run.source, last_dt)

            # Intersect with user holdings + watchlist
            user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
            if not user:
                return {"error": "no_user"}

            watched: set[str] = set()
            # Holdings
            try:
                from app.services.portfolio_cache import get_holdings
                holdings = await get_holdings(user)
                for h in holdings or []:
                    s = (h.get("tradingsymbol") or "").upper().strip()
                    if s:
                        watched.add(s)
            except Exception:
                pass
            # Watchlist
            wl_ids = (await db.execute(
                select(Watchlist.id).where(Watchlist.user_id == user.id)
            )).scalars().all()
            if wl_ids:
                wl_items = (await db.execute(
                    select(WatchlistItem.symbol).where(WatchlistItem.watchlist_id.in_(list(wl_ids)))
                )).scalars().all()
                for s in wl_items:
                    if s:
                        watched.add(s.upper().strip())

            to_refresh = sorted(affected & watched)[:MAX_REFRESH_PER_TICK]

        # Dispatch refreshes
        from app.services.stock_card import refresh_stock_analysis
        for sym in to_refresh:
            try:
                async with SM() as d_db:
                    await refresh_stock_analysis(sym, d_db, user.id)
                logger.info(f"  Event-driven refresh OK: {sym}")
            except Exception as e:
                logger.warning(f"  Event-driven refresh failed for {sym}: {e}")

        await r.set(LAST_RUN_KEY, now.isoformat())
        return {
            "tick": now.isoformat(),
            "affected": len(affected),
            "intersection": len(affected & watched),
            "queued": len(to_refresh),
            "symbols": to_refresh,
        }
    finally:
        await engine.dispose()
        try:
            await r.aclose()
        except Exception:
            pass


async def _symbols_for_source(db, source: str, since: datetime) -> set[str]:
    """Return symbols affected by completed runs of `source` since `since`."""
    try:
        if source == "nse_corporate_announcements":
            rows = await db.execute(text(
                "SELECT DISTINCT symbol FROM corporate_announcements WHERE created_at > :since"
            ), {"since": since})
            return {row.symbol for row in rows}
        elif source == "smart_money_rollup":
            rows = await db.execute(text(
                "SELECT DISTINCT symbol FROM smart_money_signals WHERE updated_at > :since"
            ), {"since": since})
            return {row.symbol for row in rows}
        elif source == "nse_insider":
            rows = await db.execute(text(
                "SELECT DISTINCT symbol FROM insider_disclosures WHERE created_at > :since"
            ), {"since": since})
            return {row.symbol for row in rows}
    except Exception as e:
        logger.debug("symbol lookup for source=%s failed: %s", source, e)
    return set()
