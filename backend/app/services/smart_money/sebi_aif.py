"""SEBI AIF quarterly disclosure ingestion (Category II and III).

Parallels `sebi_pms.py`. Uses `sebi_pdf_parser.parse_pdf` for extraction
and upserts into `aif_funds` + `aif_holdings_quarterly`.

Cat III AIFs are the "shark-adjacent" pooled vehicles (hedge-fund-style),
so their holdings are high-signal for following individual HNI conviction
at an aggregated level.

Scaffolded — needs real SEBI AIF PDF samples to finish implementation.
"""

from __future__ import annotations

import logging
from datetime import date

from app.services.smart_money.sebi_pms import _previous_quarter_end

logger = logging.getLogger(__name__)


async def ingest_aif_quarterly(report_quarter: date | None = None) -> dict:
    """Entrypoint — called by celery task. Currently a stub."""
    q = report_quarter or _previous_quarter_end(date.today())
    return {
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "partial_reason": "SEBI AIF PDF parser not yet implemented — pending real fixture PDFs",
        "report_quarter": q.isoformat(),
    }
