"""yfinance → metric_key adapter.

Wraps the existing `_fetch_from_yfinance` in `fundamentals_service.py`.
Returns `{metric_key: value_num}`. Values are normalized (D/E divided by
100, percentages kept as fractions to match metric_definitions units).
"""

from __future__ import annotations

import asyncio
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


def _yf_ticker(symbol: str, exchange: str) -> str:
    suffix = ".NS" if exchange == "NSE" else ".BO"
    return f"{symbol}{suffix}"


def _scrape_sync(symbol: str, exchange: str) -> dict[str, float | None]:
    try:
        import yfinance as yf  # local — only on cold path
    except Exception:
        return {}
    try:
        ticker = yf.Ticker(_yf_ticker(symbol, exchange))
        info = ticker.info or {}
    except Exception as e:
        logger.info("yfinance metric fetch failed for %s: %s", symbol, e)
        return {}
    if not info:
        return {}

    de_raw = _safe_float(info.get("debtToEquity"))
    de = None if de_raw is None else (None if abs(de_raw / 100) > 50 else de_raw / 100)

    market_cap_inr = _safe_float(info.get("marketCap"))
    market_cap_cr = market_cap_inr / 1e7 if market_cap_inr is not None else None

    # Cash-flow metrics from screener spec.
    ocf_inr = _safe_float(info.get("operatingCashflow"))
    ocf_cr = ocf_inr / 1e7 if ocf_inr is not None else None
    fcf_inr = _safe_float(info.get("freeCashflow"))
    fcf_cr = fcf_inr / 1e7 if fcf_inr is not None else None
    revenue_inr = _safe_float(info.get("totalRevenue"))
    cf_margin = (
        ocf_inr / revenue_inr if (ocf_inr is not None and revenue_inr and revenue_inr > 0) else None
    )

    # Earnings yield = 1/PE × 100. Skip when PE is missing or non-positive.
    pe = _safe_float(info.get("trailingPE"))
    earning_power = (1.0 / pe * 100.0) if (pe is not None and pe > 0) else None

    # Today's % move. NSE uses ±5/10/20% circuits — values past those
    # bounds are circuit-hit signals the screener filter looks for.
    ret_1d = _safe_float(info.get("regularMarketChangePercent"))
    if ret_1d is None:
        # Fallback derivation when yfinance withholds the change %
        prev_close = _safe_float(info.get("regularMarketPreviousClose") or info.get("previousClose"))
        cur = _safe_float(info.get("regularMarketPrice") or info.get("currentPrice"))
        if prev_close and prev_close > 0 and cur is not None:
            ret_1d = (cur - prev_close) / prev_close * 100.0

    # Interest coverage = EBIT / interest expense. yfinance.info doesn't
    # expose either directly on most tickers, but `ebitda` minus
    # depreciation is a workable proxy for EBIT, and `interestExpense`
    # is sometimes present. Skip silently when either component is missing.
    ebit = _safe_float(info.get("ebit"))
    if ebit is None:
        ebitda = _safe_float(info.get("ebitda"))
        # No depreciation field in info; leave EBIT as None to avoid a bad approx
        del ebitda
    interest_expense = _safe_float(info.get("interestExpense"))
    interest_coverage = (
        ebit / abs(interest_expense)
        if (ebit is not None and interest_expense and interest_expense != 0)
        else None
    )

    return {
        "pe_ratio": pe,
        "forward_pe": _safe_float(info.get("forwardPE")),
        "pb_ratio": _safe_float(info.get("priceToBook")),
        "ps_ratio": _safe_float(info.get("priceToSalesTrailing12Months")),
        "revenue_growth_1y": _safe_float(info.get("revenueGrowth")),
        "eps_growth_1y": _safe_float(info.get("earningsGrowth")),
        "earnings_growth_forward": _safe_float(info.get("earningsQuarterlyGrowth")),
        "net_profit_margin": _safe_float(info.get("profitMargins")),
        "ebitda_margin": _safe_float(info.get("ebitdaMargins")),
        "debt_to_equity": de,
        "dividend_yield": _safe_float(info.get("dividendYield")),
        "roe": _safe_float(info.get("returnOnEquity")),
        "return_on_assets": _safe_float(info.get("returnOnAssets")),
        "market_cap": market_cap_cr,
        # New screener metrics
        "operating_cash_flow": ocf_cr,
        "free_cash_flow": fcf_cr,
        "cash_flow_margin": cf_margin,
        "earning_power": earning_power,
        "ret_1d": ret_1d,
        "interest_coverage": interest_coverage,
    }


