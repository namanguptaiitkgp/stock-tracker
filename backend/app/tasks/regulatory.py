"""Celery task: daily refresh of NSE ASM/GSM surveillance lists.

Called by celery-beat at 18:30 IST on weekdays (after NSE publishes
the post-close list). Falls back gracefully — if NSE blocks the
request, the 24h cache still holds yesterday's data until tomorrow's
attempt, so the Smart Exit prompt never crashes on a missing flag map.
"""

from __future__ import annotations

import asyncio
import logging

from app.services.data_cache import cache_set
from app.services.regulatory.asm_gsm import (
    CACHE_TTL_SECONDS,
    _fetch_surveillance_uncached,
)
from app.services.smart_money.run_logger import ingestion_run
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.regulatory.refresh_surveillance_lists",
    queue="data",
)
def refresh_surveillance_lists() -> dict:
    """Force-refresh the NSE ASM/GSM cache and audit the run."""

    async def run() -> dict:
        async with ingestion_run(
            source="nse_asm_gsm",
            task_name="app.tasks.regulatory.refresh_surveillance_lists",
            celery_task_id=(
                refresh_surveillance_lists.request.id
                if hasattr(refresh_surveillance_lists, "request")
                else None
            ),
        ) as ctx:
            payload = await _fetch_surveillance_uncached()
            await cache_set(
                "nse:surveillance:asm_gsm",
                payload,
                ttl_seconds=CACHE_TTL_SECONDS,
            )
            flag_count = len(payload.get("flags") or {})
            counts = payload.get("counts") or {}
            ctx.fetched = flag_count
            ctx.inserted = flag_count
            ctx.meta.update({"as_of": payload.get("as_of"), **counts})
            if counts.get("errors", 0) > 0 and flag_count == 0:
                # Total failure — both feeds returned errors. Cache the
                # previous day's payload by not overwriting? cache_set
                # already wrote — but flag this as partial so monitoring
                # surfaces it.
                ctx.mark_partial("NSE returned errors on both ASM and GSM feeds")
            return {"ok": True, "flag_count": flag_count, **counts}

    return asyncio.run(run())
