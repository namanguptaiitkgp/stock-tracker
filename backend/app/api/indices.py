"""Live indices strip + Gemini-summary endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.market import IndexQuoteCache
from app.models.user import User
from app.services.market.indices_quotes import (
    fetch_and_cache_quotes,
    read_cached_quotes,
)
from app.services.market.indices_registry import INDICES, get_entry
from app.services.market.indices_summary import (
    read_cached_summary,
    refresh_summary_for,
)
from app.services.market.market_trend import compute_market_trend
from app.services.market.market_pulse import get_or_refresh_pulse, refresh_market_pulse

router = APIRouter()

QUOTE_TTL_SECONDS = 5 * 60

logger = logging.getLogger(__name__)


def _fire_and_forget_refresh(user: User) -> None:
    """Kick off a background refresh; ignore the result.

    Used by the stale-while-revalidate path so the request returns cached
    data immediately while a refresh runs in the background.
    """
    async def _bg() -> None:
        try:
            await fetch_and_cache_quotes(user)
        except Exception as e:
            logger.warning("Background indices refresh failed: %s", e)

    asyncio.create_task(_bg())
SUMMARY_TTL_SECONDS = 60 * 60


@router.get("/indices")
async def list_indices(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Return all tracked indices. Stale-while-revalidate: serve cached
    data immediately if we have any, kick refresh in background when stale.
    Only blocks synchronously when the cache is completely cold."""
    now = datetime.now(tz=timezone.utc)
    result = await db.execute(select(IndexQuoteCache))
    rows = {r.slug: r for r in result.scalars().all()}

    cold = len(rows) == 0
    stale = (
        len(rows) < len(INDICES)
        or any(
            r.fetched_at is None
            or (now - r.fetched_at).total_seconds() > QUOTE_TTL_SECONDS
            for r in rows.values()
        )
    )

    if cold:
        # Nothing cached — must block to avoid an empty UI.
        quotes = await fetch_and_cache_quotes(user)
    else:
        quotes = await read_cached_quotes()
        if stale:
            _fire_and_forget_refresh(user)

    # Last fetch timestamp = newest fetched_at across rows.
    newest = None
    for q in quotes:
        fa = q.get("fetched_at")
        if fa and (newest is None or fa > newest):
            newest = fa

    return {
        "indices": quotes,
        "fetched_at": newest,
        "count": len(quotes),
    }


@router.post("/indices/refresh")
async def refresh_indices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    quotes = await fetch_and_cache_quotes(user)
    return {"indices": quotes, "count": len(quotes), "forced": True}


@router.get("/trend")
async def get_market_trend(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Smart market-trend snapshot: weighted index score + breadth + VIX modifier."""
    now = datetime.now(tz=timezone.utc)
    result = await db.execute(select(IndexQuoteCache))
    rows = {r.slug: r for r in result.scalars().all()}

    cold = len(rows) == 0
    stale = (
        len(rows) < len(INDICES)
        or any(
            r.fetched_at is None
            or (now - r.fetched_at).total_seconds() > QUOTE_TTL_SECONDS
            for r in rows.values()
        )
    )

    if cold:
        quotes = await fetch_and_cache_quotes(user)
    else:
        quotes = await read_cached_quotes()
        if stale:
            _fire_and_forget_refresh(user)

    return compute_market_trend(quotes)


@router.get("/pulse")
async def get_market_pulse(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Market Pulse — Gemini-generated narrative + smart trend snapshot.

    Returns cached if `expires_at > now`, else regenerates via Gemini (~2-3s).
    """
    return await get_or_refresh_pulse(user, db=db)


@router.post("/pulse/refresh")
async def refresh_market_pulse_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Force regenerate market pulse (bypasses cache)."""
    fresh = await refresh_market_pulse(user, db=db)
    return {**fresh, "cached": False, "forced": True}


@router.get("/indices/{slug}/summary")
async def get_index_summary(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    entry = get_entry(slug)
    if not entry:
        raise HTTPException(status_code=404, detail=f"unknown index slug {slug}")

    cached = await read_cached_summary(slug)
    now = datetime.now(tz=timezone.utc)

    stale = True
    if cached and cached.get("generated_at"):
        try:
            age = (now - datetime.fromisoformat(cached["generated_at"])).total_seconds()
            stale = age > SUMMARY_TTL_SECONDS
        except Exception:
            stale = True

    if not stale and cached:
        return {**cached, "cached": True}

    fresh = await refresh_summary_for(entry, user, db=db)
    return {**fresh, "cached": False}


@router.post("/indices/{slug}/summary/refresh")
async def refresh_index_summary(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    entry = get_entry(slug)
    if not entry:
        raise HTTPException(status_code=404, detail=f"unknown index slug {slug}")
    fresh = await refresh_summary_for(entry, user, db=db)
    return {**fresh, "cached": False, "forced": True}
