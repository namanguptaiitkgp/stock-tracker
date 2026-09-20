"""Celery task for AMFI monthly MF portfolio ingestion (stub)."""

from __future__ import annotations

import asyncio
import logging

from app.services.smart_money.amfi_mf import ingest_monthly_portfolios
from app.services.smart_money.run_logger import ingestion_run
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.smart_money.amfi_monthly.ingest", queue="analysis")
def ingest() -> dict:
    async def run() -> dict:
        async with ingestion_run(
            source="amfi_mf",
            task_name="app.tasks.smart_money.amfi_monthly.ingest",
            celery_task_id=ingest.request.id if hasattr(ingest, "request") else None,
        ) as ctx:
            result = await ingest_monthly_portfolios()
            ctx.fetched = result.get("fetched", 0)
            ctx.inserted = result.get("inserted", 0)
            ctx.updated = result.get("updated", 0)
            ctx.skipped = result.get("skipped", 0)
            if reason := result.get("partial_reason"):
                ctx.mark_partial(reason)
            ctx.meta["report_month"] = result.get("report_month")
            return result

    return asyncio.run(run())
