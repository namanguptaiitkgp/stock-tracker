"""Screener.in → metric_key adapter.

Calls the shared screener_fetcher and returns {metric_key: value_num}
for the metric engine. Keys already match metric_definitions; values
are in canonical units (ratios as decimals, monetary in Cr).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def fetch(symbol: str, exchange: str = "NSE") -> dict[str, float | None]:
    from app.services.screener_fetcher import fetch_fundamentals

    raw = await fetch_fundamentals(symbol)
    if not raw:
        return {}

    out: dict[str, Any] = {}
    direct_keys = [
        "market_cap", "pe_ratio", "roce", "roe", "dividend_yield",
        "debt_to_equity", "revenue_growth_1y", "eps_growth_1y",
        "net_profit_margin", "ebitda_margin", "eps_growth_5y",
        "operating_cash_flow", "free_cash_flow", "cash_flow_margin",
        "return_on_assets",
        "promoter_holding", "fii_holding", "dii_holding",
        "promoter_holding_change_3m", "fii_holding_change_3m",
    ]
    for k in direct_keys:
        v = raw.get(k)
        if v is not None:
            out[k] = v

    return out
