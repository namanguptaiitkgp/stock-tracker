import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gemini_client import call_gemini_with_rotation
from app.models.fundamentals import StockFundamentals
from app.models.strategy import Strategy
from app.services.fundamentals_service import get_fundamentals_bulk


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _fmt_num(v: float) -> str:
    return f"{v:.2f}"


def _fmt_cap(v: float) -> str:
    if v >= 100000:
        return f"Rs {v / 100000:.1f} L Cr"
    if v >= 1000:
        return f"Rs {v / 1000:.1f} K Cr"
    return f"Rs {v:.0f} Cr"


def _check_filters(f: StockFundamentals, filters: dict) -> tuple[bool, list[dict]]:
    """Returns (passed, list of reason dicts).
    Each reason dict has: metric, actual, threshold, comparison, text.
    """
    reasons: list[dict] = []
    passed = True

    def val(attr):
        v = getattr(f, attr, None)
        return float(v) if v is not None else None

    mc = val("market_cap")
    mc_cr = mc / 10_000_000 if mc else None

    # Derived values
    near_52w_high = None
    if val("cmp") and val("high_52w") and float(f.high_52w) > 0:
        near_52w_high = float(f.cmp) / float(f.high_52w)

    # (filter_key, value, label, direction: "max" or "min", formatter, target_formatter)
    checks = [
        ("pe_ratio_max", val("pe_ratio"), "P/E Ratio", "max", _fmt_num, _fmt_num),
        ("pb_ratio_max", val("pb_ratio"), "P/B Ratio", "max", _fmt_num, _fmt_num),
        ("forward_pe_max", val("forward_pe"), "Forward P/E", "max", _fmt_num, _fmt_num),
        ("ttm_pe_max", val("ttm_pe"), "TTM P/E", "max", _fmt_num, _fmt_num),
        ("debt_to_equity_max", val("debt_to_equity"), "Debt/Equity", "max", _fmt_num, _fmt_num),
        ("net_profit_margin_min", val("net_profit_margin"), "Net Profit Margin", "min", _fmt_pct, _fmt_pct),
        ("roe_min", val("roe"), "Return on Equity", "min", _fmt_pct, _fmt_pct),
        ("revenue_growth_1y_min", val("revenue_growth_1y"), "Revenue Growth 1Y", "min", _fmt_pct, _fmt_pct),
        ("eps_growth_1y_min", val("eps_growth_1y"), "EPS Growth 1Y", "min", _fmt_pct, _fmt_pct),
        ("earnings_growth_forward_min", val("earnings_growth_forward"), "Forward Earnings Growth", "min", _fmt_pct, _fmt_pct),
        ("dividend_yield_min", val("dividend_yield"), "Dividend Yield", "min", _fmt_pct, _fmt_pct),
        ("promoter_holding_min", val("promoter_holding"), "Promoter Holding", "min", _fmt_pct, _fmt_pct),
        ("near_52w_high_pct", near_52w_high, "Near 52W High", "min", _fmt_pct, _fmt_pct),
        ("market_cap_min_cr", mc_cr, "Market Cap", "min", _fmt_cap, _fmt_cap),
        ("market_cap_max_cr", mc_cr, "Market Cap", "max", _fmt_cap, _fmt_cap),
    ]

    for filter_key, value, label, direction, fmt, fmt_target in checks:
        if filter_key not in filters:
            continue
        target = filters[filter_key]

        if value is None:
            reasons.append({
                "metric": label,
                "actual": None,
                "threshold": target,
                "comparison": direction,
                "text": f"{label}: data not available",
                "failed": True,
                "missing": True,
            })
            passed = False
            continue

        if direction == "max" and value > target:
            reasons.append({
                "metric": label,
                "actual": value,
                "threshold": target,
                "comparison": "max",
                "text": f"{label} is {fmt(value)} — exceeds max threshold of {fmt_target(target)}",
                "failed": True,
                "missing": False,
            })
            passed = False
        elif direction == "min" and value < target:
            reasons.append({
                "metric": label,
                "actual": value,
                "threshold": target,
                "comparison": "min",
                "text": f"{label} is {fmt(value)} — below min threshold of {fmt_target(target)}",
                "failed": True,
                "missing": False,
            })
            passed = False
        else:
            # Passed this check — still record it for transparency
            reasons.append({
                "metric": label,
                "actual": value,
                "threshold": target,
                "comparison": direction,
                "text": f"{label} is {fmt(value)} — meets {direction} threshold of {fmt_target(target)}",
                "failed": False,
                "missing": False,
            })

    return passed, reasons


