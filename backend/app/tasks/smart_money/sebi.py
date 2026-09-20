"""Celery tasks for SEBI PMS + AIF quarterly ingestion."""

from __future__ import annotations

import asyncio
import logging

from app.services.smart_money.run_logger import ingestion_run
from app.services.smart_money.sebi_aif import ingest_aif_quarterly as _aif
from app.services.smart_money.sebi_pms import ingest_pms_quarterly as _pms
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.smart_money.sebi.ingest_pms_quarterly", queue="analysis")
def ingest_pms_quarterly() -> dict:
    async def run() -> dict:
        async with ingestion_run(
            source="sebi_pms",
            task_name="app.tasks.smart_money.sebi.ingest_pms_quarterly",
            celery_task_id=ingest_pms_quarterly.request.id if hasattr(ingest_pms_quarterly, "request") else None,
        ) as ctx:
            result = await _pms()
            ctx.fetched = result.get("fetched", 0)
            ctx.inserted = result.get("inserted", 0)
            ctx.updated = result.get("updated", 0)
            ctx.skipped = result.get("skipped", 0)
            if reason := result.get("partial_reason"):
                ctx.mark_partial(reason)
            ctx.meta["report_quarter"] = result.get("report_quarter")
            return result

    return asyncio.run(run())


@celery_app.task(name="app.tasks.smart_money.sebi.ingest_aif_quarterly", queue="analysis")
def ingest_aif_quarterly() -> dict:
    async def run() -> dict:
        async with ingestion_run(
            source="sebi_aif",
            task_name="app.tasks.smart_money.sebi.ingest_aif_quarterly",
            celery_task_id=ingest_aif_quarterly.request.id if hasattr(ingest_aif_quarterly, "request") else None,
        ) as ctx:
            result = await _aif()
            ctx.fetched = result.get("fetched", 0)
            ctx.inserted = result.get("inserted", 0)
            ctx.updated = result.get("updated", 0)
            ctx.skipped = result.get("skipped", 0)
            if reason := result.get("partial_reason"):
                ctx.mark_partial(reason)
            ctx.meta["report_quarter"] = result.get("report_quarter")
            return result

    return asyncio.run(run())
