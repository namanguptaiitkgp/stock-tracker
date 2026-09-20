import json
import logging
import re
from collections import OrderedDict

import httpx

logger = logging.getLogger(__name__)

# Bounded LRU — NSE/BSE universe is ~6000 symbols, so 8192 is comfortable
# headroom while preventing unbounded growth on a long-running process.
_SLUG_CACHE_MAX = 8192
_slug_cache: "OrderedDict[str, str | None]" = OrderedDict()


def _slug_cache_set(symbol: str, slug: str | None) -> None:
    if symbol in _slug_cache:
        _slug_cache.move_to_end(symbol)
    _slug_cache[symbol] = slug
    while len(_slug_cache) > _SLUG_CACHE_MAX:
        _slug_cache.popitem(last=False)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


async def _discover_slug(symbol: str) -> str | None:
    """Use Tickertape's search API to find the stock slug."""
    if symbol in _slug_cache:
        _slug_cache.move_to_end(symbol)
        return _slug_cache[symbol]

    try:
        async with httpx.AsyncClient(timeout=15, headers=API_HEADERS) as client:
            resp = await client.get(f"https://api.tickertape.in/search?text={symbol}")
            if resp.status_code != 200:
                _slug_cache_set(symbol, None)
                return None

            data = resp.json()
            stocks = data.get("data", {}).get("stocks", [])
            for s in stocks:
                ticker = s.get("ticker", "").upper()
                if ticker == symbol.upper():
                    raw_slug = s.get("slug", "")
                    # slug comes as "/stocks/hdfc-bank-HDBK" — strip the prefix
                    slug = raw_slug.lstrip("/").removeprefix("stocks/")
                    if slug:
                        _slug_cache_set(symbol, slug)
                        return slug

    except Exception as e:
        logger.warning(f"Tickertape slug discovery failed for {symbol}: {e}")

    _slug_cache_set(symbol, None)
    return None


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        if f != f or f == float("inf") or f == float("-inf"):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _deep_search(obj, keys: list[str], max_depth: int = 5) -> float | None:
    """Recursively search a nested dict/list for any of the given keys."""
    if max_depth <= 0 or obj is None:
        return None
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                val = _safe_float(obj[key])
                if val is not None:
                    return val
        for v in obj.values():
            result = _deep_search(v, keys, max_depth - 1)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj[:20]:
            result = _deep_search(item, keys, max_depth - 1)
            if result is not None:
                return result
    return None


def _extract_fundamentals(next_data: dict) -> dict:
    """Extract fundamentals from Tickertape __NEXT_DATA__ JSON."""
    result = {}

    try:
        props = next_data.get("props", {}).get("pageProps", {})

        # Field → list of possible JSON key names in Tickertape's data
        field_keys = {
            "pe_ratio": ["pe", "trailingPE", "peRatio", "ttmPe"],
            "ttm_pe": ["pe", "trailingPE", "ttmPe"],
            "forward_pe": ["forwardPE", "fwdPe"],
            "pb_ratio": ["pb", "priceToBook", "pbRatio"],
            "roe": ["roe", "returnOnEquity", "rtnOnEquity", "retOnEquity"],
            "revenue_growth_1y": ["revenueGrowth", "revGrowth", "revenue1YrGrowth", "revGr1Y"],
            "eps_growth_1y": ["epsGrowth", "earningsGrowth", "eps1YrGrowth", "epsGr1Y"],
            "net_profit_margin": ["npm", "netProfitMargin", "profitMargin", "patMargin", "netMargin"],
            "dividend_yield": ["divYield", "dividendYield", "dy"],
            "market_cap": ["mcap", "marketCap"],
        }

        pct_fields = {"roe", "revenue_growth_1y", "eps_growth_1y", "net_profit_margin", "dividend_yield"}

        for our_field, keys in field_keys.items():
            val = _deep_search(props, keys, max_depth=6)
            if val is not None:
                if our_field in pct_fields and abs(val) > 1:
                    val = val / 100
                result[our_field] = val

        # D/E from balance sheet: balTdeb / balTeq (most recent annual).
        # Sanity-clamp like fundamentals_service: distressed companies with
        # near-zero / negative equity produce bogus values that LLMs then
        # echo as misleading risk alerts.
        de = _extract_debt_to_equity(props)
        if de is not None and abs(de) <= 50:
            result["debt_to_equity"] = de

        # Promoter holding from shareholding pattern (most recent quarter)
        ph = _extract_promoter_holding(props)
        if ph is not None:
            result["promoter_holding"] = ph

        # Shareholding history (last ≤6 quarters): promoter, MF, FII, DII, retail, pledge
        history = _extract_shareholding_history(props)
        if history:
            result["shareholding_history"] = history

        # Name and sector
        name = _deep_search_str(props, ["name", "companyName", "longName"])
        if name:
            result["name"] = name
        sector = _deep_search_str(props, ["sector", "sectorName"])
        if sector:
            result["sector"] = sector

    except Exception as e:
        logger.warning(f"Failed to extract Tickertape fundamentals: {e}")

    return result


