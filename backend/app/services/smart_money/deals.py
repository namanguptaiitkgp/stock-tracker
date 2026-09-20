"""NSE + BSE bulk & block deals — named-investor trades disclosed end-of-day.

NSE publishes today's deals as CSVs at:
    https://nsearchives.nseindia.com/content/equities/bulk.csv
    https://nsearchives.nseindia.com/content/equities/block.csv

Columns:
    Date, Symbol, Security Name, Client Name, Buy/Sell, Quantity Traded,
    Trade Price / Wght. Avg. Price, (Remarks)   [bulk only]

BSE: similar daily CSVs (added by follow-up).
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, datetime
from typing import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session
from app.models.smart_money import BulkBlockDeal, KnownShark

logger = logging.getLogger(__name__)

NSE_BULK_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
NSE_BLOCK_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"

# BSE publishes a daily JSON via the corporate-announcements API.
# strCat=Bulk+Deals / strCat=Block+Deals; strPrevDate=DDMMYYYY filters
# to a specific date. The endpoint requires an Origin header set to
# the BSE site or it returns 403.
BSE_DEALS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"

REQUEST_TIMEOUT = 45
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}
BSE_HEADERS = {
    **HEADERS,
    "Accept": "application/json,text/plain,*/*",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
}


def _norm_client(raw: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", raw.lower())
    s = re.sub(r"\b(llp|ltd|limited|pvt|private|pvtltd|pvtlimited)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_qty(raw: str) -> int | None:
    raw = raw.replace(",", "").strip()
    try:
        return int(float(raw))
    except ValueError:
        return None


def _parse_price(raw: str) -> float | None:
    raw = raw.replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_side(raw: str) -> str | None:
    raw = raw.strip().upper()
    if raw.startswith("B"):
        return "BUY"
    if raw.startswith("S"):
        return "SELL"
    return None


def _parse_deals_csv(text: str, deal_type: str, exchange: str = "NSE") -> list[dict]:
    rows: list[dict] = []
    if not text or "NO RECORDS" in text.upper().splitlines()[1:2][0] if text else False:
        # fall through — csv.reader handles empty safely
        pass

    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return rows

    col_ix = {c.strip().lower(): i for i, c in enumerate(header)}

    def col(name: str) -> int | None:
        return col_ix.get(name.lower())

    ix_date = col("Date")
    ix_sym = col("Symbol")
    ix_name = col("Security Name")
    ix_client = col("Client Name")
    ix_side = col("Buy/Sell")
    ix_qty = col("Quantity Traded")
    ix_price = col("Trade Price / Wght. Avg. Price") or col("Trade Price / Wght.Avg.Price") or col("Trade Price")

    if None in (ix_date, ix_sym, ix_client, ix_side, ix_qty, ix_price):
        logger.warning("deals CSV missing expected columns: %s", header)
        return rows

    for parts in reader:
        if not parts or all(not p.strip() for p in parts):
            continue
        if len(parts) <= max(ix_date, ix_sym, ix_client, ix_side, ix_qty, ix_price):
            continue
        if parts[0].strip().upper() == "NO RECORDS":
            continue
        d = _parse_date(parts[ix_date])
        sym = parts[ix_sym].strip()
        client_raw = parts[ix_client].strip()
        side = _parse_side(parts[ix_side])
        qty = _parse_qty(parts[ix_qty])
        price = _parse_price(parts[ix_price])
        if not all([d, sym, client_raw, side, qty, price]):
            continue
        rows.append(
            {
                "trade_date": d,
                "exchange": exchange,
                "symbol": sym,
                "security_name_raw": parts[ix_name].strip() if ix_name is not None and len(parts) > ix_name else None,
                "client_name_raw": client_raw,
                "client_name_norm": _norm_client(client_raw),
                "side": side,
                "quantity": qty,
                "avg_price": price,
                "trade_value_inr": float(qty) * price,
                "deal_type": deal_type,
            }
        )
    return rows


async def _fetch_csv(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.text


async def fetch_nse_deals() -> tuple[list[dict], int]:
    """Returns (rows, bytes_downloaded)."""
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, headers=HEADERS, follow_redirects=True
    ) as client:
        # Warm NSE cookies first — archives hosts sometimes check origin.
        try:
            await client.get("https://www.nseindia.com", timeout=15)
        except Exception:
            pass

        bulk_text = await _fetch_csv(client, NSE_BULK_URL)
        block_text = await _fetch_csv(client, NSE_BLOCK_URL)

    bulk_rows = _parse_deals_csv(bulk_text, "BULK", "NSE")
    block_rows = _parse_deals_csv(block_text, "BLOCK", "NSE")
    total_bytes = len(bulk_text) + len(block_text)
    return (bulk_rows + block_rows, total_bytes)


async def _load_known_sharks() -> dict[str, str]:
    """Return map of normalized_alias -> canonical_name for sharks."""
    aliases: dict[str, str] = {}
    async with async_session() as session:
        result = await session.execute(select(KnownShark).where(KnownShark.active.is_(True)))
        for shark in result.scalars().all():
            aliases[_norm_client(shark.canonical_name)] = shark.canonical_name
            for alias in (shark.aliases or []):
                aliases[_norm_client(alias)] = shark.canonical_name
    return aliases


async def upsert_deals(rows: list[dict]) -> tuple[int, int, int]:
    """Returns (inserted, updated, skipped). Dedups on (trade_date, exchange,
    symbol, client_name_norm, side, quantity, avg_price, deal_type).

    Also classifies each row into `client_category` (addendum A1c) so the
    active-traders endpoint can default-hide PROP_HFT / BROKER without
    re-running the classifier on every query.
    """
    if not rows:
        return (0, 0, 0)

    shark_map = await _load_known_sharks()
    # Lazy import to avoid bootstrapping cost when no rows are present.
    from app.services.smart_money.analyzer import party_classifier as pc

    inserted = 0
    updated = 0
    skipped = 0

    async with async_session() as session:
        for r in rows:
            canonical = shark_map.get(r["client_name_norm"])
            r["is_known_shark"] = canonical is not None
            r["client_category"] = pc.classify(r["client_name_raw"]).category

            # Dedup check
            existing = await session.execute(
                select(BulkBlockDeal.id).where(
                    BulkBlockDeal.trade_date == r["trade_date"],
                    BulkBlockDeal.exchange == r["exchange"],
                    BulkBlockDeal.symbol == r["symbol"],
                    BulkBlockDeal.client_name_norm == r["client_name_norm"],
                    BulkBlockDeal.side == r["side"],
                    BulkBlockDeal.quantity == r["quantity"],
                    BulkBlockDeal.avg_price == r["avg_price"],
                    BulkBlockDeal.deal_type == r["deal_type"],
                )
            )
            if existing.first():
                skipped += 1
                continue

            session.add(BulkBlockDeal(**r))
            inserted += 1

        await session.commit()

    return (inserted, updated, skipped)


async def sync_nse_deals() -> dict:
    """Entrypoint called by celery task."""
    rows, total_bytes = await fetch_nse_deals()
    inserted, updated, skipped = await upsert_deals(rows)
    return {
        "fetched": len(rows),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "bytes": total_bytes,
    }


async def reclassify_existing_deals(*, batch_size: int = 1000) -> dict:
    """One-off backfill: populate `client_category` for existing rows
    inserted before A1c shipped. Idempotent — only touches rows where
    the column is NULL. Re-runs are safe.
    """
    from sqlalchemy import select, update

    from app.services.smart_money.analyzer import party_classifier as pc

    updated = 0
    while True:
        async with async_session() as session:
            q = await session.execute(
                select(BulkBlockDeal.id, BulkBlockDeal.client_name_raw)
                .where(BulkBlockDeal.client_category.is_(None))
                .limit(batch_size)
            )
            batch = q.all()
            if not batch:
                break
            for row_id, raw in batch:
                cat = pc.classify(raw or "").category
                await session.execute(
                    update(BulkBlockDeal)
                    .where(BulkBlockDeal.id == row_id)
                    .values(client_category=cat)
                )
            await session.commit()
            updated += len(batch)
    return {"updated": updated}


# ---- BSE bulk/block deals --------------------------------------------------


def _parse_bse_deals(payload: dict, deal_type: str) -> list[dict]:
    """Map BSE corporate-announcements API rows to our schema.

    The BSE response shape (under the `Table` key) historically:
      [{
        "BD_DT_PURCHASE": "2026-04-30 00:00:00",
        "BD_SCRIP_CD": "500325",
        "SLONGNAME": "Reliance Industries",
        "BD_CLIENT_NAME": "ABC Family Trust",
        "BD_TP_WATR": "B",  # B=Buy, S=Sell
        "BD_QTY_TRD": "12345",
        "BD_TP_WATP": "2890.55",
        ...
      }]
    Field names occasionally drift; we coalesce on common variants.
    """
    rows: list[dict] = []
    items = payload.get("Table") or payload.get("data") or []
    if not isinstance(items, list):
        return rows

    for it in items:
        try:
            d_raw = (it.get("BD_DT_PURCHASE") or it.get("DEAL_DATE") or "").split(" ")[0]
            d = _parse_date(d_raw) or datetime.strptime(d_raw, "%Y-%m-%d").date() if d_raw else None
        except (ValueError, IndexError):
            d = None
        if d is None:
            continue

        sym = (it.get("SCRIP_NAME") or it.get("BD_SCRIP_NAME") or it.get("SLONGNAME") or "").strip()
        # BSE returns the full company name; the downstream symbol
        # resolution in the rollup keys off `client_name_norm`, but for
        # cross-exchange consistency we want the equity symbol/ticker.
        # When the API returns `BD_SCRIP_CD` we keep that as a fallback.
        if not sym:
            sym = (it.get("BD_SCRIP_CD") or "").strip()
        if not sym:
            continue

        client_raw = (it.get("BD_CLIENT_NAME") or it.get("CLIENT_NAME") or "").strip()
        if not client_raw:
            continue
        side = _parse_side(it.get("BD_TP_WATR") or it.get("DEAL_TYPE") or "")
        qty = _parse_qty(str(it.get("BD_QTY_TRD") or it.get("QTY") or ""))
        price = _parse_price(str(it.get("BD_TP_WATP") or it.get("DEAL_PRICE") or ""))
        if not all([side, qty, price]):
            continue

        rows.append(
            {
                "trade_date": d,
                "exchange": "BSE",
                "symbol": sym[:50],
                "security_name_raw": (it.get("SLONGNAME") or "").strip()[:255] or None,
                "client_name_raw": client_raw[:255],
                "client_name_norm": _norm_client(client_raw),
                "side": side,
                "quantity": qty,
                "avg_price": price,
                "trade_value_inr": float(qty) * price,
                "deal_type": deal_type,
            }
        )
    return rows


async def fetch_bse_deals() -> tuple[list[dict], int]:
    """Fetch today's BSE bulk + block deal feed."""
    today = datetime.now().date().strftime("%d%m%Y")
    bytes_total = 0
    rows: list[dict] = []

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, headers=BSE_HEADERS, follow_redirects=True
    ) as client:
        # Warm BSE cookies — same defensive pattern as NSE.
        try:
            await client.get("https://www.bseindia.com", timeout=15)
        except Exception:
            pass

        for cat, deal_type in [("Bulk+Deals", "BULK"), ("Block+Deals", "BLOCK")]:
            params = {
                "strCat": cat,
                "strPrevDate": today,
                "strScrip": "",
                "strSearch": "P",
                "strType": "C",
                "strVal": "",
            }
            try:
                resp = await client.get(BSE_DEALS_URL, params=params)
                resp.raise_for_status()
                bytes_total += len(resp.content)
                payload = resp.json()
            except Exception as e:
                logger.warning("BSE %s fetch failed: %s", cat, e)
                continue
            rows.extend(_parse_bse_deals(payload, deal_type))

    return rows, bytes_total


async def sync_bse_deals() -> dict:
    """Entrypoint called by the BSE-deals celery task. Mirrors
    `sync_nse_deals` so the unified `bulk_block_deals` table carries
    both exchanges and the rollup naturally treats them together."""
    rows, total_bytes = await fetch_bse_deals()
    inserted, updated, skipped = await upsert_deals(rows)
    return {
        "fetched": len(rows),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "bytes": total_bytes,
    }
