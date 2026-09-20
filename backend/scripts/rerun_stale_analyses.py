"""Re-run stock_analyses for portfolio holdings whose peer_verdict is
stuck at "IN_LINE" with peer_count = 0 — a state that pre-dates the
NO_DATA fix in stock_card.py. After the fix shipped, those rows aren't
overwritten until refresh_stock_analysis runs again, which requires
the full pipeline or per-stock refresh.

Usage:
    docker exec algo-trader-backend-1 python -m scripts.rerun_stale_analyses
"""

from __future__ import annotations

import asyncio
import logging
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.user import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rerun_stale_analyses")


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SM = async_sessionmaker(engine, expire_on_commit=False)

    async with SM() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
        if not user:
            logger.error("No user found")
            return

        rows = (await db.execute(text(
            "SELECT DISTINCT symbol FROM stock_analyses "
            "WHERE peer_verdict = 'IN_LINE' AND (peer_count IS NULL OR peer_count = 0)"
        ))).all()
        symbols = [r[0] for r in rows]
        logger.info(f"Found {len(symbols)} stale stock_analyses rows to re-run")
        if not symbols:
            await engine.dispose()
            return

    from app.services.stock_card import refresh_stock_analysis
    sem = asyncio.Semaphore(3)

    ok = fail = 0

    async def _one(sym: str) -> None:
        nonlocal ok, fail
        async with sem:
            async with SM() as s_db:
                try:
                    await refresh_stock_analysis(sym, s_db, user.id)
                    ok += 1
                    logger.info(f"  {sym}: re-ran")
                except Exception as e:
                    fail += 1
                    logger.warning(f"  {sym}: failed — {e}")

    await asyncio.gather(*[_one(s) for s in symbols])
    logger.info(f"Done: {ok} ok, {fail} failed")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