def _extract_debt_to_equity(props: dict) -> float | None:
    """Compute D/E from the most recent annual balance sheet (balTdeb / balTeq)."""
    try:
        bs = props.get("balancesheet-normal-annual", [])
        if not bs or not isinstance(bs, list):
            return None
        latest = bs[0]
        total_debt = _safe_float(latest.get("balTdeb"))
        total_equity = _safe_float(latest.get("balTeq"))
        if total_debt is None or total_equity is None or total_equity == 0:
            return None
        return round(total_debt / total_equity, 4)
    except Exception as e:
        logger.debug(f"D/E extraction failed: {e}")
        return None


def _extract_promoter_holding(props: dict) -> float | None:
    """Extract the most recent promoter holding % from shareholding data."""
    try:
        holdings_obj = props.get("securitySummary", {}).get("holdings", {})
        quarters = holdings_obj.get("holdings", [])
        if not quarters or not isinstance(quarters, list):
            return None
        latest = quarters[-1]
        data = latest.get("data", {})
        val = _safe_float(data.get("pmPctT"))
        if val is not None:
            return round(val, 2)
        return None
    except Exception as e:
        logger.debug(f"Promoter holding extraction failed: {e}")
        return None


def _extract_shareholding_history(props: dict) -> list[dict] | None:
    """Last ≤6 quarters of shareholding pattern (newest first).

    Tickertape's quarter-row keys (confirmed against the live payload
    on 2026-05-02 — keys silently shortened from the older "iiPctT"
    style to "iPctT", and pledge moved from `pmPldgPctT` to `plPctT`):

      pmPctT       promoter %
      plPctT       promoter pledge %  (was pmPldgPctT)
      uPlPctT      unpledged promoter %
      mfPctT       mutual funds %
      isPctT       insurance %
      diPctT       DII total %        (was diiPctT)
      othDiPctT    other DII %
      fiPctT       FII / FPI %        (was fiiPctT)
      rhPctT       retail holding %   (was retPctT / nrPctT)
      othPctT      other %
      date         "2026-03-31" (ISO-ish quarter end)

    The old key names are kept as fallbacks so older payloads still
    parse.
    """
    try:
        holdings_obj = props.get("securitySummary", {}).get("holdings", {})
        quarters = holdings_obj.get("holdings", [])
        if not quarters or not isinstance(quarters, list):
            return None
        # Newest first → reverse and take 6
        rows = list(reversed(quarters))[:6]
        out: list[dict] = []
        def _first_present(d: dict, *keys: str):
            """Return the first key whose value is not-None, regardless of
            falsy-ness. Plain `or` chains drop a legitimate `0` value (e.g.
            `plPctT == 0` for an unpledged stock) which would otherwise show
            up as `pledge: null` in the output."""
            for k in keys:
                if k in d and d[k] is not None:
                    return d[k]
            return None

        for row in rows:
            data = row.get("data", {}) if isinstance(row, dict) else {}
            q = row.get("date") or data.get("date") or ""
            out.append({
                "q": str(q)[:10] or None,
                "promoter": _safe_float(data.get("pmPctT")),
                "mf": _safe_float(data.get("mfPctT")),
                "fii": _safe_float(_first_present(data, "fiPctT", "fiiPctT", "fpiPctT")),
                "dii": _safe_float(_first_present(data, "diPctT", "diiPctT")),
                "retail": _safe_float(_first_present(data, "rhPctT", "retPctT", "nrPctT")),
                "pledge": _safe_float(_first_present(data, "plPctT", "pmPldgPctT")),
            })
        # Drop rows where everything is None (defensive)
        out = [r for r in out if any(v is not None for k, v in r.items() if k != "q")]
        return out or None
    except Exception as e:
        logger.debug(f"Shareholding history extraction failed: {e}")
        return None


def _deep_search_str(obj, keys: list[str], max_depth: int = 4) -> str | None:
    """Like _deep_search but for string values."""
    if max_depth <= 0 or obj is None:
        return None
    if isinstance(obj, dict):
        for key in keys:
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        for v in obj.values():
            result = _deep_search_str(v, keys, max_depth - 1)
            if result is not None:
                return result
    return None


async def fetch_from_tickertape(symbol: str) -> dict:
    """Fetch fundamentals for a stock from Tickertape."""
    slug = await _discover_slug(symbol.upper())
    if not slug:
        logger.debug(f"No Tickertape slug found for {symbol}")
        return {}

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=HEADERS) as client:
            resp = await client.get(f"https://www.tickertape.in/stocks/{slug}")

            if resp.status_code != 200:
                logger.warning(f"Tickertape returned {resp.status_code} for {slug}")
                return {}

            html = resp.text
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not match:
                logger.warning(f"No __NEXT_DATA__ found on Tickertape page for {slug}")
                return {}

            next_data = json.loads(match.group(1))
            result = _extract_fundamentals(next_data)
            if result:
                logger.info(f"Tickertape returned {len(result)} fields for {symbol}: {list(result.keys())}")
            return result

    except Exception as e:
        logger.warning(f"Tickertape fetch failed for {symbol} ({slug}): {e}")
        return {}
