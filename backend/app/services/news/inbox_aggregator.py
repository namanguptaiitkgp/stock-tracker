"""Unified news aggregator — single fetch + cache for all news consumers.

Sources (RSS):
- Hindu Business Line (7 feeds via existing scraper)
- Moneycontrol (3 feeds)
- ET Markets (2 feeds)
- Mint (2 feeds)
- Reuters India (2 feeds)
- PIB (Press Information Bureau, 1 feed)
- Google News (broad Indian market query)

BSE Filings (scraped from BSE API) is handled separately in ``bse_filings.py``
because it has structured per-filing metadata and bypasses Gemini company
extraction (BSE provides the symbol directly).

DB-cached via ``data_cache.cache_get_or_fetch`` with a 2-hour TTL.
All consumers — the News page, the morning pipeline broad scan, and the
dashboard refresh — share this single cached fetch.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.services.data_cache import cache_get_or_fetch

logger = logging.getLogger(__name__)

CACHE_SECONDS = 2 * 60 * 60  # 2h

RSS_SOURCES = [
    # Moneycontrol
    ("Moneycontrol", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/MCtopnews.xml"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/buzzingstocks.xml"),
    # ET Markets
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("ET Markets", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    # Mint
    ("Mint", "https://www.livemint.com/rss/markets"),
    ("Mint", "https://www.livemint.com/rss/companies"),
    # Reuters India
    ("Reuters", "https://feeds.reuters.com/reuters/INbusinessNews"),
    ("Reuters", "https://feeds.reuters.com/reuters/INtopNews"),
    # PIB (government releases)
    ("PIB", "https://pib.gov.in/RssMain.aspx?ModId=2&Lang=1&Regid=3"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AlgoTrader/1.0)",
    "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _normalize_title(t: str) -> str:
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:120]


async def _fetch_rss(source_name: str, url: str, days: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.info(f"{source_name} RSS returned {resp.status_code}")
                return []
            feed = feedparser.parse(resp.text)
    except Exception as e:
        logger.info(f"{source_name} RSS fetch failed ({url}): {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days + 1)
    out: list[dict] = []
    for entry in feed.entries[:30]:
        try:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            pub_date = None
            if getattr(entry, "published_parsed", None):
                pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif getattr(entry, "published", None):
                try:
                    pub_date = parsedate_to_datetime(entry.published)
                except Exception:
                    pass
            if pub_date and pub_date < cutoff:
                continue
            summary = (entry.get("summary") or "").strip()
            if summary:
                summary = re.sub(r"<[^>]+>", "", summary).strip()[:300]
            out.append({
                "title": title,
                "url": entry.get("link") or "",
                "source": source_name,
                "published_at": pub_date.isoformat() if pub_date else None,
                "description": summary or None,
            })
        except Exception:
            continue
    return out


async def _fetch_hindu_bl() -> list[dict]:
    try:
        from app.services.news_scraper import fetch_all_feeds
        items = await fetch_all_feeds()
        out: list[dict] = []
        for h in items:
            d = h.get("date")
            iso = None
            if d:
                try:
                    iso = datetime.fromisoformat(d).replace(tzinfo=timezone.utc).isoformat()
                except Exception:
                    iso = None
            out.append({
                "title": h["title"],
                "url": h.get("url", ""),
                "source": "Hindu BL",
                "published_at": iso,
                "description": h.get("description") or None,
            })
        return out
    except Exception as e:
        logger.info(f"Hindu BL fetch failed: {e}")
        return []


async def _fetch_google_news(days: int) -> list[dict]:
    try:
        from app.services.news_sentiment import fetch_google_news_custom
        items = await fetch_google_news_custom(
            "Indian stock market Nifty Sensex today", days=days
        )
        return [{
            "title": h.get("title", ""),
            "url": h.get("url", ""),
            "source": h.get("source") or "Google News",
            "published_at": h.get("date"),
            "description": h.get("description") or None,
        } for h in items if h.get("title")]
    except Exception as e:
        logger.info(f"Google News fetch failed: {e}")
        return []


async def _aggregate_all(days: int, cap: int) -> list[dict]:
    coros = [_fetch_hindu_bl(), _fetch_google_news(days)]
    for name, url in RSS_SOURCES:
        coros.append(_fetch_rss(name, url, days))
    results = await asyncio.gather(*coros, return_exceptions=True)

    seen: set[str] = set()
    merged: list[dict] = []
    for r in results:
        if isinstance(r, Exception) or not r:
            continue
        for h in r:
            k = _normalize_title(h["title"])
            if not k or k in seen:
                continue
            seen.add(k)
            merged.append(h)

    merged.sort(key=lambda h: h.get("published_at") or "", reverse=True)
    return merged[:cap]


async def fetch_all_news(
    days: int = 1, cap: int = 200, force: bool = False,
) -> list[dict]:
    """Unified news fetch used by both the News Inbox UI and the morning
    pipeline broad scan. DB-cached 2h.

    Returns deduped list newest-first: [{title, url, source, published_at}].
    """
    payload, _ = await fetch_all_news_with_meta(days=days, cap=cap, force=force)
    return payload


async def fetch_all_news_with_meta(
    days: int = 1, cap: int = 200, force: bool = False,
) -> tuple[list[dict], dict]:
    """Variant that also returns cache metadata for the UI."""
    key = f"rss:unified_news:{days}d"
    payload, fetched_at = await cache_get_or_fetch(
        key,
        fetch_fn=lambda: _aggregate_all(days, cap),
        ttl_seconds=CACHE_SECONDS,
        force=force,
    )
    next_refresh = fetched_at + timedelta(seconds=CACHE_SECONDS) if fetched_at else None
    meta = {
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "next_refresh_at": next_refresh.isoformat() if next_refresh else None,
        "ttl_seconds": CACHE_SECONDS,
    }
    return payload or [], meta


# ── Backwards-compatible aliases ────────────────────────────────────
# Old callers (news_inbox.py) used these names.  Keep them working so
# we don't have to touch every import in one PR.

async def fetch_rss_news(days: int = 1, cap: int = 80, force: bool = False) -> list[dict]:
    return await fetch_all_news(days=days, cap=cap, force=force)


async def fetch_rss_news_with_meta(
    days: int = 1, cap: int = 80, force: bool = False,
) -> tuple[list[dict], dict]:
    return await fetch_all_news_with_meta(days=days, cap=cap, force=force)


async def clear_cache() -> None:
    from app.services.data_cache import cache_invalidate_prefix
    await cache_invalidate_prefix("rss:unified_news")
    # Also clear legacy keys in case any are still cached
    await cache_invalidate_prefix("rss:inbox_all")
    await cache_invalidate_prefix("rss:market_news")


def available_sources() -> list[str]:
    rss = sorted({name for name, _ in RSS_SOURCES})
    return ["Google News", "Hindu BL", *rss, "BSE Filings"]
