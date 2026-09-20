import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

logger = logging.getLogger(__name__)

HINDU_BL_FEEDS = [
    ("Markets", "https://www.thehindubusinessline.com/markets/feeder/default.rss"),
    ("Stock Markets", "https://www.thehindubusinessline.com/markets/stock-markets/feeder/default.rss"),
    ("Companies", "https://www.thehindubusinessline.com/companies/feeder/default.rss"),
    ("Portfolio", "https://www.thehindubusinessline.com/portfolio/feeder/default.rss"),
    ("Stock Fundamentals", "https://www.thehindubusinessline.com/portfolio/stock-fundamental-analysis-india/feeder/default.rss"),
    ("Economy", "https://www.thehindubusinessline.com/economy/feeder/default.rss"),
    ("Money & Banking", "https://www.thehindubusinessline.com/money-and-banking/feeder/default.rss"),
]

async def _fetch_single_feed(url: str, feed_name: str) -> list[dict]:
    """Fetch a single RSS feed."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AlgoTrader/1.0)",
        }) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Feed {feed_name} returned {resp.status_code}")
                return []

            feed = feedparser.parse(resp.text)
            cutoff = datetime.now(timezone.utc) - timedelta(days=2)

            headlines = []
            for entry in feed.entries[:30]:
                try:
                    pub_date = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    elif hasattr(entry, "published") and entry.published:
                        try:
                            pub_date = parsedate_to_datetime(entry.published)
                        except Exception:
                            pass

                    if pub_date and pub_date < cutoff:
                        continue

                    title = entry.get("title", "").strip()
                    if not title:
                        continue

                    description = ""
                    if hasattr(entry, "summary"):
                        description = entry.summary[:300] if entry.summary else ""

                    headlines.append({
                        "title": title,
                        "url": entry.get("link", ""),
                        "date": pub_date.strftime("%Y-%m-%d") if pub_date else date.today().isoformat(),
                        "source": f"Hindu BL - {feed_name}",
                        "description": description,
                    })
                except Exception:
                    continue

            return headlines
    except Exception as e:
        logger.warning(f"Failed to fetch feed {feed_name}: {e}")
        return []


async def _fetch_all_feeds_uncached() -> list[dict]:
    tasks = [_fetch_single_feed(url, name) for name, url in HINDU_BL_FEEDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_headlines = []
    seen_titles = set()

    for result in results:
        if isinstance(result, Exception):
            continue
        for h in result:
            # Deduplicate by title
            title_key = h["title"].lower().strip()[:80]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                all_headlines.append(h)

    # Sort by date, newest first
    all_headlines.sort(key=lambda x: x.get("date", ""), reverse=True)
    return all_headlines[:100]  # cap at 100


async def fetch_all_feeds() -> list[dict]:
    """Hindu BL RSS aggregator — deduplicated via the unified `fetch_cache`
    (2h TTL) so all callers (inbox_aggregator, market_news_aggregator,
    morning_news_scan) share a single fan-out per refresh window."""
    from app.services.data_cache import cache_get_or_fetch
    payload, _fetched_at = await cache_get_or_fetch(
        "rss:hindu_bl_all",
        fetch_fn=_fetch_all_feeds_uncached,
        ttl_seconds=2 * 60 * 60,
    )
    return payload or []


async def run_morning_news_scan(user_id: int, db) -> dict:
    """Unified pipeline: fetch all sources → classify via Gemini → group by company.

    Uses the shared ``inbox_aggregator.fetch_all_news`` for fetching (all 18
    sources) and ``inbox_classifier.classify_headlines`` for per-headline
    stock tagging + sentiment.  One fetch, one classify — shared cache with
    the News Inbox UI.
    """
    from app.services.news.inbox_aggregator import fetch_all_news
    from app.services.news.inbox_classifier import classify_headlines

    raw_headlines = await fetch_all_news(days=1, cap=200, force=True)
    logger.info(f"Fetched {len(raw_headlines)} headlines from unified aggregator")

    if not raw_headlines:
        return {
            "report_date": date.today().isoformat(),
            "total_headlines": 0,
            "companies_found": 0,
            "companies": [],
            "all_headlines": [],
        }

    classified = await classify_headlines(list(raw_headlines), user_id, db)

    company_headlines: dict[str, list[dict]] = {}
    company_names: dict[str, str] = {}

    for item in classified:
        for stock in item.get("stocks") or []:
            symbol = (stock.get("symbol") or "").upper()
            if not symbol:
                continue
            company_names[symbol] = stock.get("name", symbol)
            company_headlines.setdefault(symbol, []).append(item)

    sentiment_map = {"tailwind": "bullish", "headwind": "bearish", "context": "neutral"}
    score_map = {"tailwind": 60, "headwind": -60, "context": 0}

    company_results = []
    for symbol, headlines in company_headlines.items():
        tailwind = sum(1 for h in headlines if h.get("sentiment") == "tailwind")
        headwind = sum(1 for h in headlines if h.get("sentiment") == "headwind")
        net = tailwind - headwind
        if net > 0:
            overall = "bullish"
            score = min(100, 40 + net * 20)
        elif net < 0:
            overall = "bearish"
            score = max(-100, -40 + net * 20)
        else:
            overall = "neutral"
            score = 0

        company_results.append({
            "symbol": symbol,
            "name": company_names.get(symbol, symbol),
            "sentiment": overall,
            "score": score,
            "summary": f"{tailwind} tailwind, {headwind} headwind across {len(headlines)} headlines",
            "headline_count": len(headlines),
            "headlines": [
                {
                    "title": h["title"],
                    "url": h.get("url", ""),
                    "date": h.get("published_at", date.today().isoformat()),
                    "source": h.get("source", ""),
                    "sentiment": sentiment_map.get(h.get("sentiment", ""), h.get("sentiment", "")),
                }
                for h in headlines[:5]
            ],
        })

    company_results.sort(key=lambda c: abs(c.get("score", 0)), reverse=True)

    sources_used = sorted({h.get("source", "") for h in raw_headlines if h.get("source")})

    return {
        "report_date": date.today().isoformat(),
        "total_headlines": len(raw_headlines),
        "companies_found": len(company_results),
        "companies": company_results,
        "all_headlines": [
            {
                "title": h["title"],
                "url": h.get("url", ""),
                "date": h.get("published_at", date.today().isoformat()),
                "source": h.get("source", ""),
            }
            for h in raw_headlines
        ],
        "feeds_used": sources_used,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }
