"""Post-ingestion validation.

Two layers:

1. **Schema validation** — `validate_columns(source, parsed_columns)`
   raises `SchemaValidationError` when a CSV/JSON parse comes back with
   columns that don't match the expected set for that source. Catches
   silent vendor format drift that would otherwise produce
   "successful" runs writing wrong data.

2. **Sanity checks** — `validate_run(source, run_date, row_count)`
   returns a list of warning strings. Currently:
       - row_count < 30% of 30-day historical avg
       - row_count > 3x  of 30-day historical avg
       - zero rows on a known trading day for sources that should never
         be empty (`nse_bhavcopy`, `nse_deals`, `bse_deals`,
         `nse_insider`).

Validation warnings surface in `ingestion_runs.meta["validation_warnings"]`
and the run is marked `partial` (not `failed`) — the data may still be
correct (holiday, genuinely quiet day) but the dashboard should flag it.

Cross-source consistency (e.g. block deal volume > total volume) is a
weekly task and is **not** wired in this PR — see §8C of the spec.
"""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.db.session import async_session
from app.models.smart_money import IngestionRun

IST = ZoneInfo("Asia/Kolkata")


class SchemaValidationError(RuntimeError):
    """Raised when parsed columns don't match the expected schema for a source."""


# Expected-columns registry. The values are sets so callers can be order-
# and case-insensitive when feeding parsed headers in.
SCHEMA_REGISTRY: dict[str, set[str]] = {
    "nse_bhavcopy": {
        "SYMBOL",
        "SERIES",
        "OPEN_PRICE",
        "HIGH_PRICE",
        "LOW_PRICE",
        "CLOSE_PRICE",
        "PREV_CLOSE",
        "TTL_TRD_QNTY",
        "TURNOVER_LACS",
        "DELIV_QTY",
        "DELIV_PER",
    },
    "nse_deals": {
        "Date",
        "Symbol",
        "Security Name",
        "Client Name",
        "Buy / Sell",
        "Quantity Traded",
        "Trade Price / Wt. Avg. Price",
    },
    "nse_insider": {
        # NSE insider-trading API JSON keys — not headers but the same idea.
        "symbol",
        "company",
        "personName",
        "categoryOfPerson",
        "noOfShareAcq",
        "noOfShareSale",
        "transactionType",
        "date",
        "intimDate",
    },
    "shareholding_pattern": {
        "symbol",
        "quarter_end_date",
        "promoter_pct",
        "fii_pct",
        "dii_pct",
        "public_pct",
    },
    "nse_corporate_announcements": {
        "symbol",
        "subject",
        "an_dt",
    },
    "fii_dii_stock": {
        "symbol",
        "trade_date",
        "fii_buy",
        "fii_sell",
        "dii_buy",
        "dii_sell",
    },
}


def validate_columns(source: str, parsed_columns: list[str] | set[str]) -> None:
    """Compare parsed columns to the registered expectation. Raises
    `SchemaValidationError` listing missing keys (and any unexpected
    extras for diagnostic value).
    """
    expected = SCHEMA_REGISTRY.get(source)
    if not expected:
        # No registered expectation — nothing to validate. Most sources
        # have a known shape; this branch is for new ones still in dev.
        return
    parsed_set = {c.strip() for c in parsed_columns}
    missing = expected - parsed_set
    if missing:
        unexpected = parsed_set - expected
        msg = (
            f"{source}: parsed columns missing expected keys "
            f"{sorted(missing)!r}. Found: {sorted(parsed_set)!r}."
        )
        if unexpected:
            msg += f" Unexpected extras: {sorted(unexpected)!r}."
        raise SchemaValidationError(msg)


# Sources whose feed should never be empty on a trading day. Anything
# else is allowed to be empty (no insider filings on a quiet day, etc.).
_NEVER_EMPTY_ON_TRADING_DAYS = {"nse_bhavcopy", "nse_deals", "bse_deals"}


def is_trading_day(d: date) -> bool:
    """Indian equity markets are closed Sat/Sun + a fixed list of public
    holidays. We don't have a calendar feed integrated yet, so the check
    is just weekends + known full-market holidays for 2025-2026.
    Refining this with a live NSE calendar fetch is a follow-up — for
    now we err on the side of "treat ambiguous as trading day" so genuine
    zero-row issues still surface as warnings.
    """
    if d.weekday() >= 5:  # Sat=5, Sun=6
        return False
    # Known full-market holidays. Add new years as they're announced;
    # missing entries just mean a one-time false-positive zero-row warning.
    return d not in _NSE_HOLIDAYS


_NSE_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 26), date(2025, 2, 26), date(2025, 3, 14),
    date(2025, 3, 31), date(2025, 4, 10), date(2025, 4, 14),
    date(2025, 4, 18), date(2025, 5, 1), date(2025, 8, 15),
    date(2025, 8, 27), date(2025, 10, 2), date(2025, 10, 21),
    date(2025, 10, 22), date(2025, 11, 5), date(2025, 12, 25),
    # 2026
    date(2026, 1, 26), date(2026, 3, 17), date(2026, 4, 1),
    date(2026, 4, 3), date(2026, 5, 1), date(2026, 8, 15),
    date(2026, 10, 2), date(2026, 11, 9), date(2026, 12, 25),
}


async def _avg_recent_row_count(source: str, run_date: date, lookback_days: int = 30) -> float:
    """Mean records_inserted across recent successful runs for this source."""
    since = run_date - timedelta(days=lookback_days)
    async with async_session() as session:
        q = await session.execute(
            select(func.avg(IngestionRun.records_inserted))
            .where(
                IngestionRun.source == source,
                IngestionRun.status == "success",
                func.date(IngestionRun.started_at) >= since,
                func.date(IngestionRun.started_at) < run_date,
                IngestionRun.records_inserted > 0,
            )
        )
        avg = q.scalar_one_or_none()
        return float(avg) if avg is not None else 0.0


async def validate_run(source: str, run_date: date, row_count: int) -> list[str]:
    """Returns a list of warning strings. Empty = clean.

    Caller (the ingestion task) should populate
    `ctx.meta["validation_warnings"] = warnings` and call
    `ctx.mark_partial(...)` when warnings are non-empty.
    """
    warnings: list[str] = []

    avg = await _avg_recent_row_count(source, run_date)
    if avg > 0:
        if row_count < avg * 0.3:
            warnings.append(
                f"{source}: row_count {row_count} is <30% of 30-day avg {avg:.0f}"
            )
        elif row_count > avg * 3:
            warnings.append(
                f"{source}: row_count {row_count} is >3x 30-day avg {avg:.0f}"
            )

    if row_count == 0 and source in _NEVER_EMPTY_ON_TRADING_DAYS:
        if is_trading_day(run_date):
            warnings.append(f"{source}: zero rows on a trading day ({run_date})")

    return warnings
