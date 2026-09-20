"""Weekly stock-card refresh for every watchlist symbol.

The post-close morning pipeline runs `refresh_stock_analysis` only for
*portfolio holdings* (cost guardrail — running it for ~150 watchlist
symbols every weekday would multiply the daily Gemini Flash spend
~7-10×). This means `stock_analyses` rows for watchlist-only symbols
go stale, and the new 3-section Price / Peers / News grid on
ResearchingCard renders without fresh data.

This task plugs that gap by refreshing every watchlist symbol once a
week — by default on Saturday morning IST (markets closed both Sat
and Sun, so the lull is ideal). Cost estimate: ~150 symbols × 2 Gemini
Flash calls per card analysis = ~300 calls/week ≈ $0.03/week.

Idempotent: a symbol whose `stock_analyses.last_completed_date` is
today is skipped, so a re-trigger within the same day is a no-op.

Wraps everything in an `ingestion_run` for audit + status tracking
(source = "watchlist_card_weekly").
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.stock_analysis import StockAnalysis
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()

# Max concurrent card analyses. Same as morning_pipeline (Semaphore(5));
# we're more conservative since this task runs alone without the rest
# of the pipeline competing for Gemini quota.
CARD_CONCURRENCY = 3


def _today_ist() -> date:
    return datetime.now(tz=ZoneInfo("Asia/Kolkata")).date()


@celery_app.task(
    name="app.tasks.watchlist_card_refresh.refresh_all_watchlist_cards",
    queue="analysis",
    bind=True,
)
def refresh_all_watchlist_cards(self) -> dict:
    """Weekly refresh of stock_analyses for every watchlist symbol."""
    logger.info("=== Weekly watchlist card refresh started ===")
    try:
        return asyncio.run(_run(celery_task_id=self.request.id))
    except Exception as e:
        logger.error(f"refresh_all_watchlist_cards failed: {e}", exc_info=True)
        return {"error": str(e)}


async def _run(celery_task_id: str | None = None) -> dict:
    from app.services.smart_money.run_logger import ingestion_run
    from app.services.stock_card import refresh_stock_analysis
    from app.observability.activity import ai_purpose

    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SM = async_sessionmaker(engine, expire_on_commit=False)

    today = _today_ist()
    ok = 0
    failed = 0
    skipped_fresh = 0
    errors: list[str] = []

    try:
        async with ingestion_run(
            source="watchlist_card_weekly",
            task_name="app.tasks.watchlist_card_refresh.refresh_all_watchlist_cards",
            celery_task_id=celery_task_id,
        ) as ctx:
            # Gather (user_id, symbol) pairs across all watchlists.
            async with SM() as db:
                users = (await db.execute(select(User))).scalars().all()
                user_by_id = {u.id: u for u in users}

                pairs: list[tuple[int, str]] = []
                for user in users:
                    wl_ids = [
                        wl.id for wl in
                        (await db.execute(select(Watchlist).where(Watchlist.user_id == user.id))).scalars().all()
                    ]
                    if not wl_ids:
                        continue
                    items = (await db.execute(
                        select(WatchlistItem).where(WatchlistItem.watchlist_id.in_(wl_ids))
                    )).scalars().all()
                    seen: set[str] = set()
                    for it in items:
                        sym = (it.symbol or "").upper()
                        if sym and sym not in seen:
                            seen.add(sym)
                            pairs.append((user.id, sym))

                # Freshness skip: drop pairs whose stock_analyses row is
                # already from today. One query covers all symbols.
                syms_unique = list({s for _, s in pairs})
                fresh_today: set[str] = set()
                if syms_unique:
                    fresh_q = await db.execute(
                        select(StockAnalysis.symbol)
                        .where(StockAnalysis.symbol.in_(syms_unique))
                        .where(StockAnalysis.last_completed_date == today)
                    )
                    fresh_today = {s for (s,) in fresh_q.all()}

            targets = [(uid, sym) for uid, sym in pairs if sym not in fresh_today]
            skipped_fresh = len(pairs) - len(targets)

            logger.info(
                f"watchlist_card_weekly: {len(pairs)} pairs total, "
                f"{skipped_fresh} fresh-today, refreshing {len(targets)}"
            )

            sem = asyncio.Semaphore(CARD_CONCURRENCY)

            async def _refresh_one(user_id: int, sym: str) -> None:
                nonlocal ok, failed
                user = user_by_id.get(user_id)
                if not user:
                    return
                async with sem:
                    try:
                        async with SM() as c_db, ai_purpose("card_analysis", symbol=sym, user_id=user_id):
                            await refresh_stock_analysis(sym, c_db, user_id)
                        ok += 1
                    except Exception as e:
                        failed += 1
                        msg = f"{sym}: {type(e).__name__}: {str(e)[:120]}"
                        errors.append(msg)
                        logger.warning(f"  Watchlist card failed for {sym}: {e}")

            await asyncio.gather(*[_refresh_one(uid, sym) for uid, sym in targets])

            ctx.fetched = len(pairs)
            ctx.inserted = ok
            ctx.skipped = skipped_fresh
            ctx.meta.update(failed=failed, errors=errors[:10])
            if failed > 0 and ok > 0:
                ctx.mark_partial(f"{failed} symbols failed of {len(targets)}")

            logger.info(
                f"=== Weekly watchlist card refresh complete: "
                f"ok={ok}, failed={failed}, skipped_fresh={skipped_fresh} ==="
            )

        return {
            "status": "ok",
            "total_pairs": len(pairs),
            "refreshed": ok,
            "failed": failed,
            "skipped_fresh": skipped_fresh,
        }
    finally:
        await engine.dispose()
