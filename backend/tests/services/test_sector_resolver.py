"""Tests for the multi-source sector resolver (P1.2).

These tests verify the priority chain:
  1. user_holdings_metadata.sector_override
  2. Nifty sector index membership
  3. stock_fundamentals.sector (Screener > yfinance)
  4. None

DB queries are mocked via AsyncMock so the resolver can be exercised
without a live Postgres. The Nifty membership lookup is the real one
(reads the JSON seed) since that's pure-Python.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.sector_resolver import (
    SOURCE_FUNDAMENTALS,
    SOURCE_NIFTY,
    SOURCE_NONE,
    SOURCE_OVERRIDE,
    SOURCE_SCREENER,
    SOURCE_YFINANCE,
    SectorResolution,
    resolve_sector,
    resolve_sectors_bulk,
)


@dataclass
class _FundRow:
    sector: str | None
    data_sources: dict | None


def _mock_db_override(override: str | None):
    """Mock a DB that returns `override` for the sector_override scalar
    query and never reaches the fundamentals query (because override
    short-circuits)."""
    db = MagicMock()
    db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = override
    db.execute.return_value = result
    return db


def _mock_db_no_override_with_fund(sector: str | None, source: str | None):
    """Mock a DB that returns no override, then returns a fundamentals row
    with the given sector + source provenance."""
    db = MagicMock()
    # Two execute calls: one for override (returns None), one for fundamentals
    override_result = MagicMock()
    override_result.scalar_one_or_none.return_value = None

    fund_result = MagicMock()
    if sector is None and source is None:
        fund_result.first.return_value = None
    else:
        fund_row = MagicMock()
        fund_row.sector = sector
        fund_row.data_sources = {"sector": source} if source else None
        fund_result.first.return_value = fund_row

    db.execute = AsyncMock(side_effect=[override_result, fund_result])
    return db


@pytest.mark.asyncio
async def test_override_wins_above_everything():
    # User has overridden TCS (which Nifty would resolve to Technology)
    # to "Energy" — the override must win.
    db = _mock_db_override("Energy")
    r = await resolve_sector("TCS", db, user_id=1)
    assert r.sector == "Energy"
    assert r.source == SOURCE_OVERRIDE
    assert r.raw == "Energy"


@pytest.mark.asyncio
async def test_override_normalized_defensively():
    # Override column contains a non-canonical value (e.g., direct DB edit
    # leaked through the API validation). normalize_sector cleans it up.
    db = _mock_db_override("fmcg")
    r = await resolve_sector("HUL", db, user_id=1)
    assert r.sector == "Consumer Defensive"
    assert r.source == SOURCE_OVERRIDE


@pytest.mark.asyncio
async def test_nifty_membership_when_no_override():
    # TCS is in Nifty IT. With no override (user_id passed but the DB
    # has no override row), Nifty membership should win — fundamentals
    # query should NOT be reached because Nifty is the second tier.
    db = MagicMock()
    override_result = MagicMock()
    override_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=override_result)
    r = await resolve_sector("TCS", db, user_id=1)
    assert r.sector == "Technology"
    assert r.source == SOURCE_NIFTY


@pytest.mark.asyncio
async def test_fundamentals_when_no_override_no_nifty():
    # Symbol not in any Nifty index (e.g., a small-cap not in the seed).
    # Falls through to stock_fundamentals.
    db = _mock_db_no_override_with_fund("Technology", "screener")
    r = await resolve_sector("SMALLCAP1", db, user_id=1)
    assert r.sector == "Technology"
    assert r.source == SOURCE_SCREENER
    assert r.raw == "Technology"


@pytest.mark.asyncio
async def test_fundamentals_yfinance_provenance():
    db = _mock_db_no_override_with_fund("Healthcare", "yfinance")
    r = await resolve_sector("OBSCUREPHARMA", db, user_id=1)
    assert r.sector == "Healthcare"
    assert r.source == SOURCE_YFINANCE


@pytest.mark.asyncio
async def test_fundamentals_unknown_provenance():
    # Legacy row written before data_sources was populated.
    db = _mock_db_no_override_with_fund("Industrials", None)
    r = await resolve_sector("LEGACY", db, user_id=1)
    assert r.sector == "Industrials"
    assert r.source == SOURCE_FUNDAMENTALS


@pytest.mark.asyncio
async def test_no_source_returns_none():
    # No override, not in Nifty seed, no fundamentals row.
    db = _mock_db_no_override_with_fund(None, None)
    r = await resolve_sector("GHOSTSTOCK", db, user_id=1)
    assert r.sector is None
    assert r.source == SOURCE_NONE


@pytest.mark.asyncio
async def test_no_user_id_skips_override():
    # System contexts (e.g., backfill scripts) may pass user_id=None.
    # Resolution should start at Nifty membership and skip the override
    # query entirely.
    db = MagicMock()
    # Only one execute should happen (the fundamentals query) since Nifty
    # resolves first for TCS.
    db.execute = AsyncMock()
    r = await resolve_sector("TCS", db, user_id=None)
    assert r.sector == "Technology"
    assert r.source == SOURCE_NIFTY
    db.execute.assert_not_called()  # neither override nor fundamentals queried


@pytest.mark.asyncio
async def test_empty_symbol():
    db = MagicMock()
    db.execute = AsyncMock()
    r = await resolve_sector("", db, user_id=1)
    assert r.sector is None
    assert r.source == SOURCE_NONE
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_resolution_is_canonical_property():
    # SectorResolution.is_canonical helper — verify both true and false paths
    canonical = SectorResolution(symbol="X", sector="Technology", source=SOURCE_NIFTY)
    assert canonical.is_canonical is True

    noncanonical = SectorResolution(symbol="X", sector="Conglomerate", source=SOURCE_FUNDAMENTALS)
    assert noncanonical.is_canonical is False

    null = SectorResolution(symbol="X", sector=None, source=SOURCE_NONE)
    assert null.is_canonical is False


@pytest.mark.asyncio
async def test_bulk_dedupes_and_preserves_order():
    # Two SELECT calls expected: one for overrides (empty), one for funds.
    db = MagicMock()
    overrides_result = MagicMock()
    overrides_result.__iter__ = lambda self: iter([])  # type: ignore[assignment]
    fund_result = MagicMock()
    fund_result.__iter__ = lambda self: iter([])  # type: ignore[assignment]
    db.execute = AsyncMock(side_effect=[overrides_result, fund_result])

    # TCS and INFY both in Nifty IT — should not require any DB rows.
    # SOMETHING is unknown — falls through to None.
    out = await resolve_sectors_bulk(
        ["TCS", "INFY", "TCS", "  infy  ", "SOMETHING"], db, user_id=1,
    )
    # Dedupe to {TCS, INFY, SOMETHING}
    assert set(out.keys()) == {"TCS", "INFY", "SOMETHING"}
    assert out["TCS"].sector == "Technology"
    assert out["TCS"].source == SOURCE_NIFTY
    assert out["INFY"].sector == "Technology"
    assert out["INFY"].source == SOURCE_NIFTY
    assert out["SOMETHING"].sector is None
    assert out["SOMETHING"].source == SOURCE_NONE
