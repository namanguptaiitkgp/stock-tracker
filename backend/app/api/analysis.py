import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from kiteconnect import KiteConnect
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gemini_client import call_gemini_with_rotation
from app.ai.credential_rotation import NoCredentialsConfiguredError, AllCredentialsExhaustedError
from app.ai.prompt_helpers import (
    DECIMAL_OUTPUT_RULE,
    INDIAN_MACRO_CONTEXT,
    STRICT_JSON_BOUNDARY,
)
from app.config import get_settings
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.analysis import PortfolioAnalysis
from app.models.user import User
from app.services.fundamentals_service import get_fundamentals
from app.services.portfolio_cache import active_holdings
from app.services.regulatory.asm_gsm import get_reg_flag, get_surveillance_flags

logger = logging.getLogger(__name__)
router = APIRouter()

# NSE NIFTY 50 index instrument token (constant in Kite).
NIFTY_50_TOKEN = 256265

SELL_STRATEGY_PROMPT = """SYSTEM: You are a ruthless, objective portfolio risk manager evaluating Indian equity holdings on {today_ist}. Your job is to protect capital — not to be polite about losers.

INPUT:
Portfolio (one line per holding with LTP/Avg/PnL%/50DMA/200DMA/52WH/30d/90d/RS30d/PE/PB/RevGr/EPSGr/ROE/DE/Sector/RegFlag):
{portfolio_data}

RegFlag values (sourced live from NSE surveillance lists):
- "CLEAR" — no NSE regulatory surveillance
- "LTASM Stage I/II/III/IV" — Long-term Additional Surveillance, escalating severity (I = 5% price band; IV = T+T segment, 100% margin)
- "STASM Stage I/II/III/IV" — Short-term Additional Surveillance (less severe than LTASM at same stage)
- "GSM" — Graded Surveillance Mechanism (most severe — trade restrictions, often eventual suspension)

Market context:
{market_context}

Tax framework (Indian capital gains):
- STCG (held < 1 year): {stcg_rate}% on gains
- LTCG (held ≥ 1 year): {ltcg_rate}% on gains above ₹{ltcg_exemption_inr:,} annual exemption

TASK: For each holding, decide HOLD, TRIM, or SELL. Protect capital above all else.

RULES:
1. [TRACEABILITY] Ground every technical claim strictly in the numbers provided. "Downtrend" requires LTP < 50DMA / 200DMA, negative 30d/90d returns, OR negative RS30d. Do not fabricate trend narratives.
2. [EXIT TRIGGERS — hard for ASM/GSM, soft for the rest] If a stock's `RegFlag` is anything other than `CLEAR` (e.g., `LTASM Stage I`, `GSM`), your signal MUST be `SELL` or `TRIM` with confidence ≥ 80, regardless of how strong the fundamentals look — regulatory surveillance is a hard sell discipline. For other patterns mentioned only in headlines (sudden pledge spikes, auditor resignations, 50/200 DMA breakdown on rising volume), prioritise SELL but use judgment on confidence.
3. [OPPORTUNITY COST] If a stock has negative RS30d AND negative 90d return while Nifty is positive over the same window, treat it as dead money — bias toward TRIM or SELL even if fundamentals are "okay".
4. [TRIM vs SELL] TRIM = partial exit (10-50% of position) when the thesis is wounded but not dead. SELL = full exit when the thesis is broken or capital protection demands it. Do NOT use TRIM for fundamentally healthy stocks — those should be HOLD.
5. [DATA HONESTY] Fields shown as `--` mean unavailable. Do not guess. If too much is missing for a verdict, default to HOLD with reasoning "insufficient data".
6. [INDIAN CONTEXT] {macro_context} Consider FII/DII flow patterns, sector rotation, Budget season volatility, INR moves on IT exporters, monsoon on FMCG/agri.

OUTPUT FORMAT (return exactly this structure):
{{
  "portfolio_summary": {{
    "overall_health": "STRONG" | "MODERATE" | "WEAK",
    "total_stocks_analyzed": <int>,
    "sell_count": <int>,
    "trim_count": <int>,
    "hold_count": <int>,
    "key_portfolio_risks": ["risk1", "risk2"],
    "sector_concentration_warning": "<warning or null>",
    "tax_optimization_note": "<note about STCG/LTCG batching, or null>"
  }},
  "stocks": [
    {{
      "symbol": "SYMBOL",
      "signal": "HOLD" | "TRIM" | "SELL",
      "confidence": <integer 0-100>,
      "technical_scratchpad": "MANDATORY: 1-sentence reading of LTP vs 50DMA/200DMA and RS30d. e.g., 'LTP ₹245 below 50DMA ₹258 and 200DMA ₹272, RS30d -8.4% → confirmed downtrend.' Required even for HOLD.",
      "current_price": <float>,
      "target_exit_price": <float>,
      "stop_loss": <float>,
      "pnl_pct": <float>,
      "key_triggers": ["trigger1", "trigger2"],
      "tax_impact": "STCG" | "LTCG" | "N/A",
      "reasoning": "2 sentences combining technicals + fundamentals"
    }}
  ],
  "top_actions": [
    "most urgent portfolio-level action",
    "second priority",
    "third priority"
  ]
}}

{decimal_rule}

{json_boundary}"""


