"""Celery task: per-stock FII/DII activity (placeholder; see service docstring)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.services.fii_dii import sync_stock_level_fii_dii
from app.services.smart_money.run_logger import ingestion_run
from app.services.smart_money.validation import validate_run
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.smart_money.fii_dii_stock.ingest_nse_daily", queue="data"
)
def ingest_nse_daily() -> dict:
    async def run() -> dict:
        task_id = ingest_nse_daily.request.id if hasattr(ingest_nse_daily, "request") else None
        async with ingestion_run(
            source="fii_dii_stock",
            task_name="app.tasks.smart_money.fii_dii_stock.ingest_nse_daily",
            celery_task_id=task_id,
        ) as ctx:
            result = await sync_stock_level_fii_dii()
            ctx.fetched = result.get("fetched", 0)
            ctx.inserted = result.get("inserted", 0)
            ctx.updated = result.get("updated", 0)
            ctx.skipped = result.get("skipped", 0)
            if "note" in result:
                ctx.meta["note"] = result["note"]
                ctx.mark_partial("upstream not wired")

            warnings = await validate_run("fii_dii_stock", datetime.now().date(), ctx.fetched)
            if warnings:
                ctx.meta["validation_warnings"] = warnings
                ctx.warnings = len(warnings)
                ctx.mark_partial("validation warnings")
            return result

    return asyncio.run(run())
