"""Google Finance scrape → metric_key adapter.

Lightweight source that provides price-related metrics (52-week range,
P/E, EPS, market cap) from the public Google Finance page. Useful as
a cross-validation layer and gap-filler for metrics that Screener/yfinance
miss. No API key required.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f or f == float("inf") or f == float("-inf"):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _parse_market_cap(raw: str | None) -> float | None:
    """Convert Google Finance market cap string to crores (INR).

    GF formats: '18.39T' (trillions), '322.78B' (billions), '53.33M' (millions).
    1 Cr = 1e7, so: T * 1e5 Cr, B * 100 Cr, M * 0.1 Cr.
    """
    if not raw:
        return None
    raw = raw.strip().replace(",", "").replace("₹", "").replace("$", "")
    multiplier = 1.0
    if raw.endswith("T"):
        raw = raw[:-1]
        multiplier = 1e5
    elif raw.endswith("B"):
        raw = raw[:-1]
        multiplier = 100
    elif raw.endswith("M"):
        raw = raw[:-1]
        multiplier = 0.1
    else:
        return _safe_float(raw)

    val = _safe_float(raw)
    if val is None:
        return None
    return round(val * multiplier, 2)


async def fetch(symbol: str, exchange: str = "NSE") -> dict[str, float | None]:
    from app.services.google_finance import lookup

    data = await lookup(symbol, default_exchange=exchange)
    if "error" in data:
        return {}

    out: dict[str, float | None] = {}

    if data.get("high_52w") is not None:
        out["high_52w"] = _safe_float(data["high_52w"])
    if data.get("low_52w") is not None:
        out["low_52w"] = _safe_float(data["low_52w"])
    if data.get("eps") is not None:
        out["eps"] = _safe_float(data["eps"])

    pe = data.get("pe_ratio")
    if pe is not None:
        out["pe_ratio"] = _safe_float(pe)

    dy = data.get("dividend_yield")
    if dy is not None:
        val = _safe_float(dy)
        if val is not None:
            out["dividend_yield"] = round(val / 100, 6) if val > 1 else val

    last_price = _safe_float(data.get("last_price"))
    if last_price is not None:
        out["last_price"] = last_price

        high_52w = out.get("high_52w") or _safe_float(data.get("high_52w"))
        if high_52w and high_52w > 0:
            out["pct_from_52w_high"] = round((last_price - high_52w) / high_52w, 6)

    if data.get("market_cap") is not None:
        mc = _parse_market_cap(data["market_cap"])
        if mc is not None:
            out["market_cap"] = mc

    filled = [k for k in out if out[k] is not None]
    if filled:
        logger.info("GF filled %d metrics for %s: %s", len(filled), symbol, filled)

    return out
