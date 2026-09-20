"""Celery task: NSE insider trading disclosures (PIT Reg 7)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.services.smart_money.insider_disclosures import sync_nse_insider
from app.services.smart_money.run_logger import ingestion_run
from app.services.smart_money.validation import validate_run
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.smart_money.insider.ingest_nse_daily", queue="data")
def ingest_nse_daily() -> dict:
    async def run() -> dict:
        task_id = ingest_nse_daily.request.id if hasattr(ingest_nse_daily, "request") else None
        async with ingestion_run(
            source="nse_insider",
            task_name="app.tasks.smart_money.insider.ingest_nse_daily",
            celery_task_id=task_id,
        ) as ctx:
            result = await sync_nse_insider()
            ctx.fetched = result.get("fetched", 0)
            ctx.inserted = result.get("inserted", 0)
            ctx.updated = result.get("updated", 0)
            ctx.skipped = result.get("skipped", 0)
            ctx.meta["bytes"] = result.get("bytes")
            ctx.meta["from_date"] = result.get("from_date")
            ctx.meta["to_date"] = result.get("to_date")

            warnings = await validate_run("nse_insider", datetime.now().date(), ctx.fetched)
            if warnings:
                ctx.meta["validation_warnings"] = warnings
                ctx.warnings = len(warnings)
                ctx.mark_partial("validation warnings")
            return result

    return asyncio.run(run())
