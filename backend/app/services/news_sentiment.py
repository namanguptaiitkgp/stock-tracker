import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.ai.gemini_client import call_gemini_with_rotation

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

SENTIMENT_PROMPT = """SYSTEM: You are a quantitative equity analyst evaluating news impact for {company_name} (NSE: {symbol}) on {today_ist}.
INPUT: {headlines}
TASK: Calculate a strict, anchored sentiment score and summarize the catalysts.
RULES:
1. [RELEVANCE] Ignore headlines where {company_name} is only mentioned incidentally. Assess relevance from 0 (noise) to 100 (direct material impact).
2. [STRICT ANCHORS] You must score sentiment from -100 to +100 based on these exact Dalal Street anchors:
   * +90 to +100: Blockbuster earnings beat, major government/defense contract, massive promoter buying.
   * +40 to +60: Positive FII momentum, steady order wins, favorable sector tailwinds.
   * -10 to +10: Routine corporate coverage, macro noise, irrelevant PR.
   * -40 to -60: Missed earnings, margin contraction, promoter stake sale.
   * -90 to -100: SEBI probe, ED raids, high promoter pledging invoked, auditor resignation.
3. [TRACEABILITY] Every item in `key_themes` must be directly traceable to a headline with a relevance score > 50.

OUTPUT FORMAT:
Start your response with "{{" and end with "}}". Do not output markdown fences.
{{
  "sentiment": "bullish" | "bearish" | "neutral",
  "score": <int>,
  "summary": "2-3 sentence summary of overall news sentiment and what's driving it",
  "key_themes": ["theme1", "theme2"],
  "headlines": [
    {{
      "title": "<exact headline>",
      "relevance_score": <int>,
      "impact": "high" | "medium" | "low"
    }}
  ]
}}
"""


async def fetch_google_news(symbol: str, company_name: str, days: int = 30) -> list[dict]:
    """Fetch news headlines from Google News RSS using multiple search queries.
    Searches: 1) "{symbol} share price"  2) "{company_name} share price"
    Then merges and deduplicates results."""

    # Strip common suffixes like "Ltd", "Limited" for a cleaner search name
    short_name = company_name or symbol
    for suffix in [" Limited", " Ltd", " Ltd.", " Private", " Industries"]:
        short_name = short_name.replace(suffix, "").strip()

    # Build multiple search queries for better coverage
    queries = [
        f"%22{symbol}+share+price%22+when:{days}d",
        f"%22{short_name.replace(' ', '+')}+share+price%22+when:{days}d",
    ]
    # If company_name is different from symbol (e.g., "Eternal Limited" vs "ETERNAL"),
    # also search the registered name
    if company_name and company_name.upper() != symbol:
        queries.append(f"%22{company_name.replace(' ', '+')}%22+stock+when:{days}d")

    all_headlines: list[dict] = []
    seen_titles: set[str] = set()

    for query in queries:
        url = GOOGLE_NEWS_RSS.format(query=query)
        try:
            feed_text = await asyncio.to_thread(_fetch_rss, url)
            if not feed_text:
                continue

            feed = feedparser.parse(feed_text)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            for entry in feed.entries[:20]:
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

                    title = entry.get("title", "")
                    source = ""
                    if " - " in title:
                        parts = title.rsplit(" - ", 1)
                        title = parts[0].strip()
                        source = parts[1].strip()

                    # Deduplicate by title
                    title_key = title.lower().strip()[:80]
                    if title_key in seen_titles:
                        continue
                    seen_titles.add(title_key)

                    all_headlines.append({
                        "title": title,
                        "source": source,
                        "url": entry.get("link", ""),
                        "date": pub_date.strftime("%Y-%m-%d") if pub_date else None,
                    })
                except Exception:
                    continue

        except Exception as e:
            logger.warning(f"Google News fetch failed for query '{query}': {e}")

    # Sort by date (newest first), return top 25
    all_headlines.sort(key=lambda h: h.get("date") or "", reverse=True)
    return all_headlines[:25]


async def fetch_google_news_custom(query: str, days: int = 30) -> list[dict]:
    """Fetch Google News headlines using a custom search query string."""
    encoded_query = query.replace(" ", "+") + f"+when:{days}d"
    url = GOOGLE_NEWS_RSS.format(query=encoded_query)

    try:
        feed_text = await asyncio.to_thread(_fetch_rss, url)
        if not feed_text:
            return []

        feed = feedparser.parse(feed_text)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        headlines = []
        for entry in feed.entries[:25]:
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

                title = entry.get("title", "")
                source = ""
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()

                headlines.append({
                    "title": title,
                    "source": source,
                    "url": entry.get("link", ""),
                    "date": pub_date.strftime("%Y-%m-%d") if pub_date else None,
                })
            except Exception:
                continue

        return headlines[:25]
    except Exception as e:
        logger.warning(f"Google News custom search failed for '{query}': {e}")
        return []


