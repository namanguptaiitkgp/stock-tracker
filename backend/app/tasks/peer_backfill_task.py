"""Celery wrapper for the peer-backfill job.

Generation runs concurrently inside the service; this task just provides the
async event loop + DB session-maker, so the work isn't blocked on the
request thread.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.user import User

settings = get_settings()
from app.services.peer_backfill import backfill_missing_peers
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.peer_backfill.run_peer_backfill",
    queue="analysis",
    bind=True,
)
def run_peer_backfill(self, user_id: int | None = None) -> dict:
    """If `user_id` is None, falls back to the admin user (first user
    in the DB). Lets the weekly beat schedule fire without hard-coding
    a user_id.
    """
    logger.info(f"=== peer_backfill started for user_id={user_id} ===")

    async def _run() -> dict:
        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        SM = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with SM() as db:
                if user_id is None:
                    user = (await db.execute(
                        select(User).order_by(User.id.asc()).limit(1)
                    )).scalar_one_or_none()
                else:
                    user = (await db.execute(
                        select(User).where(User.id == user_id)
                    )).scalar_one_or_none()
                if not user:
                    return {"error": "no user found"}

                summary = await backfill_missing_peers(user, SM, db=db)
                logger.info(f"peer_backfill done: {summary}")
                return summary
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as e:
        logger.error(f"peer_backfill failed: {e}", exc_info=True)
        return {"error": str(e)}