def _scrape_financials_sync(symbol: str, exchange: str) -> dict[str, float | None]:
    """Extract metrics from yfinance DataFrames (balance_sheet, income_stmt, cashflow).

    These fill gaps that ticker.info doesn't cover: current_ratio, quick_ratio,
    roce, ev_ebitda, eps_growth_5y."""
    try:
        import yfinance as yf
    except Exception:
        return {}
    try:
        ticker = yf.Ticker(_yf_ticker(symbol, exchange))
        bs = ticker.balance_sheet
        is_ = ticker.income_stmt
        cf = ticker.cashflow
        info = ticker.info or {}
    except Exception as e:
        logger.info("yfinance financials fetch failed for %s: %s", symbol, e)
        return {}

    out: dict[str, float | None] = {}

    # Current Ratio and Quick Ratio from balance sheet
    if bs is not None and not bs.empty:
        ca = _df_val(bs, "Current Assets", "Total Current Assets")
        cl = _df_val(bs, "Current Liabilities", "Total Current Liabilities")
        inv = _df_val(bs, "Inventory") or 0
        if ca and cl and cl != 0:
            out["current_ratio"] = ca / cl
            out["quick_ratio"] = (ca - inv) / cl

    # ROCE = EBIT / Capital Employed (Total Assets - Current Liabilities)
    if is_ is not None and not is_.empty:
        ebit = _df_val(is_, "EBIT", "Operating Income")
        if ebit and bs is not None and not bs.empty:
            ta = _df_val(bs, "Total Assets")
            cl = _df_val(bs, "Current Liabilities", "Total Current Liabilities")
            if ta and cl:
                capital_employed = ta - cl
                if capital_employed > 0:
                    out["roce"] = ebit / capital_employed

    # EV/EBITDA from enterprise value (info) + EBITDA (income_stmt or info)
    ev = _safe_float(info.get("enterpriseValue"))
    ebitda_val = _df_val(is_, "EBITDA") if (is_ is not None and not is_.empty) else None
    if ebitda_val is None:
        ebitda_val = _safe_float(info.get("ebitda"))
    if ev and ebitda_val and ebitda_val > 0:
        out["ev_ebitda"] = ev / ebitda_val

    # Free Cash Flow from cashflow (OCF - CapEx)
    if cf is not None and not cf.empty:
        ocf = _df_val(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
        capex = _df_val(cf, "Capital Expenditure")
        if ocf is not None and capex is not None:
            out["free_cash_flow"] = (ocf + capex) / 1e7  # capex is typically negative

    # Interest Coverage from income_stmt (EBIT / Interest Expense)
    if is_ is not None and not is_.empty:
        ebit = _df_val(is_, "EBIT", "Operating Income")
        int_exp = _df_val(is_, "Interest Expense", "Interest Expense Non Operating")
        if ebit is not None and int_exp is not None and int_exp != 0:
            out["interest_coverage"] = ebit / abs(int_exp)

    # EPS 5Y CAGR from multi-year income statement
    if is_ is not None and not is_.empty:
        for eps_label in ("Basic EPS", "Diluted EPS"):
            if eps_label in is_.index:
                eps_series = is_.loc[eps_label].dropna()
                if len(eps_series) >= 4:
                    eps_new = _safe_float(eps_series.iloc[0])
                    eps_old = _safe_float(eps_series.iloc[-1])
                    n = len(eps_series) - 1
                    if eps_new and eps_old and eps_old > 0 and eps_new > 0:
                        out["eps_growth_5y"] = (eps_new / eps_old) ** (1 / n) - 1
                break

    return out


def _df_val(df: Any, *row_names: str) -> float | None:
    """Get the most recent value from a yfinance DataFrame, trying multiple row names."""
    for name in row_names:
        if name in df.index:
            val = df.loc[name].iloc[0]
            return _safe_float(val)
    return None


async def fetch(symbol: str, exchange: str = "NSE") -> dict[str, float | None]:
    def _combined(symbol: str, exchange: str) -> dict[str, float | None]:
        info_vals = _scrape_sync(symbol, exchange)
        df_vals = _scrape_financials_sync(symbol, exchange)
        # info values take priority; DataFrame values fill gaps
        for k, v in df_vals.items():
            if v is not None and k not in info_vals:
                info_vals[k] = v
        return info_vals

    return await asyncio.to_thread(_combined, symbol, exchange)
