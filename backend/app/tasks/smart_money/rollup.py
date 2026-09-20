"""Celery task for composite smart-money rollup."""

from __future__ import annotations

import asyncio
import logging

from app.services.smart_money.rollup import compute_rollup
from app.services.smart_money.run_logger import ingestion_run
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.smart_money.rollup.compute", queue="analysis")
def compute() -> dict:
    async def run() -> dict:
        async with ingestion_run(
            source="smart_money_rollup",
            task_name="app.tasks.smart_money.rollup.compute",
            celery_task_id=compute.request.id if hasattr(compute, "request") else None,
        ) as ctx:
            result = await compute_rollup()
            ctx.fetched = result.get("fetched", 0)
            ctx.inserted = result.get("inserted", 0)
            ctx.updated = result.get("updated", 0)
            ctx.skipped = result.get("skipped", 0)
            ctx.meta["as_of"] = result.get("as_of")
            return result

    return asyncio.run(run())
