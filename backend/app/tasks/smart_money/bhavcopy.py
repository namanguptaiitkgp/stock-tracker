"""Celery task for NSE end-of-day bhavcopy (with delivery %)."""

from __future__ import annotations

import asyncio
import logging

from app.services.smart_money.bhavcopy import sync_bhavcopy
from app.services.smart_money.run_logger import ingestion_run
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.smart_money.bhavcopy.ingest_nse_daily", queue="data")
def ingest_nse_daily() -> dict:
    async def run() -> dict:
        async with ingestion_run(
            source="nse_bhavcopy",
            task_name="app.tasks.smart_money.bhavcopy.ingest_nse_daily",
            celery_task_id=ingest_nse_daily.request.id if hasattr(ingest_nse_daily, "request") else None,
        ) as ctx:
            result = await sync_bhavcopy()
            ctx.fetched = result.get("fetched", 0)
            ctx.inserted = result.get("inserted", 0)
            ctx.updated = result.get("updated", 0)
            ctx.skipped = result.get("skipped", 0)
            ctx.meta.update({k: v for k, v in result.items() if k in {"url", "trade_date", "bytes", "attempts"}})
            return result

    return asyncio.run(run())
