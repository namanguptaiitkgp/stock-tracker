"""AMFI monthly mutual-fund portfolio XLS ingestion.

SCOPE: Each AMC publishes a scheme-wise portfolio disclosure XLS monthly,
typically by the 10th. These land on the AMFI portal (via a form-driven
download) or on the AMC's own site. There is no single canonical URL
pattern across AMCs, so the harvester has two parts:

1. `discover_amc_urls(as_of)` — given a target month, find each AMC's
   download URL. Today this is a scraping task against the AMFI portal
   (JS-driven form; may require Playwright). Stubbed here — populate
   `KNOWN_AMC_URLS` below with static URLs per AMC as you add support.

2. `parse_amc_xls(xls_bytes, scheme_hint)` — parse a single XLS into rows.
   AMFI recommends a standard sheet layout but individual AMCs vary.
   Generic parser uses openpyxl/pandas to find tables with columns like
   "Name of Instrument", "ISIN", "Quantity", "Market Value", "% to NAV",
   grouped by scheme headers.

Both pieces are placeholder — the celery task `amfi.ingest_monthly_portfolios`
wraps them in `ingestion_run(...)` and marks the run as partial with a clear
reason when discovery yields nothing. When you ship real XLS samples,
flesh this module out and the rest of the pipeline (rollup, prompt, UI)
automatically starts picking up MF holdings data.

Targets for MfHoldingMonthly rows per parsed sheet:
    scheme_id          FK -> mf_schemes (via amfi_scheme_code match)
    symbol             resolved from instrument_name/isin
    isin
    instrument_name_raw
    report_month       first day of the month the file covers
    units              Quantity
    market_value_inr   Market Value
    pct_of_aum         % to NAV
    prev_units         filled on second run by comparing to previous month
    change_units       units - prev_units
    change_type        'added' | 'reduced' | 'new' | 'exited' | 'unchanged'
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


KNOWN_AMC_URLS: dict[str, dict] = {
    # Populate with canonical download URLs per AMC as they are verified.
    # Example:
    # "HDFC_AMC": {"name": "HDFC Mutual Fund",
    #              "template_url": "https://www.hdfcfund.com/.../monthly/{YYYYMM}.xlsx"},
}


async def discover_amc_urls(report_month: date) -> list[dict[str, Any]]:
    """Return list of {amc, url} for the given month. Stub — returns []."""
    logger.info("discover_amc_urls: stub called for %s (returns empty)", report_month)
    return []


async def parse_amc_xls(xls_bytes: bytes, report_month: date) -> list[dict[str, Any]]:
    """Parse AMC monthly portfolio XLSX into normalized rows. Stub."""
    raise NotImplementedError("parse_amc_xls: real AMFI XLS samples needed to implement")


async def ingest_monthly_portfolios(report_month: date | None = None) -> dict:
    """Entrypoint called by celery task. Currently a stub that records a
    partial run with an explanatory message."""
    report_month = report_month or date.today().replace(day=1)
    urls = await discover_amc_urls(report_month)
    return {
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "partial_reason": "AMC URL discovery not yet implemented — no files to parse",
        "report_month": report_month.isoformat(),
        "amc_count": len(urls),
    }
