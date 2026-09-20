import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.fundamentals import StockFundamentals
from app.models.investment_decision import InvestmentDecision

from app.models.news_sentiment import NewsSentimentCache
from app.models.sector_analysis import SectorAnalysis
from app.models.smart_money import SmartMoneySignal, TodayBriefCache
from app.models.stock_analysis import StockAnalysis
from app.models.user import User
from app.models.user_stock_review import UserStockReview
from app.services.portfolio_cache import get_holdings as cached_holdings
from app.services.sector_resolver import resolve_sectors_bulk

logger = logging.getLogger(__name__)
router = APIRouter()


# --- Decision matrix (spec §10) --------------------------------------------


@dataclass
class ActionResult:
    """Output of `decide_action_v2`. Frontend surfaces:
        - action            for the badge label
        - confidence_tag    for the chip ("HIGH CONVICTION" / etc.)
        - binding_signal    for the tooltip ("conviction" / "red_flag" / "ai")
        - explanation       for the card subtitle
        - red_flag_detail   set only when binding_signal == "red_flag"
    """

    action: str
    confidence_tag: str
    binding_signal: str
    explanation: str
    red_flag_detail: str | None = None


# Map current verdicts to the spec's BUY/HOLD/SELL/WATCH vocabulary.
# `WAIT` is the legacy "stay out for now" verdict — semantically closer
# to HOLD than to WATCH, which the spec reserves for "interesting but
# not actionable yet." The existing decide-action path also routes
# WAIT → WATCHFUL via the HOLD branch.
_VERDICT_TO_AI: dict[str | None, str] = {
    "INVEST": "BUY",
    "AVOID": "SELL",
    "WAIT": "HOLD",
    "BUY": "BUY",
    "SELL": "SELL",
    "HOLD": "HOLD",
    "WATCH": "WATCH",
    None: "HOLD",
}


def _top_breakdown_signal(signal_breakdown: dict | None) -> str | None:
    """Pull the single most-contributing signal name out of the breakdown
    JSON for tooltip display. Picks the abs-max normalized contribution
    across conviction + flow."""
    if not signal_breakdown:
        return None
    best_name: str | None = None
    best_mag = 0.0
    for cat in ("conviction", "flow"):
        sub = signal_breakdown.get(cat) or {}
        for key, item in sub.items():
            if not isinstance(item, dict):
                continue
            n = item.get("normalized")
            if n is None:
                continue
            try:
                mag = abs(float(n))
            except (TypeError, ValueError):
                continue
            if mag > best_mag:
                best_mag = mag
                best_name = f"{cat}.{key}"
    return best_name


def decide_action_v2(
    *,
    ai_decision: str | None,
    ai_confidence: int | None,
    news_sentiment: str | None,
    conviction_score: float | None,
    flow_score: float | None,
    red_flag_score: float | None,
    signal_breakdown: dict | None,
    red_flag_detail: str | None = None,
) -> ActionResult:
    """Three-input decision matrix from spec §10. Resolves AI + news +
    smart-money streams into a single action label plus a binding-signal
    tag the frontend can use to drive layout (red-flag override → amber
    border, etc.).

    All three score inputs are optional — when absent we default to
    Neutral / 0 so the function still produces a coherent fallback. The
    AI verdict is the strongest single signal; conviction confirms or
    weakens it; red flags override on overwhelming risk.
    """
    ai = _VERDICT_TO_AI.get((ai_decision or "").upper(), "HOLD")
    conv = conviction_score if conviction_score is not None else 0.0
    rf = red_flag_score if red_flag_score is not None else 0.0
    confidence = ai_confidence or 0

    # Red flags always have right of refusal on a BUY.
    if ai == "BUY" and rf <= -30:
        return ActionResult(
            action="REVIEW",
            confidence_tag="CONFLICTING",
            binding_signal="red_flag",
            explanation="AI says buy but red flags are firing — review before adding.",
            red_flag_detail=red_flag_detail or _summarise_red_flags(signal_breakdown),
        )

    if ai == "BUY":
        if confidence >= 70 and conv >= 60:
            return ActionResult(
                action="HIGH CONVICTION BUY",
                confidence_tag="HIGH CONVICTION",
                binding_signal="conviction",
                explanation="AI verdict + smart-money conviction aligned.",
            )
        if conv >= 30:
            return ActionResult(
                action="BUY",
                confidence_tag="CONFIRMED",
                binding_signal="conviction",
                explanation="AI buy + institutional accumulation confirms.",
            )
        return ActionResult(
            action="BUY",
            confidence_tag="UNCONFIRMED",
            binding_signal="ai",
            explanation="AI says buy but no institutional backing yet.",
        )

    if ai == "HOLD":
        if conv >= 60 and rf > -20:
            return ActionResult(
                action="ACCUMULATE",
                confidence_tag="CONFIRMED",
                binding_signal="conviction",
                explanation="Smart money is building while AI says hold.",
            )
        if conv <= -50:
            return ActionResult(
                action="WATCHFUL",
                confidence_tag="UNCONFIRMED",
                binding_signal="conviction",
                explanation="Institutions may be exiting — watch closely.",
            )
        return ActionResult(
            action="HOLD",
            confidence_tag="CONFIRMED",
            binding_signal="ai",
            explanation="No strong signal in either direction.",
        )

    if ai == "SELL":
        if conv <= -30:
            return ActionResult(
                action="STRONG SELL",
                confidence_tag="CONFIRMED",
                binding_signal="conviction",
                explanation="AI and institutions agree.",
            )
        if conv >= 30 and rf > -20:
            return ActionResult(
                action="REVIEW",
                confidence_tag="CONFLICTING",
                binding_signal="conviction",
                explanation="AI says sell but institutions are buying — review.",
            )
        return ActionResult(
            action="SELL",
            confidence_tag="CONFIRMED",
            binding_signal="ai",
            explanation="AI verdict suggests exit.",
        )

    # ai == "WATCH"
    if conv >= 60 and rf > -20:
        return ActionResult(
            action="WATCH (INTERESTING)",
            confidence_tag="CONFIRMED",
            binding_signal="conviction",
            explanation="Not ready per AI but smart money is active.",
        )
    return ActionResult(
        action="WATCH",
        confidence_tag="UNCONFIRMED",
        binding_signal="ai",
        explanation="AI verdict not yet conclusive.",
    )


