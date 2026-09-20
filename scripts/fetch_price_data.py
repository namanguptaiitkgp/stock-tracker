#!/usr/bin/env python3
"""
fetch_price_data.py — Pull current quote snapshot for an NSE-listed ticker.
Outputs price_summary.json with fetch metadata for audit trail.

Usage:
    python3 fetch_price_data.py RELIANCE
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "filings"

NSE_QUOTE = "https://www.nseindia.com/api/quote-equity?symbol={symbol}"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def nse_session() -> tuple[requests.Session, dict]:
    """NSE requires cookies from a homepage visit before API calls work."""
    s = requests.Session()
    s.headers.update(HEADERS)
    log = {
        "source": "NSE Homepage (cookie preflight)",
        "url": "https://www.nseindia.com",
        "attempted_at": datetime.now(timezone.utc).isoformat(),
    }
    t0 = time.monotonic()
    try:
        r = s.get("https://www.nseindia.com", timeout=15)
        log["status_code"] = r.status_code
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["status"] = "OK"
    except Exception as e:
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["status"] = "FAILED"
        log["error"] = str(e)
    return s, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    args = ap.parse_args()
    ticker = args.ticker.upper()

    out_dir = DATA_DIR / ticker
    out_dir.mkdir(parents=True, exist_ok=True)

    fetch_log = []

    s, cookie_log = nse_session()
    fetch_log.append(cookie_log)
    if cookie_log["status"] == "FAILED":
        print(f"Failed to establish NSE session: {cookie_log.get('error')}",
              file=sys.stderr)
        # Write partial log even on failure
        partial = {"ticker": ticker, "error": "NSE session failed", "fetch_log": fetch_log}
        (out_dir / "price_summary.json").write_text(json.dumps(partial, indent=2))
        sys.exit(1)

    quote_url = NSE_QUOTE.format(symbol=ticker)
    quote_log = {
        "source": "NSE Quote API",
        "url": quote_url,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
    }
    t0 = time.monotonic()
    try:
        r = s.get(quote_url, timeout=30)
        quote_log["status_code"] = r.status_code
        quote_log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        quote_log["response_bytes"] = len(r.content)
        r.raise_for_status()
        q = r.json()
        quote_log["status"] = "OK"
    except Exception as e:
        quote_log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        quote_log["status"] = "FAILED"
        quote_log["error"] = str(e)
        fetch_log.append(quote_log)
        partial = {"ticker": ticker, "error": str(e), "fetch_log": fetch_log}
        (out_dir / "price_summary.json").write_text(json.dumps(partial, indent=2))
        print(f"Failed to fetch quote: {e}", file=sys.stderr)
        sys.exit(1)

    fetch_log.append(quote_log)

    info = q.get("info", {})
    price = q.get("priceInfo", {})
    metadata = q.get("metadata", {})

    summary = {
        "ticker": ticker,
        "company_name": info.get("companyName"),
        "industry": info.get("industry"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "price": {
            "ltp": price.get("lastPrice"),
            "change_pct": price.get("pChange"),
            "day_high": price.get("intraDayHighLow", {}).get("max"),
            "day_low": price.get("intraDayHighLow", {}).get("min"),
            "week52_high": price.get("weekHighLow", {}).get("max"),
            "week52_low": price.get("weekHighLow", {}).get("min"),
        },
        "ratios": {
            "pe": metadata.get("pdSymbolPe"),
            "sector_pe": metadata.get("pdSectorPe"),
            "face_value": metadata.get("faceValue"),
            "isin": metadata.get("isin"),
        },
        "listing": {
            "listing_date": metadata.get("listingDate"),
            "series": metadata.get("series"),
        },
        "fetch_log": fetch_log,
    }

    dest = out_dir / "price_summary.json"
    dest.write_text(json.dumps(summary, indent=2))
    print(f"Wrote {dest}")
    print(f"  LTP: ₹{summary['price']['ltp']}  "
          f"52w: ₹{summary['price']['week52_low']} – ₹{summary['price']['week52_high']}  "
          f"P/E: {summary['ratios']['pe']}")


if __name__ == "__main__":
    main()
