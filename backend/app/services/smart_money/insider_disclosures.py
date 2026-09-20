"""NSE insider trading disclosures (PIT Reg 7 / SAST).

Source: https://www.nseindia.com/api/corporates/insiderTrading
        ?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY

Same cookie-seed pattern as `services/smart_money/deals.py`. We pull a
7-day overlapping window so late filings (T+2 deadline + occasional
slips) still land. Dedup is enforced via the unique index on
(symbol, person_name_norm, transaction_date, transaction_type, shares).

The conviction scorer reads:
  - category in ('Promoter', 'Promoter Group') + transaction_type='Buy'
    + mode='Market Purchase' → promoter open-market buying.
The red-flag scorer reads:
  - category in ('Promoter', 'Promoter Group') + transaction_type='Sale'
    over 90 days → promoter selling penalty.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session
from app.models.smart_money import InsiderDisclosure, KnownShark
from app.services.smart_money.deals import _norm_client

logger = logging.getLogger(__name__)

# NSE migrated this endpoint from /api/corporates/insiderTrading to
# /api/corporates-pit some time in 2025. The legacy URL now 404s.
NSE_INSIDER_URL = "https://www.nseindia.com/api/corporates-pit"
REQUEST_TIMEOUT = 45
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
}


def _fmt_nse_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _parse_int(v: Any) -> int | None:
    if v is None or v == "" or v == "-":
        return None
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_float(v: Any) -> float | None:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_iso_date(v: Any) -> date | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_category(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    if "promoter group" in s:
        return "Promoter Group"
    if "promoter" in s:
        return "Promoter"
    if "director" in s:
        return "Director"
    if "designated" in s or "kmp" in s:
        return "Designated Person"
    if "relative" in s or "immediate" in s:
        return "Immediate Relative"
    return raw.strip()[:50]


def _normalize_txn_type(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    if "buy" in s or "acqu" in s:  # acquisition
        return "Buy"
    if "sell" in s or "sale" in s or "dispos" in s:
        return "Sale"
    if "pledge create" in s or "creation" in s:
        return "Pledge"
    if "pledge revok" in s or "release" in s:
        return "Revoke"
    # "invok" matches "invoked" / "invoking"; "invoc" matches "invocation".
    if "invok" in s or "invoc" in s:
        return "Invoke"
    return raw.strip()[:10]


def _row_from_api(item: dict) -> dict | None:
    """Map one row from the NSE insider-trading API JSON to our schema.

    NSE field shape (as of 2026-05-01 against /api/corporates-pit):
        symbol, company, acqName, personCategory, tdpTransactionType,
        secAcq (canonical share count — `buyQuantity`/`sellquantity`
        are often zero even when secAcq is set, so prefer secAcq),
        secVal (INR value), acqfromDt (transaction date),
        intimDt (intimation date), acqMode (e.g. "Market Purchase",
        "ESOP", "Inter-se Transfer"), befAcqSharesPer / afterAcqSharesPer.
    """
    symbol = (item.get("symbol") or "").strip()
    person = (item.get("acqName") or item.get("personName") or "").strip()
    if not symbol or not person:
        return None

    txn_type = _normalize_txn_type(item.get("tdpTransactionType") or item.get("transactionType"))
    if not txn_type:
        return None

    # Pick the first share-count field that parses to a positive int.
    # `or` on raw values would short-circuit on the string "0" (truthy),
    # so we need to parse each and check.
    shares = None
    for field in ("secAcq", "noOfShareAcq", "buyQuantity", "sellquantity", "noOfShareSale"):
        candidate = _parse_int(item.get(field))
        if candidate and candidate > 0:
            shares = candidate
            break
    if shares is None:
        return None

    txn_date = _parse_iso_date(item.get("acqfromDt") or item.get("date"))
    intim_date = _parse_iso_date(item.get("intimDt") or item.get("intimDate"))
    if not txn_date:
        return None
    if not intim_date:
        # Fall back to txn_date so we don't drop the row entirely.
        intim_date = txn_date

    return {
        "symbol": symbol,
        "isin": (item.get("isin") or "").strip()[:12] or None,
        "company_name": (item.get("company") or "").strip()[:255] or None,
        "category": _normalize_category(
            item.get("personCategory") or item.get("categoryOfPerson")
        ) or "Unknown",
        "person_name": person[:255],
        "person_name_norm": _norm_client(person),
        "relation": (item.get("personDesignation") or "").strip()[:100] or None,
        "transaction_type": txn_type[:10],
        "shares": shares,
        "value_inr": _parse_float(item.get("secVal") or item.get("totalAmt")),
        "transaction_date": txn_date,
        "intimation_date": intim_date,
        "mode": (item.get("acqMode") or "").strip()[:50] or None,
        "pre_holding_pct": _parse_float(item.get("befAcqSharesPer")),
        "post_holding_pct": _parse_float(item.get("afterAcqSharesPer")),
        "exchange": "NSE",
        "raw_json": item,
    }


async def fetch_nse_insider(from_date: date, to_date: date) -> tuple[list[dict], int]:
    """Returns (parsed_rows, bytes_downloaded)."""
    params = {
        "index": "equities",
        "from_date": _fmt_nse_date(from_date),
        "to_date": _fmt_nse_date(to_date),
    }
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, headers=HEADERS, follow_redirects=True
    ) as client:
        # Warm NSE cookies (same pattern as deals.py).
        try:
            await client.get("https://www.nseindia.com", timeout=15)
        except Exception:
            pass
        resp = await client.get(NSE_INSIDER_URL, params=params)
        resp.raise_for_status()
        body = resp.text
        try:
            payload = resp.json()
        except Exception:
            logger.warning("nse insider response was not JSON: %s", body[:200])
            return [], len(body)

    items = payload.get("data") or payload.get("rows") or []
    if not isinstance(items, list):
        return [], len(body)

    rows = []
    for item in items:
        row = _row_from_api(item)
        if row is not None:
            rows.append(row)

    return rows, len(body)


async def _load_known_shark_norms() -> set[str]:
    async with async_session() as session:
        from sqlalchemy import select
        q = await session.execute(
            select(KnownShark.canonical_name).where(KnownShark.active.is_(True))
        )
        return {_norm_client(name) for name, in q.all()}


async def upsert_disclosures(rows: list[dict]) -> tuple[int, int, int]:
    """Insert via the unique index `ix_insider_dedup`. Returns (inserted, updated, skipped)."""
    if not rows:
        return (0, 0, 0)

    shark_norms = await _load_known_shark_norms()

    inserted = 0
    skipped = 0
    async with async_session() as session:
        for r in rows:
            r["is_known_shark"] = r["person_name_norm"] in shark_norms
            stmt = pg_insert(InsiderDisclosure).values(**r)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=[
                    "symbol",
                    "person_name_norm",
                    "transaction_date",
                    "transaction_type",
                    "shares",
                ]
            )
            result = await session.execute(stmt)
            if result.rowcount:
                inserted += 1
            else:
                skipped += 1
        await session.commit()

    return (inserted, 0, skipped)


async def sync_nse_insider(*, lookback_days: int = 7) -> dict:
    """Pulls the last `lookback_days` of disclosures and upserts.

    Beat schedule fires once a day at 17:30 IST; the 7-day overlap covers
    late filings that trickle in over a couple of business days.

    After ingest, runs `detect_intra_group_transfers()` to tag
    same-date matched buy/sell pairs across the promoter family — the
    BAJAJFINSV / PKTEA double-counting case from the addendum.
    """
    today = datetime.now().date()
    from_d = today - timedelta(days=lookback_days)
    rows, body_bytes = await fetch_nse_insider(from_d, today)
    inserted, updated, skipped = await upsert_disclosures(rows)
    transfers_tagged = await detect_intra_group_transfers(from_d - timedelta(days=14), today)
    return {
        "fetched": len(rows),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "bytes": body_bytes,
        "from_date": from_d.isoformat(),
        "to_date": today.isoformat(),
        "transfers_tagged": transfers_tagged,
    }


# ---- A1a: intra-group transfer detection ----------------------------------

# Categories that participate in an intra-group transfer. If two rows on
# the same (symbol, date) — one Buy, one Sale — both fall in this set
# AND their share counts match within tolerance, they're not market
# activity, they're a wallet move.
_PROMOTER_FAMILY = {"Promoter", "Promoter Group", "Immediate Relative"}
_TRANSFER_TOLERANCE = 0.05  # 5%


async def detect_intra_group_transfers(from_d: date, to_d: date) -> int:
    """Scan `insider_disclosures` for matched same-date buy/sell pairs
    inside the promoter family and flag both sides via
    `is_intra_group_transfer = TRUE`. Idempotent — re-running on already
    tagged rows is a no-op.

    Returns the number of rows newly tagged. Bounded by date so a
    re-ingest of new disclosures doesn't re-scan the entire table.
    """
    from sqlalchemy import and_, select, update

    async with async_session() as session:
        rows_q = await session.execute(
            select(InsiderDisclosure).where(
                InsiderDisclosure.symbol.is_not(None),
                InsiderDisclosure.transaction_date >= from_d,
                InsiderDisclosure.transaction_date <= to_d,
                InsiderDisclosure.category.in_(tuple(_PROMOTER_FAMILY)),
                InsiderDisclosure.transaction_type.in_(("Buy", "Sale")),
            )
        )
        rows = list(rows_q.scalars().all())

    # Bucket by (symbol, transaction_date)
    by_key: dict[tuple[str, date], list[InsiderDisclosure]] = {}
    for r in rows:
        by_key.setdefault((r.symbol, r.transaction_date), []).append(r)

    flag_ids: set[int] = set()
    for bucket in by_key.values():
        buys = [r for r in bucket if r.transaction_type == "Buy"]
        sales = [r for r in bucket if r.transaction_type == "Sale"]
        if not buys or not sales:
            continue
        # For each buy, find the unmatched sale whose share count is
        # closest within tolerance. Match-and-consume so a single buy
        # can't be matched against multiple sales.
        used_sale: set[int] = set()
        for b in buys:
            best: tuple[float, InsiderDisclosure] | None = None
            for s in sales:
                if s.id in used_sale:
                    continue
                if b.shares == 0 or s.shares == 0:
                    continue
                diff = abs(b.shares - s.shares) / max(b.shares, s.shares)
                if diff <= _TRANSFER_TOLERANCE:
                    if best is None or diff < best[0]:
                        best = (diff, s)
            if best is not None:
                used_sale.add(best[1].id)
                if not b.is_intra_group_transfer:
                    flag_ids.add(b.id)
                if not best[1].is_intra_group_transfer:
                    flag_ids.add(best[1].id)

    if not flag_ids:
        return 0

    async with async_session() as session:
        await session.execute(
            update(InsiderDisclosure)
            .where(InsiderDisclosure.id.in_(flag_ids))
            .values(is_intra_group_transfer=True)
        )
        await session.commit()

    return len(flag_ids)