def _compute_score(f: StockFundamentals, weights: dict, filters: dict) -> float:
    score = 0.0
    total_weight = 0.0

    if "pe" in weights and f.pe_ratio is not None:
        target = filters.get("pe_ratio_max", 20)
        pe = float(f.pe_ratio)
        if pe > 0:
            component = min(1.0, target / pe)
            score += component * weights["pe"]
            total_weight += weights["pe"]

    if "pb" in weights and f.pb_ratio is not None:
        target = filters.get("pb_ratio_max", 3)
        pb = float(f.pb_ratio)
        if pb > 0:
            component = min(1.0, target / pb)
            score += component * weights["pb"]
            total_weight += weights["pb"]

    if "roe" in weights and f.roe is not None:
        target = filters.get("roe_min", 0.15)
        component = min(1.0, float(f.roe) / max(target, 0.01))
        score += component * weights["roe"]
        total_weight += weights["roe"]

    if "margin" in weights and f.net_profit_margin is not None:
        target = filters.get("net_profit_margin_min", 0.10)
        component = min(1.0, float(f.net_profit_margin) / max(target, 0.01))
        score += component * weights["margin"]
        total_weight += weights["margin"]

    if "debt" in weights and f.debt_to_equity is not None:
        target = filters.get("debt_to_equity_max", 1.0)
        de = float(f.debt_to_equity)
        component = 1.0 if de <= target else max(0.0, 1.0 - (de - target) / target)
        score += component * weights["debt"]
        total_weight += weights["debt"]

    if ("revenue_growth" in weights or "growth" in weights) and f.revenue_growth_1y is not None:
        w = weights.get("revenue_growth", weights.get("growth", 0) / 2)
        target = filters.get("revenue_growth_1y_min", 0.10)
        component = min(1.0, max(0.0, float(f.revenue_growth_1y)) / max(target, 0.01))
        score += component * w
        total_weight += w

    if ("eps_growth" in weights or "growth" in weights) and f.eps_growth_1y is not None:
        w = weights.get("eps_growth", weights.get("growth", 0) / 2)
        target = filters.get("eps_growth_1y_min", 0.10)
        component = min(1.0, max(0.0, float(f.eps_growth_1y)) / max(target, 0.01))
        score += component * w
        total_weight += w

    if "dividend_yield" in weights and f.dividend_yield is not None:
        w = weights["dividend_yield"]
        target = filters.get("dividend_yield_min", 0.02)
        component = min(1.0, float(f.dividend_yield) / max(target, 0.001))
        score += component * w
        total_weight += w

    if "forward_pe" in weights and f.forward_pe is not None:
        target = filters.get("forward_pe_max", 25)
        fpe = float(f.forward_pe)
        if fpe > 0:
            component = min(1.0, target / fpe)
            score += component * weights["forward_pe"]
            total_weight += weights["forward_pe"]

    if "promoter_holding" in weights and f.promoter_holding is not None:
        target = filters.get("promoter_holding_min", 0.50)
        component = min(1.0, float(f.promoter_holding) / max(target, 0.01))
        score += component * weights["promoter_holding"]
        total_weight += weights["promoter_holding"]

    if "near_52w_high" in weights and f.cmp is not None and f.high_52w is not None:
        h52 = float(f.high_52w)
        if h52 > 0:
            pct = float(f.cmp) / h52
            target = filters.get("near_52w_high_pct", 0.85)
            component = min(1.0, pct / max(target, 0.01))
            score += component * weights["near_52w_high"]
            total_weight += weights["near_52w_high"]

    if total_weight > 0:
        return round(score / total_weight * 100, 1)
    return 0.0


