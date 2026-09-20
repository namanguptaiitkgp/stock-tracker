"""NSE Option Chain scraper for Put/Call ratio (PCR).

NSE rate-limits aggressively and requires a session cookie warm-up. We:
1. Visit the NSE homepage to seed cookies.
2. Hit the option-chain-equities API with a JSON Accept header.
3. Cache the result in-process for OPTIONS_CACHE_SECONDS.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.services.data_cache import cache_get_or_fetch

logger = logging.getLogger(__name__)

# 30 min — options data changes intraday; under the global 2h "recent" rule,
# but freshen more often since OI moves visibly.
OPTIONS_CACHE_SECONDS = 30 * 60
NSE_BASE = "https://www.nseindia.com"
NSE_OPTION_CHAIN_API = f"{NSE_BASE}/api/option-chain-equities"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{NSE_BASE}/option-chain",
}

async def _fetch_pcr_raw(symbol: str) -> Optional[dict]:
    """The actual NSE call. Cached separately via data_cache."""
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=10.0, follow_redirects=True) as client:
            # Warm up cookies by hitting the option-chain landing page
            await client.get(f"{NSE_BASE}/option-chain")
            resp = await client.get(NSE_OPTION_CHAIN_API, params={"symbol": symbol})
            if resp.status_code != 200:
                logger.warning(f"NSE option chain returned {resp.status_code} for {symbol}")
                return None
            data = resp.json()
    except Exception as e:
        logger.warning(f"NSE option chain fetch failed for {symbol}: {e}")
        return None

    records = data.get("records", {})
    rows = records.get("data", [])
    if not rows:
        return None

    underlying = records.get("underlyingValue")
    nearest_expiry = records.get("expiryDates", [None])[0]

    total_call_oi = 0
    total_put_oi = 0
    strike_oi: dict[float, dict] = {}
    for r in rows:
        # Only include nearest-expiry rows for a focused PCR
        if nearest_expiry and r.get("expiryDate") != nearest_expiry:
            continue
        ce = r.get("CE") or {}
        pe = r.get("PE") or {}
        strike = r.get("strikePrice")
        co = ce.get("openInterest") or 0
        po = pe.get("openInterest") or 0
        total_call_oi += co
        total_put_oi += po
        if strike is not None:
            strike_oi[strike] = {"call": co, "put": po}

    if total_call_oi == 0:
        return None

    pcr = round(total_put_oi / total_call_oi, 2)

    # Max pain: strike where total OI loss to writers is minimum
    max_pain = None
    if strike_oi:
        min_loss = None
        for test_strike in strike_oi.keys():
            loss = 0.0
            for k, oi in strike_oi.items():
                if k > test_strike:
                    loss += (k - test_strike) * oi["put"]
                elif k < test_strike:
                    loss += (test_strike - k) * oi["call"]
            if min_loss is None or loss < min_loss:
                min_loss = loss
                max_pain = test_strike

    payload = {
        "symbol": symbol,
        "pcr": pcr,
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "max_pain": max_pain,
        "underlying_value": underlying,
        "expiry": nearest_expiry,
    }
    return payload


async def fetch_option_chain_pcr(symbol: str, force: bool = False) -> Optional[dict]:
    """Return {pcr, total_call_oi, total_put_oi, max_pain, underlying_value} or None.
    DB-cached 30 min via unified data_cache.
    """
    sym = symbol.upper().strip()
    key = f"options:pcr:{sym}"
    payload, _fetched_at = await cache_get_or_fetch(
        key,
        fetch_fn=lambda: _fetch_pcr_raw(sym),
        ttl_seconds=OPTIONS_CACHE_SECONDS,
        force=force,
    )
    return payload
