"""Daily DB-prune cron.

Trims rows that have outlived their utility from the high-volume tables:
- fetch_cache: expired entries older than 7 days
- ingestion_runs: completion records older than 30 days
- news_sentiment_cache: older than 30 days (current sentiment kept fresh
  by the per-symbol path)
- daily_news_reports: older than 90 days (historical view in News Inbox
  doesn't go past a quarter)
- llm_calls / scrape_events: observability logs older than 30 days

Logs counts deleted so we can spot anomalies in the activity monitor.
"""

from __future__ import annotations

import asyncio
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()


# (table, time_column, retention_days)
PRUNE_PLANS = [
    ("fetch_cache", "expires_at", 7),
    ("ingestion_runs", "finished_at", 30),
    # Use `created_at` (non-null on Base) rather than `analyzed_at`
    # (nullable on the model) so any NULL-analyzed_at rows still get GC'd.
    # The semantic difference is sub-second in current writers — they
    # set both columns within the same atomic db.add()/commit.
    ("news_sentiment_cache", "created_at", 30),
    ("daily_news_reports", "created_at", 90),
    ("llm_calls", "ts", 30),
    ("scrape_events", "ts", 30),
]


@celery_app.task(
    name="app.tasks.db_prune.run_db_prune",
    queue="data",
    bind=True,
)
def run_db_prune(self) -> dict:
    logger.info("=== DB prune started ===")
    try:
        return asyncio.run(_prune())
    except Exception as e:
        logger.error(f"DB prune failed: {e}", exc_info=True)
        return {"error": str(e)}


async def _prune() -> dict:
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SM = async_sessionmaker(engine, expire_on_commit=False)
    results: dict[str, int | str] = {}

    async with SM() as db:
        for table, col, days in PRUNE_PLANS:
            try:
                # Check table exists first (avoids errors on partial deploys).
                exists = (await db.execute(text(
                    "SELECT to_regclass(:t) IS NOT NULL"
                ), {"t": f"public.{table}"})).scalar_one()
                if not exists:
                    results[table] = "missing"
                    continue
                res = await db.execute(text(
                    f"DELETE FROM {table} WHERE {col} < NOW() - INTERVAL '{int(days)} days' "
                    "RETURNING 1"
                ))
                # rowcount may be -1 for some drivers; fall back to len().
                deleted = res.rowcount if res.rowcount is not None and res.rowcount >= 0 else len(list(res))
                await db.commit()
                results[table] = deleted
                logger.info(f"  Pruned {deleted} rows from {table} (>{days}d)")
            except Exception as e:
                await db.rollback()
                logger.warning(f"  Prune failed for {table}: {e}")
                results[table] = f"error:{e!s}"

    await engine.dispose()
    return results
