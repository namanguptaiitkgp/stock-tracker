"""AMFI daily NAV feed (https://www.amfiindia.com/spages/NAVAll.txt).

The NAVAll.txt file is pipe-delimited with two kinds of context lines
mixed into the data rows:

    (blank line)
      UTI Mutual Fund              <- fund_house
    Open Ended Schemes(Equity Scheme - Large Cap Fund)   <- scheme_type / category
    101672;INF789F01018;INF789F01026;UTI Mastershare - IDCW;123.4567;21-Apr-2026
    101673;INF789F02018;...

We keep `fund_house` and `scheme_category` as rolling context while we
walk the file; each data row upserts one `mf_schemes` row.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session
from app.models.smart_money import MfScheme

logger = logging.getLogger(__name__)

NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
REQUEST_TIMEOUT = 60
USER_AGENT = "algo-trader/1.0 (+https://github.com/namanguptaiitkgp/stock-tracker)"


def _parse_nav_date(raw: str) -> datetime.date | None:
    raw = raw.strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(raw: str) -> float | None:
    raw = raw.strip()
    if not raw or raw.upper() in {"N.A.", "NA", "-"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_nav_text(text: str) -> list[dict]:
    rows: list[dict] = []
    fund_house: str | None = None
    scheme_type: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Scheme Code") or line.startswith("Open Ended Schemes") or line.startswith("Close Ended Schemes") or line.startswith("Interval Fund"):
            if line.startswith("Scheme Code"):
                continue
            scheme_type = line
            continue
        if ";" not in line:
            fund_house = line
            continue

        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6:
            continue
        code, isin_g, isin_d, scheme_name, nav_str, nav_date_str = parts[:6]
        if not code:
            continue
        rows.append(
            {
                "amfi_scheme_code": code,
                "isin_growth": isin_g or None,
                "isin_div_reinvest": isin_d or None,
                "scheme_name": scheme_name,
                "nav": _parse_float(nav_str),
                "nav_date": _parse_nav_date(nav_date_str),
                "fund_house": fund_house,
                "scheme_type": scheme_type,
            }
        )
    return rows


async def fetch_nav_text() -> str:
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        resp = await client.get(NAV_URL)
        resp.raise_for_status()
        return resp.text


async def upsert_schemes(rows: list[dict]) -> tuple[int, int, int]:
    """Returns (inserted, updated, skipped)."""
    if not rows:
        return (0, 0, 0)

    inserted = 0
    updated = 0
    skipped = 0
    now_utc = datetime.utcnow()

    async with async_session() as session:
        existing_codes = set()
        existing = await session.execute(
            select(MfScheme.amfi_scheme_code).where(
                MfScheme.amfi_scheme_code.in_([r["amfi_scheme_code"] for r in rows])
            )
        )
        existing_codes = {code for (code,) in existing.all()}

        for r in rows:
            if not r["amfi_scheme_code"] or not r["scheme_name"]:
                skipped += 1
                continue
            is_new = r["amfi_scheme_code"] not in existing_codes

            stmt = pg_insert(MfScheme).values(
                amfi_scheme_code=r["amfi_scheme_code"],
                scheme_name=r["scheme_name"],
                fund_house=r.get("fund_house"),
                scheme_type=r.get("scheme_type"),
                isin_growth=r.get("isin_growth"),
                isin_div_reinvest=r.get("isin_div_reinvest"),
                nav=r.get("nav"),
                nav_date=r.get("nav_date"),
                last_synced_at=now_utc,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["amfi_scheme_code"],
                set_={
                    "scheme_name": stmt.excluded.scheme_name,
                    "fund_house": stmt.excluded.fund_house,
                    "scheme_type": stmt.excluded.scheme_type,
                    "isin_growth": stmt.excluded.isin_growth,
                    "isin_div_reinvest": stmt.excluded.isin_div_reinvest,
                    "nav": stmt.excluded.nav,
                    "nav_date": stmt.excluded.nav_date,
                    "last_synced_at": stmt.excluded.last_synced_at,
                },
            )
            await session.execute(stmt)
            if is_new:
                inserted += 1
            else:
                updated += 1

        await session.commit()
    return (inserted, updated, skipped)


async def sync_nav() -> dict:
    """Entrypoint — called by the celery task. Returns counts for the caller to
    stash on the RunContext."""
    text = await fetch_nav_text()
    rows = _parse_nav_text(text)
    inserted, updated, skipped = await upsert_schemes(rows)
    return {
        "fetched": len(rows),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "bytes": len(text),
    }
