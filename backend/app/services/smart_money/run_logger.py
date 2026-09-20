"""Audit-log every ingestion run to `ingestion_runs`.

Usage:

    async with ingestion_run(source="amfi_mf", task_name="...") as run:
        rows = await fetch()
        run.fetched = len(rows)
        inserted, updated, skipped = await upsert(rows)
        run.inserted, run.updated, run.skipped = inserted, updated, skipped
        run.meta["gemini_fallback_count"] = 3

On normal exit: status=success, finished_at + duration_ms filled.
On exception:   status=failed, error_class + error_message filled, exception re-raises.
Call run.mark_partial("reason") to finalize as status=partial (still success-ish
but means some items were skipped/failed inside — useful for multi-PDF jobs).
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from sqlalchemy import update

from app.db.session import async_session
from app.models.smart_money import IngestionRun

logger = logging.getLogger(__name__)


class RunContext:
    def __init__(self, row_id: int):
        self._row_id = row_id
        self._started_mono = time.monotonic()
        self.fetched: int = 0
        self.inserted: int = 0
        self.updated: int = 0
        self.skipped: int = 0
        self.warnings: int = 0
        self.meta: dict[str, Any] = {}
        self._partial_reason: str | None = None

    @property
    def row_id(self) -> int:
        return self._row_id

    def mark_partial(self, reason: str) -> None:
        self._partial_reason = reason
        self.meta.setdefault("partial_reasons", []).append(reason)


@asynccontextmanager
async def ingestion_run(
    *,
    source: str,
    task_name: str | None = None,
    celery_task_id: str | None = None,
    triggered_by: str = "beat",
) -> AsyncIterator[RunContext]:
    started_at = datetime.now(tz=timezone.utc)

    async with async_session() as session:
        row = IngestionRun(
            source=source,
            task_name=task_name,
            celery_task_id=celery_task_id,
            triggered_by=triggered_by,
            status="running",
            started_at=started_at,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        row_id = row.id

    ctx = RunContext(row_id)
    status = "success"
    error_class: str | None = None
    error_message: str | None = None

    try:
        yield ctx
    except Exception as exc:
        status = "failed"
        error_class = exc.__class__.__name__
        error_message = str(exc)[:4000]
        logger.exception("ingestion_run %s failed (source=%s)", row_id, source)
        raise
    finally:
        if status == "success" and ctx._partial_reason:
            status = "partial"

        duration_ms = int((time.monotonic() - ctx._started_mono) * 1000)
        finished_at = datetime.now(tz=timezone.utc)

        try:
            async with async_session() as session:
                await session.execute(
                    update(IngestionRun)
                    .where(IngestionRun.id == row_id)
                    .values(
                        status=status,
                        finished_at=finished_at,
                        duration_ms=duration_ms,
                        records_fetched=ctx.fetched,
                        records_inserted=ctx.inserted,
                        records_updated=ctx.updated,
                        records_skipped=ctx.skipped,
                        warnings=ctx.warnings,
                        error_class=error_class,
                        error_message=error_message,
                        meta=ctx.meta or None,
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("failed to persist ingestion_run finalization for row %s", row_id)


# Cadence (hours) used to flag stale sources to the UI.
SOURCE_CADENCE_HOURS: dict[str, float] = {
    "amfi_nav": 26,
    "amfi_mf": 24 * 34,
    "sebi_pms": 24 * 100,
    "sebi_aif": 24 * 100,
    "nse_deals": 30,
    "bse_deals": 30,
    "nse_bhavcopy": 30,
    "nse_asm_gsm": 30,
    "bse_bhavcopy": 30,
    "nse_insider": 30,
    "nse_corporate_announcements": 30,
    "fii_dii_stock": 30,
    "shareholding_pattern": 24 * 95,  # quarterly + a few days slack
    "smart_money_rollup": 30,
    "morning_pipeline": 26,
    "news_scan": 26,
    "brief_refresh": 26,
    "instrument_sync": 192,
    "review_alerts": 26,
    "review_alerts_intraday": 1,
    "watchlist_snapshot": 26,
    "market_indices_quotes": 0.15,
    "market_indices_summaries": 26,
}
