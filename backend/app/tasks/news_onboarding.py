"""Celery task to onboard a stock that was just tagged by the news scan.

Closes the gap where the News Scan watchlist auto-populated with
symbols but those symbols had no fundamentals, no peers, and no
relative valuation. The watchlist was an inbox, not an idea funnel.

Onboarding pipeline (per symbol):
  1. Fetch fundamentals (Screener + yfinance + Google Finance + Gemini
     gap-fill via the existing service).
  2. Auto-generate peers via Gemini (one-time cost).
  3. Run refresh_stock_analysis to compute valuation / peer / news
     verdicts + summary line.
  4. Compute relative valuation rank (P/E percentile vs peers) and
     persist it on the WatchlistItem.notes field so it shows in the UI.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(
    name="app.tasks.news_onboarding.onboard_news_stock",
    queue="analysis",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=1,
    default_retry_delay=120,
)
def onboard_news_stock(self, symbol: str, user_id: int) -> dict:
    logger.info(f"=== Onboarding news-tagged stock {symbol} for user {user_id} ===")
    try:
        return asyncio.run(_onboard(symbol.upper().strip(), user_id))
    except Exception as e:
        logger.error(f"Onboarding failed for {symbol}: {e}", exc_info=True)
        return {"symbol": symbol, "error": str(e)}


async def _onboard(symbol: str, user_id: int) -> dict:
    from app.models.user import User
    from app.models.fundamentals import StockFundamentals
    from app.models.stock_peers import StockPeer
    from app.models.watchlist import WatchlistItem
    from app.services.fundamentals_service import get_fundamentals
    from app.services.peer_discovery import ensure_peers
    from app.services.stock_card import refresh_stock_analysis

    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SM = async_sessionmaker(engine, expire_on_commit=False)
    summary: dict = {"symbol": symbol, "steps": []}

    try:
        # ── Step 1: Fundamentals ─────────────────────────────────────
        async with SM() as db:
            user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if not user:
                return {"symbol": symbol, "error": f"user_id={user_id} not found"}
            try:
                fund = await get_fundamentals(symbol, db, force_refresh=False, user_id=user_id)
                summary["steps"].append("fundamentals_ok" if fund else "fundamentals_empty")
                if fund is None or not (fund.industry or fund.sector):
                    summary["status"] = "skipped_no_industry"
                    return summary
            except Exception as e:
                summary["steps"].append(f"fundamentals_fail:{e!s}")
                summary["status"] = "failed"
                return summary

        # ── Step 2: Peers ───────────────────────────────────────────
        async with SM() as db:
            try:
                ok = await ensure_peers(symbol, db, user_id)
                summary["steps"].append("peers_ok" if ok else "peers_skip")
            except Exception as e:
                summary["steps"].append(f"peers_fail:{e!s}")

        # ── Step 3: Stock card analysis ──────────────────────────────
        async with SM() as db:
            try:
                await refresh_stock_analysis(symbol, db, user_id)
                summary["steps"].append("analysis_ok")
            except Exception as e:
                summary["steps"].append(f"analysis_fail:{e!s}")

        # ── Step 4: Relative valuation rank (% PE vs peer median) ────
        async with SM() as db:
            try:
                peer_rows = (await db.execute(
                    select(StockPeer.peer_symbol).where(StockPeer.symbol == symbol)
                )).scalars().all()
                if peer_rows:
                    fund_q = await db.execute(
                        select(StockFundamentals).where(
                            StockFundamentals.symbol.in_([*peer_rows, symbol])
                        )
                    )
                    funds = {f.symbol: f for f in fund_q.scalars().all()}
                    self_pe = float(funds[symbol].pe_ratio) if symbol in funds and funds[symbol].pe_ratio else None
                    peer_pes = [
                        float(funds[ps].pe_ratio) for ps in peer_rows
                        if ps in funds and funds[ps].pe_ratio is not None and float(funds[ps].pe_ratio) > 0
                    ]
                    if self_pe and peer_pes:
                        from statistics import median
                        med = median(peer_pes)
                        if med > 0:
                            pct = round((self_pe / med - 1.0) * 100.0, 1)
                            tag = "premium" if pct > 15 else "discount" if pct < -15 else "fair"
                            note_line = f"vs peers: PE {self_pe:.1f} ({pct:+.0f}% {tag})"
                            wl_items = (await db.execute(
                                select(WatchlistItem).where(WatchlistItem.symbol == symbol)
                            )).scalars().all()
                            for it in wl_items:
                                existing = (it.notes or "").strip()
                                # Prepend our line; preserve user notes.
                                if note_line not in existing:
                                    it.notes = f"{note_line}\n{existing}" if existing else note_line
                            await db.commit()
                            summary["valuation_note"] = note_line
                            summary["steps"].append("valuation_ok")
            except Exception as e:
                summary["steps"].append(f"valuation_fail:{e!s}")

        summary["status"] = "ok"
        return summary
    finally:
        await engine.dispose()
