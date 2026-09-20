"""Kite historical data → return metrics.

Computes ret_1m, ret_1y, pct_from_52w_high from daily candles fetched
via portfolio_cache.get_historical_data. Returns empty dict gracefully
when Kite is not connected.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import Stock
from app.models.user import User

logger = logging.getLogger(__name__)


async def fetch(
    symbol: str, exchange: str, user: User, db: AsyncSession,
) -> dict[str, float | None]:
    if not user.kite_api_key or not user.kite_access_token:
        return {}

    # Look up instrument_token
    result = await db.execute(
        select(Stock.instrument_token).where(Stock.symbol == symbol.upper()).limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        return {}
    instrument_token = int(row)

    try:
        from app.services.portfolio_cache import get_historical_data

        today = date.today()
        from_date = today - timedelta(days=400)
        candles = await get_historical_data(
            user, instrument_token, from_date, today, "day",
        )
    except RuntimeError:
        return {}
    except Exception as e:
        logger.debug("Kite historical fetch failed for %s: %s", symbol, e)
        return {}

    if not candles or len(candles) < 2:
        return {}

    out: dict[str, float | None] = {}

    closes = [c["close"] for c in candles if c.get("close")]
    if not closes:
        return {}

    current = closes[-1]

    # 1-month return (~22 trading days)
    if len(closes) >= 22:
        month_ago = closes[-22]
        if month_ago > 0:
            out["ret_1m"] = (current - month_ago) / month_ago * 100.0

    # 1-year return (~252 trading days)
    if len(closes) >= 252:
        year_ago = closes[-252]
        if year_ago > 0:
            out["ret_1y"] = (current - year_ago) / year_ago * 100.0

    # % from 52-week high
    highs = [c["high"] for c in candles if c.get("high")]
    if highs:
        high_52w = max(highs[-252:]) if len(highs) >= 252 else max(highs)
        if high_52w > 0:
            out["pct_from_52w_high"] = (current - high_52w) / high_52w * 100.0

    return out
