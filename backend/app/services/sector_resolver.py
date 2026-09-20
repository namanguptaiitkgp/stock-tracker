"""Sector resolver — single source of truth for "what sector is this stock in?"

Composes four sources in priority order:

  1. `user_holdings_metadata.sector_override`  (per user × symbol)
     — manual override always wins; user-set canonical value.
  2. Nifty sector index membership
     — deterministic for ~130 large/mid-cap stocks via the curated JSON seed
       at `backend/app/data/nifty_sector_constituents.json`.
  3. `stock_fundamentals.sector`
     — best-effort auto-detected (Screener.in preferred, yfinance fallback;
       already normalized via `normalize_sector()` at write time).
  4. None
     — no source could resolve.

Provenance is preserved in `SectorResolution.source` so the UI and logs
can show *why* a particular sector was chosen. This is critical for
debugging mistagging reports — "it says Energy because user override" vs
"because it's in Nifty Energy" vs "because Screener says Refineries &
Marketing" lead to very different fixes.

The resolver is a *read-through*: it does not write back to
`stock_fundamentals.sector`. Auto-detected values are persisted there by
the fundamentals refresh pipeline; the resolver layers user overrides
and Nifty membership on top at read time. This keeps user-personal data
out of the global `stock_fundamentals` row.

Used by:
  • `app/api/today.py` — when building the morning brief and the per-card
    `news_section.sector_mood` lookup
  • `app/services/stock_card.py` — for the valuation-preset selection and
    SectorAnalysis row lookup
  • `app/tasks/morning_pipeline.py` — when building the unique-sectors
    set for the sector-news refresh loop
  • (Phase 4) `app/api/sectors.py` — for the dedicated /sectors page
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fundamentals import StockFundamentals
from app.models.user_holdings_metadata import UserHoldingsMetadata
from app.services.nifty_membership import get_sector_for_symbol as nifty_sector
from app.services.screener_presets import (
    CANONICAL_SECTORS,
    is_canonical_sector,
    normalize_sector,
)

logger = logging.getLogger(__name__)


# Provenance tags — keep stable; consumers may key UI on these.
SOURCE_OVERRIDE = "override"
SOURCE_NIFTY = "nifty"
SOURCE_SCREENER = "screener"
SOURCE_YFINANCE = "yfinance"
SOURCE_FUNDAMENTALS = "fundamentals"  # source unknown but value present
SOURCE_NONE = "none"


@dataclass(frozen=True)
class SectorResolution:
    """The outcome of resolving a sector for one symbol."""

    symbol: str
    sector: str | None  # canonical name (in CANONICAL_SECTORS) or None
    source: str  # one of the SOURCE_* constants above
    raw: str | None = None  # pre-normalization value, for diagnostics

    @property
    def is_canonical(self) -> bool:
        """True iff sector is a member of CANONICAL_SECTORS. False for null
        and for fallthrough title-cased strings like "Conglomerate"."""
        return is_canonical_sector(self.sector)


async def resolve_sector(
    symbol: str,
    db: AsyncSession,
    user_id: int | None = None,
) -> SectorResolution:
    """Resolve the canonical sector for a single symbol with provenance.

    See module docstring for the priority chain. Returns
    `SectorResolution(sector=None, source=SOURCE_NONE)` if no source has a
    value — never raises for missing data.

    `user_id` is optional; when omitted, the override step is skipped and
    resolution starts at Nifty membership. Pass `None` only for system
    contexts where user-personal overrides aren't applicable.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return SectorResolution(symbol=symbol or "", sector=None, source=SOURCE_NONE)

    # 1. Manual override (per user × symbol)
    if user_id is not None:
        row = await db.execute(
            select(UserHoldingsMetadata.sector_override).where(
                UserHoldingsMetadata.user_id == user_id,
                UserHoldingsMetadata.symbol == sym,
            )
        )
        override = row.scalar_one_or_none()
        if override:
            # Re-normalize defensively — the column is validated at write
            # time but a direct DB edit could leak garbage.
            canon = normalize_sector(override) or override
            logger.debug(
                "sector_resolved", extra={
                    "symbol": sym, "sector": canon, "source": SOURCE_OVERRIDE,
                }
            )
            return SectorResolution(
                symbol=sym, sector=canon, source=SOURCE_OVERRIDE, raw=override,
            )

    # 2. Nifty sector index membership (O(1) in-memory lookup)
    nm = nifty_sector(sym)
    if nm:
        logger.debug(
            "sector_resolved", extra={
                "symbol": sym, "sector": nm, "source": SOURCE_NIFTY,
            }
        )
        return SectorResolution(symbol=sym, sector=nm, source=SOURCE_NIFTY, raw=nm)

    # 3. stock_fundamentals.sector (Screener-preferred, yfinance-fallback)
    row = await db.execute(
        select(StockFundamentals.sector, StockFundamentals.data_sources).where(
            StockFundamentals.symbol == sym
        )
    )
    fund = row.first()
    if fund and fund.sector:
        # Determine provenance from data_sources.sector when available.
        sources = fund.data_sources or {}
        src = sources.get("sector")
        if src == "screener":
            tag = SOURCE_SCREENER
        elif src == "yfinance":
            tag = SOURCE_YFINANCE
        else:
            tag = SOURCE_FUNDAMENTALS
        # Defensive re-normalization — handles legacy rows written before
        # `normalize_sector` was wired in.
        canon = normalize_sector(fund.sector) or fund.sector
        if not is_canonical_sector(canon):
            # Sector value is non-canonical (e.g., "Conglomerate" that fell
            # through the alias map). Log a warning so the alias dict can
            # be grown; still return the value so the UI shows something.
            logger.warning(
                "unknown_sector — neither alias nor canonical match",
                extra={"symbol": sym, "raw": fund.sector, "source": tag},
            )
        logger.debug(
            "sector_resolved", extra={
                "symbol": sym, "sector": canon, "source": tag,
            }
        )
        return SectorResolution(
            symbol=sym, sector=canon, source=tag, raw=fund.sector,
        )

    # 4. No source has a value
    logger.info("sector_unresolved", extra={"symbol": sym})
    return SectorResolution(symbol=sym, sector=None, source=SOURCE_NONE)


