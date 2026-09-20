"""Tests for the Nifty sector-index membership lookup (P1.5)."""

from datetime import date, timedelta

from app.services.nifty_membership import (
    _load,
    as_of_date,
    get_constituents,
    get_sector_for_symbol,
    total_symbols,
)
from app.services.screener_presets import CANONICAL_SECTORS, INDEX_TO_SECTOR


def setup_function(_):
    # Clear the LRU cache so each test reads the JSON fresh. Belt-and-suspenders
    # against accidental cross-test state.
    _load.cache_clear()


def test_total_symbols_reasonable():
    # Seed has ~10-15 stocks per index × 11 indices, with overlap between
    # nifty_bank and the two sub-bank indices. Net distinct symbols should
    # land somewhere in 100-300. Anything outside that range probably
    # means the JSON got truncated or corrupted.
    n = total_symbols()
    assert 100 <= n <= 300, f"total_symbols={n} is outside expected 100-300 range"


def test_as_of_is_recent_ish():
    # Don't enforce "within 90 days" since CI could be far behind real life,
    # but assert it's a real date in this millennium.
    d = as_of_date()
    assert d.year >= 2020
    assert d <= date.today() + timedelta(days=1)  # not future-dated


def test_canonical_constituents():
    # Spot-check that the marquee constituents land in the right sector.
    assert get_sector_for_symbol("TCS") == "Technology"
    assert get_sector_for_symbol("INFY") == "Technology"
    assert get_sector_for_symbol("HDFCBANK") == "Financial Services"
    assert get_sector_for_symbol("SBIN") == "Financial Services"
    assert get_sector_for_symbol("MARUTI") == "Consumer Cyclical"
    assert get_sector_for_symbol("HINDUNILVR") == "Consumer Defensive"
    assert get_sector_for_symbol("ITC") == "Consumer Defensive"
    assert get_sector_for_symbol("SUNPHARMA") == "Healthcare"
    assert get_sector_for_symbol("RELIANCE") == "Energy"
    assert get_sector_for_symbol("TATASTEEL") == "Basic Materials"
    assert get_sector_for_symbol("DLF") == "Real Estate"
    assert get_sector_for_symbol("ZEEL") == "Communication Services"


def test_overlap_handled_consistently():
    # HDFCBANK is in both nifty_bank and nifty_pvt_bank; both map to
    # Financial Services so the resolution must be stable.
    assert get_sector_for_symbol("HDFCBANK") == "Financial Services"
    # SBIN is in both nifty_bank and nifty_psu_bank — same story.
    assert get_sector_for_symbol("SBIN") == "Financial Services"


def test_case_and_whitespace_insensitive():
    assert get_sector_for_symbol("tcs") == "Technology"
    assert get_sector_for_symbol("  HDFCBANK  ") == "Financial Services"
    assert get_sector_for_symbol("Reliance") == "Energy"


def test_unknown_symbol_returns_none():
    assert get_sector_for_symbol("SOMETHINGRANDOM") is None
    assert get_sector_for_symbol("") is None
    assert get_sector_for_symbol(None) is None  # type: ignore[arg-type]


def test_get_constituents():
    tech = get_constituents("Technology")
    assert "TCS" in tech
    assert "INFY" in tech
    assert "HCLTECH" in tech
    assert len(tech) >= 10  # Nifty IT has 10 names

    fin = get_constituents("Financial Services")
    # nifty_bank (12) + nifty_pvt_bank (10) + nifty_psu_bank (12) merged,
    # with overlap on HDFCBANK/ICICIBANK/SBIN/etc. — expect ~25 distinct.
    assert "HDFCBANK" in fin
    assert "SBIN" in fin
    assert "BANKBARODA" in fin
    assert len(fin) >= 20


def test_get_constituents_empty_for_unknown_sector():
    assert get_constituents("Conglomerate") == set()
    assert get_constituents("") == set()


def test_every_index_sector_is_canonical():
    # The JSON declares a `sector` per index; the loader cross-checks
    # against INDEX_TO_SECTOR. Confirm that every value in
    # INDEX_TO_SECTOR is itself a canonical sector — otherwise the
    # cross-check is permissive of garbage.
    for slug, sector in INDEX_TO_SECTOR.items():
        assert sector in CANONICAL_SECTORS, f"{slug} → {sector!r} is not canonical"
