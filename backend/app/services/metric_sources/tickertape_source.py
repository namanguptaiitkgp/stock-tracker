"""Tickertape → metric_key adapter.

Reuses the existing scraper in `services/tickertape_fetcher.py` which
already extracts the headline ratios + shareholding history. Maps the
tickertape field names to canonical metric keys and exposes ownership
deltas computed from `shareholding_history`.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.tickertape_fetcher import fetch_from_tickertape as _fetch_tt

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


async def fetch(symbol: str, exchange: str = "NSE") -> dict[str, float | None]:
    # Disabled — Tickertape search API returns 403 for all symbols.
    # Replaced by yfinance DataFrames + NSE XBRL ownership.
    return {}
