"""Stock Summary Card — three-section analysis pipeline.

Section 1: Fair Price? (Valuation) — sector-specific fundamental rules
Section 2: Stacks Up? (Peer Comparison) — deterministic + LLM summary
Section 3: What's Ahead? (News + Sector) — qualitative with Search Grounding
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gemini_client import call_gemini_with_rotation
from app.models.fundamentals import StockFundamentals
from app.models.news_sentiment import NewsSentimentCache
from app.models.sector_analysis import SectorAnalysis
from app.models.stock_analysis import StockAnalysis
from app.services.fundamental_analysis import evaluate_from_preset
from app.services.fundamentals_service import get_cached_fundamentals_bulk
from app.services.peer_discovery import ensure_peers, get_effective_peers, get_stored_peers
from app.services.screener_presets import (
    INDIAN_SCREENER_PRESET,
    SECTOR_PRESETS,
    SECTOR_TO_PRESET,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PEER_SUMMARY_PROMPT = """\
Summarize this peer comparison for {symbol} vs peers {peers} in 2 sentences.
Metric comparison: {breakdown}
Focus on where the stock meaningfully leads or lags. Be specific with numbers. No hedging.\
"""

QUALITATIVE_PROMPT = """\
Today is {today_ist}. Using your access to live Google Search and Google \
Finance, perform a qualitative analysis of {company_name} (NSE: {symbol}) \
based on information from the past 30 days (i.e. from approximately one \
month before {today_ist} through {today_ist}). Return the response \
strictly as a JSON object without any markdown formatting. Use the \
following keys: 'company_overview' (a 1-sentence business summary), \
'overall_sentiment' (classify as Bullish, Bearish, or Neutral), \
'bull_case' (an array of 2 bullet points detailing current growth \
drivers or positive catalysts), \
'bear_case' (an array of 2 bullet points detailing current risks \
or headwinds), and \
'earnings_highlights' (a 2-sentence summary of management commentary \
from the most recent earnings or latest major corporate announcement).\
"""

QUALITATIVE_TOOLS = [
    {
        "googleSearchRetrieval": {
            "dynamicRetrievalConfig": {
                "mode": "MODE_DYNAMIC",
                "dynamicThreshold": 0.3,
            }
        }
    }
]

# SUMMARY_LINE_PROMPT removed (catalogue v3 — entry #12 deleted).
# Dashboard now renders the rich `decision.reasoning` paragraph from
# InvestmentDecision instead of a 15-word LLM-generated summary line.
# See PositionCard.tsx:458 — the cascade is `reasoning || summary_line ||
# headline`, and post-deletion the `summary_line` arm is always None.

# Verdict → numeric score for act_now_score computation
VERDICT_SCORES: dict[str, int] = {
    "STRONG": 80, "DISCOUNT": 80, "FAIR": 50, "WEAK": 20, "PREMIUM": 20,
    "REJECTED": 10, "NA": 50,
    "LEADS_PEERS": 80, "IN_LINE": 50, "LAGS_PEERS": 20,
    "BULLISH": 80, "NEUTRAL": 50, "BEARISH": 20,
}
WEIGHTS = {"valuation": 0.35, "peer": 0.25, "news": 0.40}

COMPARISON_METRICS = [
    "revenue_growth_1y", "roe", "net_profit_margin", "dividend_yield",
    "pe_ratio", "pb_ratio",
]
# Lower is better for valuation multiples — invert the lead/lag thresholds.
INVERTED_METRICS = {"pe_ratio", "pb_ratio"}
# Per-metric weight in the majority vote. Growth + quality + valuation each
# carry equal influence at the verdict level; within each group metrics are
# equally weighted. Total = 1.0.
METRIC_WEIGHTS = {
    # Quality (40%): operational excellence
    "roe": 0.20,
    "net_profit_margin": 0.20,
    # Growth (20%)
    "revenue_growth_1y": 0.20,
    # Valuation (40%): is this cheap relative to peers
    "pe_ratio": 0.20,
    "pb_ratio": 0.20,
    # Income (0% — informational only; payout policy varies too much
    # across industries to weight uniformly)
    "dividend_yield": 0.0,
}

METRIC_LABELS = {
    "pe_ratio": "P/E",
    "pb_ratio": "P/B",
    "roe": "ROE",
    "net_profit_margin": "Margin",
    "revenue_growth_1y": "Rev Growth",
    "debt_to_equity": "D/E",
    "dividend_yield": "Div Yield",
    "operating_cash_flow": "OCF",
    "ebitda_margin": "EBITDA Margin",
    "roce": "ROCE",
}


# ---------------------------------------------------------------------------
# Section 1: Fair Price? (Valuation)
# ---------------------------------------------------------------------------

async def evaluate_valuation(
    symbol: str, db: AsyncSession, user_id: int | None = None,
) -> dict[str, Any]:
    fund = (await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol == symbol.upper())
    )).scalar_one_or_none()

    # Resolve sector via the multi-source resolver (override → Nifty →
    # fundamentals) so the valuation preset honors user corrections and
    # Nifty index membership, not just yfinance's guess.
    from app.services.sector_resolver import resolve_sector
    resolution = await resolve_sector(symbol, db, user_id=user_id)
    sector = resolution.sector

    preset_key = SECTOR_TO_PRESET.get(sector) if sector else None
    if sector and preset_key is None:
        # Sector is set but not in the preset map — fall through to universal
        # preset, but log so we can grow SECTOR_ALIASES / SECTOR_TO_PRESET.
        logger.warning(
            "unknown_sector_for_preset",
            extra={"symbol": symbol, "sector": sector, "source": resolution.source},
        )
    preset = SECTOR_PRESETS.get(preset_key) if preset_key else None
    rules = (preset or INDIAN_SCREENER_PRESET)["rules"]

    verdict = await evaluate_from_preset(db, symbol, rules)

    section_verdict = {
        "STRONG": "DISCOUNT", "FAIR": "FAIR", "WEAK": "PREMIUM",
        "REJECTED": "PREMIUM", "NA": "FAIR",
    }.get(verdict.verdict, "FAIR")

    signals = _extract_valuation_signals(verdict.breakdown, preset)

    return {
        "verdict": section_verdict,
        "score": verdict.score,
        "signals": signals[:3],
        "hard_failed": verdict.hard_failed,
        "rule_verdict": verdict.verdict,
    }


def _extract_valuation_signals(breakdown: list, preset: dict | None) -> list[dict]:
    signals: list[dict] = []
    for r in breakdown:
        if r.status == "missing" or r.actual is None:
            continue
        label = METRIC_LABELS.get(r.metric_key, r.metric_key)
        actual = r.actual

        if r.operator == "between":
            lo = r.threshold.get("low")
            hi = r.threshold.get("high")
            if lo is not None and hi is not None:
                if r.status == "failed":
                    if actual < lo:
                        signals.append({"label": f"{label} {_fmt(actual)} below {_fmt(lo)}", "direction": "low"})
                    else:
                        signals.append({"label": f"{label} {_fmt(actual)} above {_fmt(hi)}", "direction": "high"})
                elif r.is_hard_filter and r.status == "passed":
                    mid = (lo + hi) / 2
                    if actual < mid * 0.7:
                        signals.append({"label": f"{label} {_fmt(actual)} — attractive", "direction": "low"})
        elif r.operator in ("gte", ">="):
            threshold = r.threshold.get("value")
            if threshold is not None:
                if r.status == "failed":
                    signals.append({"label": f"{label} {_fmt(actual)} below {_fmt(threshold)}", "direction": "low"})
                elif actual >= threshold * 1.5 and r.weight >= 3:
                    signals.append({"label": f"{label} {_fmt(actual)} — strong", "direction": "high"})

    signals.sort(key=lambda s: s.get("weight", 0), reverse=True)
    return signals


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) < 1:
        return f"{v * 100:.0f}%"
    if abs(v) >= 100:
        return f"{v:.0f}"
    return f"{v:.1f}"


# ---------------------------------------------------------------------------
# Section 2: Stacks Up? (Peer Comparison)
# ---------------------------------------------------------------------------

async def evaluate_peers(
    symbol: str,
    db: AsyncSession,
    user_id: int,
) -> dict[str, Any]:
    # Use the shared resolver — same logic as /api/market-data/peers/{symbol}
    # so the dashboard verdict and detail-panel peer cards always agree on
    # which peers are being compared.
    peers, peer_source = await get_effective_peers(symbol, db, target=6)
    peer_symbols = [p["symbol"] for p in peers]

    if len(peer_symbols) < 2:
        return {
            "verdict": "NO_DATA",
            "metric_breakdown": [],
            "peer_summary": None,
            "peer_count": len(peer_symbols),
            "peer_set_weak": True,
        }

    all_syms = [symbol] + peer_symbols
    fund_map = await get_cached_fundamentals_bulk(all_syms, db)

    stock_fund = fund_map.get(symbol.upper())
    metric_breakdown: list[dict] = []

    for metric in COMPARISON_METRICS:
        stock_val = _safe_float(getattr(stock_fund, metric, None)) if stock_fund else None
        peer_vals = [
            _safe_float(getattr(fund_map.get(ps.upper()), metric, None))
            for ps in peer_symbols
            if fund_map.get(ps.upper())
        ]
        peer_vals = [v for v in peer_vals if v is not None]

        if stock_val is None or not peer_vals:
            continue

        peer_med = median(peer_vals)
        if peer_med == 0:
            status = "in_line"
        else:
            ratio = stock_val / peer_med
            if metric in INVERTED_METRICS:
                # Lower is better — flip the bands so cheaper = lead.
                status = "lead" if ratio < 0.8 else "lag" if ratio > 1.2 else "in_line"
            else:
                status = "lead" if ratio > 1.2 else "lag" if ratio < 0.8 else "in_line"

        metric_breakdown.append({
            "metric": metric,
            "stock_value": round(float(stock_val), 4),
            "peer_median": round(float(peer_med), 4),
            "status": status,
        })

    verdict = _majority_verdict(metric_breakdown)
    peer_count = len(peer_symbols)

    peer_summary = None
    if metric_breakdown:
        try:
            raw = await call_gemini_with_rotation(
                user_id, db,
                PEER_SUMMARY_PROMPT.format(
                    symbol=symbol,
                    peers=", ".join(peer_symbols[:6]),
                    breakdown=json.dumps(metric_breakdown),
                ),
            )
            peer_summary = raw.strip()[:500]
        except Exception as e:
            logger.warning(f"Peer summary LLM failed for {symbol}: {e}")

    return {
        "verdict": verdict,
        "metric_breakdown": metric_breakdown,
        "peer_summary": peer_summary,
        "peer_count": peer_count,
        "peer_set_weak": peer_count < 4,
    }


def _majority_verdict(breakdown: list[dict]) -> str:
    """Weighted vote across COMPARISON_METRICS — see METRIC_WEIGHTS for the
    rationale. Valuation now contributes 40% to the verdict, growth+quality
    60%. A net-zero (leads == lags by weight) returns IN_LINE."""
    weighted_lead = 0.0
    weighted_lag = 0.0
    for m in breakdown:
        w = METRIC_WEIGHTS.get(m["metric"], 0.0)
        if m["status"] == "lead":
            weighted_lead += w
        elif m["status"] == "lag":
            weighted_lag += w
    if weighted_lead > weighted_lag + 0.05:
        return "LEADS_PEERS"
    if weighted_lag > weighted_lead + 0.05:
        return "LAGS_PEERS"
    return "IN_LINE"


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Section 3: What's Ahead? (News + Sector Outlook)
# ---------------------------------------------------------------------------

async def evaluate_news_outlook(
    symbol: str,
    company_name: str | None,
    sector: str | None,
    db: AsyncSession,
    user_id: int,
) -> dict[str, Any]:
    cached_sentiment = (await db.execute(
        select(NewsSentimentCache)
        .where(NewsSentimentCache.symbol == symbol.upper())
        .order_by(NewsSentimentCache.analyzed_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    sector_analysis = None
    if sector:
        sector_analysis = (await db.execute(
            select(SectorAnalysis).where(SectorAnalysis.sector == sector)
        )).scalar_one_or_none()

    qualitative: dict[str, Any] = {}
    try:
        raw = await call_gemini_with_rotation(
            user_id, db,
            QUALITATIVE_PROMPT.format(
                symbol=symbol,
                company_name=company_name or symbol,
                today_ist=datetime.now(tz=ZoneInfo("Asia/Kolkata")).strftime("%d %B %Y"),
            ),
            tools=QUALITATIVE_TOOLS,
        )
        qualitative = json.loads(raw)
    except Exception as e:
        logger.warning(f"Qualitative analysis failed for {symbol}: {e}")

    sentiment_str = (qualitative.get("overall_sentiment") or "").upper()
    if sentiment_str in ("BULLISH", "BEARISH", "NEUTRAL"):
        verdict = sentiment_str
    elif cached_sentiment and cached_sentiment.score is not None:
        score = cached_sentiment.score
        verdict = "BULLISH" if score >= 30 else "BEARISH" if score <= -30 else "NEUTRAL"
    else:
        verdict = "NEUTRAL"

    stock_signals = _merge_signals(qualitative, cached_sentiment)
    source_count = len(qualitative.get("bull_case", [])) + len(qualitative.get("bear_case", []))
    if cached_sentiment and cached_sentiment.result_json:
        source_count += len((cached_sentiment.result_json or {}).get("headlines", []))

    return {
        "verdict": verdict,
        "stock_signals": stock_signals[:3],
        "source_count": source_count,
        "qualitative": qualitative,
        "sector_mood": sector_analysis.mood if sector_analysis else None,
        "sector_last_run_at": (
            sector_analysis.last_run_at.isoformat()
            if sector_analysis and sector_analysis.last_run_at else None
        ),
    }


def _merge_signals(qualitative: dict, cached: NewsSentimentCache | None) -> list[dict]:
    signals: list[dict] = []
    for bc in (qualitative.get("bull_case") or [])[:1]:
        signals.append({"label": bc[:80], "direction": "bullish"})
    for bc in (qualitative.get("bear_case") or [])[:1]:
        signals.append({"label": bc[:80], "direction": "bearish"})
    if cached and cached.result_json:
        for theme in (cached.result_json.get("key_themes") or [])[:1]:
            signals.append({"label": theme[:80], "direction": "theme"})
    return signals


# ---------------------------------------------------------------------------
# Card-level: act_now_score + summary_line
# ---------------------------------------------------------------------------

def compute_act_now_score(
    val_verdict: str,
    peer_verdict: str,
    news_verdict: str,
) -> int:
    val_score = VERDICT_SCORES.get(val_verdict, 50)
    peer_score = VERDICT_SCORES.get(peer_verdict, 50)
    news_score = VERDICT_SCORES.get(news_verdict, 50)
    return round(
        WEIGHTS["valuation"] * val_score
        + WEIGHTS["peer"] * peer_score
        + WEIGHTS["news"] * news_score
    )


# generate_summary_line() removed (catalogue v3 — entry #12 deleted).
# The dashboard now prefers `decision.reasoning` over `summary_line` (see
# PositionCard.tsx:458). One Gemini call saved per refresh_stock_analysis run.


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def refresh_stock_analysis(
    symbol: str,
    db: AsyncSession,
    user_id: int,
) -> StockAnalysis | None:
    fund = (await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol == symbol.upper())
    )).scalar_one_or_none()

    company_name = fund.name if fund else None
    # Resolve sector via the multi-source resolver so the per-card news
    # section reads from the same SectorAnalysis row the today brief uses.
    from app.services.sector_resolver import resolve_sector
    resolution = await resolve_sector(symbol, db, user_id=user_id)
    sector = resolution.sector

    # Auto-seed peers when the stock has none — ensure_peers is a no-op
    # when peers already exist, and Gemini-driven discovery is a one-time
    # cost per symbol; subsequent runs reuse the stored set.
    await ensure_peers(symbol.upper(), db, user_id)

    val_result, peer_result, news_result = await asyncio.gather(
        evaluate_valuation(symbol, db, user_id=user_id),
        evaluate_peers(symbol, db, user_id),
        evaluate_news_outlook(symbol, company_name, sector, db, user_id),
    )

    act_now = compute_act_now_score(
        val_result.get("verdict", "FAIR"),
        peer_result.get("verdict", "IN_LINE"),
        news_result.get("verdict", "NEUTRAL"),
    )

    # `summary_line` is intentionally None — entry #12 in the catalogue
    # was deleted. The dashboard prefers `decision.reasoning` over this
    # field via the PositionCard.tsx:458 cascade. The DB column persists
    # for backwards compat with rows written before the deletion.
    summary: str | None = None

    now = datetime.now(timezone.utc)
    today = date.today()

    stmt = pg_insert(StockAnalysis).values(
        symbol=symbol.upper(),
        valuation_verdict=val_result.get("verdict"),
        valuation_score=val_result.get("score"),
        valuation_signals=val_result.get("signals"),
        valuation_hard_failed=val_result.get("hard_failed"),
        valuation_last_run_at=now,
        peer_verdict=peer_result.get("verdict"),
        peer_metric_breakdown=peer_result.get("metric_breakdown"),
        peer_summary=peer_result.get("peer_summary"),
        peer_count=peer_result.get("peer_count"),
        peer_set_weak=peer_result.get("peer_set_weak", False),
        peer_last_run_at=now,
        news_verdict=news_result.get("verdict"),
        news_stock_signals=news_result.get("stock_signals"),
        news_source_count=news_result.get("source_count"),
        news_qualitative=news_result.get("qualitative"),
        news_last_run_at=now,
        act_now_score=act_now,
        summary_line=summary,
        last_completed_date=today,
    ).on_conflict_do_update(
        index_elements=["symbol"],
        set_={
            "valuation_verdict": val_result.get("verdict"),
            "valuation_score": val_result.get("score"),
            "valuation_signals": val_result.get("signals"),
            "valuation_hard_failed": val_result.get("hard_failed"),
            "valuation_last_run_at": now,
            "peer_verdict": peer_result.get("verdict"),
            "peer_metric_breakdown": peer_result.get("metric_breakdown"),
            "peer_summary": peer_result.get("peer_summary"),
            "peer_count": peer_result.get("peer_count"),
            "peer_set_weak": peer_result.get("peer_set_weak", False),
            "peer_last_run_at": now,
            "news_verdict": news_result.get("verdict"),
            "news_stock_signals": news_result.get("stock_signals"),
            "news_source_count": news_result.get("source_count"),
            "news_qualitative": news_result.get("qualitative"),
            "news_last_run_at": now,
            "act_now_score": act_now,
            "summary_line": summary,
            "last_completed_date": today,
        },
    )
    await db.execute(stmt)
    await db.commit()

    row = (await db.execute(
        select(StockAnalysis).where(StockAnalysis.symbol == symbol.upper())
    )).scalar_one_or_none()

    logger.info(
        f"Stock card {symbol}: val={val_result.get('verdict')} "
        f"peer={peer_result.get('verdict')} news={news_result.get('verdict')} "
        f"score={act_now}"
    )
    return row
