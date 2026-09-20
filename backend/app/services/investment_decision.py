import asyncio
import json
import logging
from datetime import datetime, timedelta

from kiteconnect import KiteConnect
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompt_helpers import (
    DECIMAL_OUTPUT_RULE,
    INDIAN_MACRO_CONTEXT,
    STRICT_JSON_BOUNDARY,
)
from app.ai.provider import AIProviderConfigError
from app.ai.registry import get_ai_provider
from app.api.analysis import _fetch_history, _technicals, NIFTY_50_TOKEN
from app.models.fundamentals import StockFundamentals
from app.models.news_sentiment import NewsSentimentCache
from app.models.smart_money import SmartMoneySignal
from app.models.stock import Stock
from app.models.strategy import Strategy
from app.models.user import User
from app.services.default_strategies import DEFAULT_STRATEGIES
from app.services.fundamentals_service import get_fundamentals
from app.services.strategy_runner import _check_filters, _compute_score

logger = logging.getLogger(__name__)


INVESTMENT_DECISION_PROMPT = """You are a world-class equity research analyst specializing in the Indian stock market (NSE/BSE).

A user is asking: "Should I invest in {symbol}?"

Your job is to synthesize fundamental data, technical data, and rule-based strategy evaluations into a clear, actionable verdict.

## Fundamental Analysis (rule-based)
{strategy_breakdown}

## Fundamentals Data
{fundamentals_data}

## Peer Comparison
{peer_comparison_context}

## Technical Data
{technicals_data}

## Market Context
{market_context}

## Smart-Money Snapshot
{smart_money_context}

## News Sentiment
{news_sentiment_context}

## Instructions
- [TRACEABILITY] Every claim in `reasoning`, `valuation_view`, and `technical_view` MUST be grounded in the data blocks above — cite the specific number (e.g., "PE 74× vs peer median 28×", "LTP ₹245 below 200DMA ₹272"). Vague phrasing without a concrete number is not acceptable.
- When citing valuation as cheap, fair, or stretched, ground it in the Peer Comparison block — cite peer median and the stock's spread to it.
- [MISSING-DATA DEGRADATION] If more than 50% of fundamental fields are "--" (missing) in the Fundamentals Data block, your verdict MUST be `WAIT`, `reasoning` MUST start with "Insufficient data:", and `confidence` MUST be ≤ 30.
- Incorporate the smart-money snapshot and news sentiment as overlays. Call out divergence between data blocks in `reasoning`.
- {macro_context}
- ENTRY ZONE ANCHORING (CRITICAL):
  - Always populate `entry_calculation_scratchpad` FIRST with a concrete anchor sentence (e.g., "Next major support at ₹450 (50-DMA) → entry zone ₹445-455" OR "Fair value PE 22× → ₹620 → entry zone ₹590-625"). Required for INVEST, WAIT, AND AVOID.
  - Then derive `entry_recommendation` numbers consistently with that scratchpad anchor. Never zero. Use LTP, support/resistance, or fair-value-PE — whichever you cited.

Return a JSON object with this exact structure. The field ORDER matters — emit them in the order shown:
{{
  "verdict": "INVEST" | "WAIT" | "AVOID",
  "confidence": 0-100,
  "strategies_diverge": <true if your verdict contradicts the majority of passed fundamental rules above, else false>,
  "reasoning": "3-4 sentences explaining the verdict, grounded in cited numbers",
  "strategy_consensus": {{
    "summary": "How the rule-based fundamental analysis views this stock",
    "best_fit_strategy": "Name of best-fit rule set if applicable (or null)",
    "worst_fit_strategy": "Name of worst-fit rule set if applicable (or null)"
  }},
  "valuation_view": "1-2 sentences on valuation, citing PE/PB/peer median",
  "technical_view": "1-2 sentences on technicals, citing 50DMA/200DMA/RS",
  "market_sentiment": {{
    "nifty_trend": "Bullish/Bearish/Neutral with context",
    "sector_outlook": "Sector-specific outlook",
    "sentiment_summary": "1-2 sentences overall market sentiment"
  }},
  "entry_calculation_scratchpad": "MANDATORY one-sentence anchor used to derive entry zone — e.g., 'Next major support at ₹450 (50-DMA) → entry zone ₹445-455' OR 'Fair value PE 22× → ₹620 → entry zone ₹590-625'. Required for INVEST, WAIT, AND AVOID — never skip.",
  "entry_recommendation": {{
    "entry_price_low": <float — must be consistent with scratchpad, NEVER zero>,
    "entry_price_high": <float — NEVER zero>,
    "stop_loss": <float — NEVER zero>,
    "target_price": <float — NEVER zero>,
    "time_horizon": "e.g. 6-12 months"
  }},
  "key_risks": ["risk1", "risk2", "risk3"],
  "action_items": ["action1", "action2", "action3"]
}}

{decimal_rule}

{json_boundary}"""


