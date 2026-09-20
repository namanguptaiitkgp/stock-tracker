"""F&O universe browsing API.

Returns the complete NSE / BSE derivatives underlying list, enriched
with any existing per-symbol analysis (AI verdict, news sentiment,
cached fundamentals) so the frontend can render one unified table.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session as _async_session, get_db
from app.dependencies import get_current_user
from app.models.fundamentals import StockFundamentals
from app.models.investment_decision import InvestmentDecision
from app.models.news_sentiment import NewsSentimentCache
from app.models.stock import Stock
from app.models.user import User
from app.services.fundamentals_service import get_fundamentals
from app.services.market.fno_universe import get_fno_full

logger = logging.getLogger(__name__)

router = APIRouter()

EXCHANGE_MAP = {"NSE": "NFO", "BSE": "BFO"}


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@router.get("/stocks")
async def list_fno_stocks(
    exchange: str = Query(default="NSE", pattern="^(NSE|BSE)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    kite_exchange = EXCHANGE_MAP[exchange]
    underlyings = await get_fno_full(kite_exchange)

    if not underlyings:
        return {
            "exchange": exchange,
            "count": 0,
            "stocks": [],
            "warning": "F&O list unavailable — Kite not connected or instruments call failed",
        }

    symbols = [u["symbol"] for u in underlyings]

    # Map symbol -> human-readable name from the cash-equity stocks table
    stock_result = await db.execute(
        select(Stock.tradingsymbol, Stock.name)
        .where(Stock.exchange == exchange)
        .where(Stock.tradingsymbol.in_(symbols))
    )
    name_map = {s: n for s, n in stock_result.all() if n}

    # Latest investment decision per symbol for this user
    verdict_map: dict[str, InvestmentDecision] = {}
    vr = await db.execute(
        select(InvestmentDecision)
        .where(
            InvestmentDecision.user_id == user.id,
            InvestmentDecision.symbol.in_(symbols),
        )
        .order_by(InvestmentDecision.symbol, InvestmentDecision.created_at.desc())
    )
    for row in vr.scalars().all():
        if row.symbol not in verdict_map:
            verdict_map[row.symbol] = row

    # Latest news sentiment per symbol
    sent_map: dict[str, NewsSentimentCache] = {}
    sr = await db.execute(
        select(NewsSentimentCache)
        .where(NewsSentimentCache.symbol.in_(symbols))
        .order_by(NewsSentimentCache.symbol, NewsSentimentCache.analyzed_at.desc())
    )
    for row in sr.scalars().all():
        if row.symbol not in sent_map:
            sent_map[row.symbol] = row

    # Cached fundamentals
    fmap: dict[str, StockFundamentals] = {}
    fr = await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol.in_(symbols))
    )
    for row in fr.scalars().all():
        fmap[row.symbol] = row

    out = []
    for u in underlyings:
        sym = u["symbol"]
        v = verdict_map.get(sym)
        s = sent_map.get(sym)
        f = fmap.get(sym)
        lot_size = u.get("lot_size")
        cmp_val = _f(f.cmp) if f else None
        min_investment = None
        if lot_size and cmp_val:
            min_investment = round(lot_size * cmp_val, 2)
        out.append({
            "symbol": sym,
            "name": name_map.get(sym, u["display_name"]),
            "exchange": exchange,
            "lot_size": lot_size,
            "nearest_expiry": u.get("nearest_expiry"),
            "min_investment_inr": min_investment,
            "verdict": v.verdict if v else None,
            "verdict_confidence": v.confidence if v else None,
            "verdict_at": v.created_at.isoformat() if v and v.created_at else None,
            "news_sentiment": s.sentiment if s else None,
            "news_score": s.score if s else None,
            "news_at": s.analyzed_at.isoformat() if s and s.analyzed_at else None,
            "cmp": _f(f.cmp) if f else None,
            "market_cap": _f(f.market_cap) if f else None,
            "pe_ratio": _f(f.pe_ratio) if f else None,
            "ttm_pe": _f(f.ttm_pe) if f else None,
            "pb_ratio": _f(f.pb_ratio) if f else None,
            "revenue_growth_1y": _f(f.revenue_growth_1y) if f else None,
            "eps_growth_1y": _f(f.eps_growth_1y) if f else None,
            "net_profit_margin": _f(f.net_profit_margin) if f else None,
            "debt_to_equity": _f(f.debt_to_equity) if f else None,
            "dividend_yield": _f(f.dividend_yield) if f else None,
            "roe": _f(f.roe) if f else None,
        })

    return {
        "exchange": exchange,
        "count": len(out),
        "stocks": out,
    }


@router.post("/refresh-fundamentals")
async def refresh_fno_fundamentals(
    exchange: str = Query(default="NSE", pattern="^(NSE|BSE)$"),
    only_missing: bool = Query(default=True),
    concurrency: int = Query(default=8, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bulk-populate `stock_fundamentals` for every F&O underlying.
    yfinance / tickertape fetches are run with a concurrency cap so the
    whole universe takes ~30-60s instead of 218 sequential requests.
    By default skips symbols that already have a cached row (caller can
    pass only_missing=false to force-refresh every one)."""
    kite_exchange = EXCHANGE_MAP[exchange]
    underlyings = await get_fno_full(kite_exchange)
    if not underlyings:
        raise HTTPException(status_code=503, detail="F&O list unavailable — Kite not connected")

    symbols = [u["symbol"] for u in underlyings]

    existing_symbols: set[str] = set()
    if only_missing:
        existing = await db.execute(
            select(StockFundamentals.symbol).where(StockFundamentals.symbol.in_(symbols))
        )
        existing_symbols = {s for (s,) in existing.all()}

    todo = [s for s in symbols if s not in existing_symbols]

    sem = asyncio.Semaphore(concurrency)
    ok = 0
    failed = 0

    async def worker(sym: str) -> None:
        nonlocal ok, failed
        async with sem:
            # Each fetch needs its own session to avoid contention.
            async with _async_session() as session:
                try:
                    rec = await get_fundamentals(sym, session, exchange=exchange, user_id=user.id)
                    if rec:
                        ok += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.warning("fund fetch failed for %s: %s", sym, e)
                    failed += 1

    await asyncio.gather(*(worker(s) for s in todo))

    return {
        "exchange": exchange,
        "universe_size": len(symbols),
        "already_cached": len(existing_symbols),
        "attempted": len(todo),
        "ok": ok,
        "failed": failed,
    }
