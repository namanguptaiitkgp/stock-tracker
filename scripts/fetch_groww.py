#!/usr/bin/env python3
"""
fetch_groww.py — Comprehensive filing fetcher for Groww (Billionbrains Garage Ventures).
Uses BSE Announcements API, NSE Corporate Announcements API, and company IR page discovery.
"""

import sys
import json
import time
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "filings" / "GROWW"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TICKER = "GROWW"
SCRIP_CODE = "544603"
COMPANY_NAME = "Billionbrains Garage Ventures Limited"
ISIN = "INE0HOQ01053"

BSE_ANNOUNCE_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
BSE_SUBCAT_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
NSE_ANNOUNCE_URL = "https://www.nseindia.com/api/corporate-announcements"

BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (equity-research-mvp/0.1)",
    "Accept": "application/json",
    "Referer": "https://www.bseindia.com/",
}

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

manifest = {
    "ticker": TICKER,
    "company_name": COMPANY_NAME,
    "scrip_code": SCRIP_CODE,
    "isin": ISIN,
    "fetched_at": datetime.now(timezone.utc).isoformat(),
    "files": [],
    "fetch_log": [],
}


def log_entry(source, url=None, params=None):
    entry = {
        "source": source,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
    }
    if url:
        entry["url"] = url
    if params:
        entry["params"] = params
    return entry


def download_pdf(url, dest, label):
    log = log_entry(f"PDF Download: {label}", url)
    if dest.exists():
        log["status"] = "SKIPPED"
        log["note"] = "file already exists"
        log["bytes"] = dest.stat().st_size
        manifest["fetch_log"].append(log)
        return True

    t0 = time.monotonic()
    try:
        r = requests.get(url, headers=BSE_HEADERS, timeout=60, stream=True)
        log["status_code"] = r.status_code
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        r.raise_for_status()

        content = r.content
        if content[:4] == b"%PDF":
            dest.write_bytes(content)
            log["status"] = "OK"
            log["bytes"] = len(content)
            manifest["fetch_log"].append(log)
            return True
        else:
            log["status"] = "FAILED"
            log["error"] = f"Not a PDF, got content-type: {r.headers.get('content-type', '?')}, first bytes: {content[:20]}"
            manifest["fetch_log"].append(log)
            return False
    except Exception as e:
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["status"] = "FAILED"
        log["error"] = str(e)
        manifest["fetch_log"].append(log)
        return False


# ── BSE Announcements API ──────────────────────────────────────────────
def bse_fetch_category(category):
    to_date = datetime.now().strftime("%Y%m%d")
    from_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    params = {
        "pageno": 1,
        "strCat": category,
        "strPrevDate": from_date,
        "strScrip": SCRIP_CODE,
        "strSearch": "P",
        "strToDate": to_date,
        "strType": "C",
    }
    log = log_entry(f"BSE Announcements ({category})", BSE_ANNOUNCE_URL, params)
    t0 = time.monotonic()
    try:
        r = requests.get(BSE_ANNOUNCE_URL, headers=BSE_HEADERS, params=params, timeout=30)
        log["status_code"] = r.status_code
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["response_bytes"] = len(r.content)
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("Table", []) or []
        log["status"] = "OK"
        log["rows_returned"] = len(rows)
        manifest["fetch_log"].append(log)
        return rows
    except Exception as e:
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["status"] = "FAILED"
        log["error"] = str(e)
        manifest["fetch_log"].append(log)
        return []


def bse_fetch_subcategory(category, subcategory):
    to_date = datetime.now().strftime("%Y%m%d")
    from_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    params = {
        "pageno": 1,
        "strCat": category,
        "strPrevDate": from_date,
        "strScrip": SCRIP_CODE,
        "strSearch": "P",
        "strToDate": to_date,
        "strType": "C",
        "strSubCat": subcategory,
    }
    log = log_entry(f"BSE SubCategory ({category}/{subcategory})", BSE_SUBCAT_URL, params)
    t0 = time.monotonic()
    try:
        r = requests.get(BSE_SUBCAT_URL, headers=BSE_HEADERS, params=params, timeout=30)
        log["status_code"] = r.status_code
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["response_bytes"] = len(r.content)
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("Table", []) or []
        log["status"] = "OK"
        log["rows_returned"] = len(rows)
        manifest["fetch_log"].append(log)
        return rows
    except Exception as e:
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["status"] = "FAILED"
        log["error"] = str(e)
        manifest["fetch_log"].append(log)
        return []


