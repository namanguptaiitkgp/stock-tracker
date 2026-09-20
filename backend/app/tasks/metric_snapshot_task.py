"""Daily portfolio-scope metric_snapshots refresh.

Wraps `metric_engine.run_refresh(scope="portfolio")` as a celery task.
Dispatched from the post-close pipeline (`morning_pipeline.py`) so the
`metric_snapshots` table is brought up to date alongside the legacy
`stock_fundamentals` writes.

This is Stage 3a of the fundamentals unification (see plan file). It
runs ADDITIVELY — both stores are updated daily. The full reader
migration (Stage 3b–3f) is documented as follow-up work; until that
ships, this task is what keeps the "Snapshot" chip on the stock-detail
page fresh.

Runs sequentially internally (run_refresh iterates symbols one at a
time, each doing parallel source HTTP calls). For ~270 symbols this
is ~10–15 min wall-clock — acceptable as a side task because it
doesn't block the rest of the pipeline.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.user import User
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(
    name="app.tasks.metric_snapshot.refresh_portfolio_snapshots",
    queue="analysis",
    bind=True,
)
def refresh_portfolio_snapshots(self) -> dict:
    """Run metric_engine for the admin user's portfolio+watchlist scope."""
    logger.info("=== Portfolio metric snapshots refresh started ===")
    try:
        return asyncio.run(_run())
    except Exception as e:
        logger.error(f"refresh_portfolio_snapshots failed: {e}", exc_info=True)
        return {"error": str(e)}


async def _run() -> dict:
    from app.services.metric_engine import run_refresh

    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SM = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with SM() as db:
            user = (await db.execute(
                select(User).order_by(User.id.asc()).limit(1)
            )).scalar_one_or_none()
            if not user:
                logger.warning("refresh_portfolio_snapshots: no user found")
                return {"skipped": "no_user"}

            run = await run_refresh(db, user, scope="portfolio")
            logger.info(
                "Portfolio metric snapshots done: run_id=%s ok=%s failed=%s",
                run.id, run.stocks_ok, run.stocks_failed,
            )
            return {
                "run_id": run.id,
                "stocks_total": run.stocks_total,
                "stocks_ok": run.stocks_ok,
                "stocks_failed": run.stocks_failed,
                "status": run.status,
            }
    finally:
        await engine.dispose()
