"""Sector-level news sentiment analysis.

Runs once per sector during the morning pipeline. All stocks in the
same sector read from the cached SectorAnalysis row.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gemini_client import call_gemini_with_rotation
from app.models.sector_analysis import SectorAnalysis
from app.services.news_sentiment import fetch_google_news

logger = logging.getLogger(__name__)

# Top-3 NSE bellwethers per sector. Keys MUST match the canonical sector
# strings the dashboard uses (`SectorAnalysis.sector`). Anchoring the
# model on concrete listed names ("for IT: TCS, INFY, HCLTECH") yields
# crisper sector summaries than abstract "leading IT companies" phrasing.
# Sectors not in this map degrade gracefully — `{bellwethers}` becomes
# "(none specified)" and the prompt still works.
SECTOR_BELLWETHERS: dict[str, list[str]] = {
    # Indian-market vernacular keys
    "Information Technology": ["TCS", "INFY", "HCLTECH"],
    "IT": ["TCS", "INFY", "HCLTECH"],
    "Banking": ["HDFCBANK", "ICICIBANK", "SBIN"],
    "Financial Services": ["HDFCBANK", "ICICIBANK", "BAJFINANCE"],
    "NBFC": ["BAJFINANCE", "CHOLAFIN", "SHRIRAMFIN"],
    "Auto": ["MARUTI", "M&M", "TATAMOTORS"],
    "Automobile": ["MARUTI", "M&M", "TATAMOTORS"],
    "Pharma": ["SUNPHARMA", "DRREDDY", "CIPLA"],
    "Pharmaceuticals": ["SUNPHARMA", "DRREDDY", "CIPLA"],
    "Healthcare": ["SUNPHARMA", "APOLLOHOSP", "DRREDDY"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND"],
    "Consumer Goods": ["HINDUNILVR", "ITC", "NESTLEIND"],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
    "Metal": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
    "Energy": ["RELIANCE", "ONGC", "IOC"],
    "Oil & Gas": ["RELIANCE", "ONGC", "IOC"],
    "Power": ["NTPC", "POWERGRID", "TATAPOWER"],
    "Utilities": ["NTPC", "POWERGRID", "ADANIPOWER"],
    "Telecom": ["BHARTIARTL", "RELIANCE", "IDEA"],
    "Realty": ["DLF", "GODREJPROP", "OBEROIRLTY"],
    "Real Estate": ["DLF", "GODREJPROP", "OBEROIRLTY"],
    "Cement": ["ULTRACEMCO", "GRASIM", "AMBUJACEM"],
    "Capital Goods": ["LT", "SIEMENS", "ABB"],
    "Infrastructure": ["LT", "ADANIPORTS", "GMRINFRA"],
    "Consumer Durables": ["TITAN", "HAVELLS", "VOLTAS"],
    "Chemicals": ["PIDILITIND", "SRF", "UPL"],
    "Media": ["ZEEL", "SUNTV", "PVRINOX"],
    "Insurance": ["SBILIFE", "HDFCLIFE", "ICICIPRULI"],
    # GICS-style aliases — yfinance/Screener.in canonical names that
    # `sector_resolver.resolve_sectors_bulk` returns for many Indian
    # holdings. Without these the model loses its bellwether anchor.
    "Technology": ["TCS", "INFY", "HCLTECH"],
    "Communication Services": ["BHARTIARTL", "RELIANCE", "ZEEL"],
    "Consumer Cyclical": ["MARUTI", "TITAN", "ZOMATO"],
    "Consumer Defensive": ["HINDUNILVR", "ITC", "NESTLEIND"],
    "Basic Materials": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
    "Industrials": ["LT", "ADANIPORTS", "GMRINFRA"],
}


def _bellwether_hint(sector: str) -> str:
    names = SECTOR_BELLWETHERS.get(sector) or SECTOR_BELLWETHERS.get(sector.title())
    return ", ".join(names) if names else "(none specified)"


SECTOR_SENTIMENT_PROMPT = """SYSTEM: You are a macro-sector analyst for Dalal Street on {today_ist}.
INPUT: Nifty Sector: {sector}. Bellwether stocks: {top_stocks_in_sector}. Headlines: {headlines}.
TASK: Determine the prevailing 7-day sentiment for this sectoral index.
RULES:
1. [BELLWETHER FOCUS] Prioritize news affecting {top_stocks_in_sector}, as their market cap dictates the index direction.
2. [MACRO & DIVERGENCE] Consider Indian macroeconomic factors (RBI MPC, FII/DII flows, capex, PLI schemes, INR/USD). IMPORTANT: When fundamentals are strong but stock reactions are weak (e.g., "good earnings but stock falls"), tilt the score negative — it indicates the market priced in higher expectations.
3. [STRICT ANCHORS] Score from -100 to +100 based on these exact anchors:
   * +80 to +100: Massive structural tailwinds (e.g., major PLI scheme, massive FII inflow).
   * +30 to +60: Positive earnings cycle for bellwethers, steady macro tailwinds.
   * -10 to +10: Routine noise, mixed signals.
   * -30 to -60: Cyclical downturns, bellwether earnings misses, margin pressures.
   * -80 to -100: Structural headwinds (e.g., severe regulatory crackdown, windfall taxes, demand collapse).
