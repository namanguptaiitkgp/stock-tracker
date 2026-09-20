"""Tests for the Screener.in taxonomy extraction added in P1.3 of the
sector-intelligence plan.

These tests use canned HTML fixtures that mimic the structure of real
Screener.in company pages (the `title="Broad Sector"` /
`title="Sector"` / `title="Broad Industry"` / `title="Industry"` anchors
in the breadcrumb). No network calls.
"""

from bs4 import BeautifulSoup

from app.services.screener_fetcher import _extract_taxonomy


def _make_soup(broad_sector=None, sector=None, broad_industry=None, industry=None):
    parts = ['<html><body><div class="company-info">']
    for title_attr, txt in [
        ("Broad Sector", broad_sector),
        ("Sector", sector),
        ("Broad Industry", broad_industry),
        ("Industry", industry),
    ]:
        if txt is not None:
            parts.append(f'<a href="/m/" title="{title_attr}">{txt}</a>')
    parts.append("</div></body></html>")
    return BeautifulSoup("".join(parts), "html.parser")


def test_extract_full_taxonomy_tcs_shape():
    soup = _make_soup(
        broad_sector="Information Technology",
        sector="Information Technology",
        broad_industry="IT - Software",
        industry="Computers - Software & Consulting",
    )
    sector, industry = _extract_taxonomy(soup)
    # "Information Technology" → "Technology" (canonical) via SECTOR_ALIASES
    assert sector == "Technology"
    # Industry kept verbatim — used downstream for sub-sector breakdowns
    assert industry == "Computers - Software & Consulting"


def test_extract_bank_taxonomy():
    soup = _make_soup(
        broad_sector="Financial Services",
        sector="Banking",
        broad_industry="Private Sector Bank",
        industry="Private Sector Bank",
    )
    sector, industry = _extract_taxonomy(soup)
    assert sector == "Financial Services"
    assert industry == "Private Sector Bank"


def test_extract_falls_back_to_sector_when_broad_missing():
    # No "Broad Sector" anchor — must fall back to "Sector"
    soup = _make_soup(sector="Pharma", industry="API Manufacturers")
    sector, industry = _extract_taxonomy(soup)
    assert sector == "Healthcare"  # "Pharma" aliased
    assert industry == "API Manufacturers"


def test_extract_falls_back_to_broad_industry_when_sector_missing():
    # Neither Broad Sector nor Sector present — fall to Broad Industry
    soup = _make_soup(broad_industry="Auto Ancillaries", industry="Brake Components")
    sector, industry = _extract_taxonomy(soup)
    assert sector == "Consumer Cyclical"  # "Auto Ancillaries" aliased
    assert industry == "Brake Components"


def test_extract_industry_prefers_fine_grained():
    # Both Industry and Broad Industry present — prefer Industry (more specific)
    soup = _make_soup(
        broad_sector="Energy",
        broad_industry="Refineries",
        industry="Integrated Oil & Gas",
    )
    sector, industry = _extract_taxonomy(soup)
    assert sector == "Energy"
    assert industry == "Integrated Oil & Gas"


def test_extract_empty_soup():
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    sector, industry = _extract_taxonomy(soup)
    assert sector is None
    assert industry is None


def test_extract_unknown_sector_preserved():
    # Screener could one day return a label we haven't aliased; the helper
    # should preserve it (title-cased) rather than dropping it.
    soup = _make_soup(broad_sector="Aviation Services")
    sector, industry = _extract_taxonomy(soup)
    assert sector == "Aviation Services"  # passes normalize_sector fallthrough
    assert industry is None
