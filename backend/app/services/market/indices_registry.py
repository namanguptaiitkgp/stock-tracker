"""Hardcoded catalog of tracked indices. Order here = order on the strip."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IndexEntry:
    slug: str
    display_name: str
    short_name: str
    provider: str  # "kite" | "scrape"
    source_symbol: str | None  # Kite symbol like "NSE:NIFTY 50", or URL key for scrape
    search_query: str  # query fragment for Google News RSS


# Sensex first per user preference.
INDICES: list[IndexEntry] = [
    IndexEntry(
        slug="sensex",
        display_name="BSE Sensex",
        short_name="Sensex",
        provider="kite",
        source_symbol="BSE:SENSEX",
        search_query='"BSE Sensex" OR "Sensex" India stock market today',
    ),
    IndexEntry(
        slug="nifty50",
        display_name="Nifty 50",
        short_name="Nifty",
        provider="kite",
        source_symbol="NSE:NIFTY 50",
        search_query='"Nifty 50" India stock market today',
    ),
    IndexEntry(
        slug="banknifty",
        display_name="Nifty Bank",
        short_name="BankNifty",
        provider="kite",
        source_symbol="NSE:NIFTY BANK",
        search_query='"Bank Nifty" India banking stocks today',
    ),
    IndexEntry(
        slug="gift_nifty",
        display_name="Gift Nifty",
        short_name="GiftNifty",
        provider="scrape",
        source_symbol="gift_nifty",
        search_query='"Gift Nifty" OR "SGX Nifty" pre-market India',
    ),
    IndexEntry(
        slug="india_vix",
        display_name="India VIX",
        short_name="VIX",
        provider="kite",
        source_symbol="NSE:INDIA VIX",
        search_query='"India VIX" volatility NSE',
    ),
    IndexEntry(
        slug="nifty_it",
        display_name="Nifty IT",
        short_name="Nifty IT",
        provider="kite",
        source_symbol="NSE:NIFTY IT",
        search_query='"Nifty IT" Indian IT stocks TCS Infosys',
    ),
    IndexEntry(
        slug="nifty_midcap100",
        display_name="Nifty Midcap 100",
        short_name="Midcap 100",
        provider="kite",
        source_symbol="NSE:NIFTY MIDCAP 100",
        search_query='"Nifty Midcap 100" India midcap stocks',
    ),
    IndexEntry(
        slug="nifty_smlcap100",
        display_name="Nifty Smallcap 100",
        short_name="Smallcap 100",
        provider="kite",
        source_symbol="NSE:NIFTY SMLCAP 100",
        search_query='"Nifty Smallcap" India smallcap stocks',
    ),
    IndexEntry(
        slug="nifty_fmcg",
        display_name="Nifty FMCG",
        short_name="FMCG",
        provider="kite",
        source_symbol="NSE:NIFTY FMCG",
        search_query='"Nifty FMCG" HUL ITC Nestle',
    ),
    IndexEntry(
        slug="nifty_auto",
        display_name="Nifty Auto",
        short_name="Auto",
        provider="kite",
        source_symbol="NSE:NIFTY AUTO",
        search_query='"Nifty Auto" India auto stocks Maruti Tata Motors',
    ),
    IndexEntry(
        slug="nifty_pharma",
        display_name="Nifty Pharma",
        short_name="Pharma",
        provider="kite",
        source_symbol="NSE:NIFTY PHARMA",
        search_query='"Nifty Pharma" India pharma Sun Pharma Cipla',
    ),
    IndexEntry(
        slug="nifty_energy",
        display_name="Nifty Energy",
        short_name="Energy",
        provider="kite",
        source_symbol="NSE:NIFTY ENERGY",
        search_query='"Nifty Energy" Reliance ONGC IOC oil gas',
    ),
    # Additional NSE sectoral indices added so every canonical sector
    # has a matching index card in Market Brief. Kite symbol names match
    # the active instruments dump; any mismatch surfaces as
    # status='unavailable' + error_message in index_quote_cache.
    IndexEntry(
        slug="nifty_fin_services",
        display_name="Nifty Financial Services",
        short_name="Fin Services",
        provider="kite",
        source_symbol="NSE:NIFTY FIN SERVICE",
        search_query='"Nifty Financial Services" India HDFC Bank ICICI Bajaj Finance',
    ),
    IndexEntry(
        slug="nifty_healthcare",
        display_name="Nifty Healthcare",
        short_name="Healthcare",
        provider="kite",
        source_symbol="NSE:NIFTY HEALTHCARE",
        search_query='"Nifty Healthcare" India hospital pharma Apollo Sun Pharma',
    ),
    IndexEntry(
        slug="nifty_consr_durbl",
        display_name="Nifty Consumer Durables",
        short_name="Cons Durbl",
        provider="kite",
        source_symbol="NSE:NIFTY CONSR DURBL",
        search_query='"Nifty Consumer Durables" India Titan Havells Voltas',
    ),
    IndexEntry(
        slug="nifty_metal",
        display_name="Nifty Metal",
        short_name="Metal",
        provider="kite",
        source_symbol="NSE:NIFTY METAL",
        search_query='"Nifty Metal" India Tata Steel JSW Hindalco',
    ),
    IndexEntry(
        slug="nifty_media",
        display_name="Nifty Media",
        short_name="Media",
        provider="kite",
        source_symbol="NSE:NIFTY MEDIA",
        search_query='"Nifty Media" India Zee Sun TV PVR Inox',
    ),
    IndexEntry(
        slug="nifty_realty",
        display_name="Nifty Realty",
        short_name="Realty",
        provider="kite",
        source_symbol="NSE:NIFTY REALTY",
        search_query='"Nifty Realty" India DLF Godrej Properties Oberoi',
    ),
    IndexEntry(
        slug="nifty_infra",
        display_name="Nifty Infrastructure",
        short_name="Infra",
        provider="kite",
        source_symbol="NSE:NIFTY INFRA",
        search_query='"Nifty Infrastructure" India L&T Adani Ports GMR',
    ),
    IndexEntry(
        slug="nifty_pvt_bank",
        display_name="Nifty Private Bank",
        short_name="Pvt Bank",
        provider="kite",
        source_symbol="NSE:NIFTY PVT BANK",
        search_query='"Nifty Private Bank" India HDFC ICICI Kotak Axis',
    ),
    IndexEntry(
        slug="nifty_psu_bank",
        display_name="Nifty PSU Bank",
        short_name="PSU Bank",
        provider="kite",
        source_symbol="NSE:NIFTY PSU BANK",
        search_query='"Nifty PSU Bank" India SBI Bank of Baroda Canara',
    ),
    IndexEntry(
        slug="nifty_oil_gas",
        display_name="Nifty Oil & Gas",
        short_name="Oil & Gas",
        provider="kite",
        source_symbol="NSE:NIFTY OIL AND GAS",
        search_query='"Nifty Oil and Gas" India Reliance ONGC IOC',
    ),
]


_BY_SLUG: dict[str, IndexEntry] = {e.slug: e for e in INDICES}


def get_entry(slug: str) -> IndexEntry | None:
    return _BY_SLUG.get(slug)
