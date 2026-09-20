"""Gemini AI gap-fill → metric_key adapter.

Last-resort source in the metric engine chain. Only fires when key
metrics remain null after Screener, yfinance, Kite, and NSE ownership.
Uses Google Search grounding for web-backed accuracy.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_SKIP_KEYS = {
    "ret_1d", "ret_1m", "ret_1y", "pct_from_52w_high",
    "pe_premium_vs_sector",
    "promoter_holding_change_3m", "fii_holding_change_3m",
    "mf_holding", "pledged_promoter_holding",
}

_FIELD_LABELS = {
    "pe_ratio": "Trailing P/E ratio (number, e.g. 22.5)",
    "forward_pe": "Forward P/E ratio (number, e.g. 18.5)",
    "pb_ratio": "Price to Book ratio (number, e.g. 3.2)",
    "ev_ebitda": "EV/EBITDA ratio (number, e.g. 15.0)",
    "ps_ratio": "Price to Sales ratio (number, e.g. 2.5)",
    "earning_power": "Earnings Yield (decimal, e.g. 0.05 for 5%)",
    "dividend_yield": "Dividend Yield (decimal, e.g. 0.012 for 1.2%)",
    "market_cap": "Market Capitalization in Crores (number, e.g. 1500000)",
    "roe": "Return on Equity (decimal, e.g. 0.15 for 15%)",
    "roce": "Return on Capital Employed (decimal, e.g. 0.12 for 12%)",
    "return_on_assets": "Return on Assets (decimal, e.g. 0.08 for 8%)",
    "net_profit_margin": "Net Profit Margin (decimal, e.g. 0.10 for 10%)",
    "ebitda_margin": "EBITDA/Operating Profit Margin (decimal, e.g. 0.20 for 20%)",
    "debt_to_equity": "Debt to Equity ratio (number, e.g. 0.5)",
    "current_ratio": "Current Ratio (number, e.g. 1.5)",
    "quick_ratio": "Quick Ratio (number, e.g. 1.1)",
    "interest_coverage": "Interest Coverage Ratio (number, e.g. 8.5)",
    "revenue_growth_1y": "Revenue Growth 1 Year (decimal, e.g. 0.12 for 12%)",
    "eps_growth_1y": "EPS Growth 1 Year (decimal, e.g. 0.10 for 10%)",
    "earnings_growth_forward": "Forward Earnings Growth (decimal, e.g. 0.15 for 15%)",
    "eps_growth_5y": "EPS 5-Year CAGR (decimal, e.g. 0.12 for 12%)",
    "operating_cash_flow": "Operating Cash Flow in Crores (number, e.g. 50000)",
    "free_cash_flow": "Free Cash Flow in Crores (number, e.g. 30000)",
    "cash_flow_margin": "Cash Flow Margin (decimal, e.g. 0.15 for 15%)",
    "promoter_holding": "Promoter Holding percentage (number, e.g. 50.3)",
    "fii_holding": "FII Holding percentage (number, e.g. 22.5)",
    "dii_holding": "DII Holding percentage (number, e.g. 16.1)",
}


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


async def fetch(
    symbol: str,
    exchange: str,
    user_id: int | None,
    db: AsyncSession,
    existing_values: dict[str, Any],
) -> dict[str, float | None]:
    if user_id is None:
        return {}

    null_keys = [
        k for k in _FIELD_LABELS
        if k not in existing_values and k not in _SKIP_KEYS
    ]
    if not null_keys:
        return {}

    needed = {k: _FIELD_LABELS[k] for k in null_keys}

    from app.ai.gemini_client import call_gemini_with_rotation

    prompt = (
        f"For the Indian stock {symbol} listed on NSE, provide these financial metrics.\n"
        f"Return a JSON object with these exact keys. Use null for any value you are not confident about.\n"
        f"All percentage values should be decimals (e.g., 15% = 0.15).\n\n"
        f"Needed: {json.dumps(needed)}\n\n"
        f"COST FAIL-SAFE: If you cannot confidently find at least 3 of the\n"
        f"requested values from authoritative Indian financial sources (NSE\n"
        f"filings, BSE announcements, company annual reports, Screener.in,\n"
        f"MoneyControl), return an empty JSON object {{}} with no explanation.\n"
        f"Do NOT fabricate values you are uncertain about.\n\n"
        f"Start your response with \"{{\" and end with \"}}\". No markdown fences."
    )

    try:
        raw = await call_gemini_with_rotation(
            user_id, db, prompt,
            tools=[{"googleSearch": {}}],
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(cleaned)
        result: dict[str, float | None] = {}
        for key in null_keys:
            if key in data and data[key] is not None:
                val = _safe_float(data[key])
                if val is not None:
                    result[key] = val
        if result:
            logger.info("Gemini filled %d metrics for %s: %s", len(result), symbol, list(result.keys()))
        return result
    except Exception as e:
        logger.warning("Gemini metric fetch failed for %s: %s", symbol, e)
        return {}
