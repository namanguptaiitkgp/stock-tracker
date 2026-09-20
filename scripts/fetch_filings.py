#!/usr/bin/env python3
"""
fetch_filings.py — Download annual reports, quarterly results, and investor
presentations for an NSE-listed company. Produces a manifest.json with
structured fetch logs for audit trail.

Usage:
    python3 fetch_filings.py RELIANCE

Output:
    data/filings/<TICKER>/
        q1_results.pdf, q2_results.pdf, ...
        investor_presentation_latest.pdf
        manifest.json   (what was fetched, when, from where, with audit log)
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "filings"

BSE_TICKER_MAP = {
    "RELIANCE": "500325",
    "TCS": "532540",
    "INFY": "500209",
    "HDFCBANK": "500180",
    "ICICIBANK": "532174",
    "INA": "543620",
}

BSE_ANNOUNCE_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (equity-research-mvp/0.1)",
    "Accept": "application/json",
    "Referer": "https://www.bseindia.com/",
}


def fetch_announcements(scrip_code: str, category: str) -> tuple[list[dict], dict]:
    """Returns (announcements, fetch_log_entry)."""
    url = BSE_ANNOUNCE_URL
    to_date = datetime.now().strftime("%Y%m%d")
    from_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    params = {
        "pageno": 1,
        "strCat": category,
        "strPrevDate": from_date,
        "strScrip": scrip_code,
        "strSearch": "P",
        "strToDate": to_date,
        "strType": "C",
    }
    log = {
        "source": f"BSE Announcements ({category})",
        "url": url,
        "params": params,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
    }
    t0 = time.monotonic()
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        log["status_code"] = r.status_code
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["response_bytes"] = len(r.content)
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("Table", []) or []
        log["status"] = "OK"
        log["rows_returned"] = len(rows)
        return rows, log
    except Exception as e:
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["status"] = "FAILED"
        log["error"] = str(e)
        return [], log


def download(url: str, dest: Path) -> dict:
    """Download a file and return a fetch log entry."""
    log = {
        "url": url,
        "dest": str(dest.name),
        "attempted_at": datetime.now(timezone.utc).isoformat(),
    }
    if dest.exists():
        log["status"] = "SKIPPED"
        log["note"] = "file already exists"
        log["bytes"] = dest.stat().st_size
        return log
    t0 = time.monotonic()
    try:
        r = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        log["status_code"] = r.status_code
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        r.raise_for_status()
        if not r.content[:4] == b"%PDF":
            log["status"] = "FAILED"
            log["error"] = f"Expected PDF but got {r.headers.get('content-type', '?')}"
            return log
        dest.write_bytes(r.content)
        log["status"] = "OK"
        log["bytes"] = len(r.content)
        return log
    except Exception as e:
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["status"] = "FAILED"
        log["error"] = str(e)
        return log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    args = ap.parse_args()
    ticker = args.ticker.upper()

    scrip = BSE_TICKER_MAP.get(ticker)
    if not scrip:
        print(f"Unknown ticker '{ticker}'. Add it to BSE_TICKER_MAP.",
              file=sys.stderr)
        sys.exit(2)

    out_dir = DATA_DIR / ticker
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "ticker": ticker,
        "scrip_code": scrip,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "files": [],
        "fetch_log": [],
    }

    # Quarterly results
    print(f"Fetching quarterly results for {ticker}...")
    results, api_log = fetch_announcements(scrip, "Result")
    manifest["fetch_log"].append(api_log)
    for i, ann in enumerate(results[:4]):
        url = ann.get("ATTACHMENTNAME")
        if not url:
            continue
        if not url.startswith("http"):
            url = f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{url}"
        dest = out_dir / f"q{i+1}_results.pdf"
        dl_log = download(url, dest)
        manifest["fetch_log"].append(dl_log)
        if dl_log["status"] in ("OK", "SKIPPED"):
            manifest["files"].append({
                "type": "quarterly_result",
                "path": str(dest.relative_to(ROOT)),
                "source_url": url,
                "headline": ann.get("HEADLINE"),
                "bytes": dl_log.get("bytes"),
            })
        time.sleep(1)

    # Investor presentations
    print(f"Fetching company updates for {ticker}...")
    updates, api_log = fetch_announcements(scrip, "Company Update")
    manifest["fetch_log"].append(api_log)
    pres = next((u for u in updates
                 if "presentation" in (u.get("HEADLINE") or "").lower()), None)
    if pres:
        url = pres.get("ATTACHMENTNAME")
        if url and not url.startswith("http"):
            url = f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{url}"
        if url:
            dest = out_dir / "investor_presentation_latest.pdf"
            dl_log = download(url, dest)
            manifest["fetch_log"].append(dl_log)
            if dl_log["status"] in ("OK", "SKIPPED"):
                manifest["files"].append({
                    "type": "investor_presentation",
                    "path": str(dest.relative_to(ROOT)),
                    "source_url": url,
                    "headline": pres.get("HEADLINE"),
                    "bytes": dl_log.get("bytes"),
                })
    else:
        manifest["fetch_log"].append({
            "source": "BSE Company Update (investor presentation)",
            "status": "NOT_FOUND",
            "note": "No announcement with 'presentation' in headline",
        })

    # Annual report — stubbed
    manifest["fetch_log"].append({
        "source": "Annual Report",
        "status": "NOT_AVAILABLE",
        "note": "Stubbed — BSE doesn't expose annual reports cleanly via announcements API. Manual download or company IR page needed.",
    })

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nDone. Manifest: {manifest_path}")
    print(f"Files fetched: {len(manifest['files'])}")
    print(f"Fetch log entries: {len(manifest['fetch_log'])}")


if __name__ == "__main__":
    main()
