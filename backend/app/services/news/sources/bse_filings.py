"""BSE Corporate Filings scraper.

Pulls recent corporate announcements from the BSE public API. Each filing
has a direct scrip<->symbol mapping, so we don't need Gemini company
extraction for this source.

In-memory 30-min cache.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import httpx

from app.services.data_cache import cache_get_or_fetch, cache_invalidate_prefix

logger = logging.getLogger(__name__)

BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
BSE_PDF_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"

CACHE_SECONDS = 2 * 60 * 60  # 2h, aligned to global default

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}


def _fmt_bse_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def _parse_bse_dt(s: str | None) -> str | None:
    if not s:
        return None
    # BSE returns timestamps like "2026-04-30T15:32:00" (no tz) or "2026-04-30T15:32:00.000"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            # Treat as IST (BSE local time), convert to UTC
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


async def _do_fetch_bse(days: int, limit: int) -> list[dict]:
    today = date.today()
    start = today - timedelta(days=days)

    params = {
        "pageno": "1",
        "strCat": "-1",          # all categories
        "strPrevDate": _fmt_bse_date(start),
        "strScrip": "",
        "strSearch": "P",
        "strToDate": _fmt_bse_date(today),
        "strType": "C",           # Company filings
        "subcategory": "-1",
    }

    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=HEADERS) as client:
            # Warm up cookies (BSE often requires a prior visit)
            try:
                await client.get("https://www.bseindia.com/corporates/ann.html")
            except Exception:
                pass
            resp = await client.get(BSE_API, params=params)
            if resp.status_code != 200:
                logger.info(f"BSE filings returned {resp.status_code}")
                return []
            data = resp.json()
    except Exception as e:
        logger.info(f"BSE filings fetch failed: {e}")
        return []

    rows = data.get("Table") or []
    out: list[dict] = []
    for r in rows[:limit]:
        try:
            scrip_code = r.get("SCRIP_CD") or r.get("ScripCd")
            symbol = (r.get("SLONGNAME") or r.get("CompName") or "").strip()
            short_symbol = (r.get("NSURL") or r.get("NEWSSUB") or "").strip()
            company_name = (r.get("SLONGNAME") or "").strip()
            heading = (r.get("HEADLINE") or r.get("NEWSSUB") or "").strip()
            news_id = r.get("NEWSID") or ""
            attachment = (r.get("ATTACHMENTNAME") or "").strip()
            category = (r.get("CATEGORYNAME") or r.get("SUBCATNAME") or "").strip()
            news_dt = r.get("NEWS_DT") or r.get("DT_TM")

            sym = (r.get("NSE_SYMBOL") or short_symbol or company_name or "").upper().strip()
            if not heading or not sym:
                continue

            url = ""
            if attachment:
                url = f"{BSE_PDF_BASE}{attachment}"
            elif news_id:
                url = f"https://www.bseindia.com/corporates/anndet_new.aspx?newsid={news_id}"

            title = heading if not company_name else f"{company_name}: {heading}"

            out.append({
                "title": title[:280],
                "url": url,
                "source": "BSE Filings",
                "published_at": _parse_bse_dt(news_dt),
                "stocks": [{"symbol": sym, "name": company_name or sym}],
                "category": category,
                "scrip_code": str(scrip_code) if scrip_code else None,
            })
        except Exception:
            continue

    # Newest first
    out.sort(key=lambda h: h.get("published_at") or "", reverse=True)
    return out


async def fetch_bse_filings(days: int = 2, limit: int = 50, force: bool = False) -> list[dict]:
    """Fetch recent BSE corporate announcements. DB-cached 2h via data_cache.

    Returns list of:
      { title, url, source: "BSE Filings", published_at, stocks: [{symbol, name}],
        category, scrip_code }
    """
    key = f"bse:filings:{days}d:{limit}"
    payload, _fetched_at = await cache_get_or_fetch(
        key,
        fetch_fn=lambda: _do_fetch_bse(days, limit),
        ttl_seconds=CACHE_SECONDS,
        force=force,
    )
    return payload


async def clear_cache() -> None:
    await cache_invalidate_prefix("bse:")
