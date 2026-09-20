"""NSE end-of-day bhavcopy with delivery %.

URL: https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv

Columns:
    SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE,
    LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS,
    NO_OF_TRADES, DELIV_QTY, DELIV_PER

Turnover is in lakhs of rupees (multiply by 100_000 for INR).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session
from app.models.smart_money import BhavcopyDaily

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*",
}


def _url_for(d: date) -> str:
    return f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"


def _fnum(raw: str) -> float | None:
    raw = raw.replace(",", "").strip()
    if not raw or raw in {"-", "N.A.", "NA"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _fint(raw: str) -> int | None:
    v = _fnum(raw)
    return int(v) if v is not None else None


def _parse_bhav_csv(text: str) -> list[dict]:
    rows: list[dict] = []
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return rows

    cols = {c.strip().lower(): i for i, c in enumerate(header)}
    req = [
        "symbol", "series", "date1", "prev_close", "open_price", "high_price",
        "low_price", "close_price", "ttl_trd_qnty", "turnover_lacs",
        "deliv_qty", "deliv_per",
    ]
    if any(k not in cols for k in req):
        logger.warning("bhavcopy CSV header mismatch: %s", header)
        return rows

    for parts in reader:
        if not parts or all(not p.strip() for p in parts):
            continue
        try:
            trade_dt = datetime.strptime(parts[cols["date1"]].strip(), "%d-%b-%Y").date()
        except (ValueError, IndexError):
            continue

        series = parts[cols["series"]].strip()
        if series not in {"EQ", "BE", "BZ", "SM", "ST"}:
            continue

        symbol = parts[cols["symbol"]].strip()
        if not symbol:
            continue

        turnover_lacs = _fnum(parts[cols["turnover_lacs"]])
        rows.append(
            {
                "trade_date": trade_dt,
                "exchange": "NSE",
                "symbol": symbol,
                "series": series,
                "open_price": _fnum(parts[cols["open_price"]]),
                "high_price": _fnum(parts[cols["high_price"]]),
                "low_price": _fnum(parts[cols["low_price"]]),
                "close_price": _fnum(parts[cols["close_price"]]),
                "prev_close": _fnum(parts[cols["prev_close"]]),
                "traded_qty": _fint(parts[cols["ttl_trd_qnty"]]),
                "turnover_inr": (turnover_lacs * 100_000) if turnover_lacs is not None else None,
                "delivery_qty": _fint(parts[cols["deliv_qty"]]),
                "delivery_pct": _fnum(parts[cols["deliv_per"]]),
            }
        )
    return rows


async def _fetch_for_date(d: date) -> tuple[str, str] | None:
    """Returns (url, text) for the given date, or None if 404."""
    url = _url_for(d)
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, headers=HEADERS, follow_redirects=True
    ) as client:
        try:
            await client.get("https://www.nseindia.com", timeout=15)
        except Exception:
            pass
        resp = await client.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return (url, resp.text)


async def upsert_bhavcopy(rows: list[dict]) -> tuple[int, int, int]:
    if not rows:
        return (0, 0, 0)

    inserted = 0
    updated = 0
    skipped = 0

    async with async_session() as session:
        for r in rows:
            stmt = pg_insert(BhavcopyDaily).values(**r)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_bhav_date_exch_symbol",
                set_={
                    "series": stmt.excluded.series,
                    "open_price": stmt.excluded.open_price,
                    "high_price": stmt.excluded.high_price,
                    "low_price": stmt.excluded.low_price,
                    "close_price": stmt.excluded.close_price,
                    "prev_close": stmt.excluded.prev_close,
                    "traded_qty": stmt.excluded.traded_qty,
                    "turnover_inr": stmt.excluded.turnover_inr,
                    "delivery_qty": stmt.excluded.delivery_qty,
                    "delivery_pct": stmt.excluded.delivery_pct,
                },
            )
            await session.execute(stmt)
            inserted += 1  # pg_insert doesn't cleanly distinguish; accept "ingested" count
        await session.commit()

    return (inserted, updated, skipped)


async def sync_bhavcopy(trade_date: date | None = None) -> dict:
    """Pulls the most recent available bhavcopy. If `trade_date` is None, walks
    back up to 5 days from today looking for the first 200."""
    attempts = 0
    today = trade_date or datetime.now().date()
    result = None
    for delta in range(0, 5):
        d = today - timedelta(days=delta)
        attempts += 1
        fetched = await _fetch_for_date(d)
        if fetched:
            result = (d, *fetched)
            break

    if not result:
        raise RuntimeError(f"bhavcopy: no data found within {attempts} days back from {today}")

    d, url, text = result
    rows = _parse_bhav_csv(text)
    ingested, updated, skipped = await upsert_bhavcopy(rows)
    return {
        "trade_date": d.isoformat(),
        "url": url,
        "fetched": len(rows),
        "inserted": ingested,
        "updated": updated,
        "skipped": skipped,
        "bytes": len(text),
        "attempts": attempts,
    }
