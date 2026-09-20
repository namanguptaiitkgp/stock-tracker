"""Scrape google.com/finance/quote pages for quick in-app lookups.

Not a realtime feed — 10–15 s latency typical. Used by the floating
Finance widget to show price/change/key-stats without leaving the page.
Short in-memory cache keeps re-queries snappy and reduces scrape load.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, asdict
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}

CACHE_TTL_SECONDS = 60
# Bounded LRU — caps memory on a long-running process. 60s TTL means most
# entries roll over fast, so 4096 keys is plenty.
_CACHE_MAX = 4096
from collections import OrderedDict as _OD  # local import to keep file-top tidy
_cache: "_OD[str, tuple[float, dict]]" = _OD()


def _cache_put(key: str, payload: tuple[float, dict]) -> None:
    if key in _cache:
        _cache.move_to_end(key)
    _cache[key] = payload
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


# Common exchanges Google Finance understands.
DEFAULT_EXCHANGES = ["NSE", "BSE", "NASDAQ", "NYSE", "LON", "TYO", "HKG"]


@dataclass
class GFQuote:
    query: str
    symbol: str
    exchange: str
    name: str | None
    url: str
    last_price: float | None
    currency: str | None
    change: float | None
    change_pct: float | None
    prev_close: float | None
    day_range: str | None
    year_range: str | None
    market_cap: str | None
    pe_ratio: str | None
    dividend_yield: str | None
    avg_volume: str | None
    about: str | None
    high_52w: float | None = None
    low_52w: float | None = None
    eps: float | None = None
    day_high: float | None = None
    day_low: float | None = None


def _f(raw: str | None) -> float | None:
    if not raw:
        return None
    raw = raw.replace(",", "").replace("₹", "").replace("$", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _pct(raw: str | None) -> float | None:
    """Parse "+0.12%" or "-1.45%" or "1.23%". Returns signed float."""
    if not raw:
        return None
    raw = raw.strip().rstrip("%").replace(",", "")
    return _f(raw)


def _first(pattern: str, text: str, flags: int = re.DOTALL) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _extract_key_stats(html: str) -> dict[str, str]:
    """Extract label→value pairs from Google Finance key stats section.

    Current structure (as of May 2026):
        <div class="SwQK7">Label</div>
        <div class="dO6ijd">Value</div>
    """
    return dict(re.findall(
        r'<div class="SwQK7">([^<]+)</div>\s*<div class="dO6ijd">([^<]+)</div>',
        html,
    ))


async def _fetch_quote_page(symbol: str, exchange: str) -> tuple[str, str] | None:
    url = f"https://www.google.com/finance/quote/{symbol}:{exchange}"
    async with httpx.AsyncClient(
        timeout=15, headers=HEADERS, follow_redirects=True
    ) as c:
        try:
            r = await c.get(url)
            if r.status_code != 200:
                return None
            return (url, r.text)
        except Exception as e:
            logger.warning("GF fetch failed for %s:%s — %s", symbol, exchange, e)
            return None


def _parse_quote_html(html: str, query: str, symbol: str, exchange: str, url: str) -> GFQuote:
    title = _first(r"<title>([^<]+)</title>", html)
    name = None
    if title:
        name = re.sub(r"\s*\([^)]+\)\s*Stock Price.*$", "", title).strip()

    # Current price: <div class="N6SYTe"><span ...><span>₹1,361.20</span></span></div>
    price_raw = _first(r'class="N6SYTe"[^>]*>(.+?)</div>', html)
    if price_raw:
        price_raw = re.sub(r"<[^>]+>", "", price_raw).strip()
    currency = None
    if price_raw:
        m = re.match(r"([^\d\-\s.,]+)?\s*([\d.,]+)", price_raw.strip())
        if m:
            currency = (m.group(1) or "").strip() or None
    last_price = _f(price_raw)

    # Key stats: <div class="SwQK7">Label</div><div class="dO6ijd">Value</div>
    stats = _extract_key_stats(html)

    open_price = _f(stats.get("Open"))
    day_high = _f(stats.get("High"))
    day_low = _f(stats.get("Low"))
    market_cap = stats.get("Mkt. cap") or stats.get("Mkt cap")
    avg_volume = stats.get("Avg. vol.") or stats.get("Avg vol.")
    volume = stats.get("Volume")
    pe_ratio = stats.get("P/E ratio")
    dividend_raw = stats.get("Dividend")
    dividend_yield = dividend_raw.rstrip("%") if dividend_raw else None
    high_52w = _f(stats.get("52-wk high"))
    low_52w = _f(stats.get("52-wk low"))
    eps = _f(stats.get("EPS"))

    # Prev close: not in static HTML. Approximate from Open price.
    prev_close = open_price

    # Day/year range strings for backward compat
    day_range = f"{stats.get('Low', '-')} - {stats.get('High', '-')}" if day_high else None
    year_range = f"{stats.get('52-wk low', '-')} - {stats.get('52-wk high', '-')}" if high_52w else None

    change = None
    change_pct = None
    if last_price is not None and prev_close is not None and prev_close != 0:
        change = round(last_price - prev_close, 4)
        change_pct = round((change / prev_close) * 100, 4)

    about = _first(r'class="bLLb2d">([^<]{20,400})</div>', html)

    return GFQuote(
        query=query,
        symbol=symbol,
        exchange=exchange,
        name=name,
        url=url,
        last_price=last_price,
        currency=currency,
        change=change,
        change_pct=change_pct,
        prev_close=prev_close,
        day_range=day_range,
        year_range=year_range,
        market_cap=market_cap,
        pe_ratio=pe_ratio,
        dividend_yield=dividend_yield,
        avg_volume=avg_volume or volume,
        about=about,
        high_52w=high_52w,
        low_52w=low_52w,
        eps=eps,
        day_high=day_high,
        day_low=day_low,
    )


def _parse_query(raw: str, default_exchange: str = "NSE") -> tuple[str, str]:
    q = (raw or "").strip().upper()
    if ":" in q:
        sym, exch = q.split(":", 1)
        return sym.strip(), exch.strip()
    return q, default_exchange


async def lookup(query: str, default_exchange: str = "NSE") -> dict[str, Any]:
    """Return a serialized GFQuote (dict). On miss, tries the provided
    exchange first, then falls back to other common exchanges."""
    q = (query or "").strip()
    if not q:
        return {"error": "empty query"}

    now = time.time()
    cache_key = f"{q.upper()}|{default_exchange}"
    hit = _cache.get(cache_key)
    if hit and (now - hit[0]) < CACHE_TTL_SECONDS:
        _cache.move_to_end(cache_key)
        return {**hit[1], "cached": True}

    symbol, exchange = _parse_query(q, default_exchange)
    to_try = [exchange]
    for e in DEFAULT_EXCHANGES:
        if e not in to_try:
            to_try.append(e)

    last_err: str | None = None
    for ex in to_try:
        fetched = await _fetch_quote_page(symbol, ex)
        if not fetched:
            last_err = f"fetch failed for {symbol}:{ex}"
            continue
        url, html = fetched
        # Heuristic: if Google serves a "not found" page, `last_price`
        # will be None. Only accept a result that has a price.
        quote = _parse_quote_html(html, query=q, symbol=symbol, exchange=ex, url=url)
        if quote.last_price is not None:
            data = asdict(quote)
            data["cached"] = False
            _cache_put(cache_key, (now, data))
            return data
        last_err = f"no price parsed for {symbol}:{ex}"

    return {
        "error": last_err or "no match",
        "query": q,
        "tried_exchanges": to_try,
    }