def _build_prompt(strategy: Strategy, results: list[dict]) -> str:
    cfg = strategy.config_json
    rules = cfg.get("signal_rules", "")
    filters = cfg.get("filters", {})

    summary_lines = []
    for r in results:
        summary_lines.append(
            f"- {r['symbol']}: score={r['score']}, pass={r['passed']}, "
            f"CMP={r.get('cmp', '?')}, PE={r.get('pe', '?')}, "
            f"PB={r.get('pb', '?')}, D/E={r.get('de', '?')}, "
            f"RevGr={r.get('rev_gr', '?')}, EPSGr={r.get('eps_gr', '?')}"
        )

    return f"""You are evaluating stocks against the "{strategy.name}" strategy.

Strategy type: {strategy.strategy_type}
Description: {strategy.description}
Filters: {json.dumps(filters)}
Signal rules: {rules}

## Candidate stocks (pre-filtered with scores):
{chr(10).join(summary_lines)}

For each stock, give:
- signal: STRONG_BUY, BUY, HOLD, or AVOID
- reasoning: 1-2 sentences explaining why this stock fits (or doesn't fit) the strategy

Return ONLY a JSON object:
{{
  "top_picks": ["SYMBOL1", "SYMBOL2", "SYMBOL3"],
  "strategy_fit_summary": "overall verdict on how well this target set suits the strategy",
  "stocks": [
    {{"symbol": "SYM", "signal": "BUY", "reasoning": "..."}}
  ]
}}"""


async def run_strategy_on_symbols(
    strategy: Strategy,
    symbols: list[str],
    db: AsyncSession,
    user_id: int,
    target_label: str,
) -> dict:
    if not symbols:
        return {"error": "No symbols to evaluate"}

    cfg = strategy.config_json
    filters = cfg.get("filters", {})
    weights = cfg.get("weights", {})

    fundamentals_map = await get_fundamentals_bulk(symbols, db, user_id=user_id)

    rows = []
    for symbol in symbols:
        f = fundamentals_map.get(symbol.upper())
        if not f:
            rows.append({
                "symbol": symbol, "passed": False, "score": 0,
                "reasons": [{
                    "metric": "Fundamentals",
                    "text": "Fundamentals data not available for this stock",
                    "failed": True,
                    "missing": True,
                }],
                "failure_reasons": ["No fundamentals data available"],
                "missing_data": True,
            })
            continue

        passed, reasons = _check_filters(f, filters)
        score = _compute_score(f, weights, filters)

        # Structured reasons kept as full list (pass + fail); simple list for legacy / UI
        failure_reasons = [r["text"] for r in reasons if r.get("failed")]

        rows.append({
            "symbol": symbol,
            "name": f.name,
            "passed": passed,
            "score": score,
            "reasons": reasons,  # full structured list (all checks)
            "failure_reasons": failure_reasons,  # simple strings for UI
            "cmp": float(f.cmp) if f.cmp else None,
            "market_cap": float(f.market_cap) if f.market_cap else None,
            "pe": float(f.pe_ratio) if f.pe_ratio else None,
            "pb": float(f.pb_ratio) if f.pb_ratio else None,
            "de": float(f.debt_to_equity) if f.debt_to_equity else None,
            "rev_gr": float(f.revenue_growth_1y) if f.revenue_growth_1y else None,
            "eps_gr": float(f.eps_growth_1y) if f.eps_growth_1y else None,
            "margin": float(f.net_profit_margin) if f.net_profit_margin else None,
            "roe": float(f.roe) if f.roe else None,
        })

    rows.sort(key=lambda r: (-int(r["passed"]), -r["score"]))

    ai_insight = None
    passing = [r for r in rows if r["passed"]]
    if passing:
        try:
            prompt = _build_prompt(strategy, passing[:15])
            raw = await call_gemini_with_rotation(user_id, db, prompt)
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            ai_insight = json.loads(cleaned)
        except Exception as e:
            ai_insight = {"error": f"AI analysis failed: {str(e)[:200]}"}

    return {
        "strategy_id": strategy.id,
        "strategy_name": strategy.name,
        "target_label": target_label,
        "total_evaluated": len(rows),
        "passed_count": sum(1 for r in rows if r["passed"]),
        "stocks": rows,
        "ai_insight": ai_insight,
    }
