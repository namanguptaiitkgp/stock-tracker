"""Celery task: quarterly shareholding pattern (BSE)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.services.smart_money.run_logger import ingestion_run
from app.services.smart_money.shareholding_pattern import sync_shareholding_patterns
from app.services.smart_money.validation import validate_run
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.smart_money.shareholding.ingest_bse_quarterly", queue="data")
def ingest_bse_quarterly() -> dict:
    async def run() -> dict:
        task_id = ingest_bse_quarterly.request.id if hasattr(ingest_bse_quarterly, "request") else None
        async with ingestion_run(
            source="shareholding_pattern",
            task_name="app.tasks.smart_money.shareholding.ingest_bse_quarterly",
            celery_task_id=task_id,
        ) as ctx:
            result = await sync_shareholding_patterns()
            ctx.fetched = result.get("fetched", 0)
            ctx.inserted = result.get("inserted", 0)
            ctx.updated = result.get("updated", 0)
            ctx.skipped = result.get("skipped", 0)
            ctx.meta["bytes"] = result.get("bytes")
            ctx.meta["targets"] = result.get("targets")
            ctx.meta["failures"] = result.get("failures")
            if result.get("note"):
                ctx.meta["note"] = result["note"]
                ctx.mark_partial(result["note"])
            elif result.get("failures", 0) > 0:
                ctx.warnings = result["failures"]
                ctx.mark_partial(f"{result['failures']} per-symbol failures")

            warnings = await validate_run(
                "shareholding_pattern", datetime.now().date(), ctx.fetched
            )
            if warnings:
                ctx.meta["validation_warnings"] = warnings
                ctx.warnings = (ctx.warnings or 0) + len(warnings)
                ctx.mark_partial("validation warnings")
            return result

    return asyncio.run(run())