def _fetch_rss(url: str) -> str:
    """Sync HTTP fetch for RSS feed."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AlgoTrader/1.0)",
        }) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.text
    except Exception as e:
        logger.warning(f"RSS fetch error: {e}")
    return ""


async def analyze_sentiment(
    symbol: str,
    company_name: str,
    headlines: list[dict],
    user_id: int,
    db,
) -> dict:
    """Use Gemini to analyze sentiment of news headlines."""
    if not headlines:
        return {
            "sentiment": "neutral",
            "score": 0,
            "summary": f"No recent news found for {symbol}.",
            "key_themes": [],
            "headlines": [],
        }

    # Sort headlines by recency descending. The anchor-based prompt does NOT
    # see inline decay weights — the sort order itself is the temporal
    # signal. Math in Python, semantic reasoning in the LLM. Headlines
    # without a parseable date sort to the end.
    from zoneinfo import ZoneInfo as _ZoneInfo

    def _hdate(h: dict) -> str:
        return (h.get("date") or h.get("published_at") or "")[:10]

    headlines_sorted = sorted(headlines, key=_hdate, reverse=True)

    headline_text = "\n".join(
        f"- {h['title']} ({h.get('source', '?')}, {h.get('date', '?')})"
        for h in headlines_sorted
    )

    today_ist = datetime.now(tz=_ZoneInfo("Asia/Kolkata")).strftime("%d %B %Y")

    prompt = SENTIMENT_PROMPT.format(
        symbol=symbol,
        company_name=company_name or symbol,
        today_ist=today_ist,
        headlines=headline_text,
    )

    try:
        raw = await call_gemini_with_rotation(user_id, db, prompt)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(cleaned)

        # Merge URL info back into AI-analyzed headlines
        ai_headlines = result.get("headlines", [])
        for i, ah in enumerate(ai_headlines):
            if i < len(headlines):
                ah["url"] = headlines[i].get("url", "")
                ah["source"] = headlines[i].get("source", ah.get("source", ""))
                ah["date"] = headlines[i].get("date", ah.get("date", ""))

        return result
    except Exception as e:
        logger.warning(f"Sentiment analysis failed for {symbol}: {e}")
        # Fallback: return headlines without AI analysis
        return {
            "sentiment": "neutral",
            "score": 0,
            "summary": f"AI analysis unavailable. {len(headlines)} headlines found.",
            "key_themes": [],
            "headlines": [
                {"title": h["title"], "source": h.get("source", ""), "date": h.get("date", ""), "url": h.get("url", ""), "sentiment": "neutral", "impact": "medium"}
                for h in headlines
            ],
        }


async def _headlines_from_unified_aggregator(
    symbol: str, days: int, user_id: int, db,
) -> list[dict]:
    """Pull headlines mentioning *symbol* from the unified 18-source aggregator."""
    try:
        from app.services.news.inbox_aggregator import fetch_all_news
        from app.services.news.inbox_classifier import classify_headlines

        all_news = await fetch_all_news(days=days, cap=200)
        classified = await classify_headlines(list(all_news), user_id, db)

        sym = symbol.upper()
        out: list[dict] = []
        for item in classified:
            stocks = item.get("stocks") or []
            if any((s.get("symbol") or "").upper() == sym for s in stocks):
                pub = item.get("published_at") or ""
                if pub and "T" in pub:
                    pub = pub[:10]
                out.append({
                    "title": item["title"],
                    "source": item.get("source", ""),
                    "url": item.get("url", ""),
                    "date": pub,
                })
        return out
    except Exception as e:
        logger.warning(f"Unified aggregator headlines failed for {symbol}: {e}")
        return []


async def get_news_sentiment(
    symbol: str,
    company_name: str | None = None,
    days: int = 7,
    user_id: int = 0,
    db=None,
) -> dict:
    """Full pipeline: fetch from all 18 sources + Google News per-stock → analyze sentiment."""
    name = company_name or symbol

    inbox_headlines, google_headlines = await asyncio.gather(
        _headlines_from_unified_aggregator(symbol, days, user_id, db),
        fetch_google_news(symbol, name, days=days),
    )

    seen: set[str] = set()
    merged: list[dict] = []
    for h in inbox_headlines + google_headlines:
        key = (h.get("title") or "").lower().strip()[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(h)

    merged.sort(key=lambda h: h.get("date") or "", reverse=True)
    merged = merged[:30]

    analysis = await analyze_sentiment(symbol, name, merged, user_id, db)

    analysis["symbol"] = symbol
    analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    analysis["headline_count"] = len(merged)
    analysis["days_analyzed"] = days
    sources_used = sorted({h.get("source", "") for h in merged if h.get("source")})
    analysis["sources_used"] = sources_used

    return analysis