4. [CONFIDENCE SCORING] Set confidence to "HIGH" if there are >=5 high-impact headlines on bellwether stocks. Set to "LOW" if there are <3 sector-specific headlines. Otherwise, "MEDIUM".
5. [TRACEABILITY] Every item in `key_themes` MUST be directly traceable to at least one provided headline.
6. [SUMMARY FORMAT] The summary must be exactly 5 sentences. You must open with the single most important driver.

OUTPUT FORMAT:
Start your response with "{{" and end with "}}". Do not output markdown fences.
{{
  "sentiment": "bullish" | "bearish" | "neutral",
  "score": <int>,
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "macro_drivers": [
    {{
      "factor": "e.g., RBI MPC, FII Flows, or Commodity Prices",
      "tilt": "+" | "-" | "0",
      "rationale": "1 sentence explanation"
    }}
  ],
  "key_themes": ["..."],
  "summary": "Exactly 5 sentences. Open with the single most important driver.",
  "what_to_watch": [
    "Specific upcoming event or data print 1",
    "Specific upcoming event or data print 2"
  ]
}}
"""


async def refresh_sector_analysis(
    sector: str,
    db: AsyncSession,
    user_id: int,
) -> SectorAnalysis | None:
    if not sector:
        return None

    query = f'"{sector}" India stock market sector'
    try:
        headlines = await fetch_google_news(sector, sector, days=7)
    except Exception as e:
        logger.warning(f"Sector news fetch failed for {sector}: {e}")
        headlines = []

    if not headlines:
        logger.info(f"No headlines found for sector '{sector}'")
        return None

    formatted = "\n".join(
        f"- {h.get('title', '')}" for h in headlines[:20]
    )

    today_ist = datetime.now(tz=ZoneInfo("Asia/Kolkata")).strftime("%d %B %Y")

    try:
        prompt = SECTOR_SENTIMENT_PROMPT.format(
            today_ist=today_ist,
            sector=sector,
            top_stocks_in_sector=_bellwether_hint(sector),
            headlines=formatted,
        )
        raw = await call_gemini_with_rotation(user_id, db, prompt)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(cleaned)
    except Exception as e:
        logger.warning(f"Sector sentiment analysis failed for {sector}: {e}")
        return None

    # Legacy fields — kept so the dashboard's per-holding sector_mood
    # chip (today.py:_compute_brief) keeps working with no change.
    mood = (result.get("sentiment") or "neutral").upper()
    if mood not in ("BULLISH", "BEARISH", "NEUTRAL"):
        mood = "NEUTRAL"
    signals = (result.get("key_themes") or [])[:3]

    # Richer columns (v3 Market Brief — Sectors). Score is clamped into
    # the prompt's stated -100..+100 range so a model glitch can't blow
    # up downstream sort/rendering. Confidence falls back to MEDIUM —
    # the prompt has its own rule for setting it from headline counts.
    raw_score = result.get("score")
    try:
        score = int(raw_score) if raw_score is not None else None
        if score is not None:
            score = max(-100, min(100, score))
    except (TypeError, ValueError):
        score = None

    confidence_raw = (result.get("confidence") or "MEDIUM").upper()
    confidence = confidence_raw if confidence_raw in {"HIGH", "MEDIUM", "LOW"} else "MEDIUM"

    summary = result.get("summary") or None
    macro_drivers = result.get("macro_drivers") if isinstance(result.get("macro_drivers"), list) else None
    what_to_watch = result.get("what_to_watch") if isinstance(result.get("what_to_watch"), list) else None

    # Persist the top headlines that fed the prompt so the deep-dive
    # sheet has the receipts. Cap at 8 to keep the row small.
    top_headlines = [
        {
            "title": h.get("title"),
            "source": h.get("source"),
            "url": h.get("url"),
            "date": h.get("date"),
        }
        for h in headlines[:8]
    ]

    now = datetime.now(timezone.utc)
    values = dict(
        sector=sector,
        mood=mood,
        signals=signals,
        headline_count=len(headlines),
        last_run_at=now,
        score=score,
        confidence=confidence,
        summary=summary,
        macro_drivers=macro_drivers,
        what_to_watch=what_to_watch,
        top_headlines=top_headlines,
    )

    stmt = pg_insert(SectorAnalysis).values(**values).on_conflict_do_update(
        index_elements=["sector"],
        set_={k: v for k, v in values.items() if k != "sector"},
    )
    await db.execute(stmt)
    await db.commit()

    row = (await db.execute(
        select(SectorAnalysis).where(SectorAnalysis.sector == sector)
    )).scalar_one_or_none()
    logger.info(
        f"Sector analysis for '{sector}': {mood} score={score} conf={confidence} "
        f"({len(headlines)} headlines)"
    )
    return row