async def resolve_sectors_bulk(
    symbols: Iterable[str],
    db: AsyncSession,
    user_id: int | None = None,
) -> dict[str, SectorResolution]:
    """Bulk resolver. Issues at most two SELECTs (one for overrides, one
    for fundamentals) plus an in-memory Nifty pass. O(N) for N symbols.

    Used by the morning pipeline's sectors loop so we don't issue
    N×2 queries when resolving 24+ holdings.
    """
    syms = [s.strip().upper() for s in symbols if s and s.strip()]
    syms = list(dict.fromkeys(syms))  # dedupe preserving order
    if not syms:
        return {}

    # Single SELECT for all overrides (if user_id given)
    overrides: dict[str, str] = {}
    if user_id is not None:
        rows = await db.execute(
            select(
                UserHoldingsMetadata.symbol,
                UserHoldingsMetadata.sector_override,
            ).where(
                UserHoldingsMetadata.user_id == user_id,
                UserHoldingsMetadata.symbol.in_(syms),
                UserHoldingsMetadata.sector_override.is_not(None),
            )
        )
        overrides = {r.symbol: r.sector_override for r in rows}

    # Single SELECT for all fundamentals rows
    rows = await db.execute(
        select(
            StockFundamentals.symbol,
            StockFundamentals.sector,
            StockFundamentals.data_sources,
        ).where(StockFundamentals.symbol.in_(syms))
    )
    fundamentals: dict[str, tuple[str | None, dict | None]] = {
        r.symbol: (r.sector, r.data_sources) for r in rows
    }

    out: dict[str, SectorResolution] = {}
    for sym in syms:
        # 1. Override
        ov = overrides.get(sym)
        if ov:
            canon = normalize_sector(ov) or ov
            out[sym] = SectorResolution(
                symbol=sym, sector=canon, source=SOURCE_OVERRIDE, raw=ov,
            )
            continue

        # 2. Nifty
        nm = nifty_sector(sym)
        if nm:
            out[sym] = SectorResolution(
                symbol=sym, sector=nm, source=SOURCE_NIFTY, raw=nm,
            )
            continue

        # 3. Fundamentals
        fund = fundamentals.get(sym)
        if fund and fund[0]:
            sector_raw, sources = fund
            src_tag = (sources or {}).get("sector")
            if src_tag == "screener":
                tag = SOURCE_SCREENER
            elif src_tag == "yfinance":
                tag = SOURCE_YFINANCE
            else:
                tag = SOURCE_FUNDAMENTALS
            canon = normalize_sector(sector_raw) or sector_raw
            if not is_canonical_sector(canon):
                logger.warning(
                    "unknown_sector",
                    extra={"symbol": sym, "raw": sector_raw, "source": tag},
                )
            out[sym] = SectorResolution(
                symbol=sym, sector=canon, source=tag, raw=sector_raw,
            )
            continue

        # 4. None
        out[sym] = SectorResolution(symbol=sym, sector=None, source=SOURCE_NONE)

    return out


def canonical_sector_list() -> list[str]:
    """Convenience accessor — returns CANONICAL_SECTORS for use by callers
    that don't want to import `screener_presets` directly (e.g., API
    endpoints exposing the dropdown options)."""
    return list(CANONICAL_SECTORS)
