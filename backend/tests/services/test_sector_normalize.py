"""Tests for the sector-normalization helper introduced in P1.4 of the
sector-intelligence plan."""

from app.services.screener_presets import (
    CANONICAL_SECTORS,
    INDEX_TO_SECTOR,
    SECTOR_ALIASES,
    is_canonical_sector,
    normalize_sector,
)


def test_canonical_sectors_count():
    # 11 canonical names — Technology, Financial Services, Healthcare,
    # Consumer Cyclical, Consumer Defensive, Industrials, Basic Materials,
    # Communication Services, Energy, Utilities, Real Estate.
    assert len(CANONICAL_SECTORS) == 11


def test_aliases_all_map_to_canonical():
    for k, v in SECTOR_ALIASES.items():
        assert v in CANONICAL_SECTORS, f"alias {k!r} maps to non-canonical {v!r}"


def test_index_to_sector_targets_canonical():
    for slug, sector in INDEX_TO_SECTOR.items():
        assert sector in CANONICAL_SECTORS, (
            f"index {slug!r} maps to non-canonical sector {sector!r}"
        )


def test_normalize_empty_inputs():
    assert normalize_sector(None) is None
    assert normalize_sector("") is None
    assert normalize_sector("   ") is None


def test_normalize_canonical_passthrough():
    for s in CANONICAL_SECTORS:
        assert normalize_sector(s) == s


def test_normalize_case_drift():
    assert normalize_sector("technology") == "Technology"
    assert normalize_sector("FINANCIAL SERVICES") == "Financial Services"
    assert normalize_sector("Consumer Defensive  ") == "Consumer Defensive"


def test_normalize_indian_aliases():
    # FMCG / staples
    assert normalize_sector("FMCG") == "Consumer Defensive"
    assert normalize_sector("Consumer Staples") == "Consumer Defensive"
    # Pharma
    assert normalize_sector("Pharma") == "Healthcare"
    assert normalize_sector("Pharmaceuticals") == "Healthcare"
    # Banking
    assert normalize_sector("Banks - Private Sector") == "Financial Services"
    assert normalize_sector("NBFC") == "Financial Services"
    # Auto
    assert normalize_sector("Auto") == "Consumer Cyclical"
    assert normalize_sector("Auto Ancillaries") == "Consumer Cyclical"
    # IT
    assert normalize_sector("IT Services") == "Technology"
    assert normalize_sector("IT - Software") == "Technology"
    # Materials
    assert normalize_sector("Metals & Mining") == "Basic Materials"
    assert normalize_sector("Cement") == "Basic Materials"
    # Energy
    assert normalize_sector("Oil & Gas") == "Energy"
    # Real estate
    assert normalize_sector("Realty") == "Real Estate"
    assert normalize_sector("real estate") == "Real Estate"
    # Telecom
    assert normalize_sector("Telecom") == "Communication Services"


def test_normalize_unknown_preserved_titled():
    # Fail-open: never drop the value, just clean case/whitespace.
    # This lets the read site log it as "unknown sector" and grow the alias map.
    assert normalize_sector("Conglomerate") == "Conglomerate"
    assert normalize_sector("metals and mining") == "Metals & Mining"
    # Note: "Metals & Mining" IS in CANONICAL_SECTORS via SECTOR_ALIASES,
    # but only the lower-cased "metals & mining" alias is registered.
    # Confirm the title-case path hits the alias dict, not the fallback.
    assert normalize_sector("Metals & Mining") == "Basic Materials"


def test_is_canonical_sector():
    assert is_canonical_sector("Technology") is True
    assert is_canonical_sector("Healthcare") is True
    assert is_canonical_sector("Conglomerate") is False
    assert is_canonical_sector("technology") is False  # case-sensitive on canonical check
    assert is_canonical_sector(None) is False
    assert is_canonical_sector("") is False
