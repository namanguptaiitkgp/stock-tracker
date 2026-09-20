"""F&O-eligible underlying universe for NSE (NFO) and BSE (BFO).

Source: Kite's derivatives instrument master. NFO/BFO rows have
`name` = the underlying equity symbol. We cache the distinct set in
memory with a 24-hour TTL — the F&O list changes only a handful of
times a year.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from kiteconnect import KiteConnect
from sqlalchemy import select

from app.db.session import async_session
from app.models.user import User

logger = logging.getLogger(__name__)


_CACHE: dict[str, tuple[float, set[str]]] = {}
_FULL_CACHE: dict[str, tuple[float, list[dict]]] = {}
_TTL = 24 * 3600  # 24 hours


async def _first_kite_user() -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).order_by(User.id).limit(1))
        user = result.scalar_one_or_none()
    if user and user.kite_api_key and user.kite_access_token:
        return user
    return None


def _fetch_underlyings_full(user: User, exchange: str) -> list[dict]:
    """Return list of { symbol, display_name, exchange, lot_size,
    nearest_expiry } unique underlyings. lot_size is from the
    nearest-expiry FUT contract (fallbacks: any FUT, then CE/PE)."""
    from datetime import date

    kite = KiteConnect(api_key=user.kite_api_key)
    kite.set_access_token(user.kite_access_token)
    try:
        rows: list[dict[str, Any]] = kite.instruments(exchange)
    except Exception as e:
        logger.warning("kite.instruments(%s) failed: %s", exchange, e)
        return []
    equity_exchange = "NSE" if exchange == "NFO" else "BSE"
    today = date.today()
    seen: dict[str, dict] = {}
    rank_map = {"FUT": 2, "CE": 1, "PE": 0}

    for r in rows:
        name = (r.get("name") or "").strip().upper()
        itype = (r.get("instrument_type") or "").upper()
        if not name or itype not in rank_map:
            continue

        entry = seen.setdefault(name, {
            "symbol": name,
            "display_name": name,
            "exchange": equity_exchange,
            "lot_size": None,
            "nearest_expiry": None,
            "_source_itype": None,
        })

        lot = r.get("lot_size")
        expiry = r.get("expiry")
        if isinstance(expiry, date):
            exp_date = expiry
        elif isinstance(expiry, str):
            try:
                exp_date = date.fromisoformat(expiry[:10])
            except ValueError:
                exp_date = None
        else:
            exp_date = None

        cur_rank = rank_map[itype]
        prev_itype = entry.get("_source_itype") or ""
        prev_rank = rank_map.get(prev_itype, -1)

        # Prefer FUT rows over options, and within those prefer the
        # earliest future-dated expiry.
        take = False
        if entry["lot_size"] is None or cur_rank > prev_rank:
            take = True
        elif cur_rank == prev_rank and exp_date:
            prev_exp = entry.get("nearest_expiry")
            if prev_exp is None:
                take = True
            elif prev_exp < today and exp_date >= today:
                take = True
            elif prev_exp >= today and exp_date >= today and exp_date < prev_exp:
                take = True

        if take:
            if lot:
                entry["lot_size"] = int(lot)
            entry["nearest_expiry"] = exp_date
            entry["_source_itype"] = itype

    # Clean up internal fields + serialize date
    for e in seen.values():
        e.pop("_source_itype", None)
        ne = e.get("nearest_expiry")
        from datetime import date as _date
        if isinstance(ne, _date):
            e["nearest_expiry"] = ne.isoformat()
    return sorted(seen.values(), key=lambda x: x["symbol"])


def _fetch_underlyings(user: User, exchange: str) -> set[str]:
    full = _fetch_underlyings_full(user, exchange)
    return {r["symbol"] for r in full}


async def get_fno_full(exchange: str) -> list[dict]:
    """Returns full underlying list for `exchange` ('NFO' or 'BFO')."""
    now = time.time()
    cached = _FULL_CACHE.get(exchange)
    if cached and (now - cached[0]) < _TTL:
        return cached[1]

    user = await _first_kite_user()
    if not user:
        return cached[1] if cached else []

    import asyncio
    rows = await asyncio.to_thread(_fetch_underlyings_full, user, exchange)
    if rows:
        _FULL_CACHE[exchange] = (now, rows)
    return rows


async def get_fno_sets() -> tuple[set[str], set[str]]:
    """Returns (nse_fno_underlyings, bse_fno_underlyings).
    Cached 24h. If Kite isn't available, returns (empty, empty)."""
    now = time.time()

    cached_nse = _CACHE.get("NFO")
    cached_bse = _CACHE.get("BFO")
    fresh = (
        cached_nse and (now - cached_nse[0]) < _TTL
        and cached_bse and (now - cached_bse[0]) < _TTL
    )
    if fresh:
        return cached_nse[1], cached_bse[1]

    user = await _first_kite_user()
    if not user:
        return cached_nse[1] if cached_nse else set(), cached_bse[1] if cached_bse else set()

    import asyncio

    nse, bse = await asyncio.gather(
        asyncio.to_thread(_fetch_underlyings, user, "NFO"),
        asyncio.to_thread(_fetch_underlyings, user, "BFO"),
    )

    if nse:
        _CACHE["NFO"] = (now, nse)
    if bse:
        _CACHE["BFO"] = (now, bse)

    return nse, bse


def invalidate_cache() -> None:
    _CACHE.clear()
