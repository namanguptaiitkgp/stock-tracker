"""Celery task to warm up the peer set for a symbol.

Called from:
- Watchlist add endpoint (when user adds a stock)
- Kite portfolio sync (when a new holding appears)
- News onboarding (when a symbol surfaces as a "new opportunity")
- /api/market-data/peers/{symbol} (lazy trigger when stored peers < 2)

Idempotent — ensure_peers is a no-op when peers already exist, so duplicate
calls from multiple trigger surfaces are cheap. Also chains into
refresh_stock_analysis when new peers were generated, so the dashboard
verdict picks them up same-day rather than waiting for next morning_pipeline.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.user import User
from app.tasks.celery_app import celery_app

settings = get_settings()
logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.peer_warmup.warm_peers_for_symbol",
    queue="analysis",
    bind=True,
    # Retry only on genuinely transient network errors. The previous
    # `autoretry_for=(Exception,)` re-ran the task 3× even on data-quality
    # failures (e.g. yfinance returning out-of-range values that overflow
    # NUMERIC columns) — that triples the cascade blast radius without
    # any chance of success. Connection / timeout errors at the network
    # layer are the only legitimate transients here. Inner `_run` already
    # catches and returns an error dict for everything else.
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def warm_peers_for_symbol(
    self,
    symbol: str,
    user_id: int | None = None,
    *,
    chain_analysis: bool = True,
) -> dict:
    """Generate peers for a single symbol if missing, then optionally refresh
    its stock_analyses row so the dashboard verdict reflects the new peers.

    Args:
        symbol: NSE/BSE tradingsymbol (case-insensitive).
        user_id: For Gemini API key + InvestmentDecision attribution.
            Falls back to admin user if None.
        chain_analysis: If True and peers were just generated, also call
            refresh_stock_analysis so stock_analyses is up to date. Set to
            False from lazy-trigger paths to avoid the 30s extra latency
            on the user-blocking request.
    """
    symbol = symbol.upper().strip()
    logger.info(f"warm_peers_for_symbol: {symbol} (user_id={user_id})")

    async def _run() -> dict:
        from app.services.peer_discovery import ensure_peers, get_stored_peers

        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        SM = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with SM() as db:
                if user_id is None:
                    user = (await db.execute(
                        select(User).order_by(User.id.asc()).limit(1)
                    )).scalar_one_or_none()
                else:
                    user = (await db.execute(
                        select(User).where(User.id == user_id)
                    )).scalar_one_or_none()
                if not user:
                    return {"symbol": symbol, "error": "no user found"}

                before = await get_stored_peers(symbol, db)
                before_count = len(before)
                generated = await ensure_peers(symbol, db, user.id, min_peers=2)
                after = await get_stored_peers(symbol, db)
                after_count = len(after)
                await db.commit()

            # Chain into refresh_stock_analysis only when new peers were
            # generated AND the caller opted in. This is intentionally a
            # separate session to avoid the asyncio.gather + shared-session
            # race inside refresh_stock_analysis.
            chained = False
            if chain_analysis and generated and after_count > before_count:
                try:
                    from app.services.stock_card import refresh_stock_analysis
                    async with SM() as s_db:
                        await refresh_stock_analysis(symbol, s_db, user.id)
                    chained = True
                except Exception as e:
                    logger.warning(
                        f"warm_peers_for_symbol: chained refresh failed for "
                        f"{symbol}: {type(e).__name__}: {e}"
                    )

            return {
                "symbol": symbol,
                "peers_before": before_count,
                "peers_after": after_count,
                "generated": generated,
                "analysis_chained": chained,
            }
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as e:
        logger.error(
            f"warm_peers_for_symbol failed for {symbol}: {e}",
            exc_info=True,
        )
        return {"symbol": symbol, "error": str(e)}
