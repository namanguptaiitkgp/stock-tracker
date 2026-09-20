import asyncio
import logging
from datetime import date

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.daily_analysis.run_daily_analysis")
def run_daily_analysis():
    """Celery task: run portfolio analysis on all holdings every morning."""
    logger.info("Starting daily portfolio analysis...")
    try:
        asyncio.run(_run_analysis())
    except Exception as e:
        logger.error(f"Daily analysis failed: {e}")


async def _run_analysis():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from kiteconnect import KiteConnect

    from app.config import get_settings
    from app.models.user import User
    from app.models.analysis import PortfolioAnalysis
    from app.services.investment_decision import evaluate_stock_for_investment

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as db:
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            logger.warning("No user found — skipping daily analysis")
            return

        if not user.kite_api_key or not user.kite_access_token:
            logger.warning("Kite not connected — skipping daily analysis")
            return

        # Fetch holdings from Kite
        kite = KiteConnect(api_key=user.kite_api_key)
        kite.set_access_token(user.kite_access_token)

        try:
            holdings = kite.holdings()
        except Exception as e:
            logger.error(f"Failed to fetch holdings: {e}")
            return

        from app.services.portfolio_cache import active_holdings
        active = active_holdings(holdings)
        if not active:
            logger.info("No active holdings — skipping")
            return

        logger.info(f"Running investment evaluation on {len(active)} holdings...")

        results = []
        failed = []

        for h in active:
            symbol = h.get("tradingsymbol", "").upper()
            exchange = h.get("exchange", "NSE")
            if not symbol:
                continue

            try:
                evaluation = await evaluate_stock_for_investment(
                    symbol=symbol,
                    exchange=exchange,
                    user=user,
                    db=db,
                )

                # Save to investment_decisions table
                from app.models.investment_decision import InvestmentDecision
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
                logger.info(f"  {symbol}: {evaluation.get('verdict')} ({evaluation.get('confidence')}%)")

            except Exception as e:
                logger.warning(f"  {symbol}: evaluation failed — {e}")
                failed.append({"symbol": symbol, "error": str(e)[:200]})

        logger.info(f"Daily analysis complete: {len(results)} evaluated, {len(failed)} failed")

    await engine.dispose()
