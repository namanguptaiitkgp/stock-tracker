"""Fetch live quotes for tracked indices.

- Kite-provided indices (Nifty 50, Sensex, Bank Nifty, sector indices,
  India VIX) via a single `kite.quote([...])` batch call.
- Gift Nifty scraped from moneycontrol as a best-effort fallback (Kite
  doesn't cover NSE IX / GIFT City). Graceful-degrade on scrape failure.

Results upsert into `index_quote_cache` keyed by slug. Callers read from
the cache — short-TTL (~5 min by default).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from kiteconnect import KiteConnect
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session
from app.models.market import IndexQuoteCache
from app.models.user import User
from app.services.market.indices_registry import INDICES, IndexEntry

logger = logging.getLogger(__name__)


GIFT_NIFTY_URL = "https://www.moneycontrol.com/indian-indices/gift-nifty-117.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _to_f(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _fetch_kite_quotes(user: User, entries: list[IndexEntry]) -> dict[str, dict]:
    """Returns {slug: {ltp, prev_close, change, change_pct, high, low}}."""
    if not user.kite_api_key or not user.kite_access_token:
        return {}
    kite = KiteConnect(api_key=user.kite_api_key)
    kite.set_access_token(user.kite_access_token)
    symbols = [e.source_symbol for e in entries if e.source_symbol]
    try:
        raw = kite.quote(symbols)
    except Exception as e:
        logger.warning("Kite quote batch failed: %s", e)
        return {}

    out: dict[str, dict] = {}
    for e in entries:
        q = raw.get(e.source_symbol) or {}
        ltp = _to_f(q.get("last_price"))
        prev = _to_f((q.get("ohlc") or {}).get("close"))
        high = _to_f((q.get("ohlc") or {}).get("high"))
        low = _to_f((q.get("ohlc") or {}).get("low"))
        change = None
        change_pct = None
        if ltp is not None and prev:
            change = ltp - prev
            change_pct = (change / prev) * 100
        if ltp is None:
            continue
        out[e.slug] = {
            "ltp": ltp,
            "prev_close": prev,
            "change": change,
            "change_pct": change_pct,
            "day_high": high,
            "day_low": low,
        }
    return out


async def _fetch_gift_nifty() -> dict | None:
    """Best-effort scrape of moneycontrol's Gift Nifty page. Returns None on
    any failure — caller must handle absent data."""
    try:
        async with httpx.AsyncClient(
            timeout=15, headers=HEADERS, follow_redirects=True
        ) as c:
            r = await c.get(GIFT_NIFTY_URL)
            r.raise_for_status()
            html = r.text
    except Exception as e:
        logger.info("Gift Nifty fetch failed: %s", e)
        return None

    # Moneycontrol's page puts last/change values in a few data-* spans and
    # inline JSON. Try a few heuristics; each gated so a layout change
    # yields None instead of a crash.
    def _extract_number(pattern: str) -> float | None:
        m = re.search(pattern, html, flags=re.DOTALL | re.IGNORECASE)
        if not m:
            return None
        raw = m.group(1).replace(",", "").strip()
        try:
            return float(raw)
        except ValueError:
            return None

    ltp = (
        _extract_number(r'id=["\']sp_val["\'][^>]*>([\d,.]+)')
        or _extract_number(r'class=["\'][^"\']*spotprice[^"\']*["\'][^>]*>\s*([\d,.]+)')
        or _extract_number(r'"spot_price"\s*:\s*"?([\d,.]+)"?')
        or _extract_number(r'"last_price"\s*:\s*"?([\d,.]+)"?')
    )
    change = _extract_number(r'"change"\s*:\s*"?(-?[\d,.]+)"?') or _extract_number(
        r'id=["\']chg["\'][^>]*>(-?[\d,.]+)'
    )
    change_pct = _extract_number(r'"per_change"\s*:\s*"?(-?[\d,.]+)"?') or _extract_number(
        r'id=["\']perchg["\'][^>]*>(-?[\d,.]+)'
    )
    prev = None
    if ltp is not None and change is not None:
        prev = ltp - change

    if ltp is None:
        return None
    return {
        "ltp": ltp,
        "prev_close": prev,
        "change": change,
        "change_pct": change_pct,
        "day_high": None,
        "day_low": None,
    }


async def fetch_and_cache_quotes(user: User) -> list[dict]:
    """Fetch live quotes for every tracked index and upsert the cache.
    Returns the rows serialized for the API (same shape as reading
    from the cache)."""
    kite_entries = [e for e in INDICES if e.provider == "kite"]
    kite_data = await _fetch_kite_quotes(user, kite_entries)

    gift = await _fetch_gift_nifty()

    now = datetime.now(tz=timezone.utc)
    serialized: list[dict] = []

    async with async_session() as session:
        for entry in INDICES:
            if entry.provider == "kite":
                quote = kite_data.get(entry.slug)
            elif entry.slug == "gift_nifty":
                quote = gift
            else:
                quote = None

            status = "ok"
            error_message = None
            if quote is None:
                # Don't wipe a previous good value — fetch the stored row
                existing = await session.execute(
                    select(IndexQuoteCache).where(IndexQuoteCache.slug == entry.slug)
                )
                prev_row = existing.scalar_one_or_none()
                if prev_row and prev_row.ltp is not None:
                    status = "stale"
                    error_message = "source fetch failed; showing last known"
                    serialized.append(_row_to_dict(prev_row, status, error_message))
                    continue
                status = "unavailable"
                error_message = "source fetch failed, no cached value"
                values = {
                    "slug": entry.slug,
                    "display_name": entry.display_name,
                    "provider": entry.provider,
                    "source_symbol": entry.source_symbol,
                    "ltp": None,
                    "prev_close": None,
                    "change": None,
                    "change_pct": None,
                    "day_high": None,
                    "day_low": None,
                    "fetched_at": now,
                    "status": status,
                    "error_message": error_message,
                }
            else:
                values = {
                    "slug": entry.slug,
                    "display_name": entry.display_name,
                    "provider": entry.provider,
                    "source_symbol": entry.source_symbol,
                    "ltp": quote["ltp"],
                    "prev_close": quote["prev_close"],
                    "change": quote["change"],
                    "change_pct": quote["change_pct"],
                    "day_high": quote["day_high"],
                    "day_low": quote["day_low"],
                    "fetched_at": now,
                    "status": "ok",
                    "error_message": None,
                }

            stmt = pg_insert(IndexQuoteCache).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["slug"],
                set_={k: stmt.excluded[k] for k in values if k != "slug"},
            )
            await session.execute(stmt)
            serialized.append({
                "slug": entry.slug,
                "display_name": entry.display_name,
                "short_name": entry.short_name,
                "provider": entry.provider,
                "source_symbol": entry.source_symbol,
                "ltp": values["ltp"],
                "prev_close": values["prev_close"],
                "change": values["change"],
                "change_pct": values["change_pct"],
                "day_high": values["day_high"],
                "day_low": values["day_low"],
                "fetched_at": now.isoformat(),
                "status": values["status"],
                "error_message": values["error_message"],
            })

        await session.commit()

    return serialized


def _row_to_dict(row: IndexQuoteCache, status: str | None = None, error_message: str | None = None) -> dict:
    entry = next((e for e in INDICES if e.slug == row.slug), None)
    return {
        "slug": row.slug,
        "display_name": row.display_name,
        "short_name": entry.short_name if entry else row.display_name,
        "provider": row.provider,
        "source_symbol": row.source_symbol,
        "ltp": _to_f(row.ltp),
        "prev_close": _to_f(row.prev_close),
        "change": _to_f(row.change),
        "change_pct": _to_f(row.change_pct),
        "day_high": _to_f(row.day_high),
        "day_low": _to_f(row.day_low),
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "status": status or row.status,
        "error_message": error_message or row.error_message,
    }


async def read_cached_quotes() -> list[dict]:
    """Return cached quote rows in the registry order (Sensex first)."""
    async with async_session() as session:
        result = await session.execute(select(IndexQuoteCache))
        by_slug = {r.slug: r for r in result.scalars().all()}

    out: list[dict] = []
    for entry in INDICES:
        row = by_slug.get(entry.slug)
        if row:
            out.append(_row_to_dict(row))
        else:
            out.append({
                "slug": entry.slug,
                "display_name": entry.display_name,
                "short_name": entry.short_name,
                "provider": entry.provider,
                "source_symbol": entry.source_symbol,
                "ltp": None,
                "prev_close": None,
                "change": None,
                "change_pct": None,
                "day_high": None,
                "day_low": None,
                "fetched_at": None,
                "status": "never_fetched",
                "error_message": None,
            })
    return out
