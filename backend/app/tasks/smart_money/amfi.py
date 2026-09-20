"""Celery tasks for AMFI (mutual fund) ingestion."""

from __future__ import annotations

import asyncio
import logging

from app.services.smart_money.amfi_nav import sync_nav
from app.services.smart_money.run_logger import ingestion_run
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.smart_money.amfi.sync_nav_and_schemes", queue="data")
def sync_nav_and_schemes() -> dict:
    async def run() -> dict:
        async with ingestion_run(
            source="amfi_nav",
            task_name="app.tasks.smart_money.amfi.sync_nav_and_schemes",
            celery_task_id=sync_nav_and_schemes.request.id if hasattr(sync_nav_and_schemes, "request") else None,
        ) as ctx:
            result = await sync_nav()
            ctx.fetched = result.get("fetched", 0)
            ctx.inserted = result.get("inserted", 0)
            ctx.updated = result.get("updated", 0)
            ctx.skipped = result.get("skipped", 0)
            ctx.meta["bytes"] = result.get("bytes")
            return result

    return asyncio.run(run())