def _summarise_red_flags(signal_breakdown: dict | None) -> str | None:
    """Extract a one-liner describing the binding red flag for the
    frontend tooltip. Picks the most-penalised flag in the breakdown."""
    if not signal_breakdown:
        return None
    rf = (signal_breakdown.get("red_flags") or {}).get("triggered") or []
    if not rf:
        return None
    detail = (signal_breakdown.get("red_flags") or {}).get("detail") or {}
    # Pick the worst penalty
    worst_flag = None
    worst_penalty = 0
    for flag in rf:
        pen = (detail.get(flag) or {}).get("penalty") or 0
        try:
            pen = float(pen)
        except (TypeError, ValueError):
            pen = 0
        if pen < worst_penalty:
            worst_penalty = pen
            worst_flag = flag
    if worst_flag is None:
        return None
    label_map = {
        "circular_trading": "Circular trading suspects detected",
        "pump_pattern": "Pump pattern: rising price, falling delivery",
        "promoter_selling": "Promoter selling in last 90 days",
        "high_pledge": "Promoter pledge above 40% threshold",
        "pledge_invocation": "Pledge invocation event",
    }
    return label_map.get(worst_flag, worst_flag.replace("_", " "))


def _newest_headline_date(sentiment_record: NewsSentimentCache | None) -> str | None:
    """Max headline pub_date across cached headlines for this symbol, as a
    YYYY-MM-DD string. Used by the dashboard to show 'news today' / 'news
    3d ago' / 'quiet 7d' instead of opaque job-runtime timestamps.

    If the underlying news scan finds zero new headlines for a stock today,
    this value silently stays equal to whatever the newest cached headline's
    pub_date is — and the UI label advances day by day ('news 1d' → 'news 2d'
    → 'quiet 7d') honestly, without any backend job needing to stamp anything.
    """
    if not sentiment_record or not sentiment_record.result_json:
        return None
    heads = (sentiment_record.result_json or {}).get("headlines") or []
    candidates: list[str] = []
    for h in heads:
        # Coalesce across the two field names this column has used historically.
        d = h.get("date") or h.get("published_at") or h.get("pub_date")
        if isinstance(d, str) and len(d) >= 10:
            candidates.append(d[:10])
    if not candidates:
        return None
    return max(candidates)


def _sector_to_dict(sec: SectorAnalysis, *, compact: bool = False) -> dict:
    """Serialise a SectorAnalysis row for the Market Brief surface.

    `compact=True` strips the heavy fields (top_headlines, what_to_watch,
    macro_drivers) so the brief response stays small. The Market Brief
    modal hits GET /api/today/sectors for the full shape.
    """
    from app.services.sector_news import SECTOR_BELLWETHERS  # local: avoid cycle at import

    base = {
        "sector": sec.sector,
        "mood": sec.mood,
        "score": sec.score,
        "confidence": sec.confidence,
        "signals": sec.signals,
        "summary": sec.summary,
        "headline_count": sec.headline_count,
        "last_run_at": sec.last_run_at.isoformat() if sec.last_run_at else None,
        "bellwethers": SECTOR_BELLWETHERS.get(sec.sector) or SECTOR_BELLWETHERS.get((sec.sector or "").title()) or [],
    }
    if compact:
        return base
    return {
        **base,
        "macro_drivers": sec.macro_drivers,
        "what_to_watch": sec.what_to_watch,
        "top_headlines": sec.top_headlines,
    }


