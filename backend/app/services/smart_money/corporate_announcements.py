"""NSE corporate announcements — buyback / pledge filings.

Source: https://www.nseindia.com/api/corporate-announcements
        ?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY&fo_sec=false

We filter by `subject` keywords to keep only the announcement types the
spec scorers care about. Subjects are vendor-typed strings; they drift,
so the matcher is generous.

Down-stream readers:
  - flow_score: BUYBACK announcements in 90d → +30 binary boost.
  - red_flag_score: PLEDGE_INVOKED in 90d → -40 penalty.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session
from app.models.smart_money import CorporateAnnouncement
from app.services.smart_money.insider_disclosures import HEADERS as NSE_HEADERS, _fmt_nse_date, _parse_iso_date
from app.services.smart_money.deals import _parse_qty

logger = logging.getLogger(__name__)

NSE_ANN_URL = "https://www.nseindia.com/api/corporate-announcements"
REQUEST_TIMEOUT = 60


# Subject-keyword → announcement_type. Matched in priority order
# because some subjects mention both "pledge" and "release".
_SUBJECT_RULES: list[tuple[str, str]] = [
    ("pledge invoked", "PLEDGE_INVOKED"),
    ("invoke", "PLEDGE_INVOKED"),
    ("invocation", "PLEDGE_INVOKED"),
    ("pledge release", "PLEDGE_RELEASED"),
    ("release of pledge", "PLEDGE_RELEASED"),
    ("revoke", "PLEDGE_RELEASED"),
    ("encumbrance release", "PLEDGE_RELEASED"),
    ("pledge create", "PLEDGE_CREATED"),
    ("creation of pledge", "PLEDGE_CREATED"),
    ("encumbrance creation", "PLEDGE_CREATED"),
    ("encumbrance", "PLEDGE_CREATED"),  # default for plain "encumbrance"
    ("pledge", "PLEDGE_CREATED"),       # fallback
    ("buy back", "BUYBACK"),
    ("buyback", "BUYBACK"),
    ("preferential allotment", "PREFERENTIAL_ALLOTMENT"),
    ("preferential issue", "PREFERENTIAL_ALLOTMENT"),
]


def _classify_subject(subject: str | None) -> str | None:
    if not subject:
        return None
    s = subject.lower()
    for needle, ann_type in _SUBJECT_RULES:
        if needle in s:
            return ann_type
    return None


def _row_from_api(item: dict) -> dict | None:
    """One NSE announcement → CorporateAnnouncement insert dict, or None."""
    subject = (item.get("subject") or item.get("desc") or "").strip()
    ann_type = _classify_subject(subject)
    if not ann_type:
        return None

    symbol = (item.get("symbol") or "").strip()
    if not symbol:
        return None

    ann_date = _parse_iso_date(item.get("an_dt") or item.get("annDate"))
    if not ann_date:
        return None

    detail: dict[str, Any] = {}
    pledge_shares = None
    pledge_dir = None
    buyback_size = None
    buyback_price = None

    if ann_type.startswith("PLEDGE"):
        pledge_dir = ann_type.replace("PLEDGE_", "")
        # NSE doesn't include parsed pledge values in the listing payload —
        # the PDF attachment carries them. We capture the headline so a
        # downstream Gemini-flash parser (PR 4 stretch) can fill the
        # numeric fields. Until then, the type alone drives scoring.
    elif ann_type == "BUYBACK":
        # NSE's listing endpoint sometimes includes total buyback amount /
        # max price in the description; light regex below.
        detail["headline_raw"] = subject

    return {
        "symbol": symbol[:50],
        "announcement_type": ann_type,
        "headline": subject[:2000],
        "detail_json": detail or None,
        "buyback_size_inr": buyback_size,
        "buyback_price_inr": buyback_price,
        "pledge_shares": pledge_shares,
        "pledge_pct_of_holding": None,
        "pledge_direction": pledge_dir,
        "pledgor_name": None,
        "announcement_date": ann_date,
        "exchange": "NSE",
        "raw_json": item,
    }


async def fetch_nse_announcements(
    from_date: date, to_date: date
) -> tuple[list[dict], int]:
    params = {
        "index": "equities",
        "from_date": _fmt_nse_date(from_date),
        "to_date": _fmt_nse_date(to_date),
        "fo_sec": "false",
    }
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, headers=NSE_HEADERS, follow_redirects=True
    ) as client:
        try:
            await client.get("https://www.nseindia.com", timeout=15)
        except Exception:
            pass
        resp = await client.get(NSE_ANN_URL, params=params)
        resp.raise_for_status()
        body = resp.text
        try:
            payload = resp.json()
        except Exception:
            return [], len(body)

    items = payload if isinstance(payload, list) else payload.get("rows") or payload.get("data") or []
    rows: list[dict] = []
    for it in items:
        r = _row_from_api(it)
        if r is not None:
            rows.append(r)
    return rows, len(body)


async def upsert_announcements(rows: list[dict]) -> tuple[int, int, int]:
    """Dedup is enforced via the partial unique index on
    (symbol, announcement_type, announcement_date, md5(headline)) at the
    DB layer (see migration). The unique index has an expression in the
    column list which on_conflict_do_nothing can't reference by
    `index_elements`, so we use a per-row "exists?" check instead."""
    if not rows:
        return (0, 0, 0)

    inserted = 0
    skipped = 0
    async with async_session() as session:
        from sqlalchemy import select, func
        from app.models.smart_money import CorporateAnnouncement as CA

        for r in rows:
            existing = await session.execute(
                select(CA.id).where(
                    CA.symbol == r["symbol"],
                    CA.announcement_type == r["announcement_type"],
                    CA.announcement_date == r["announcement_date"],
                    func.md5(CA.headline) == func.md5(r["headline"]),
                )
            )
            if existing.first():
                skipped += 1
                continue
            session.add(CA(**r))
            inserted += 1
        await session.commit()

    return (inserted, 0, skipped)


async def sync_nse_announcements(*, lookback_days: int = 7) -> dict:
    today = datetime.now().date()
    from_d = today - timedelta(days=lookback_days)
    rows, body_bytes = await fetch_nse_announcements(from_d, today)
    inserted, _, skipped = await upsert_announcements(rows)
    return {
        "fetched": len(rows),
        "inserted": inserted,
        "updated": 0,
        "skipped": skipped,
        "bytes": body_bytes,
        "from_date": from_d.isoformat(),
        "to_date": today.isoformat(),
    }