def resolve_bse_url(attachment):
    if not attachment:
        return None
    if attachment.startswith("http"):
        return attachment
    return f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{attachment}"


# ── NSE Corporate Announcements ────────────────────────────────────────
def nse_session():
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    log = log_entry("NSE Homepage (cookie preflight)", "https://www.nseindia.com")
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
    manifest["fetch_log"].append(log)
    return s, log["status"] == "OK"


def nse_fetch_announcements(session):
    params = {
        "index": "equities",
        "symbol": TICKER,
    }
    log = log_entry("NSE Corporate Announcements", NSE_ANNOUNCE_URL, params)
    t0 = time.monotonic()
    try:
        r = session.get(NSE_ANNOUNCE_URL, params=params, timeout=30)
        log["status_code"] = r.status_code
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["response_bytes"] = len(r.content)
        r.raise_for_status()
        data = r.json()
        log["status"] = "OK"
        log["rows_returned"] = len(data) if isinstance(data, list) else "unknown"
        manifest["fetch_log"].append(log)
        return data if isinstance(data, list) else []
    except Exception as e:
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["status"] = "FAILED"
        log["error"] = str(e)
        manifest["fetch_log"].append(log)
        return []


# ── NSE Quote API ──────────────────────────────────────────────────────
def nse_fetch_quote(session):
    url = f"https://www.nseindia.com/api/quote-equity?symbol={TICKER}"
    log = log_entry("NSE Quote API", url)
    t0 = time.monotonic()
    try:
        r = session.get(url, timeout=30)
        log["status_code"] = r.status_code
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["response_bytes"] = len(r.content)
        r.raise_for_status()
        q = r.json()
        log["status"] = "OK"
        manifest["fetch_log"].append(log)
        return q
    except Exception as e:
        log["duration_ms"] = round((time.monotonic() - t0) * 1000)
        log["status"] = "FAILED"
        log["error"] = str(e)
        manifest["fetch_log"].append(log)
        return None


# ── Company IR Page Discovery ──────────────────────────────────────────
def try_ir_page():
    ir_urls = [
        "https://groww.in/investors",
        "https://www.billionbrainsgarageventures.com/investors",
        "https://www.billionbrainsgarageventures.com/investor-relations",
        "https://groww.in/investor-relations",
    ]
    for url in ir_urls:
        log = log_entry("Company IR Page Discovery", url)
        t0 = time.monotonic()
        try:
            r = requests.get(url, headers={"User-Agent": NSE_HEADERS["User-Agent"]},
                             timeout=15, allow_redirects=True)
            log["status_code"] = r.status_code
            log["duration_ms"] = round((time.monotonic() - t0) * 1000)
            log["final_url"] = r.url
            if r.status_code == 200:
                log["status"] = "OK"
                log["note"] = f"Page found ({len(r.content)} bytes), may contain annual report links"
                manifest["fetch_log"].append(log)
                return r.text, r.url
            else:
                log["status"] = "NOT_FOUND"
                manifest["fetch_log"].append(log)
        except Exception as e:
            log["duration_ms"] = round((time.monotonic() - t0) * 1000)
            log["status"] = "FAILED"
            log["error"] = str(e)
            manifest["fetch_log"].append(log)
    return None, None