async def _compute_brief(user: User, db: AsyncSession, *, force_kite: bool = False) -> dict:
    """Expensive path — calls Kite holdings() live and joins against
    DB-resident signal tables. Returns the brief payload."""

    holdings_data = []
    portfolio_symbols: set[str] = set()
    if user.kite_api_key:
        try:
            holdings = await cached_holdings(user, force=force_kite and bool(user.kite_access_token))
            for h in holdings:
                # Kite splits a position across several fields:
                #   quantity            — free demat-settled shares
                #   t1_quantity         — bought today, not yet delivered
                #   collateral_quantity — pledged as margin collateral
                #   realised_quantity   — awaiting pledge release
                # "Total owned" is the sum of all four. Ignoring
                # collateral_quantity hides pledged positions (e.g. if
                # the user has pledged Angel One shares for margin).
                demat_qty = h.get("quantity", 0) or 0
                t1_qty = h.get("t1_quantity", 0) or 0
                coll_qty = h.get("collateral_quantity", 0) or 0
                realised_qty = h.get("realised_quantity", 0) or 0
                # Exclude realised_quantity — it can overlap with quantity
                # after pledge-release settlement, causing double-count.
                qty = demat_qty + t1_qty + coll_qty
                if qty <= 0:
                    continue
                sym = h.get("tradingsymbol", "").upper()
                portfolio_symbols.add(sym)
                avg = h.get("average_price", 0) or 0
                ltp = h.get("last_price", 0) or 0
                invested = avg * qty
                current = ltp * qty
                pnl = current - invested
                pnl_pct = (pnl / invested * 100) if invested else 0
                prev_close = h.get("close_price", 0) or 0
                day_pnl = (ltp - prev_close) * qty

                holdings_data.append({
                    "symbol": sym,
                    "exchange": h.get("exchange", "NSE"),
                    "quantity": qty,
                    "demat_quantity": demat_qty,
                    "t1_quantity": t1_qty,
                    "collateral_quantity": coll_qty,
                    "realised_quantity": realised_qty,
                    "pledged": bool(coll_qty),
                    "collateral_type": h.get("collateral_type"),
                    "average_price": round(avg, 2),
                    "last_price": round(ltp, 2),
                    "invested": round(invested, 2),
                    "current": round(current, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "day_pnl": round(day_pnl, 2),
                    "day_change_pct": round(h.get("day_change_percentage", 0), 2),
                })
        except Exception as e:
            logger.warning(f"Holdings fetch failed: {e}")

    # Batch-fetch fundamentals for market_cap + sector lookup
    market_caps: dict[str, float | None] = {}
    fund_by_symbol: dict[str, StockFundamentals] = {}
    if portfolio_symbols:
        fund_result = await db.execute(
            select(StockFundamentals)
            .where(StockFundamentals.symbol.in_(list(portfolio_symbols)))
        )
        for f in fund_result.scalars().all():
            fund_by_symbol[f.symbol] = f
            market_caps[f.symbol] = float(f.market_cap) if f.market_cap is not None else None

    # Batch-fetch StockAnalysis + SectorAnalysis for card sections
    analyses_by_symbol: dict[str, StockAnalysis] = {}
    sector_analyses: dict[str, SectorAnalysis] = {}
    peer_set_age_by_symbol: dict[str, datetime] = {}
    # Canonical sector per holding via the multi-source resolver. Populated
    # inside the `if portfolio_symbols` block below; initialized empty so
    # the per-holding loop can look up safely even when there's no portfolio.
    sector_resolutions: dict = {}
    if portfolio_symbols:
        sa_result = await db.execute(
            select(StockAnalysis).where(StockAnalysis.symbol.in_(list(portfolio_symbols)))
        )
        for sa in sa_result.scalars().all():
            analyses_by_symbol[sa.symbol] = sa

        # Peer-set age: max(generated_at) across both directions, per symbol.
        from sqlalchemy import func as _func, or_ as _or
        from app.models.stock_peers import StockPeer
        age_result = await db.execute(
            select(
                StockPeer.symbol,
                _func.max(StockPeer.generated_at).label("max_gen"),
            )
            .where(_or(
                StockPeer.symbol.in_(list(portfolio_symbols)),
                StockPeer.peer_symbol.in_(list(portfolio_symbols)),
            ))
            .group_by(StockPeer.symbol)
        )
        for row in age_result.all():
            if row.max_gen:
                peer_set_age_by_symbol[row.symbol] = row.max_gen

        # Top-N stored peers (with names) per symbol — so the dashboard card
        # can show peer names even when metric_breakdown is empty (e.g. for
        # stocks whose peers' fundamentals lack the metric fields we compare).
        # Keeps PositionCard from rendering a misleading "No peer data" state.
        peers_top5_by_symbol: dict[str, list[dict]] = {}
        peer_rows_q = await db.execute(
            select(
                StockPeer.symbol,
                StockPeer.peer_symbol,
                StockPeer.rank,
                StockFundamentals.name,
            )
            .join(StockFundamentals, StockFundamentals.symbol == StockPeer.peer_symbol)
            .where(StockPeer.symbol.in_(list(portfolio_symbols)))
            .order_by(StockPeer.symbol, StockPeer.rank.asc().nullslast(), StockPeer.peer_symbol)
        )
        for row in peer_rows_q.all():
            sym = row.symbol
            if sym not in peers_top5_by_symbol:
                peers_top5_by_symbol[sym] = []
            if len(peers_top5_by_symbol[sym]) < 5:
                peers_top5_by_symbol[sym].append({
                    "symbol": row.peer_symbol,
                    "name": row.name,
                })

        # Resolve each holding's canonical sector via the multi-source
        # resolver (override → Nifty membership → stock_fundamentals).
        # Used downstream to set `resolved_sector` on each holding card
        # (e.g. for the per-card sector-mood chip).
        sector_resolutions = await resolve_sectors_bulk(
            list(portfolio_symbols), db, user_id=user.id,
        )
        # SectorAnalysis fetch: always fetch the canonical 11 sectors so
        # Market Brief shows full macro coverage, not just whatever the
        # user happens to hold. The morning pipeline refreshes the same
        # canonical set daily. See plan §A2.
        from app.services.screener_presets import CANONICAL_SECTORS
        sec_result = await db.execute(
            select(SectorAnalysis).where(SectorAnalysis.sector.in_(list(CANONICAL_SECTORS)))
        )
        for sec in sec_result.scalars().all():
            sector_analyses[sec.sector] = sec

    # Batch-fetch latest decision / sentiment / smart-money rows for all
    # symbols in one query each instead of N×3. Uses DISTINCT ON to pick the
    # most recent row per symbol.
    decisions_by_symbol: dict[str, InvestmentDecision] = {}
    sentiments_by_symbol: dict[str, NewsSentimentCache] = {}
    smart_money_by_symbol: dict[str, SmartMoneySignal] = {}
    if portfolio_symbols:
        symbols = list(portfolio_symbols)
        dec_q = (
            select(InvestmentDecision)
            .where(
                InvestmentDecision.user_id == user.id,
                InvestmentDecision.symbol.in_(symbols),
            )
            .order_by(InvestmentDecision.symbol, desc(InvestmentDecision.created_at))
            .distinct(InvestmentDecision.symbol)
        )
        for d in (await db.execute(dec_q)).scalars().all():
            decisions_by_symbol[d.symbol] = d

        sent_q = (
            select(NewsSentimentCache)
            .where(NewsSentimentCache.symbol.in_(symbols))
            .order_by(NewsSentimentCache.symbol, NewsSentimentCache.analyzed_at.desc())
            .distinct(NewsSentimentCache.symbol)
        )
        for s in (await db.execute(sent_q)).scalars().all():
            sentiments_by_symbol[s.symbol] = s

        sm_q = (
            select(SmartMoneySignal)
            .where(SmartMoneySignal.symbol.in_(symbols))
            .order_by(SmartMoneySignal.symbol, desc(SmartMoneySignal.as_of))
            .distinct(SmartMoneySignal.symbol)
        )
        for sm in (await db.execute(sm_q)).scalars().all():
            smart_money_by_symbol[sm.symbol] = sm

    holding_actions = []
    for hd in holdings_data:
        decision = decisions_by_symbol.get(hd["symbol"])
        sentiment = sentiments_by_symbol.get(hd["symbol"])
        news_sentiment = sentiment.sentiment if sentiment else None
        news_score = sentiment.score if sentiment else None
        sm_sig = smart_money_by_symbol.get(hd["symbol"])
        sm_composite = int(round(float(sm_sig.composite))) if sm_sig and sm_sig.composite is not None else None
        sm_conviction = float(sm_sig.conviction_score) if sm_sig and sm_sig.conviction_score is not None else None
        sm_flow = float(sm_sig.flow_score) if sm_sig and sm_sig.flow_score is not None else None
        sm_red_flag = float(sm_sig.red_flag_score) if sm_sig and sm_sig.red_flag_score is not None else None
        sm_breakdown = sm_sig.signal_breakdown if sm_sig else None
        sm_sharks = sm_sig.named_sharks if sm_sig else None
        top_shark_line = None
        if sm_sharks:
            s0 = sm_sharks[0]
            top_shark_line = f"{s0.get('name')} {s0.get('side')} on {s0.get('date')}"

        action = "HOLD"
        confidence = None
        reasoning = ""
        analyzed_at = None
        high_conviction = False

        reviewed_at = None
        strategies_diverge = False
        if decision:
            v = decision.verdict
            confidence = decision.confidence
            analyzed_at = decision.created_at.isoformat() if decision.created_at else None
            reviewed_at = decision.reviewed_at.isoformat() if decision.reviewed_at else None
            rj = decision.result_json or {}
            reasoning = rj.get("reasoning", "")
            strategies_diverge = bool(rj.get("strategies_diverge", False))

            if v == "INVEST":
                action = "ACCUMULATE"
            elif v == "AVOID":
                action = "SELL"
            elif v == "WAIT":
                action = "WATCHFUL"

        if not decision and news_score is not None:
            if news_score >= 30:
                action = "ACCUMULATE"
                confidence = min(abs(news_score), 90)
                reasoning = f"Bullish news sentiment (score: {news_score}). No full strategy evaluation yet — run daily analysis for detailed verdict."
            elif news_score <= -30:
                action = "WATCHFUL"
                confidence = min(abs(news_score), 90)
                reasoning = f"Bearish news sentiment (score: {news_score}). Consider running full analysis."

        if decision and action == "HOLD" and news_score is not None and news_score >= 40:
            action = "ACCUMULATE"
            reasoning = (reasoning + f" | Bullish news sentiment ({news_score}).") if reasoning else f"Bullish news sentiment (score: {news_score})."

        if decision and action == "HOLD" and news_score is not None and news_score <= -40:
            action = "WATCHFUL"
            reasoning = (reasoning + f" | Bearish news sentiment ({news_score}).") if reasoning else f"Bearish news sentiment (score: {news_score})."

        if sm_composite is not None:
            if action == "HOLD" and sm_composite >= 60:
                action = "ACCUMULATE"
                reasoning = (reasoning + f" | Smart money +{sm_composite} moving in.") if reasoning else f"Smart money +{sm_composite} moving in."
            elif action == "ACCUMULATE" and sm_composite <= -50:
                action = "WATCHFUL"
                reasoning = (reasoning + f" | But smart money {sm_composite:+} diverges.") if reasoning else f"Smart money {sm_composite:+} contradicts the AI BUY."
            elif action == "HOLD" and sm_composite <= -50:
                action = "WATCHFUL"
                reasoning = (reasoning + f" | Smart money {sm_composite:+} exiting.") if reasoning else f"Smart money {sm_composite:+} exiting."

            if (decision and decision.verdict == "INVEST"
                    and (news_score or 0) >= 30
                    and sm_composite >= 40):
                high_conviction = True

        if top_shark_line and action in {"ACCUMULATE", "WATCHFUL"}:
            reasoning = (reasoning + f" | {top_shark_line}.") if reasoning else top_shark_line

        # Signal pills (design spec: every card shows source · direction · recency)
        signals: list[dict] = []
        if sm_sig:
            composite = sm_composite or 0
            direction = "accumulating" if composite >= 15 else "distributing" if composite <= -15 else "neutral"
            recency = sm_sig.as_of.isoformat() if sm_sig.as_of else None
            # Surface sub-scores as distinct signals when present
            for src_key, sub in [
                ("FII", None),  # FII sub not yet captured per-stock
                ("MF", float(sm_sig.mf_score) if sm_sig.mf_score is not None else None),
                ("DII", None),
                ("INS", None),
                ("PRO", None),
                ("RET", None),
            ]:
                if sub is None:
                    continue
                sub_dir = "accumulating" if sub >= 15 else "distributing" if sub <= -15 else "neutral"
                signals.append({"source": src_key, "direction": sub_dir, "recency": recency, "strength": round(abs(sub) / 100, 2)})
            if not signals:
                # Fall back to composite under "PRO" proxy (we don't know source breakdown yet)
                signals.append({"source": "PRO", "direction": direction, "recency": recency, "strength": round(abs(composite) / 100, 2)})
        # Only surface a NEWS chip when sentiment is materially non-neutral.
        # Recency is the newest headline pub_date (YYYY-MM-DD), not the
        # sentiment-analysed-at timestamp — so the chip stops claiming
        # freshness when the underlying news data isn't actually fresh.
        if news_score is not None and abs(news_score) >= 15:
            nd = "accumulating" if news_score >= 15 else "distributing"
            signals.append({
                "source": "RET",  # news reflects retail/market narrative
                "direction": nd,
                "recency": _newest_headline_date(sentiment) or "",
                "strength": round(abs(news_score) / 100, 2),
                "label": "NEWS",
            })

        # Risk flags derived from fundamentals (best-effort — field availability varies)
        risk_flags: list[dict] = []
        risks: list[dict] = []
        strengths: list[dict] = []
        if decision:
            rj = decision.result_json or {}
            # Split a "label — sublabel" string into (label, sublabel)
            def _split(text: str) -> tuple[str, str | None]:
                t = text.strip()
                for sep in (" — ", " - ", " · ", ": "):
                    if sep in t:
                        head, tail = t.split(sep, 1)
                        return head.strip()[:60], tail.strip()[:120]
                return t[:60], None

            for r in (rj.get("key_risks") or [])[:4]:
                if isinstance(r, str) and r.strip():
                    label, sub = _split(r)
                    risk_flags.append({"severity": "red", "label": label})
                    risks.append({"severity": "high", "label": label, "sublabel": sub})

            val_view = rj.get("valuation_view") or ""
            if "overvalued" in val_view.lower() or "stretched" in val_view.lower():
                risk_flags.append({"severity": "amber", "label": "Valuation stretched"})
                risks.append({"severity": "med", "label": "Valuation stretched", "sublabel": val_view[:120]})
            elif "undervalued" in val_view.lower() or "cheap" in val_view.lower():
                risk_flags.append({"severity": "blue", "label": "Valuation attractive"})
                strengths.append({"label": "Valuation attractive", "sublabel": val_view[:120]})

            # Action items can serve as supplementary "strengths" (positive forward steps)
            for a in (rj.get("action_items") or [])[:2]:
                if isinstance(a, str) and a.strip():
                    label, sub = _split(a)
                    strengths.append({"label": label, "sublabel": sub})

        # Synthetic strengths from quantitative signals
        if news_score is not None and news_score >= 40:
            strengths.append({"label": f"Bullish news +{news_score}", "sublabel": "Recent coverage favorable"})
        if sm_composite is not None and sm_composite >= 40:
            strengths.append({"label": f"Smart money +{sm_composite}", "sublabel": "Institutional accumulation"})

        # Spec §10 decision matrix — runs alongside the legacy merge so
        # the existing UI path keeps working until the frontend revamp
        # in PR 5 picks up `action_v2` and the breakdown fields.
        action_v2 = decide_action_v2(
            ai_decision=decision.verdict if decision else None,
            ai_confidence=confidence,
            news_sentiment=news_sentiment,
            conviction_score=sm_conviction,
            flow_score=sm_flow,
            red_flag_score=sm_red_flag,
            signal_breakdown=sm_breakdown,
        )
        top_signal = _top_breakdown_signal(sm_breakdown)

        # Stock card sections (populated by morning pipeline step 4)
        sa = analyses_by_symbol.get(hd["symbol"])
        fund = fund_by_symbol.get(hd["symbol"])
        resolution = sector_resolutions.get(hd["symbol"])
        resolved_sector = resolution.sector if resolution else (fund.sector if fund else None)
        sec = sector_analyses.get(resolved_sector) if resolved_sector else None

        valuation_section = None
        peer_section = None
        news_section = None
        card_act_now_score = None
        card_summary_line = None

        if sa:
            valuation_section = {
                "verdict": sa.valuation_verdict,
                "score": float(sa.valuation_score) if sa.valuation_score is not None else None,
                "signals": sa.valuation_signals,
                "hard_failed": sa.valuation_hard_failed,
                "last_run_at": sa.valuation_last_run_at.isoformat() if sa.valuation_last_run_at else None,
            }
            peers_gen_at = peer_set_age_by_symbol.get(sa.symbol)
            peer_section = {
                "verdict": sa.peer_verdict,
                "metric_breakdown": sa.peer_metric_breakdown,
                "peer_summary": sa.peer_summary,
                "peer_count": sa.peer_count,
                "peer_set_weak": sa.peer_set_weak,
                "last_run_at": sa.peer_last_run_at.isoformat() if sa.peer_last_run_at else None,
                "peers_generated_at": peers_gen_at.isoformat() if peers_gen_at else None,
                # Top stored peer names so dashboard renders something useful
                # when metric_breakdown is empty but peers exist in stock_peers.
                "peers_top5": peers_top5_by_symbol.get(sa.symbol, []),
            }
            news_section = {
                "verdict": sa.news_verdict,
                "stock_signals": sa.news_stock_signals,
                "source_count": sa.news_source_count,
                "qualitative": sa.news_qualitative,
                "sector_mood": sec.mood if sec else None,
                # Resolved sector name + provenance — lets the card show
                # "Industrials · Sector mood: BULLISH" with a (?) tooltip
                # explaining where the sector came from (override/Nifty/
                # Screener/yfinance). User can spot mistagging at a glance
                # and correct via Settings → Holdings.
                "sector": resolution.sector if resolution else None,
                "sector_source": resolution.source if resolution else None,
                "last_run_at": sa.news_last_run_at.isoformat() if sa.news_last_run_at else None,
                # `newest_headline_at`: max pub_date across cached headlines —
                # the only honest "this is how fresh the news data is" signal.
                # Frontend renders 'news today' / 'news 3d ago' / 'quiet 7d'
                # off this, instead of the misleading job-runtime stamp above.
                "newest_headline_at": _newest_headline_date(sentiment),
            }
            card_act_now_score = sa.act_now_score
            card_summary_line = sa.summary_line

        # Narrative-stale check: the deep-analysis narrative (stored on
        # `decision.result_json`) bakes in numeric values from the
        # fundamentals row at the time it ran. If a fresher fundamentals
        # snapshot has since been fetched, the rules card next to the
        # narrative will evaluate against the new numbers and the two can
        # disagree (e.g. ETERNAL: narrative "PE 648x", rules card "P/E 616").
        # Surface that mismatch so the UI can show a "narrative may be
        # stale" warning rather than presenting two conflicting numbers
        # without context. Threshold: 24h is enough to span an overnight
        # fundamentals refresh.
        narrative_stale = False
        narrative_fund_lag_hours: float | None = None
        if decision and decision.created_at and fund and fund.fetched_at:
            try:
                lag = (fund.fetched_at - decision.created_at).total_seconds() / 3600.0
                narrative_fund_lag_hours = round(lag, 1) if lag > 0 else 0.0
                if lag > 24:
                    narrative_stale = True
            except (TypeError, ValueError):
                pass

        holding_actions.append({
            **hd,
            "market_cap": market_caps.get(hd["symbol"]),
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning if reasoning else "",
            "analyzed_at": analyzed_at,
            "narrative_stale": narrative_stale,
            "narrative_fund_lag_hours": narrative_fund_lag_hours,
            "news_sentiment": news_sentiment,
            "news_score": news_score,
            "smart_money_composite": sm_composite,
            "smart_money_conviction": int(round(sm_conviction)) if sm_conviction is not None else None,
            "smart_money_flow": int(round(sm_flow)) if sm_flow is not None else None,
            "smart_money_red_flag": int(round(sm_red_flag)) if sm_red_flag is not None else None,
            "smart_money_top_signal": top_signal,
            "smart_money_top_shark": top_shark_line,
            "high_conviction": high_conviction,
            # Surface AI-vs-rule divergence so the dashboard chip row can
            # render a STRAT ↯ chip when the verdict contradicts the
            # majority of passed fundamental rules. Boolean lives in
            # InvestmentDecision.result_json["strategies_diverge"]; see
            # plan §D2.5 for the UI treatment.
            "strategies_diverge": strategies_diverge,
            # New: spec §10 matrix output for the upcoming frontend.
            "action_v2": action_v2.action,
            "confidence_tag": action_v2.confidence_tag,
            "binding_signal": action_v2.binding_signal,
            "action_explanation": action_v2.explanation,
            "red_flag_detail": action_v2.red_flag_detail,
            "signals": signals,
            "risk_flags": risk_flags,  # legacy, kept for one cycle
            "risks": risks[:4],
            "strengths": strengths[:3],
            "reviewed_at": reviewed_at,
            # Stock card sections
            "valuation_section": valuation_section,
            "peer_section": peer_section,
            "news_section": news_section,
            "act_now_score": card_act_now_score,
            "summary_line": card_summary_line,
        })

    def _staleness_seconds(analyzed_at_iso: str | None) -> float:
        if not analyzed_at_iso:
            return float("inf")
        try:
            return (datetime.now(tz=timezone.utc) - datetime.fromisoformat(analyzed_at_iso)).total_seconds()
        except (ValueError, TypeError):
            return float("inf")

    action_order = {"SELL": 0, "ACCUMULATE": 1, "WATCHFUL": 2, "HOLD": 3}
    holding_actions.sort(key=lambda x: (
        action_order.get(x["action"], 3),
        1 if x.get("reviewed_at") else 0,
        -_staleness_seconds(x.get("analyzed_at")),
        -abs(x.get("pnl_pct", 0)),
    ))

    action_counts = {"SELL": 0, "ACCUMULATE": 0, "WATCHFUL": 0, "HOLD": 0}
    for ha in holding_actions:
        action_counts[ha["action"]] = action_counts.get(ha["action"], 0) + 1

    total_invested = sum(h.get("invested", 0) for h in holdings_data)
    total_current = sum(h.get("current", 0) for h in holdings_data)
    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0
    total_day_pnl = sum(h.get("day_pnl", 0) for h in holding_actions)

    # Full-shape sectors[] for the Market Pulse "Sectors" section. The
    # inline expansion below each row needs macro_drivers / what_to_watch
    # / top_headlines, and shipping them in the brief response saves a
    # second round-trip. Sector count is ~5-10 per user so payload
    # overhead is negligible.
    sectors_compact = sorted(
        (_sector_to_dict(sec, compact=False) for sec in sector_analyses.values()),
        key=lambda s: (s.get("score") is None, -(s.get("score") or 0)),
    )

    return {
        "date": date.today().isoformat(),
        "holdings_actions": holding_actions,
        "action_counts": action_counts,
        "portfolio_summary": {
            "total_invested": round(total_invested, 2),
            "total_current": round(total_current, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "total_day_pnl": round(total_day_pnl, 2),
            "stock_count": len(holdings_data),
        },
        "sectors": sectors_compact,
        "kite_connected": bool(user.kite_access_token),
    }


async def _persist_cache(db: AsyncSession, user_id: int, payload: dict, compute_ms: int, now: datetime) -> None:
    stmt = pg_insert(TodayBriefCache).values(
        user_id=user_id,
        payload=payload,
        refreshed_at=now,
        compute_ms=compute_ms,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "payload": stmt.excluded.payload,
            "refreshed_at": stmt.excluded.refreshed_at,
            "compute_ms": stmt.excluded.compute_ms,
        },
    )
    await db.execute(stmt)
    await db.commit()


async def _read_cache(db: AsyncSession, user_id: int) -> TodayBriefCache | None:
    result = await db.execute(
        select(TodayBriefCache).where(TodayBriefCache.user_id == user_id)
    )
    return result.scalar_one_or_none()


@router.get("/brief")
async def get_morning_brief(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Returns the last-computed brief from cache (instant). If no cache
    exists yet, computes on-demand once and caches. Client triggers
    POST /brief/refresh for explicit recompute."""
    cached = await _read_cache(db, user.id)
    if cached:
        return {
            **(cached.payload or {}),
            "cached": True,
            "refreshed_at": cached.refreshed_at.isoformat() if cached.refreshed_at else None,
            "compute_ms": cached.compute_ms,
        }

    started = time.monotonic()
    payload = await _compute_brief(user, db)
    compute_ms = int((time.monotonic() - started) * 1000)
    now = datetime.now(tz=timezone.utc)
    await _persist_cache(db, user.id, payload, compute_ms, now)

    return {
        **payload,
        "cached": False,
        "refreshed_at": now.isoformat(),
        "compute_ms": compute_ms,
    }


@router.post("/brief/refresh")
async def refresh_morning_brief(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dispatch a lightweight background refresh (fundamentals + Kite prices
    + AI evaluation + brief cache). Returns immediately with a task_id the
    client can poll. Rejects with 409 if any pipeline is already running."""
    from app.tasks.morning_pipeline import get_active_pipeline, run_brief_refresh

    active = await get_active_pipeline(db)
    if active:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "pipeline_running",
                "source": active["source"],
                "started_at": active["started_at"],
            },
        )

    result = run_brief_refresh.delay()
    return {"task_id": result.id, "status": "dispatched", "mode": "refresh"}


