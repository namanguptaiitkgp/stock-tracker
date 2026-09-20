"""Unified DB-backed fetch cache.

Default TTL: 2 hours. All raw external fetches (RSS, BSE API, Google News,
NSE option chain, Gemini batch responses) go through this layer to avoid
duplicate fetches across services and survive backend restarts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session
from app.models.fetch_cache import FetchCache

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 2 * 60 * 60  # 2 hours — the user's "recent" rule


def _source_from_key(key: str) -> str:
    return key.split(":", 1)[0] if ":" in key else "unknown"


async def cache_get(key: str, *, ignore_ttl: bool = False) -> tuple[Any, datetime] | None:
    """Return (payload, fetched_at) if cached, else None.

    With ignore_ttl=True, returns the entry even if expired — used for
    stale fallback when a live fetch fails (e.g. Kite disconnected).
    """
    now = datetime.now(tz=timezone.utc)
    async with async_session() as session:
        res = await session.execute(
            select(FetchCache).where(FetchCache.cache_key == key)
        )
        row = res.scalar_one_or_none()
    if not row:
        return None
    if not ignore_ttl and row.expires_at and row.expires_at < now:
        return None
    return row.payload, row.fetched_at


async def cache_set(key: str, payload: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> datetime:
    """Upsert a cache entry. Returns fetched_at."""
    now = datetime.now(tz=timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    async with async_session() as session:
        stmt = pg_insert(FetchCache).values(
            cache_key=key,
            source=_source_from_key(key),
            payload=payload,
            fetched_at=now,
            expires_at=expires,
            refresh_count=0,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["cache_key"],
            set_={
                "payload": stmt.excluded.payload,
                "fetched_at": stmt.excluded.fetched_at,
                "expires_at": stmt.excluded.expires_at,
                "source": stmt.excluded.source,
                "refresh_count": FetchCache.refresh_count + 1,
            },
        )
        await session.execute(stmt)
        await session.commit()
    return now


async def cache_get_or_fetch(
    key: str,
    fetch_fn: Callable[[], Awaitable[Any]],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    *,
    force: bool = False,
) -> tuple[Any, datetime]:
    """Returns (payload, fetched_at). On hit (within TTL & not forced),
    serves the cache row. On miss, calls fetch_fn(), upserts, returns.

    If fetch_fn raises, we re-raise — we don't fall back to a stale value
    here. Callers can wrap if they want.

    Each miss (live fetch) is logged to `scrape_events` for the activity
    monitor — including failures.
    """
    if not force:
        hit = await cache_get(key)
        if hit is not None:
            return hit

    # Miss → live fetch. Time it and log result.
    import time as _time
    from app.observability.activity import log_scrape_event

    source = _source_from_key(key)
    start = _time.time()
    payload: Any = None
    success = True
    error_class: str | None = None
    try:
        payload = await fetch_fn()
        fetched_at = await cache_set(key, payload, ttl_seconds=ttl_seconds)
        return payload, fetched_at
    except Exception as e:
        success = False
        error_class = type(e).__name__
        raise
    finally:
        try:
            await log_scrape_event(
                source=source,
                url=key,
                latency_ms=int((_time.time() - start) * 1000),
                success=success,
                error_class=error_class,
                bytes_=(len(str(payload)) if payload is not None else None),
            )
        except Exception:
            pass


async def cache_invalidate(key: str) -> int:
    """Delete one cache entry. Returns rows deleted."""
    async with async_session() as session:
        res = await session.execute(
            select(FetchCache).where(FetchCache.cache_key == key)
        )
        row = res.scalar_one_or_none()
        if not row:
            return 0
        await session.delete(row)
        await session.commit()
        return 1


async def cache_invalidate_prefix(prefix: str) -> int:
    """Delete all cache entries whose key starts with the given prefix.
    Useful for forced refresh of a whole source family (e.g. 'rss:')."""
    from sqlalchemy import delete
    async with async_session() as session:
        result = await session.execute(
            delete(FetchCache).where(FetchCache.cache_key.like(f"{prefix}%"))
        )
        await session.commit()
        return result.rowcount or 0


async def cache_prune_expired(grace_seconds: int = 24 * 60 * 60) -> int:
    """Delete rows whose `expires_at` is older than grace_seconds. Run periodically."""
    from sqlalchemy import delete
    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=grace_seconds)
    async with async_session() as session:
        result = await session.execute(
            delete(FetchCache).where(FetchCache.expires_at < cutoff)
        )
        await session.commit()
        return result.rowcount or 0