# ── Main ───────────────────────────────────────────────────────────────
def main():
    file_counter = {"quarterly": 0, "presentation": 0, "transcript": 0, "other": 0}

    print(f"{'='*60}")
    print(f"Fetching filings for {COMPANY_NAME} ({TICKER})")
    print(f"BSE: {SCRIP_CODE} | ISIN: {ISIN}")
    print(f"{'='*60}\n")

    # ── 1. BSE: Quarterly Results ──
    print("[1/7] BSE Announcements — Category: Result...")
    results = bse_fetch_category("Result")
    print(f"  → {len(results)} announcements found")

    for i, ann in enumerate(results[:6]):
        url = resolve_bse_url(ann.get("ATTACHMENTNAME"))
        headline = ann.get("HEADLINE", "")
        dt = ann.get("DT_TM", "")
        if not url:
            continue
        dest = OUT_DIR / f"q{i+1}_results.pdf"
        print(f"  Downloading: {headline[:80]}...")
        ok = download_pdf(url, dest, f"Q{i+1} Results")
        if ok:
            manifest["files"].append({
                "type": "quarterly_result",
                "path": str(dest.relative_to(ROOT)),
                "source_url": url,
                "headline": headline,
                "date": dt,
                "source": "BSE",
            })
            file_counter["quarterly"] += 1
        time.sleep(1)

    # ── 2. BSE: Company Updates (for investor presentations) ──
    print("\n[2/7] BSE Announcements — Category: Company Update...")
    updates = bse_fetch_category("Company Update")
    print(f"  → {len(updates)} announcements found")

    pres_count = 0
    for ann in updates:
        headline = (ann.get("HEADLINE") or "").lower()
        if "presentation" in headline or "investor" in headline:
            url = resolve_bse_url(ann.get("ATTACHMENTNAME"))
            dt = ann.get("DT_TM", "")
            if not url:
                continue
            pres_count += 1
            dest = OUT_DIR / f"investor_presentation_{pres_count}.pdf"
            print(f"  Downloading presentation: {ann.get('HEADLINE', '')[:80]}...")
            ok = download_pdf(url, dest, f"Investor Presentation {pres_count}")
            if ok:
                manifest["files"].append({
                    "type": "investor_presentation",
                    "path": str(dest.relative_to(ROOT)),
                    "source_url": url,
                    "headline": ann.get("HEADLINE"),
                    "date": dt,
                    "source": "BSE",
                })
                file_counter["presentation"] += 1
            time.sleep(1)
            if pres_count >= 3:
                break

    if pres_count == 0:
        print("  → No investor presentations found in Company Update")

    # ── 3. BSE: Earnings Call Transcripts (subcategory search) ──
    print("\n[3/7] BSE SubCategory — Earnings Call Transcript...")
    transcripts = bse_fetch_subcategory("Company Update", "Earnings Call Transcript")
    print(f"  → {len(transcripts)} transcript announcements found")

    for i, ann in enumerate(transcripts[:3]):
        url = resolve_bse_url(ann.get("ATTACHMENTNAME"))
        if not url:
            continue
        dest = OUT_DIR / f"earnings_transcript_{i+1}.pdf"
        print(f"  Downloading: {ann.get('HEADLINE', '')[:80]}...")
        ok = download_pdf(url, dest, f"Earnings Transcript {i+1}")
        if ok:
            manifest["files"].append({
                "type": "earnings_transcript",
                "path": str(dest.relative_to(ROOT)),
                "source_url": url,
                "headline": ann.get("HEADLINE"),
                "date": ann.get("DT_TM", ""),
                "source": "BSE",
            })
            file_counter["transcript"] += 1
        time.sleep(1)

    # ── 4. BSE: Other useful categories ──
    print("\n[4/7] BSE Announcements — Category: Board Meeting...")
    board = bse_fetch_category("Board Meeting")
    print(f"  → {len(board)} announcements found")

    for i, ann in enumerate(board[:3]):
        url = resolve_bse_url(ann.get("ATTACHMENTNAME"))
        if not url:
            continue
        dest = OUT_DIR / f"board_meeting_{i+1}.pdf"
        print(f"  Downloading: {ann.get('HEADLINE', '')[:80]}...")
        ok = download_pdf(url, dest, f"Board Meeting {i+1}")
        if ok:
            manifest["files"].append({
                "type": "board_meeting",
                "path": str(dest.relative_to(ROOT)),
                "source_url": url,
                "headline": ann.get("HEADLINE"),
                "date": ann.get("DT_TM", ""),
                "source": "BSE",
            })
            file_counter["other"] += 1
        time.sleep(1)

    # ── 5. NSE: Corporate Announcements + Quote ──
    print("\n[5/7] NSE — Establishing session...")
    nse_sess, nse_ok = nse_session()

    if nse_ok:
        time.sleep(1)

        print("  Fetching corporate announcements...")
        nse_anns = nse_fetch_announcements(nse_sess)
        print(f"  → {len(nse_anns)} NSE announcements found")

        nse_results_found = []
        nse_pres_found = []
        for ann in nse_anns:
            subj = (ann.get("subject") or "").lower()
            desc = (ann.get("desc") or "").lower()
            combined = subj + " " + desc
            if "financial result" in combined or "quarterly" in combined:
                nse_results_found.append(ann)
            if "presentation" in combined or "investor" in combined:
                nse_pres_found.append(ann)

        print(f"  → Results-related: {len(nse_results_found)}, Presentation-related: {len(nse_pres_found)}")
        manifest["fetch_log"].append({
            "source": "NSE Announcements Analysis",
            "status": "OK",
            "results_related": len(nse_results_found),
            "presentation_related": len(nse_pres_found),
            "note": "NSE announcements don't always include direct PDF links; BSE is primary source",
        })

        # NSE attachments (if available)
        for i, ann in enumerate(nse_pres_found[:2]):
            att_url = ann.get("attchmntFile")
            if att_url and att_url.startswith("http") and att_url.endswith(".pdf"):
                dest = OUT_DIR / f"nse_presentation_{i+1}.pdf"
                print(f"  Downloading NSE attachment: {ann.get('subject', '')[:60]}...")
                ok = download_pdf(att_url, dest, f"NSE Presentation {i+1}")
                if ok:
                    manifest["files"].append({
                        "type": "investor_presentation",
                        "path": str(dest.relative_to(ROOT)),
                        "source_url": att_url,
                        "headline": ann.get("subject"),
                        "date": ann.get("an_dt", ""),
                        "source": "NSE",
                    })
                time.sleep(1)

        time.sleep(1)

        # NSE Quote
        print("\n[6/7] NSE — Fetching quote data...")
        quote = nse_fetch_quote(nse_sess)
        if quote:
            info = quote.get("info", {})
            price = quote.get("priceInfo", {})
            metadata = quote.get("metadata", {})
            summary = {
                "ticker": TICKER,
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
                "fetch_log": [manifest["fetch_log"][-1]],
            }
            price_path = OUT_DIR / "price_summary.json"
            price_path.write_text(json.dumps(summary, indent=2))
            print(f"  LTP: Rs {summary['price']['ltp']}  "
                  f"52w: Rs {summary['price']['week52_low']} – Rs {summary['price']['week52_high']}  "
                  f"P/E: {summary['ratios']['pe']}")
        else:
            print("  → Quote fetch failed")
    else:
        print("  → NSE session failed, skipping NSE sources")
        manifest["fetch_log"].append({
            "source": "NSE Corporate Announcements",
            "status": "SKIPPED",
            "note": "NSE session could not be established",
        })

    # ── 6. Company IR Page ──
    print("\n[7/7] Company IR Page Discovery...")
    ir_html, ir_url = try_ir_page()
    if ir_html:
        print(f"  → Found IR page at {ir_url}")
        pdf_links = re.findall(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', ir_html, re.IGNORECASE)
        annual_links = [l for l in pdf_links if "annual" in l.lower() or "report" in l.lower()]
        print(f"  → {len(pdf_links)} PDF links found, {len(annual_links)} annual-report-related")
        manifest["fetch_log"].append({
            "source": "Company IR Page PDF Discovery",
            "url": ir_url,
            "status": "OK",
            "total_pdf_links": len(pdf_links),
            "annual_report_links": len(annual_links),
            "links_sample": annual_links[:5] if annual_links else pdf_links[:5],
        })

        for i, link in enumerate(annual_links[:2]):
            if not link.startswith("http"):
                from urllib.parse import urljoin
                link = urljoin(ir_url, link)
            dest = OUT_DIR / f"annual_report_{i+1}.pdf"
            print(f"  Downloading: {link[:80]}...")
            ok = download_pdf(link, dest, f"Annual Report {i+1}")
            if ok:
                manifest["files"].append({
                    "type": "annual_report",
                    "path": str(dest.relative_to(ROOT)),
                    "source_url": link,
                    "headline": "Annual Report (from IR page)",
                    "source": "Company IR Page",
                })
            time.sleep(1)
    else:
        print("  → No IR page found")
        manifest["fetch_log"].append({
            "source": "Company IR Page Discovery",
            "status": "NOT_FOUND",
            "note": "Tried multiple URL patterns, none returned 200",
        })

    # ── Write manifest ──
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\n{'='*60}")
    print(f"Done. Manifest: {manifest_path}")
    print(f"Files fetched: {len(manifest['files'])}")
    print(f"  Quarterly results: {file_counter['quarterly']}")
    print(f"  Investor presentations: {file_counter['presentation']}")
    print(f"  Earnings transcripts: {file_counter['transcript']}")
    print(f"  Other (board meetings): {file_counter['other']}")
    print(f"Fetch log entries: {len(manifest['fetch_log'])}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