@router.get("/brief/refresh/status/{task_id}")
async def brief_refresh_status(
    task_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Poll the status of a background task dispatched by
    POST /brief/refresh or POST /pipeline/run."""
    from celery.result import AsyncResult
    result = AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.state,
        "ready": result.ready(),
    }


# ─────────────────────────────────────────────────────────────────────
# Market Brief — Sectors (v1)
# Backs the new "Market Brief" modal on the dashboard. The sectors are
# the ones the morning pipeline already refreshes (portfolio + watchlist).
# ─────────────────────────────────────────────────────────────────────


@router.get("/sectors")
async def list_sectors(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Full-shape sector cards for the Market Brief modal.

    Scope: the project's canonical 11-sector taxonomy
    (`CANONICAL_SECTORS` in `screener_presets.py`) — Technology,
    Financial Services, Healthcare, Consumer Cyclical, Consumer Defensive,
    Industrials, Basic Materials, Communication Services, Energy,
    Utilities, Real Estate. Sorted by score descending, NULL scores
    last so any unrefreshed legacy sector surfaces below scored rows.

    Returns the same 11 rows that `_compute_brief.sectors[]` returns —
    intentional parity. See plan §A3.
    """
    from app.services.screener_presets import CANONICAL_SECTORS

    rows = (await db.execute(
        select(SectorAnalysis).where(SectorAnalysis.sector.in_(list(CANONICAL_SECTORS)))
    )).scalars().all()

    payload = [_sector_to_dict(s, compact=False) for s in rows]
    payload.sort(key=lambda d: (d.get("score") is None, -(d.get("score") or 0)))
    return payload


@router.post("/sectors/{sector}/refresh")
async def refresh_sector(
    sector: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Synchronously re-run the sector-sentiment prompt for one sector.

    Mirrors the brief's refresh UX — the Market Brief modal's per-sector
    refresh button hits this. Slow (one Gemini call); call sparingly.
    """
    from app.services.sector_news import refresh_sector_analysis

    sector = (sector or "").strip()
    if not sector:
        raise HTTPException(status_code=400, detail="sector is required")

    try:
        row = await refresh_sector_analysis(sector, db, user.id)
    except Exception as e:
        logger.exception("sector refresh failed for %s", sector)
        raise HTTPException(status_code=502, detail=f"Refresh failed: {str(e)[:200]}")

    if not row:
        raise HTTPException(status_code=404, detail=f"No headlines found for sector '{sector}'")

    return _sector_to_dict(row, compact=False)


@router.post("/pipeline/run")
async def run_morning_pipeline_now(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually dispatch the full morning pipeline (news scan + data refresh
    + AI analysis) as a background Celery task. Rejects with 409 if any
    pipeline is already running."""
    from app.tasks.morning_pipeline import get_active_pipeline, run_morning_pipeline

    active = await get_active_pipeline(db)
    if active:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "pipeline_running",
                "source": active["source"],
                "started_at": active["started_at"],
            },
        )

    result = run_morning_pipeline.delay()
    return {"task_id": result.id, "status": "dispatched", "mode": "full"}


