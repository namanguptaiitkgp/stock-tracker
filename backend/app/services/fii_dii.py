import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


async def fetch_fii_dii_data() -> list[dict]:
    """Fetch recent FII/DII trading activity from NSE."""
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=NSE_HEADERS) as client:
            # Step 1: Get cookies by visiting the main page
            await client.get("https://www.nseindia.com")

            # Step 2: Call the FII/DII API
            resp = await client.get("https://www.nseindia.com/api/fiidiiTradeReact")

            if resp.status_code != 200:
                logger.warning(f"NSE FII/DII API returned {resp.status_code}")
                return []

            data = resp.json()

            results = []
            for entry in data:
                try:
                    category = entry.get("category", "")
                    buy = _parse_amount(entry.get("buyValue"))
                    sell = _parse_amount(entry.get("sellValue"))
                    net = _parse_amount(entry.get("netValue"))
                    entry_date = entry.get("date", "")

                    results.append({
                        "category": category,  # "FII/FPI" or "DII"
                        "date": entry_date,
                        "buy_value": buy,
                        "sell_value": sell,
                        "net_value": net if net is not None else (buy - sell if buy and sell else None),
                    })
                except Exception:
                    continue

            return results
    except Exception as e:
        logger.warning(f"FII/DII fetch failed: {e}")
        return []


def _parse_amount(val) -> float | None:
    """Parse amount values from NSE. They may be strings with commas."""
    if val is None:
        return None
    try:
        if isinstance(val, str):
            val = val.replace(",", "").strip()
        return float(val)
    except (TypeError, ValueError):
        return None


async def sync_stock_level_fii_dii() -> dict:
    """Per-stock FII/DII daily activity → `fii_dii_stock_daily`.

    **Data-source gap:** NSE / BSE don't publish per-stock FII/DII flows
    publicly. The market-wide aggregate (above) is the only NSE-direct
    source. Possible workarounds for a follow-up:
      - Derive monthly per-stock FII change from `shareholding_patterns`
        (Δ FII% × shares outstanding × avg quarter price) and spread it
        across the quarter as a coarse daily approximation.
      - Paid feed (Tickertape / Trendlyne) — out of scope for cost.

    Until the upstream is settled this task is a no-op that completes
    successfully so the celery beat schedule and the
    `SOURCE_CADENCE_HOURS` freshness strip aren't blocked. The
    `fii_dii_stock_daily` table stays empty; the flow scorer's
    `fii_dii_stock` sub-signal lists as absent in `signal_breakdown`.
    """
    return {
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "note": "stock-level FII/DII upstream not wired; see fii_dii.py docstring",
    }


def format_fii_dii(raw_data: list[dict]) -> dict:
    """Format FII/DII data into a structured response."""
    fii = None
    dii = None

    for entry in raw_data:
        cat = entry.get("category", "").upper()
        if "FII" in cat or "FPI" in cat:
            fii = entry
        elif "DII" in cat:
            dii = entry

    return {
        "date": (fii or dii or {}).get("date"),
        "fii": {
            "buy": fii["buy_value"] if fii else None,
            "sell": fii["sell_value"] if fii else None,
            "net": fii["net_value"] if fii else None,
        } if fii else None,
        "dii": {
            "buy": dii["buy_value"] if dii else None,
            "sell": dii["sell_value"] if dii else None,
            "net": dii["net_value"] if dii else None,
        } if dii else None,
    }
