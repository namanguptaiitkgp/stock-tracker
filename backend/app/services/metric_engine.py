"""Metric refresh orchestration.

`run_refresh(scope, ...)` resolves the target symbols, calls each source
adapter in priority order, layers manual overrides on top, and writes
one wide-JSONB `metric_snapshots` row per stock. The `metric_runs` audit
row is updated with status + counts at the end.

Sources (merge order — first writer wins per key):
  1. Screener.in (HTML scrape, cached 24h)
  2. yfinance (.info + DataFrames)
  3. Google Finance (public page scrape, 60s cache)
  4. Kite historical (computed returns)
  5. NSE ownership (DB read from ShareholdingPattern)
  6. Gemini AI gap-fill (web-search grounded, last resort)
  7. Manual overrides (always win)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric import MetricRun, MetricSnapshot
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem
from app.services.fundamentals_validation import clamp_fundamentals
from app.services.metric_sources import (
    gemini_source,
    google_finance_source,
    kite_returns_source,
    manual_source,
    nse_ownership_source,
    screener_source,
    yfinance_source,
)

logger = logging.getLogger(__name__)


Scope = Literal["stock", "watchlist", "portfolio"]


async def _resolve_targets(
    db: AsyncSession, user: User, scope: Scope, target_symbol: str | None, target_id: int | None,
) -> list[tuple[str, str]]:
    """Return list of (symbol, exchange) for the run."""
    if scope == "stock":
        if not target_symbol:
            return []
        return [(target_symbol.upper(), "NSE")]

    if scope == "watchlist":
        if not target_id:
            return []
        res = await db.execute(
            select(WatchlistItem.symbol, WatchlistItem.exchange)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_id == user.id, WatchlistItem.watchlist_id == target_id)
        )
        return [(s.upper(), e or "NSE") for (s, e) in res.all() if s]

    if scope == "portfolio":
        # Portfolio scope = all unique symbols across the user's watchlists
        # plus the user's Kite holdings (when connected).
        res = await db.execute(
            select(WatchlistItem.symbol, WatchlistItem.exchange)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_id == user.id)
        )
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for sym, exch in res.all():
            if not sym:
                continue
            sym_u = sym.upper()
            if sym_u in seen:
                continue
            seen.add(sym_u)
            out.append((sym_u, exch or "NSE"))
        # Holdings symbols layered on top
        if user.kite_api_key and user.kite_access_token:
            try:
                from app.services.portfolio_cache import get_holdings as cached_holdings
                hs = await cached_holdings(user)
                for h in hs:
                    sym = (h.get("tradingsymbol") or "").upper()
                    if sym and sym not in seen:
                        seen.add(sym)
                        out.append((sym, h.get("exchange") or "NSE"))
            except Exception:
                logger.exception("portfolio metric refresh: holdings fetch failed")
        return out

    return []


async def _gather_one(
    db: AsyncSession, user: User, symbol: str, exchange: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Run all sources for a single symbol, return (values, sources)."""
    # External calls in parallel (no dependency between them)
    sc_task = screener_source.fetch(symbol, exchange)
    yf_task = yfinance_source.fetch(symbol, exchange)
    gf_task = google_finance_source.fetch(symbol, exchange)
    kite_task = kite_returns_source.fetch(symbol, exchange, user, db)
    sc_vals, yf_vals, gf_vals, kite_vals = await asyncio.gather(
        sc_task, yf_task, gf_task, kite_task, return_exceptions=True,
    )

    # DB read (no external call)
    ownership_vals = await nse_ownership_source.fetch(db, symbol)

    # Merge: screener → yfinance → google_finance → kite → ownership
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for v_dict, src in [
        (sc_vals, "screener"),
        (yf_vals, "yfinance"),
        (gf_vals, "google_finance"),
        (kite_vals, "kite"),
        (ownership_vals, "nse_ownership"),
    ]:
        if isinstance(v_dict, Exception):
            logger.debug("metric source %s failed for %s: %s", src, symbol, v_dict)
            continue
        for k, v in v_dict.items():
            if v is not None and k not in values:
                values[k] = v
                sources[k] = src

    # Gemini AI gap-fill (needs existing values to know what's missing)
    try:
        gemini_vals = await gemini_source.fetch(
            symbol, exchange, user.id, db, existing_values=values,
        )
        for k, v in gemini_vals.items():
            if v is not None and k not in values:
                values[k] = v
                sources[k] = "gemini"
    except Exception:
        logger.debug("gemini source failed for %s", symbol, exc_info=True)

    # Sanity-clamp external sources before manual overrides — see
    # fundamentals_validation.SANITY_BOUNDS. Manual overrides are
    # trusted and applied AFTER the clamp so an operator can deliberately
    # store an out-of-band value (rare).
    pre_clamp_keys = set(values)
    values = clamp_fundamentals(values, source=f"merged:{symbol}")
    # Drop the source attribution for keys the clamp set to None — keeps
    # sources_json honest about what's actually in values_json.
    for k in pre_clamp_keys:
        if values.get(k) is None:
            sources.pop(k, None)

    # Manual overrides always win
    overrides = await manual_source.fetch(db, user.id, symbol)
    for k, v in overrides.items():
        values[k] = v
        sources[k] = f"manual:{user.id}"

    return values, sources


async def run_refresh(
    db: AsyncSession,
    user: User,
    scope: Scope,
    target_symbol: str | None = None,
    target_id: int | None = None,
) -> MetricRun:
    """Create a MetricRun, fetch metrics for every target symbol, write
    a MetricSnapshot per stock. Updates run status and counts on finish.
    """
    started = datetime.now(timezone.utc)
    run = MetricRun(
        user_id=user.id,
        scope=scope,
        target_id=target_id,
        target_symbol=target_symbol.upper() if target_symbol else None,
        started_at=started,
        status="running",
    )
    db.add(run)
    await db.flush()
    run_id = run.id

    targets = await _resolve_targets(db, user, scope, target_symbol, target_id)
    run.stocks_total = len(targets)

    ok = failed = 0
    errors: list[str] = []

    for sym, exch in targets:
        try:
            values, sources = await _gather_one(db, user, sym, exch)
            if not values:
                # Nothing usable from any source — record an empty snapshot
                # so the audit row reflects the attempt, but mark the
                # symbol as failed in the count.
                snap = MetricSnapshot(
                    run_id=run_id,
                    symbol=sym,
                    exchange=exch,
                    fetched_at=datetime.now(timezone.utc),
                    values_json={},
                    sources_json={},
                )
                db.add(snap)
                failed += 1
                errors.append(f"{sym}: no source returned data")
                continue
            snap = MetricSnapshot(
                run_id=run_id,
                symbol=sym,
                exchange=exch,
                fetched_at=datetime.now(timezone.utc),
                values_json=values,
                sources_json=sources,
            )
            db.add(snap)
            ok += 1
        except Exception as e:
            logger.exception("metric refresh failed for %s", sym)
            failed += 1
            errors.append(f"{sym}: {type(e).__name__}: {str(e)[:80]}")

    run.stocks_ok = ok
    run.stocks_failed = failed
    run.finished_at = datetime.now(timezone.utc)
    run.status = "ok" if failed == 0 else ("partial" if ok > 0 else "failed")
    if errors:
        run.error_summary = "\n".join(errors[:20])

    await db.commit()
    await db.refresh(run)
    return run