@router.post("/news/scan")
async def run_news_scan_now(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dispatch a news-only scan (broad scan + per-symbol sentiment + sector
    analysis). Rejects with 409 if any pipeline is already running."""
    from app.tasks.morning_pipeline import get_active_pipeline, run_news_scan

    active = await get_active_pipeline(db)
    if active:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "pipeline_running",
                "source": active["source"],
                "started_at": active["started_at"],
            },
        )

    result = run_news_scan.delay()
    return {"task_id": result.id, "status": "dispatched", "mode": "news"}


@router.post("/cards/refresh")
async def run_cards_refresh_now(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-run stock-card analysis (valuation + peers + news verdict) for
    every portfolio holding. Auto-seeds peers for holdings that don't have
    them. Much faster than the full pipeline because it skips the news
    scan / fundamentals refresh / Kite quote refresh / AI eval steps."""
    from app.tasks.morning_pipeline import get_active_pipeline, run_cards_refresh

    active = await get_active_pipeline(db)
    if active:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "pipeline_running",
                "source": active["source"],
                "started_at": active["started_at"],
            },
        )

    result = run_cards_refresh.delay()
    return {"task_id": result.id, "status": "dispatched", "mode": "cards"}


@router.get("/pipeline/status")
async def pipeline_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return current pipeline state + whether new news data is available
    since the last brief refresh."""
    from app.models.smart_money import IngestionRun
    from app.tasks.morning_pipeline import get_active_pipeline

    active = await get_active_pipeline(db)

    # Compute news_available: last successful news_scan or morning_pipeline
    # finished_at vs TodayBriefCache.refreshed_at
    news_available = False
    brief_cache = await _read_cache(db, user.id)
    brief_refreshed_at = brief_cache.refreshed_at if brief_cache else None

    if brief_refreshed_at:
        last_news = (await db.execute(
            select(IngestionRun.finished_at)
            .where(
                IngestionRun.source.in_(("morning_pipeline", "news_scan")),
                IngestionRun.status.in_(("success", "partial")),
                IngestionRun.finished_at.isnot(None),
            )
            .order_by(IngestionRun.finished_at.desc())
            .limit(1)
        )).scalar_one_or_none()

        if last_news and last_news > brief_refreshed_at:
            news_available = True

    return {
        "running": active is not None,
        "active": active,
        "news_available": news_available,
        "brief_refreshed_at": brief_refreshed_at.isoformat() if brief_refreshed_at else None,
    }


@router.post("/stock/{symbol}/refresh")
async def refresh_stock_sections(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    force_news: bool = True,
) -> dict:
    """Unified manual refresh for a single stock card.

    With `force_news=True` (default), this is the same end-to-end refresh
    the user gets from the bottom "Refresh news" button in the News tab:
    re-scrapes headlines + re-runs sentiment + refreshes the card row.
    The small refresh icon on the dashboard card's News section and the
    bottom button now do the same thing.

    `force_news=false` keeps the lightweight behaviour for callers that
    only want to re-run the card analysis on already-cached sentiment.
    """
    from app.tasks.morning_pipeline import get_active_pipeline
    active = await get_active_pipeline(db)
    if active:
        raise HTTPException(409, detail=f"Pipeline '{active['source']}' is running")

    symbol_u = symbol.upper()

    # Step 1: optional sentiment force-refresh. Same code path the
    # `/api/market-data/sentiment/{symbol}?force=true` endpoint uses —
    # scrapes ~18 sources + Google News + reruns Gemini sentiment, and
    # writes a new NewsSentimentCache row. ~60-90s on prod.
    if force_news:
        try:
            from app.services.news_sentiment import get_news_sentiment
            fund_res = await db.execute(
                select(StockFundamentals).where(StockFundamentals.symbol == symbol_u)
            )
            fund_for_news = fund_res.scalar_one_or_none()
            company_name = fund_for_news.name if fund_for_news else None
            sentiment_result = await get_news_sentiment(
                symbol_u, company_name, days=7, user_id=user.id, db=db,
            )
            db.add(NewsSentimentCache(
                symbol=symbol_u,
                sentiment=sentiment_result.get("sentiment"),
                score=sentiment_result.get("score"),
                result_json=sentiment_result,
                analyzed_at=datetime.now(timezone.utc),
            ))
            await db.flush()
        except Exception as e:
            logger.warning(f"refresh_stock_sections: force-news sentiment failed for {symbol_u}: {e}")
            # Continue — the card refresh below will still run on whatever
            # sentiment row exists. Better degraded than blocked.

    # Step 2: refresh the card row — reads the just-updated NewsSentimentCache
    # if force_news was True, otherwise the existing cache.
    from app.services.stock_card import refresh_stock_analysis
    sa = await refresh_stock_analysis(symbol_u, db, user.id)
    if not sa:
        raise HTTPException(404, detail=f"No fundamentals found for {symbol_u}")

    # Read back the latest sentiment record so we can compute newest_headline_at
    # for the response. Fresh row if force_news=True; otherwise existing.
    sentiment_q = await db.execute(
        select(NewsSentimentCache)
        .where(NewsSentimentCache.symbol == symbol_u)
        .order_by(NewsSentimentCache.analyzed_at.desc())
        .limit(1)
    )
    sentiment = sentiment_q.scalar_one_or_none()

    sec = None
    if sa.news_verdict:
        fund_res = await db.execute(
            select(StockFundamentals.sector).where(StockFundamentals.symbol == symbol_u)
        )
        sector = fund_res.scalar_one_or_none()
        if sector:
            sec_res = await db.execute(
                select(SectorAnalysis).where(SectorAnalysis.sector == sector)
            )
            sec = sec_res.scalar_one_or_none()

    return {
        "valuation_section": {
            "verdict": sa.valuation_verdict,
            "score": float(sa.valuation_score) if sa.valuation_score is not None else None,
            "signals": sa.valuation_signals,
            "hard_failed": sa.valuation_hard_failed,
            "last_run_at": sa.valuation_last_run_at.isoformat() if sa.valuation_last_run_at else None,
        },
        "peer_section": {
            "verdict": sa.peer_verdict,
            "metric_breakdown": sa.peer_metric_breakdown,
            "peer_summary": sa.peer_summary,
            "peer_count": sa.peer_count,
            "peer_set_weak": sa.peer_set_weak,
            "last_run_at": sa.peer_last_run_at.isoformat() if sa.peer_last_run_at else None,
        },
        "news_section": {
            "verdict": sa.news_verdict,
            "stock_signals": sa.news_stock_signals,
            "source_count": sa.news_source_count,
            "qualitative": sa.news_qualitative,
            "sector_mood": sec.mood if sec else None,
            "last_run_at": sa.news_last_run_at.isoformat() if sa.news_last_run_at else None,
            "newest_headline_at": _newest_headline_date(sentiment),
        },
        "act_now_score": sa.act_now_score,
        "summary_line": sa.summary_line,
    }


@router.post("/review/{symbol}")
async def mark_reviewed(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(tz=timezone.utc)
    stmt = pg_insert(UserStockReview).values(
        user_id=user.id,
        symbol=symbol.upper(),
        reviewed_at=now,
    ).on_conflict_do_update(
        constraint="uq_user_stock_review",
        set_={"reviewed_at": now},
    )
    await db.execute(stmt)
    await db.commit()
    return {"symbol": symbol.upper(), "reviewed_at": now.isoformat()}


@router.delete("/review/{symbol}")
async def unmark_reviewed(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import delete
    await db.execute(
        delete(UserStockReview).where(
            UserStockReview.user_id == user.id,
            UserStockReview.symbol == symbol.upper(),
        )
    )
    await db.commit()
    return {"symbol": symbol.upper(), "reviewed_at": None}
