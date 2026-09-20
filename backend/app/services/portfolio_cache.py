"""Per-user Kite read fan-out, cached through `data_cache.fetch_cache`.

Centralizes the calls to `kite.holdings()`, `kite.quote()`, `kite.historical_data()`
that were scattered across 7 / 4 / 3 call sites. Every read goes through the unified
fetch-cache (DB-resident, survives restarts), so concurrent dashboard widgets / brief
computations / strategy runs hitting the same data within the TTL only fan-out a
single live Kite call.

TTL policy (matches CLAUDE.md "data fetched less than two hour ago is recent"):
- holdings:    2h
- quote:       60s   (intraday — must feel live)
- historical:  1h on intraday intervals, 24h on daily/weekly

Usage:
    holdings = await get_holdings(user)              # cache hit when warm
    holdings = await get_holdings(user, force=True)  # explicit refresh

All helpers accept a `User` and build a per-user KiteConnect client on the fly via
`_authed_kite()`. They raise `RuntimeError` if the user has not connected Kite —
callers (typically FastAPI handlers) should translate that to a 400/502.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from kiteconnect import KiteConnect

from app.models.user import User
from app.services.data_cache import cache_get, cache_get_or_fetch, cache_invalidate, cache_set

logger = logging.getLogger(__name__)


HOLDINGS_TTL_SECONDS = 2 * 60 * 60      # 2 hours
HOLDINGS_SNAPSHOT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days — stale fallback ceiling
QUOTE_TTL_SECONDS = 60                  # 1 minute (intraday)
HISTORICAL_INTRADAY_TTL_SECONDS = 60 * 60        # 1 hour
HISTORICAL_DAILY_TTL_SECONDS = 24 * 60 * 60      # 24 hours

INTRADAY_INTERVALS = {
    "minute", "3minute", "5minute", "10minute", "15minute", "30minute", "60minute",
}


def _authed_kite(user: User) -> KiteConnect:
    if not user.kite_api_key:
        raise RuntimeError("Kite API key not configured for this user.")
    if not user.kite_access_token:
        raise RuntimeError("Not connected to Kite. Login via Settings.")
    kite = KiteConnect(api_key=user.kite_api_key)
    kite.set_access_token(user.kite_access_token)
    return kite


# --------------------------------------------------------------------------- #
# holdings
# --------------------------------------------------------------------------- #

def _holdings_key(user_id: int) -> str:
    return f"kite_holdings:{user_id}"


def _holdings_snapshot_key(user_id: int) -> str:
    return f"kite_holdings_snapshot:{user_id}"


async def get_holdings(user: User, *, force: bool = False) -> list[dict]:
    """Return the user's Kite holdings, served from `fetch_cache` when fresh.

    On successful fetch, a long-lived snapshot (7 days) is written alongside
    the normal 2-hour cache entry.  When the live fetch fails (Kite token
    expired, API down), the snapshot is returned so downstream consumers
    like the morning pipeline can continue with stale-but-usable data.
    """

    async def _fetch() -> list[dict]:
        kite = _authed_kite(user)
        return await asyncio.to_thread(kite.holdings)

    try:
        payload, _ = await cache_get_or_fetch(
            _holdings_key(user.id),
            _fetch,
            ttl_seconds=HOLDINGS_TTL_SECONDS,
            force=force,
        )
        if payload:
            # On a forced fetch (morning pipeline / explicit refresh), detect
            # any holdings whose symbol has never been peer-discovered and
            # fire the warmup task asynchronously. Idempotent — warm_peers
            # is a no-op when peers already exist. Gated to forced fetches
            # to avoid firing on every minute-frequency dashboard poll.
            if force:
                try:
                    await _warm_new_holding_peers(user, payload)
                except Exception as e:  # pragma: no cover — best-effort
                    logger.warning(f"holdings peer-warmup dispatch failed: {e}")

            await cache_set(
                _holdings_snapshot_key(user.id),
                payload,
                ttl_seconds=HOLDINGS_SNAPSHOT_TTL_SECONDS,
            )
        return payload or []
    except Exception as exc:
        snapshot = await cache_get(_holdings_snapshot_key(user.id))
        if snapshot is not None:
            payload, fetched_at = snapshot
            logger.warning(
                "Using holdings snapshot from %s (live fetch failed: %s)",
                fetched_at.isoformat(),
                exc,
            )
            return payload or []
        raise


async def _warm_new_holding_peers(user: User, payload: list[dict]) -> None:
    """For any holding whose symbol has no rows in stock_peers, fire the
    warm_peers_for_symbol Celery task so the dashboard's peer column +
    detail panel get populated without waiting for the next morning
    pipeline. Idempotent.
    """
    symbols = {
        (h.get("tradingsymbol") or "").upper().strip()
        for h in payload
        if (h.get("tradingsymbol") and holding_total_qty(h) > 0)
    }
    symbols.discard("")
    if not symbols:
        return

    from sqlalchemy import select as _select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.config import get_settings
    from app.models.stock_peers import StockPeer

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    SM = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with SM() as db:
            existing = (await db.execute(
                _select(StockPeer.symbol).where(StockPeer.symbol.in_(list(symbols)))
            )).scalars().all()
            covered = {s.upper() for s in existing}
        missing = symbols - covered
        if not missing:
            return
        from app.tasks.peer_warmup_task import warm_peers_for_symbol
        for sym in missing:
            warm_peers_for_symbol.delay(sym, user.id)
        logger.info(
            "holdings peer-warmup: dispatched %d new symbol(s): %s",
            len(missing), ", ".join(sorted(missing)),
        )
    finally:
        await engine.dispose()


def holding_total_qty(h: dict) -> int:
    """Total shares owned including pledged collateral and T1 settlement."""
    return (h.get("quantity", 0) or 0) + (h.get("collateral_quantity", 0) or 0) + (h.get("t1_quantity", 0) or 0)


def active_holdings(holdings: list[dict]) -> list[dict]:
    """Filter to holdings with positive total quantity (includes pledged/T1)."""
    return [h for h in holdings if holding_total_qty(h) > 0]


async def invalidate_holdings(user_id: int) -> int:
    return await cache_invalidate(_holdings_key(user_id))


async def peek_holdings(user_id: int) -> tuple[list[dict] | None, Any]:
    """Read the cached holdings without triggering a fetch. Returns (payload, fetched_at)."""
    hit = await cache_get(_holdings_key(user_id))
    if hit is None:
        return None, None
    payload, fetched_at = hit
    return payload, fetched_at


# --------------------------------------------------------------------------- #
# quotes
# --------------------------------------------------------------------------- #

def _quote_key(user_id: int, symbols: list[str]) -> str:
    # Sort + dedup so cache key is stable regardless of caller-side ordering.
    sig = ",".join(sorted(set(symbols)))
    return f"kite_quote:{user_id}:{sig}"


async def get_quote(user: User, symbols: list[str], *, force: bool = False) -> dict[str, Any]:
    """Batch quote lookup. `symbols` are full instrument keys ("NSE:RELIANCE")."""
    if not symbols:
        return {}

    async def _fetch() -> dict[str, Any]:
        kite = _authed_kite(user)
        return await asyncio.to_thread(kite.quote, symbols)

    payload, _ = await cache_get_or_fetch(
        _quote_key(user.id, symbols),
        _fetch,
        ttl_seconds=QUOTE_TTL_SECONDS,
        force=force,
    )
    return payload or {}


# --------------------------------------------------------------------------- #
# historical
# --------------------------------------------------------------------------- #

def _historical_key(
    user_id: int,
    instrument_token: int,
    from_date: date,
    to_date: date,
    interval: str,
) -> str:
    return f"kite_historical:{user_id}:{instrument_token}:{interval}:{from_date}:{to_date}"


async def get_historical_data(
    user: User,
    instrument_token: int,
    from_date: date,
    to_date: date,
    interval: str,
    *,
    force: bool = False,
) -> list[dict]:
    """Cached historical bars. Intraday intervals get 1h TTL, daily+ get 24h TTL."""
    ttl = (
        HISTORICAL_INTRADAY_TTL_SECONDS
        if interval in INTRADAY_INTERVALS
        else HISTORICAL_DAILY_TTL_SECONDS
    )

    async def _fetch() -> list[dict]:
        kite = _authed_kite(user)
        return await asyncio.to_thread(
            kite.historical_data, instrument_token, from_date, to_date, interval
        )

    payload, _ = await cache_get_or_fetch(
        _historical_key(user.id, instrument_token, from_date, to_date, interval),
        _fetch,
        ttl_seconds=ttl,
        force=force,
    )
    return payload or []