def _get_authed_kite(user: User) -> KiteConnect:
    if not user.kite_api_key or not user.kite_access_token:
        raise HTTPException(status_code=400, detail="Not connected to Kite")
    kite = KiteConnect(api_key=user.kite_api_key)
    kite.set_access_token(user.kite_access_token)
    return kite


async def _fetch_history(kite: KiteConnect, instrument_token: int) -> list[dict]:
    """Fetch ~400 days of daily OHLC. Kite SDK is sync, so run in a thread.
    Returns [] on failure so one bad symbol doesn't fail the whole analysis."""
    if not instrument_token:
        return []
    try:
        return await asyncio.to_thread(
            kite.historical_data,
            instrument_token,
            date.today() - timedelta(days=400),
            date.today(),
            "day",
        )
    except Exception as e:
        logger.warning(f"historical_data failed for token {instrument_token}: {e}")
        return []


def _technicals(candles: list[dict]) -> dict:
    """Compute DMA, 52W range, and 30d/90d returns from daily candles (oldest → newest)."""
    closes = [c["close"] for c in candles if c.get("close") is not None]
    if len(closes) < 10:
        return {}
    latest = closes[-1]

    def _sma(window: int) -> float | None:
        if len(closes) < max(5, window // 2):
            return None
        tail = closes[-window:]
        return sum(tail) / len(tail)

    def _ret_pct(days: int) -> float | None:
        if len(closes) <= days:
            return None
        past = closes[-(days + 1)]
        if not past:
            return None
        return (latest - past) / past * 100

    win_52w = closes[-252:] if len(closes) >= 60 else closes
    high_52w = max(win_52w)
    low_52w = min(win_52w)

    return {
        "latest": latest,
        "dma50": _sma(50),
        "dma200": _sma(200),
        "high_52w": high_52w,
        "low_52w": low_52w,
        "pct_from_52wh": ((latest - high_52w) / high_52w * 100) if high_52w else None,
        "ret_30d": _ret_pct(30),
        "ret_90d": _ret_pct(90),
    }


def _fmt(v, pct: bool = False, decimals: int = 1) -> str:
    if v is None:
        return "--"
    if pct:
        return f"{v:+.{decimals}f}%"
    return f"{v:.{decimals}f}"


@router.get("/")
async def get_analysis() -> dict:
    return {"status": "Use POST /api/analysis/run-portfolio to run analysis"}


@router.post("/run-portfolio")
async def run_portfolio_analysis(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.portfolio_cache import get_holdings as cached_holdings
    kite = _get_authed_kite(user)
    try:
        holdings = await cached_holdings(user)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite API error: {e}")

    if not holdings:
        raise HTTPException(status_code=400, detail="No holdings found in your Kite account")

    active = active_holdings(holdings)
    if not active:
        raise HTTPException(status_code=400, detail="No active holdings found")

    # Fetch Nifty 50 history + per-holding history in parallel so we can compute
    # returns and relative strength. Falls back to empty lists on failure.
    nifty_task = _fetch_history(kite, NIFTY_50_TOKEN)
    stock_tasks = [_fetch_history(kite, h.get("instrument_token")) for h in active]
    nifty_candles, *stock_candles = await asyncio.gather(nifty_task, *stock_tasks)

    nifty_tech = _technicals(nifty_candles)
    nifty_30d = nifty_tech.get("ret_30d")
    nifty_90d = nifty_tech.get("ret_90d")

    # Fundamentals per symbol (cached in DB, refreshed when stale).
    fund_by_symbol: dict = {}
    for h in active:
        sym = h.get("tradingsymbol", "").upper()
        try:
            fund_by_symbol[sym] = await get_fundamentals(
                sym, db, exchange=h.get("exchange", "NSE"), user_id=user.id,
            )
        except Exception as e:
            logger.warning(f"fundamentals fetch failed for {sym}: {e}")
            fund_by_symbol[sym] = None

    # Pull the NSE ASM/GSM surveillance map once (24h cached) so each
    # row can append `RegFlag: <flag>` inline. Empty dict on fetch
    # failure → every row gets RegFlag: CLEAR, which is the safe degrade.
    try:
        reg_flags_map = await get_surveillance_flags()
    except Exception as e:
        logger.warning("ASM/GSM fetch failed for portfolio: %s", e)
        reg_flags_map = {}

    portfolio_lines = []
    for h, candles in zip(active, stock_candles):
        qty = h.get("quantity", 0)
        avg = h.get("average_price", 0)
        ltp = h.get("last_price", 0)
        invested = avg * qty
        current = ltp * qty
        pnl = current - invested
        pnl_pct = (pnl / invested * 100) if invested else 0

        tech = _technicals(candles)
        rs_30d = None
        if tech.get("ret_30d") is not None and nifty_30d is not None:
            rs_30d = tech["ret_30d"] - nifty_30d

        fund = fund_by_symbol.get(h.get("tradingsymbol", "").upper())
        sector = fund.sector if fund else None
        pe = float(fund.ttm_pe) if fund and fund.ttm_pe is not None else None
        pb = float(fund.pb_ratio) if fund and fund.pb_ratio is not None else None
        rev_gr = float(fund.revenue_growth_1y) * 100 if fund and fund.revenue_growth_1y is not None else None
        eps_gr = float(fund.eps_growth_1y) * 100 if fund and fund.eps_growth_1y is not None else None
        roe = float(fund.roe) * 100 if fund and fund.roe is not None else None
        de = float(fund.debt_to_equity) if fund and fund.debt_to_equity is not None else None

        reg_flag = get_reg_flag(h.get("tradingsymbol", ""), reg_flags_map)
        portfolio_lines.append(
            f"- {h['tradingsymbol']} ({h.get('exchange','NSE')}): "
            f"Qty={qty}, Avg={avg:.2f}, LTP={ltp:.2f}, "
            f"P&L={pnl:.0f} ({pnl_pct:+.1f}%), DayChg={h.get('day_change_percentage', 0):+.1f}% | "
            f"50DMA={_fmt(tech.get('dma50'))}, 200DMA={_fmt(tech.get('dma200'))}, "
            f"52WH={_fmt(tech.get('high_52w'))} (FromHigh={_fmt(tech.get('pct_from_52wh'), pct=True)}), "
            f"52WL={_fmt(tech.get('low_52w'))}, "
            f"30d={_fmt(tech.get('ret_30d'), pct=True)}, 90d={_fmt(tech.get('ret_90d'), pct=True)}, "
            f"RS30d={_fmt(rs_30d, pct=True)} | "
            f"PE={_fmt(pe)}, PB={_fmt(pb)}, RevGr={_fmt(rev_gr, pct=True)}, "
            f"EPSGr={_fmt(eps_gr, pct=True)}, ROE={_fmt(roe, pct=True)}, DE={_fmt(de)}, "
            f"Sector={sector or '--'} | RegFlag: {reg_flag}"
        )

    portfolio_data = "\n".join(portfolio_lines)
    market_context = (
        f"Nifty 50 — 30d return: {_fmt(nifty_30d, pct=True)}, "
        f"90d return: {_fmt(nifty_90d, pct=True)}, "
        f"current: {_fmt(nifty_tech.get('latest'))}, "
        f"50-DMA: {_fmt(nifty_tech.get('dma50'))}, "
        f"200-DMA: {_fmt(nifty_tech.get('dma200'))}"
    )

    settings = get_settings()
    today_ist = datetime.now(tz=ZoneInfo("Asia/Kolkata")).strftime("%d %B %Y")
    prompt = SELL_STRATEGY_PROMPT.format(
        today_ist=today_ist,
        portfolio_data=portfolio_data,
        market_context=market_context,
        stcg_rate=settings.INDIA_STCG_RATE,
        ltcg_rate=settings.INDIA_LTCG_RATE,
        ltcg_exemption_inr=settings.INDIA_LTCG_EXEMPTION_INR,
        macro_context=INDIAN_MACRO_CONTEXT,
        decimal_rule=DECIMAL_OUTPUT_RULE,
        json_boundary=STRICT_JSON_BOUNDARY,
    )

    try:
        raw_response = await call_gemini_with_rotation(user.id, db, prompt)
    except (NoCredentialsConfiguredError, AllCredentialsExhaustedError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI API error: {e}")

    try:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        analysis = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        return {
            "status": "partial",
            "message": "AI returned non-JSON response. Showing raw.",
            "raw_response": raw_response[:5000],
            "holdings_count": len(portfolio_lines),
        }

    analysis["meta"] = {
        "model_used": "credential-default",
        "holdings_analyzed": len(portfolio_lines),
    }

    # Save analysis to history
    summary = analysis.get("portfolio_summary", {})
    # Prompt #8 was reworked from HOLD/SELL/WATCHFUL to HOLD/TRIM/SELL.
    # Existing PortfolioAnalysis.watchful_count column is reused for TRIM
    # to avoid a schema migration; the model also falls back to the old
    # watchful_count field for any responses still using the prior shape.
    record = PortfolioAnalysis(
        user_id=user.id,
        model_used="credential-default",
        holdings_count=len(portfolio_lines),
        sell_count=summary.get("sell_count", 0),
        hold_count=summary.get("hold_count", 0),
        watchful_count=summary.get("trim_count", summary.get("watchful_count", 0)),
        overall_health=summary.get("overall_health"),
        result_json=analysis,
        raw_prompt_data=f"{market_context}\n\n{portfolio_data}",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    analysis["meta"]["id"] = record.id
    analysis["meta"]["created_at"] = record.created_at.isoformat() if record.created_at else None

    return analysis


@router.get("/history")
async def list_analysis_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> list[dict]:
    result = await db.execute(
        select(PortfolioAnalysis)
        .where(PortfolioAnalysis.user_id == user.id)
        .order_by(desc(PortfolioAnalysis.created_at))
        .limit(limit)
    )
    analyses = result.scalars().all()
    return [
        {
            "id": a.id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "model_used": a.model_used,
            "holdings_count": a.holdings_count,
            "sell_count": a.sell_count,
            "hold_count": a.hold_count,
            "watchful_count": a.watchful_count,
            "overall_health": a.overall_health,
            "top_actions": a.result_json.get("top_actions", [])[:2] if a.result_json else [],
        }
        for a in analyses
    ]


@router.get("/history/{analysis_id}")
async def get_analysis_detail(
    analysis_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(PortfolioAnalysis).where(
            PortfolioAnalysis.id == analysis_id,
            PortfolioAnalysis.user_id == user.id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")

    data = dict(record.result_json)
    data.setdefault("meta", {})
    data["meta"]["id"] = record.id
    data["meta"]["created_at"] = record.created_at.isoformat() if record.created_at else None
    data["meta"]["model_used"] = record.model_used
    data["meta"]["holdings_analyzed"] = record.holdings_count
    return data


@router.delete("/history/{analysis_id}")
async def delete_analysis(
    analysis_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(PortfolioAnalysis).where(
            PortfolioAnalysis.id == analysis_id,
            PortfolioAnalysis.user_id == user.id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    await db.delete(record)
    await db.commit()
    return {"status": "deleted", "id": analysis_id}


@router.post("/run-all-holdings")
async def run_all_holdings_analysis(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run investment evaluation on ALL holdings. Saves each to investment_decisions."""
    from app.services.investment_decision import evaluate_stock_for_investment
    from app.models.investment_decision import InvestmentDecision
    from app.services.portfolio_cache import get_holdings as cached_holdings

    if not user.kite_api_key or not user.kite_access_token:
        raise HTTPException(status_code=400, detail="Kite not connected")

    try:
        holdings = await cached_holdings(user)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite API error: {e}")

    active = active_holdings(holdings)
    if not active:
        raise HTTPException(status_code=400, detail="No active holdings found")

    results = []
    failed = []

    for h in active:
        symbol = h.get("tradingsymbol", "").upper()
        exchange = h.get("exchange", "NSE")
        if not symbol:
            continue

        try:
            evaluation = await evaluate_stock_for_investment(symbol, exchange, user, db)

            record = InvestmentDecision(
                user_id=user.id,
                symbol=symbol,
                exchange=exchange,
                verdict=evaluation.get("verdict"),
                confidence=evaluation.get("confidence"),
                model_used=evaluation.get("model_used", ""),
                strategies_passed=evaluation.get("strategies_passed", 0),
                strategies_total=evaluation.get("strategies_total", 0),
                result_json=evaluation,
            )
            db.add(record)
            await db.commit()

            results.append({
                "symbol": symbol,
                "verdict": evaluation.get("verdict"),
                "confidence": evaluation.get("confidence"),
            })
        except Exception as e:
            failed.append({"symbol": symbol, "error": str(e)[:200]})

    return {
        "evaluated": len(results),
        "failed": len(failed),
        "total": len(active),
        "results": results,
        "failures": failed,
    }
