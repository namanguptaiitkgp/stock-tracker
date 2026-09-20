"""One-time backfill: fetch last 6 quarters of NSE XBRL shareholding data.

Usage:
    docker exec -it algo-trader-backend-1 python -m scripts.backfill_shareholding

Idempotent — uses ON CONFLICT DO NOTHING so re-runs are safe.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import httpx
from sqlalchemy import select

from app.db.session import async_session
from app.models.smart_money import ShareholdingPattern
from app.models.watchlist import WatchlistItem
from app.services.smart_money.insider_disclosures import HEADERS as NSE_HEADERS
from app.services.smart_money.shareholding_pattern import (
    NSE_SHP_MASTER_URL,
    REQUEST_TIMEOUT,
    _fetch_nse_filings_index,
    _parse_quarter_label,
    _parse_xbrl_quarter_end,
    _parse_xbrl_shareholding,
    _persist_with_deltas,
    _row_from_nse_xbrl,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MAX_FILINGS = 6


async def _get_all_symbols() -> list[str]:
    async with async_session() as session:
        result = await session.execute(
            select(WatchlistItem.symbol).distinct()
        )
        return [row[0] for row in result.all() if row[0]]


async def _backfill_symbol(
    symbol: str, client: httpx.AsyncClient,
) -> list[dict]:
    filings = await _fetch_nse_filings_index(symbol, client)
    if not filings:
        logger.info("  %s: no filings found", symbol)
        return []

    rows: list[dict] = []
    count = 0
    attempts = 0
    for filing in filings:
        if count >= MAX_FILINGS or attempts >= MAX_FILINGS * 2:
            break
        attempts += 1

        url = filing.get("xbrl") or filing.get("xbrlFile") or filing.get("fileName")
        if not url:
            continue
        if not url.startswith("http"):
            url = f"https://nsearchives.nseindia.com{url}" if url.startswith("/") else f"https://nsearchives.nseindia.com/{url}"

        try:
            resp = await client.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            logger.debug("  %s: XBRL download failed: %s", symbol, e)
            continue

        xml_bytes = resp.content
        parsed = _parse_xbrl_shareholding(xml_bytes)
        quarter_end = _parse_xbrl_quarter_end(xml_bytes)

        if not quarter_end:
            date_str = filing.get("date") or filing.get("toDate") or filing.get("period")
            if date_str:
                from datetime import datetime
                for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        quarter_end = datetime.strptime(str(date_str).strip(), fmt).date()
                        break
                    except ValueError:
                        continue

        if not quarter_end or not parsed:
            continue

        row = _row_from_nse_xbrl(symbol, None, parsed, quarter_end, url)
        if row:
            rows.append(row)
            count += 1

        await asyncio.sleep(0.3)

    return rows


async def main() -> None:
    symbols = await _get_all_symbols()
    if not symbols:
        logger.info("No watchlist symbols found.")
        return

    logger.info("Backfilling shareholding for %d symbols...", len(symbols))
    all_rows: list[dict] = []

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, headers=NSE_HEADERS, follow_redirects=True,
    ) as client:
        try:
            await client.get("https://www.nseindia.com", timeout=15)
        except Exception:
            pass

        for i, symbol in enumerate(symbols, 1):
            logger.info("[%d/%d] %s", i, len(symbols), symbol)
            rows = await _backfill_symbol(symbol, client)
            all_rows.extend(rows)
            logger.info("  %s: %d filings parsed", symbol, len(rows))
            await asyncio.sleep(0.5)

    if all_rows:
        inserted, _, skipped = await _persist_with_deltas(all_rows)
        logger.info("Done. %d inserted, %d skipped (already existed).", inserted, skipped)
    else:
        logger.info("No rows to insert.")


if __name__ == "__main__":
    asyncio.run(main())
