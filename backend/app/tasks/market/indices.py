"""Celery tasks for indices strip — quote refresh + summary refresh."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db.session import async_session
from app.models.user import User
from app.services.market.indices_quotes import fetch_and_cache_quotes
from app.services.market.indices_registry import INDICES
from app.services.market.indices_summary import refresh_summary_for
from app.services.smart_money.run_logger import ingestion_run
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _first_user() -> User | None:
    """Indices are shared market data — we just need any user's Kite
    token to fetch quotes and any user's Gemini key for summaries. For
    the single-admin deployment this is always user id=1."""
    async with async_session() as session:
        result = await session.execute(select(User).order_by(User.id).limit(1))
        return result.scalar_one_or_none()


@celery_app.task(name="app.tasks.market.indices.refresh_quotes", queue="data")
def refresh_quotes() -> dict:
    async def run() -> dict:
        async with ingestion_run(
            source="market_indices_quotes",
            task_name="app.tasks.market.indices.refresh_quotes",
            celery_task_id=refresh_quotes.request.id if hasattr(refresh_quotes, "request") else None,
        ) as ctx:
            user = await _first_user()
            if user is None:
                ctx.mark_partial("no user available to authenticate Kite")
                return {"fetched": 0, "inserted": 0}
            quotes = await fetch_and_cache_quotes(user)
            ok = [q for q in quotes if q.get("status") == "ok"]
            ctx.fetched = len(quotes)
            ctx.inserted = len(ok)
            ctx.skipped = len(quotes) - len(ok)
            ctx.meta["slugs"] = [q["slug"] for q in quotes]
            return {"fetched": len(quotes), "ok": len(ok)}

    return asyncio.run(run())


@celery_app.task(name="app.tasks.market.indices.refresh_summaries", queue="analysis")
def refresh_summaries() -> dict:
    async def run() -> dict:
        async with ingestion_run(
            source="market_indices_summaries",
            task_name="app.tasks.market.indices.refresh_summaries",
            celery_task_id=refresh_summaries.request.id if hasattr(refresh_summaries, "request") else None,
        ) as ctx:
            user = await _first_user()
            if user is None:
                ctx.mark_partial("no user available for Gemini key")
                return {"fetched": 0, "inserted": 0}

            ok, failed = 0, 0
            for entry in INDICES:
                try:
                    async with async_session() as summary_db:
                        result = await refresh_summary_for(entry, user, db=summary_db)
                    if result.get("error_message"):
                        failed += 1
                    else:
                        ok += 1
                except Exception as e:
                    logger.warning("summary for %s failed: %s", entry.slug, e)
                    failed += 1
            ctx.fetched = len(INDICES)
            ctx.inserted = ok
            ctx.skipped = failed
            if failed:
                ctx.mark_partial(f"{failed} of {len(INDICES)} summaries failed or had no headlines")
            return {"ok": ok, "failed": failed}

    return asyncio.run(run())