def _safe_num(v) -> float | None:
    """Coerce numeric-ish JSON values (None / "0" / 0 / 12.5) to float
    without raising on garbage strings. Returns None when the value
    cannot be parsed."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v, pct: bool = False, decimals: int = 1) -> str:
    if v is None:
        return "--"
    if pct:
        return f"{v:+.{decimals}f}%"
    return f"{v:.{decimals}f}"


def _format_strategy_breakdown(strategies: list[Strategy], fund: StockFundamentals | None) -> tuple[str, int, int]:
    """Run each strategy's filters/scoring against the stock and format results.
    Returns (formatted_text, strategies_passed, strategies_total).
    """
    if not fund:
        return "No fundamentals data available — strategy evaluation skipped.", 0, 0

    lines = []
    passed_count = 0
    total = len(strategies)

    for s in strategies:
        cfg = s.config_json or {}
        filters = cfg.get("filters", {})
        weights = cfg.get("weights", {})

        passed, reasons = _check_filters(fund, filters)
        score = _compute_score(fund, weights, filters)

        if passed:
            passed_count += 1

        status = "PASSED" if passed else "FAILED"
        header = f"- {s.name} ({s.strategy_type}): {status}, Score: {score}/100"

        # Format individual filter checks
        filter_parts = []
        for r in reasons:
            actual_str = _fmt(r["actual"]) if r["actual"] is not None else "N/A"
            threshold_str = _fmt(r["threshold"]) if r.get("threshold") is not None else "?"
            direction = r.get("comparison", "")
            tag = "PASS" if not r.get("failed") else "FAIL"
            filter_parts.append(f"{r['metric']} {actual_str} {'<=' if direction == 'max' else '>='} {threshold_str} {direction} [{tag}]")

        filter_line = " | ".join(filter_parts) if filter_parts else "No filters configured"
        lines.append(f"{header}\n  {filter_line}")

    return "\n".join(lines), passed_count, total


def _format_fundamentals(
    fund: StockFundamentals | None,
    snapshot_values: dict | None = None,
) -> str:
    if not fund:
        return "Fundamentals data unavailable"

    cmp = float(fund.cmp) if fund.cmp is not None else None
    pe = float(fund.pe_ratio) if fund.pe_ratio is not None else None
    pb = float(fund.pb_ratio) if fund.pb_ratio is not None else None
    roe = float(fund.roe) * 100 if fund.roe is not None else None
    margin = float(fund.net_profit_margin) * 100 if fund.net_profit_margin is not None else None
    de = float(fund.debt_to_equity) if fund.debt_to_equity is not None else None
    rev_gr = float(fund.revenue_growth_1y) * 100 if fund.revenue_growth_1y is not None else None
    eps_gr = float(fund.eps_growth_1y) * 100 if fund.eps_growth_1y is not None else None
    div_yield = float(fund.dividend_yield) * 100 if fund.dividend_yield is not None else None
    sector = fund.sector

    lines = [
        f"CMP={_fmt(cmp)}, PE={_fmt(pe)}, PB={_fmt(pb)}, "
        f"ROE={_fmt(roe, pct=True)}, NetMargin={_fmt(margin, pct=True)}, "
        f"D/E={_fmt(de)}, RevGr={_fmt(rev_gr, pct=True)}, "
        f"EPSGr={_fmt(eps_gr, pct=True)}, DivYield={_fmt(div_yield, pct=True)}, "
        f"Sector={sector or '--'}"
    ]

    sv = snapshot_values or {}

    # Extended metrics from metric snapshot
    extended_parts = []
    if sv.get("forward_pe") is not None:
        extended_parts.append(f"FwdPE={_fmt(sv['forward_pe'])}")
    if sv.get("ev_ebitda") is not None:
        extended_parts.append(f"EV/EBITDA={_fmt(sv['ev_ebitda'])}")
    if sv.get("roce") is not None:
        extended_parts.append(f"ROCE={_fmt(sv['roce'] * 100, pct=True)}")
    if sv.get("current_ratio") is not None:
        extended_parts.append(f"CurrentRatio={_fmt(sv['current_ratio'])}")
    if sv.get("ebitda_margin") is not None:
        extended_parts.append(f"EBITDAMargin={_fmt(sv['ebitda_margin'] * 100, pct=True)}")
    if sv.get("operating_cash_flow") is not None:
        extended_parts.append(f"OCF={_fmt(sv['operating_cash_flow'])}Cr")
    if sv.get("cash_flow_margin") is not None:
        extended_parts.append(f"CFMargin={_fmt(sv['cash_flow_margin'] * 100, pct=True)}")
    if extended_parts:
        lines.append(", ".join(extended_parts))

    # Ownership from NSE XBRL
    own_parts = []
    if sv.get("promoter_holding") is not None:
        own_parts.append(f"Promoter={_fmt(sv['promoter_holding'])}%")
    if sv.get("fii_holding") is not None:
        own_parts.append(f"FII={_fmt(sv['fii_holding'])}%")
    if sv.get("dii_holding") is not None:
        own_parts.append(f"DII={_fmt(sv['dii_holding'])}%")
    if sv.get("mf_holding") is not None:
        own_parts.append(f"MF={_fmt(sv['mf_holding'])}%")
    if sv.get("pledged_promoter_holding") is not None:
        own_parts.append(f"Pledge={_fmt(sv['pledged_promoter_holding'])}%")
    if sv.get("promoter_holding_change_3m") is not None:
        own_parts.append(f"PromoterΔ3M={_fmt(sv['promoter_holding_change_3m'], pct=True)}")
    if sv.get("fii_holding_change_3m") is not None:
        own_parts.append(f"FIIΔ3M={_fmt(sv['fii_holding_change_3m'], pct=True)}")
    if own_parts:
        lines.append("Ownership: " + ", ".join(own_parts))

    return "\n".join(lines)


def _format_technicals(stock_tech: dict, nifty_tech: dict) -> str:
    if not stock_tech:
        return "Technical data unavailable"

    nifty_30d = nifty_tech.get("ret_30d")
    rs_30d = None
    if stock_tech.get("ret_30d") is not None and nifty_30d is not None:
        rs_30d = stock_tech["ret_30d"] - nifty_30d

    return (
        f"50DMA={_fmt(stock_tech.get('dma50'))}, "
        f"200DMA={_fmt(stock_tech.get('dma200'))}, "
        f"52WH={_fmt(stock_tech.get('high_52w'))}, "
        f"52WL={_fmt(stock_tech.get('low_52w'))}, "
        f"FromHigh={_fmt(stock_tech.get('pct_from_52wh'), pct=True)}, "
        f"30dRet={_fmt(stock_tech.get('ret_30d'), pct=True)}, "
        f"90dRet={_fmt(stock_tech.get('ret_90d'), pct=True)}, "
        f"RS30d={_fmt(rs_30d, pct=True)} (vs Nifty)"
    )


async def _load_news_sentiment(db: AsyncSession, symbol: str) -> NewsSentimentCache | None:
    result = await db.execute(
        select(NewsSentimentCache)
        .where(NewsSentimentCache.symbol == symbol)
        .order_by(desc(NewsSentimentCache.analyzed_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _format_news_sentiment(record: NewsSentimentCache | None) -> str:
    if not record:
        return "News sentiment unavailable (no recent analysis cached for this symbol)"

    payload = record.result_json or {}
    parts: list[str] = []

    sentiment = record.sentiment or payload.get("sentiment") or "neutral"
    score = record.score if record.score is not None else payload.get("score")
    analyzed_at = record.analyzed_at.isoformat() if record.analyzed_at else "unknown time"

    if score is not None:
        parts.append(f"Sentiment: {sentiment} (score {score:+d}/100, analyzed at {analyzed_at})")
    else:
        parts.append(f"Sentiment: {sentiment} (analyzed at {analyzed_at})")

    summary = payload.get("summary")
    if summary:
        parts.append(f"Summary: {summary}")

    themes = payload.get("key_themes") or []
    if themes:
        parts.append("Key themes: " + ", ".join(str(t) for t in themes[:5]))

    headlines = payload.get("headlines") or []
    if headlines:
        head_lines = []
        for h in headlines[:5]:
            title = h.get("title", "").strip()
            if not title:
                continue
            tags = []
            h_sent = h.get("sentiment")
            if h_sent:
                tags.append(h_sent)
            impact = h.get("impact")
            if impact:
                tags.append(f"{impact} impact")
            date = h.get("date")
            if date:
                tags.append(date)
            tag_str = f" [{', '.join(tags)}]" if tags else ""
            head_lines.append(f"- {title}{tag_str}")
        if head_lines:
            parts.append("Recent headlines:\n" + "\n".join(head_lines))

    return "\n".join(parts)


async def _load_smart_money(db: AsyncSession, symbol: str) -> SmartMoneySignal | None:
    result = await db.execute(
        select(SmartMoneySignal)
        .where(SmartMoneySignal.symbol == symbol)
        .order_by(desc(SmartMoneySignal.as_of))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _score_label(score: float | None) -> str:
    """Map a -100..+100 score to the bucket labels from spec §9."""
    if score is None:
        return "n/a"
    if score >= 60:
        return "Strong Buy Signal"
    if score >= 30:
        return "Moderate Buy Signal"
    if score >= -29:
        return "Neutral"
    if score >= -59:
        return "Moderate Sell Signal"
    return "Strong Sell Signal"


def _format_smart_money(sig: SmartMoneySignal | None) -> str:
    """Provider-agnostic smart-money block appended to the deep-analysis
    prompt. See spec §9 — no provider-specific formatting (no tool use,
    no provider-specific JSON modes); the prompt is plain Markdown text.

    Subsections that have no source data are omitted entirely so the
    LLM doesn't get null artifacts. Labels for each score follow the
    bucket ranges (Strong Buy / Moderate / Neutral / etc.).
    """
    if not sig:
        return "Smart-money data unavailable"

    breakdown = sig.signal_breakdown or {}
    conv = breakdown.get("conviction") or {}
    flow = breakdown.get("flow") or {}
    rf = breakdown.get("red_flags") or {}
    sharks = sig.named_sharks or []

    conviction_score = float(sig.conviction_score) if sig.conviction_score is not None else None
    flow_score = float(sig.flow_score) if sig.flow_score is not None else None
    red_flag_score = float(sig.red_flag_score) if sig.red_flag_score is not None else None
    composite = float(sig.composite) if sig.composite is not None else None

    parts: list[str] = [f"## Smart-Money Snapshot (as of {sig.as_of})"]

    # ---- Conviction ----
    conv_lines: list[str] = []
    pb = conv.get("promoter_buying") or {}
    if pb.get("raw") is not None:
        conv_lines.append(
            f"- Promoter open-market buying: {int(pb['raw']):,} shares (signal {pb.get('normalized', 0):+.0f}/100)."
        )
    sa = conv.get("shark_accumulation") or {}
    if sa.get("raw") is not None:
        conv_lines.append(
            f"- Tracked-investor accumulation: tier-weighted net {int(sa['raw']):,} "
            f"shares across {sa.get('source_rows', 0)} parties (signal {sa.get('normalized', 0):+.0f}/100)."
        )
    mc = conv.get("mf_consensus") or {}
    if mc.get("raw") is not None:
        conv_lines.append(
            f"- Mutual fund consensus: {mc.get('increased', 0)} houses increased, "
            f"{mc.get('decreased', 0)} decreased over the last 3 months "
            f"(signal {mc.get('normalized', 0):+.0f}/100)."
        )
    sd = conv.get("shareholding_delta") or {}
    if sd.get("raw") is not None:
        conv_lines.append(
            f"- Shareholding pattern Δ: promoter holding moved {sd['raw']:+.2f}% "
            f"in {sd.get('quarter', '?')} (signal {sd.get('normalized', 0):+.0f}/100)."
        )
    if sharks:
        sample = ", ".join(
            f"{s.get('name')} {s.get('side')} {int(s.get('quantity', 0)):,}@{s.get('date')}"
            for s in sharks[:3]
        )
        conv_lines.append(f"- Recent named-shark deals: {sample}.")
    if conv_lines:
        parts.append(
            f"### Conviction (score: {conviction_score:+.0f}/100)" if conviction_score is not None
            else "### Conviction (score: n/a)"
        )
        parts.extend(conv_lines)

    # ---- Flow ----
    flow_lines: list[str] = []
    dlv = flow.get("delivery") or {}
    if dlv.get("recent_avg") is not None and dlv.get("baseline_avg") is not None:
        flow_lines.append(
            f"- Delivery: 5d avg {dlv['recent_avg']:.1f}% vs 90d baseline "
            f"{dlv['baseline_avg']:.1f}% (z-score {dlv.get('z_score', 0):+.2f}, "
            f"signal {dlv.get('normalized', 0):+.0f}/100)."
        )
    fd = flow.get("fii_dii_stock") or {}
    if fd.get("fii_net_cr") is not None or fd.get("dii_net_cr") is not None:
        flow_lines.append(
            f"- Stock-level FII/DII (5d net): FII {fd.get('fii_net_cr', 0):+.1f} Cr, "
            f"DII {fd.get('dii_net_cr', 0):+.1f} Cr (signal {fd.get('normalized', 0):+.0f}/100)."
        )
    bb = flow.get("block_bulk_net") or {}
    if bb.get("raw") is not None:
        flow_lines.append(
            f"- Institutional block/bulk net: {int(bb['raw']):,} shares across "
            f"{bb.get('party_count', 0)} parties (signal {bb.get('normalized', 0):+.0f}/100)."
        )
    by = flow.get("buyback_active") or {}
    if by.get("raw"):
        flow_lines.append(f"- Active buyback announced in last 90 days (boost {by.get('normalized', 0):+.0f}).")
    if flow_lines:
        parts.append(
            f"### Flow (score: {flow_score:+.0f}/100)" if flow_score is not None
            else "### Flow (score: n/a)"
        )
        parts.extend(flow_lines)

    # ---- Red Flags ----
    triggered = rf.get("triggered") or []
    if triggered:
        parts.append(f"### Red Flags (penalty: {red_flag_score:+.0f})")
        detail = rf.get("detail") or {}
        for flag in triggered:
            d = detail.get(flag) or {}
            if flag == "circular_trading":
                susp = ", ".join(d.get("suspects", [])[:3])
                parts.append(f"- Circular trading suspected: {susp}.")
            elif flag == "pump_pattern":
                parts.append(
                    f"- Pump pattern: price up {d.get('pct_change_20d', 0):+.1f}% in 20 days "
                    f"with delivery % declining (speculative volume)."
                )
            elif flag == "promoter_selling":
                parts.append(f"- Promoter selling: net {int(d.get('shares_sold', 0)):,} shares in 90 days.")
            elif flag == "high_pledge":
                parts.append(
                    f"- High promoter pledge: {d.get('pledge_pct', 0):.1f}% pledged "
                    f"({d.get('quarter', '?')}); penalty {d.get('penalty', 0):+.0f}."
                )
            elif flag == "pledge_invocation":
                parts.append(f"- Pledge invocation: {d.get('events', 0)} event(s) in last 90 days.")
            else:
                parts.append(f"- {flag}: penalty {d.get('penalty', 0):+.0f}.")
    else:
        parts.append("### Red Flags\n- None identified.")

    # ---- Summary ----
    summary_lines = [
        "### Signal Summary",
        f"Conviction: {_score_label(conviction_score)} ({conviction_score:+.0f})"
        if conviction_score is not None else "Conviction: n/a",
        f"Flow: {_score_label(flow_score)} ({flow_score:+.0f})"
        if flow_score is not None else "Flow: n/a",
        f"Red flags: {red_flag_score:+.0f}" if red_flag_score is not None else "Red flags: 0",
        f"Composite: {composite:+.0f}" if composite is not None else "Composite: n/a",
    ]
    parts.append("\n".join(summary_lines))

    return "\n".join(parts)


async def _format_peer_comparison(
    db: AsyncSession,
    symbol: str,
    fund: StockFundamentals | None,
) -> str:
    """Build a peer-comparison Markdown block for the deep-analysis prompt.

    Uses the shared `get_effective_peers` resolver (stored Gemini peers →
    industry → sector fallback) so this surface stays aligned with the
    dashboard three-section card and `/api/market-data/peers/{symbol}`.

    Robust to all the edge cases:
    - Per-metric None filtering — one missing PE doesn't drop the peer.
    - Empty-after-filter metrics are omitted (no "median None" lines).
    - Subject `fund=None` → print medians only, no lead/lag verdict.
    - Outliers (negative PE, etc.) handled naturally by median.
    - Whole-helper exception envelope — peer lookup failure must NOT
      crash the deep analysis.
    """
    try:
        from statistics import median
        from app.services.peer_discovery import get_effective_peers

        peers, source = await get_effective_peers(symbol, db, target=6)
        if not peers:
            return "Peer comparison: no comparable peers found in the same industry or sector."

        peer_symbols = [p["symbol"] for p in peers if p["symbol"].upper() != symbol.upper()]
        if not peer_symbols:
            return "Peer comparison: no comparable peers found."

        # One batched fundamentals query (not N).
        fund_q = await db.execute(
            select(StockFundamentals).where(StockFundamentals.symbol.in_(peer_symbols))
        )
        peer_funds = {f.symbol: f for f in fund_q.scalars().all()}

        metrics = [
            ("pe_ratio", "PE", "×", False, True),         # invert=True (lower better)
            ("pb_ratio", "PB", "×", False, True),
            ("roe", "ROE", "%", True, False),
            ("revenue_growth_1y", "Rev growth", "%", True, False),
            ("net_profit_margin", "Net margin", "%", True, False),
        ]

        def _val(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def _fmt_metric(v: float | None, suffix: str, pct: bool) -> str:
            if v is None:
                return "--"
            if pct:
                return f"{v * 100:.1f}{suffix}"
            return f"{v:.1f}{suffix}"

        def _classify(stock_v: float | None, peer_med: float, invert: bool) -> str:
            """invert=True means lower is better (PE/PB)."""
            if stock_v is None or peer_med == 0:
                return ""
            ratio = stock_v / peer_med
            if invert:
                if ratio < 0.8:
                    return "cheaper than peers"
                if ratio > 1.2:
                    return "stretched vs peers"
                return "in line with peers"
            else:
                if ratio > 1.2:
                    return "leads peers"
                if ratio < 0.8:
                    return "lags peers"
                return "in line with peers"

        industry_label = fund.industry if fund and fund.industry else (fund.sector if fund and fund.sector else "comparable companies")
        header_peers = ", ".join(peer_symbols[:5])
        if len(peer_symbols) > 5:
            header_peers += f" +{len(peer_symbols) - 5}"
        lines = [f"Peer comparison (vs {len(peer_symbols)} peers in {industry_label}: {header_peers}):"]

        any_metric_rendered = False
        for field, label, suffix, pct, invert in metrics:
            peer_vals = [_val(getattr(peer_funds.get(ps), field, None)) for ps in peer_symbols if peer_funds.get(ps)]
            peer_vals = [v for v in peer_vals if v is not None]
            if not peer_vals:
                continue  # this metric has no peer data; omit the line
            peer_med = median(peer_vals)
            stock_v = _val(getattr(fund, field, None)) if fund else None
            stock_str = _fmt_metric(stock_v, suffix, pct)
            peer_str = _fmt_metric(peer_med, suffix, pct)
            verdict = _classify(stock_v, peer_med, invert)
            verdict_str = f" — {verdict}" if verdict else ""
            lines.append(f"- {label}: {stock_str} vs peer median {peer_str}{verdict_str}")
            any_metric_rendered = True

        if not any_metric_rendered:
            return "Peer comparison: peer fundamentals unavailable for valuation metrics."

        lines.append(f"(Peer set source: {source}.)")
        return "\n".join(lines)
    except Exception as e:  # pragma: no cover — best-effort, must never crash deep analysis
        import logging
        logging.getLogger(__name__).warning(
            "peer_comparison_context build failed for %s: %s",
            symbol, e,
        )
        return "Peer comparison: temporarily unavailable."


def _format_market_context(nifty_tech: dict) -> str:
    if not nifty_tech:
        return "Nifty 50 data unavailable"

    return (
        f"Nifty 50 -- 30d: {_fmt(nifty_tech.get('ret_30d'), pct=True)}, "
        f"90d: {_fmt(nifty_tech.get('ret_90d'), pct=True)}, "
        f"LTP: {_fmt(nifty_tech.get('latest'))}, "
        f"50DMA: {_fmt(nifty_tech.get('dma50'))}, "
        f"200DMA: {_fmt(nifty_tech.get('dma200'))}"
    )


async def _ensure_strategies(user: User, db: AsyncSession) -> list[Strategy]:
    """Load user + default strategies. Seed defaults if none exist."""
    result = await db.execute(
        select(Strategy).where(
            or_(
                Strategy.user_id.is_(None) & Strategy.is_default.is_(True),
                Strategy.user_id == user.id,
            )
        )
    )
    strategies = list(result.scalars().all())

    if not strategies:
        for s_data in DEFAULT_STRATEGIES:
            s = Strategy(
                user_id=None,
                name=s_data["name"],
                description=s_data["description"],
                strategy_type=s_data["strategy_type"],
                config_json=s_data["config_json"],
                is_default=True,
                is_active=True,
            )
            db.add(s)
        await db.commit()

        result = await db.execute(
            select(Strategy).where(Strategy.is_default.is_(True))
        )
        strategies = list(result.scalars().all())

    return [s for s in strategies if s.is_active]


async def evaluate_stock_for_investment(
    symbol: str,
    exchange: str,
    user: User,
    db: AsyncSession,
) -> dict:
    symbol = symbol.upper().strip()

    # Step 1: Load strategies
    strategies = await _ensure_strategies(user, db)

    # Step 2: Check if Kite is connected
    kite_connected = bool(user.kite_api_key and user.kite_access_token)
    kite = None
    instrument_token = None

    if kite_connected:
        kite = KiteConnect(api_key=user.kite_api_key)
        kite.set_access_token(user.kite_access_token)

        # Look up instrument_token from stocks table
        stock_result = await db.execute(
            select(Stock).where(
                Stock.tradingsymbol == symbol,
                Stock.exchange == exchange,
            )
        )
        stock_row = stock_result.scalar_one_or_none()
        if stock_row:
            instrument_token = stock_row.instrument_token

    # Step 3: Parallel fetch — fundamentals, stock history, nifty history
    async def fetch_fund():
        try:
            return await get_fundamentals(symbol, db, exchange=exchange, user_id=user.id)
        except Exception as e:
            logger.warning(f"Fundamentals fetch failed for {symbol}: {e}")
            return None

    async def fetch_stock_history():
        if kite and instrument_token:
            return await _fetch_history(kite, instrument_token)
        return []

    async def fetch_nifty_history():
        if kite:
            return await _fetch_history(kite, NIFTY_50_TOKEN)
        return []

    fund, stock_candles, nifty_candles = await asyncio.gather(
        fetch_fund(),
        fetch_stock_history(),
        fetch_nifty_history(),
    )

    # Step 4: Compute technicals
    stock_tech = _technicals(stock_candles) if stock_candles else {}
    nifty_tech = _technicals(nifty_candles) if nifty_candles else {}

    # Step 5: Rule-based Fundamental Analysis (replaces the legacy
    # per-strategy block). The user's default rule set is the single
    # source of truth for "does this stock meet my fundamental
    # criteria?" — strategies are now a preset library only and don't
    # affect the verdict prompt.
    from app.services.fundamental_analysis import evaluate_for_user as _fa_eval
    fa_verdict = await _fa_eval(db, user.id, symbol)
    if fa_verdict.rules_total == 0:
        strategy_breakdown_text = (
            "No Fundamental Analysis rules configured yet — the user can set them in "
            "Settings → Fundamental Analysis Rules."
        )
    else:
        passes = [b for b in fa_verdict.breakdown if b.status == "passed"][:5]
        fails = [b for b in fa_verdict.breakdown if b.status == "failed"][:5]

        def _fmt_b(b) -> str:
            t = b.threshold or {}
            thresh = t.get("value")
            if thresh is None and (t.get("low") is not None or t.get("high") is not None):
                thresh = f"[{t.get('low')}..{t.get('high')}]"
            return f"{b.metric_key} {b.operator} {thresh} (actual: {b.actual})"

        strategy_breakdown_text = (
            f"### Fundamental Analysis (rule-based, user's default rule set)\n"
            f"Verdict: {fa_verdict.verdict}  ·  Score: "
            f"{fa_verdict.score if fa_verdict.score is not None else 'n/a'}/100\n"
            f"Passed: {fa_verdict.rules_passed}/{fa_verdict.rules_passed + fa_verdict.rules_failed}  "
            f"·  Failed: {fa_verdict.rules_failed}  ·  Missing: {fa_verdict.rules_missing}\n"
            + (("Top passes:\n  " + "\n  ".join(_fmt_b(b) for b in passes) + "\n") if passes else "")
            + (("Top fails:\n  " + "\n  ".join(_fmt_b(b) for b in fails) + "\n") if fails else "")
        )

    # Strategy table is retired from the analysis flow but the response
    # shape stays stable for one transitional release — empty arrays.
    strategy_details: list[dict] = []
    strategies_passed = 0
    strategies_total = 0

    # Step 6: Format prompt sections
    fundamentals_data = _format_fundamentals(fund, snapshot_values=fa_verdict.snapshot_values)
    technicals_data = _format_technicals(stock_tech, nifty_tech) if kite_connected else "Technical data unavailable (Kite not connected)"
    market_context = _format_market_context(nifty_tech) if kite_connected else "Market context unavailable (Kite not connected)"
    smart_money_sig = await _load_smart_money(db, symbol)
    smart_money_context = _format_smart_money(smart_money_sig)
    news_record = await _load_news_sentiment(db, symbol)
    news_sentiment_context = _format_news_sentiment(news_record)
    peer_comparison_context = await _format_peer_comparison(db, symbol, fund)

    # Step 7: Build AI prompt — `{strategy_breakdown}` placeholder now
    # carries the Fundamental Analysis text instead of per-strategy
    # results. The prompt template is unchanged so existing tests pass.
    prompt = INVESTMENT_DECISION_PROMPT.format(
        symbol=symbol,
        strategy_breakdown=strategy_breakdown_text,
        fundamentals_data=fundamentals_data,
        peer_comparison_context=peer_comparison_context,
        technicals_data=technicals_data,
        market_context=market_context,
        smart_money_context=smart_money_context,
        news_sentiment_context=news_sentiment_context,
        macro_context=INDIAN_MACRO_CONTEXT,
        decimal_rule=DECIMAL_OUTPUT_RULE,
        json_boundary=STRICT_JSON_BOUNDARY,
    )

    # Step 8: Call the configured deep-analysis provider via the registry.
    # The registry reads `analysis_model` (with legacy `gemini_model`
    # fallback) and instantiates the right provider class.
    model = None

    try:
        provider = await get_ai_provider(user, db, purpose="analysis")
    except AIProviderConfigError:
        provider = None

    if provider is None:
        # Return partial result without AI verdict
        return {
            "symbol": symbol,
            "exchange": exchange,
            "verdict": None,
            "confidence": None,
            "model_used": None,
            "strategies_passed": strategies_passed,
            "strategies_total": strategies_total,
            "strategy_breakdown": [
                {"strategy_name": sd["name"], "strategy_type": sd["type"], "description": sd.get("description"), "signal_rules": sd.get("signal_rules"), "passed": sd["passed"], "score": sd["score"], "reasons": sd.get("reasons", [])}
                for sd in strategy_details
            ],
            "strategies_summary": {"total": strategies_total, "passed": strategies_passed},
            "fundamentals": fundamentals_data,
            "technicals": technicals_data if kite_connected else None,
            "market_context": market_context if kite_connected else None,
            "smart_money_context": smart_money_context,
            "smart_money_composite": float(smart_money_sig.composite) if smart_money_sig and smart_money_sig.composite is not None else None,
            "news_sentiment_context": news_sentiment_context,
            "news_sentiment": news_record.sentiment if news_record else None,
            "news_score": news_record.score if news_record else None,
            "error": "No AI credentials configured. Add one in Settings → Connections → AI Infra.",
        }

    ai_result = None
    try:
        ai_response = await provider.analyze(prompt, model=model)
        cleaned = ai_response.content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        ai_result = json.loads(cleaned)
        model = ai_response.model  # provider may have swapped to its default
    except Exception as e:
        logger.error(f"AI provider call failed for investment decision on {symbol}: {e}")
        # Return partial result with strategy breakdown but no AI verdict
        return {
            "symbol": symbol,
            "exchange": exchange,
            "verdict": None,
            "confidence": None,
            "model_used": model,
            "strategies_passed": strategies_passed,
            "strategies_total": strategies_total,
            "strategy_breakdown": [
                {"strategy_name": sd["name"], "strategy_type": sd["type"], "description": sd.get("description"), "signal_rules": sd.get("signal_rules"), "passed": sd["passed"], "score": sd["score"], "reasons": sd.get("reasons", [])}
                for sd in strategy_details
            ],
            "strategies_summary": {"total": strategies_total, "passed": strategies_passed},
            "fundamentals": fundamentals_data,
            "technicals": technicals_data if kite_connected else None,
            "market_context": market_context if kite_connected else None,
            "smart_money_context": smart_money_context,
            "smart_money_composite": float(smart_money_sig.composite) if smart_money_sig and smart_money_sig.composite is not None else None,
            "news_sentiment_context": news_sentiment_context,
            "news_sentiment": news_record.sentiment if news_record else None,
            "news_score": news_record.score if news_record else None,
            "error": f"AI analysis failed: {str(e)[:300]}",
        }

    # Step 8.5: Validator — patch zero entry_recommendation values
    # deterministically from LTP. Defensive layer behind D1's CoT
    # scratchpad: when the prompt's structural anchoring fails (~few %),
    # rather than save ₹0 to the DB, derive from LTP × {0.90, 0.95, 0.85,
    # 1.15} and tag the LlmCall row for monitoring. See plan §D2.
    er = ai_result.get("entry_recommendation") or {}
    low = _safe_num(er.get("entry_price_low"))
    high = _safe_num(er.get("entry_price_high"))
    if (low == 0 or low is None) and (high == 0 or high is None):
        ltp = _safe_num(fund.cmp if fund else None)
        if ltp:
            ai_result["entry_recommendation"] = {
                "entry_price_low":  round(ltp * 0.90, 2),
                "entry_price_high": round(ltp * 0.95, 2),
                "stop_loss":        round(ltp * 0.85, 2),
                "target_price":     round(ltp * 1.15, 2),
                "time_horizon":     er.get("time_horizon") or "6-12 months",
            }
            logger.warning(
                "investment_decision validator patched zero entry for %s "
                "(ltp=%s) — D1 scratchpad fell through", symbol, ltp,
            )
        else:
            logger.warning(
                "investment_decision validator could not patch zero entry "
                "for %s — no LTP available", symbol,
            )

    # Step 9: Build final result — flatten AI fields to top level for frontend
    verdict = ai_result.get("verdict")
    confidence = ai_result.get("confidence")

    # Remap strategy_details to match frontend expectations
    strategy_breakdown = [
        {
            "strategy_name": sd["name"],
            "strategy_type": sd["type"],
            "description": sd.get("description"),
            "signal_rules": sd.get("signal_rules"),
            "passed": sd["passed"],
            "score": sd["score"],
            "reasons": sd.get("reasons", []),
        }
        for sd in strategy_details
    ]

    return {
        "symbol": symbol,
        "exchange": exchange,
        "verdict": verdict,
        "confidence": confidence,
        "reasoning": ai_result.get("reasoning", ""),
        "model_used": model,
        "strategies_passed": strategies_passed,
        "strategies_total": strategies_total,
        "strategies_summary": {"total": strategies_total, "passed": strategies_passed},
        "strategy_breakdown": strategy_breakdown,
        "strategy_consensus": ai_result.get("strategy_consensus"),
        "strategies_diverge": bool(ai_result.get("strategies_diverge")),
        "valuation_view": ai_result.get("valuation_view"),
        "technical_view": ai_result.get("technical_view"),
        "market_sentiment": ai_result.get("market_sentiment"),
        "entry_calculation_scratchpad": ai_result.get("entry_calculation_scratchpad"),
        "entry_recommendation": ai_result.get("entry_recommendation"),
        "key_risks": ai_result.get("key_risks", []),
        "action_items": ai_result.get("action_items", []),
        "fundamentals": fundamentals_data,
        "technicals": technicals_data if kite_connected else None,
        "market_context": market_context if kite_connected else None,
        "smart_money_context": smart_money_context,
        "smart_money_composite": float(smart_money_sig.composite) if smart_money_sig and smart_money_sig.composite is not None else None,
        "news_sentiment_context": news_sentiment_context,
        "news_sentiment": news_record.sentiment if news_record else None,
        "news_score": news_record.score if news_record else None,
        "ai_analysis": ai_result,
    }
