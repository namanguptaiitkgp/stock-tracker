"""SEBI PMS quarterly disclosure ingestion.

Discovers newly published PMS disclosures on sebi.gov.in, downloads each
PDF, parses via `sebi_pdf_parser.parse_pdf`, and upserts rows into
`pms_managers` + `pms_strategy_holdings_quarterly`.

Scaffolded — needs real SEBI PMS PDF samples to finish implementation.
The celery task `sebi.ingest_pms_quarterly` wraps this in `ingestion_run`
and marks the run as `partial` with a reason until real parsing ships.
"""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)


async def ingest_pms_quarterly(report_quarter: date | None = None) -> dict:
    """Entrypoint — called by celery task. Currently a stub."""
    q = report_quarter or _previous_quarter_end(date.today())
    return {
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "partial_reason": "SEBI PMS PDF parser not yet implemented — pending real fixture PDFs",
        "report_quarter": q.isoformat(),
    }


def _previous_quarter_end(today: date) -> date:
    """Return the most-recent completed quarter-end date prior to `today`."""
    q_month = ((today.month - 1) // 3) * 3 + 1  # start of current quarter
    last_q_month = q_month - 3
    year = today.year
    if last_q_month <= 0:
        last_q_month += 12
        year -= 1
    # last day of last_q_month + 2 = quarter end
    from calendar import monthrange

    end_month = last_q_month + 2
    end_year = year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    last_day = monthrange(end_year, end_month)[1]
    return date(end_year, end_month, last_day)
