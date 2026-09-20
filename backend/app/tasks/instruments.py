"""Weekly Kite instrument-list refresh task.

Wraps `app.services.instrument_sync.sync_instruments()` so it can run on a
beat schedule. Uses the first connected admin user's Kite credentials —
production setups with multiple users should still get fresh instruments
since the universe is shared (NSE/BSE listings).
"""

from __future__ import annotations

import asyncio
import logging

from kiteconnect import KiteConnect
from sqlalchemy import select

from app.db.session import async_session
from app.models.user import User
from app.services.instrument_sync import sync_instruments
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run(celery_task_id: str | None = None) -> dict:
    from app.services.smart_money.run_logger import ingestion_run

    async with ingestion_run(
        source="instrument_sync",
        task_name="app.tasks.instruments.sync_instruments",
        celery_task_id=celery_task_id,
    ) as ctx:
        async with async_session() as db:
            res = await db.execute(
                select(User)
                .where(User.kite_api_key.isnot(None), User.kite_access_token.isnot(None))
                .limit(1)
            )
            user = res.scalar_one_or_none()
            if not user:
                logger.warning("instrument-sync skipped: no user has Kite connected.")
                ctx.meta["skipped"] = "no_kite_user"
                return {"skipped": True, "reason": "no_kite_user"}

            kite = KiteConnect(api_key=user.kite_api_key)
            kite.set_access_token(user.kite_access_token)
            result = await sync_instruments(kite, db)
            ctx.fetched = result.get("total", result.get("fetched", 0))
            ctx.inserted = result.get("inserted", 0)
            ctx.updated = result.get("updated", 0)
            return result


@celery_app.task(name="app.tasks.instruments.sync_instruments", bind=True)
def sync_instruments_task(self) -> dict:
    return asyncio.run(_run(celery_task_id=self.request.id))
