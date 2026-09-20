"""Priority symbol cohort — what gets denser smart-money coverage.

The full NSE universe is ~3000 symbols and tail-distributed: most of
those stocks the user will never look at. The cohort that matters for
this single-user platform is much smaller — currently held positions,
watchlists, and recent research targets — typically 30-80 symbols.

This service returns that cohort. Used by:

  * Priority insider / deals backfills — wider lookback windows
    (90 days vs the universe-wide 7-day overlap) for these symbols.
  * Holdings signal compute — the universe over which we produce
    per-holding output.
  * Coverage diagnostic — informs whether a thin signal is "we don't
    track this aggressively" vs "this is a holding, we should."
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.investment_decision import InvestmentDecision
from app.models.watchlist import Watchlist, WatchlistItem


async def get_priority_universe(user_id: int, db: AsyncSession) -> set[str]:
    """Return the union of:
      - watchlist symbols (across all of the user's watchlists)
      - symbols evaluated via `investment_decisions` in the last 90 days

    Note: Kite holdings symbols are added by the caller via
    `portfolio_cache.get_holdings()` — that requires the user's Kite
    session to be live, which not every code path has. This function
    stays DB-only.
    """
    cutoff_dt = datetime.utcnow() - timedelta(days=90)

    wl_q = await db.execute(
        select(WatchlistItem.symbol)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.user_id == user_id)
    )
    syms: set[str] = {row[0] for row in wl_q.all()}

    dec_q = await db.execute(
        select(InvestmentDecision.symbol)
        .where(
            InvestmentDecision.user_id == user_id,
            InvestmentDecision.created_at >= cutoff_dt,
        )
    )
    syms.update(row[0] for row in dec_q.all())

    return syms


async def get_priority_universe_with_holdings(
    user_id: int, db: AsyncSession, holdings_symbols: list[str] | None = None
) -> set[str]:
    """Same as `get_priority_universe` but folds in caller-provided
    Kite holdings symbols. Use this from request handlers / tasks that
    already have a live Kite session.
    """
    syms = await get_priority_universe(user_id, db)
    if holdings_symbols:
        syms.update(s.upper().strip() for s in holdings_symbols if s)
    return syms
