"""Decides whether to re-run the AI investment evaluation for a symbol.

Reasoning model:
- AI verdicts shouldn't flip every day on stable positions. Re-running the
  same prompt against barely-changed inputs produces verdict noise, not
  signal.
- A re-evaluation should be triggered by an information change: a fresh
  material news swing, a corp action, a smart-money flip, or a long-enough
  quiet period (safety fallback).

Used by the morning pipeline's AI-evaluation step. Per-stock manual refresh
endpoints bypass this gate — explicit user intent always wins.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Safety net — re-eval anyway if it's been longer than this.
# Tightened from 7 → 3 so active holdings without trigger-firing events
# (no news swing, no corp ann, no smart-money update) still get a
# refreshed verdict within a few days. At 26 holdings the extra Gemini
# Flash spend is sub-rupee per day.
FALLBACK_DAYS = 3
# News sentiment swing magnitude that triggers re-eval.
SENTIMENT_SWING_THRESHOLD = 20.0
# Smart-money score delta that triggers re-eval.
SMART_MONEY_DELTA_THRESHOLD = 15.0
# Corp announcement types that warrant re-eval.
MATERIAL_ANN_TYPES = ("Results", "Buy-back", "Dividend", "Pledge", "Bonus", "Split")


async def should_reevaluate(
    symbol: str, db: AsyncSession, user_id: int,
) -> tuple[bool, str]:
    """Returns (True, reason) if any trigger fires; (False, reason) otherwise.

    Reasons are short tags suitable for log lines.
    """
    from app.models.investment_decision import InvestmentDecision
    from app.models.news_sentiment import NewsSentimentCache

    symbol = symbol.upper().strip()

    # ── Last eval info ─────────────────────────────────────────────────
    last_eval = (await db.execute(
        select(InvestmentDecision)
        .where(InvestmentDecision.user_id == user_id)
        .where(InvestmentDecision.symbol == symbol)
        .order_by(desc(InvestmentDecision.created_at))
        .limit(1)
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if last_eval is None or last_eval.created_at is None:
        return True, "no_prior_eval"

    age = now - last_eval.created_at
    if age >= timedelta(days=FALLBACK_DAYS):
        return True, f"fallback_{age.days}d"

    last_eval_at = last_eval.created_at

    # ── Trigger: news sentiment swing >20 points since last eval ───────
    try:
        sentiment_rows = (await db.execute(
            select(NewsSentimentCache.score, NewsSentimentCache.analyzed_at)
            .where(NewsSentimentCache.symbol == symbol)
            .order_by(desc(NewsSentimentCache.analyzed_at))
            .limit(2)
        )).all()
        if len(sentiment_rows) >= 2:
            (cur_score, cur_ts), (prev_score, _) = sentiment_rows[0], sentiment_rows[1]
            if (
                cur_ts is not None
                and cur_ts > last_eval_at
                and cur_score is not None
                and prev_score is not None
                and abs(float(cur_score) - float(prev_score)) >= SENTIMENT_SWING_THRESHOLD
            ):
                return True, f"sentiment_swing_{abs(float(cur_score) - float(prev_score)):.0f}"
    except Exception as e:
        logger.debug("sentiment trigger check failed for %s: %s", symbol, e)

    # ── Trigger: new material corp announcement since last eval ────────
    try:
        from sqlalchemy import text
        ann_rows = (await db.execute(
            text(
                "SELECT announcement_type FROM corporate_announcements "
                "WHERE symbol = :sym "
                "  AND announcement_type = ANY(:types) "
                "  AND created_at > :since "
                "LIMIT 1"
            ),
            {"sym": symbol, "types": list(MATERIAL_ANN_TYPES), "since": last_eval_at},
        )).all()
        if ann_rows:
            return True, f"corp_ann_{ann_rows[0][0]}"
    except Exception as e:
        logger.debug("corp-ann trigger check failed for %s: %s", symbol, e)

    # ── Trigger: smart-money signal updated with material delta ────────
    try:
        from sqlalchemy import text
        sm_rows = (await db.execute(
            text(
                "SELECT conviction_score, red_flag_score, updated_at "
                "FROM smart_money_signals "
                "WHERE symbol = :sym AND window_days = 30 "
                "  AND updated_at > :since "
                "ORDER BY as_of DESC LIMIT 2"
            ),
            {"sym": symbol, "since": last_eval_at},
        )).all()
        if sm_rows:
            # Even a fresh row counts as a trigger when the signal was
            # absent before. Strict delta comparison is hard with only one
            # row, so any post-last-eval update is treated as material.
            return True, "smart_money_updated"
    except Exception as e:
        logger.debug("smart-money trigger check failed for %s: %s", symbol, e)

    return False, "no_change"
