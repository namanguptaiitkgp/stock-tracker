"""Nifty sector-index membership lookup.

Resolves a stock's canonical sector by checking which Nifty sector index
(Nifty IT, Nifty Auto, Nifty FMCG, Nifty Pharma, Nifty Energy, Nifty Bank,
Nifty Metal, Nifty Realty, Nifty Media, Nifty Pvt Bank, Nifty PSU Bank)
contains it. Used as the second-priority source in `sector_resolver.py`
(after manual override, before Screener.in / yfinance).

Data lives in `backend/app/data/nifty_sector_constituents.json`. The file
is a quarterly-curated seed — Nifty indices only reconstitute on the last
business day of March / June / September / December, so a manual PR
every three months is sufficient. There is intentionally no scraper or
Celery task; the trade-off is documented in the plan at
`~/.claude/plans/parsed-finding-hinton.md` § Task 4.

Refresh playbook:
  1. Pull the latest factsheets from https://niftyindices.com/indices/equity/sectoral-indices
     for each tracked index (IT, Bank, Auto, FMCG, Pharma, Energy, Metal,
     Realty, Media, Pvt Bank, PSU Bank).
  2. Update `symbols` in the JSON for any index whose constituents changed.
  3. Bump the top-level `as_of` field to today's date.
  4. PR the diff for review; merging redeploys via the standard pipeline.

The JSON's `sector` field for each index must match a value in
`screener_presets.INDEX_TO_SECTOR` — this is enforced at load time.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.services.screener_presets import (
    CANONICAL_SECTORS,
    INDEX_TO_SECTOR,
)

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent.parent / "data" / "nifty_sector_constituents.json"


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, str], date, dict[str, set[str]]]:
    """Loads the JSON once and returns (symbol→sector, as_of_date,
    sector→symbol_set). LRU-cached so the file is read at most once per
    process; clear with `_load.cache_clear()` if you need to reload
    after an edit (e.g., during tests)."""
    try:
        payload = json.loads(_DATA_PATH.read_text())
    except FileNotFoundError:
        logger.error("nifty_membership: seed JSON not found at %s", _DATA_PATH)
        return {}, date.min, {}
    except json.JSONDecodeError as e:
        logger.error("nifty_membership: seed JSON is malformed: %s", e)
        return {}, date.min, {}

    symbol_to_sector: dict[str, str] = {}
    sector_to_symbols: dict[str, set[str]] = {s: set() for s in CANONICAL_SECTORS}
    as_of_str = payload.get("as_of", "1970-01-01")
    try:
        as_of = date.fromisoformat(as_of_str)
    except ValueError:
        logger.warning("nifty_membership: invalid as_of %r, defaulting to epoch", as_of_str)
        as_of = date.min

    for entry in payload.get("indices", []):
        slug = entry.get("slug")
        declared = entry.get("sector")
        symbols = entry.get("symbols") or []

        # Cross-check: the JSON's `sector` must match INDEX_TO_SECTOR. This
        # prevents the JSON drifting from the canonical mapping silently.
        canonical = INDEX_TO_SECTOR.get(slug)
        if canonical is None:
            logger.warning(
                "nifty_membership: index %r not in INDEX_TO_SECTOR, skipping",
                slug,
            )
            continue
        if declared != canonical:
            logger.warning(
                "nifty_membership: index %r declares sector %r but "
                "INDEX_TO_SECTOR has %r — using INDEX_TO_SECTOR",
                slug, declared, canonical,
            )

        for sym in symbols:
            sym_u = sym.strip().upper()
            if not sym_u:
                continue
            # First-write wins on overlap (e.g., HDFCBANK appears in both
            # nifty_bank and nifty_pvt_bank but both map to Financial
            # Services, so the resolution is the same either way).
            symbol_to_sector.setdefault(sym_u, canonical)
            sector_to_symbols[canonical].add(sym_u)

    return symbol_to_sector, as_of, sector_to_symbols


def get_sector_for_symbol(symbol: str) -> str | None:
    """O(1) lookup. Returns the canonical sector if `symbol` is in any
    tracked Nifty sector index, else None."""
    if not symbol:
        return None
    table, _, _ = _load()
    return table.get(symbol.strip().upper())


def get_constituents(sector: str) -> set[str]:
    """All symbols tagged to a canonical `sector` via Nifty index
    membership. Empty set if the sector is not in CANONICAL_SECTORS or
    has no constituents in the seed."""
    _, _, by_sector = _load()
    return set(by_sector.get(sector, set()))


def as_of_date() -> date:
    """The `as_of` field from the JSON seed. Used by
    `/api/admin/sector-coverage` to flag a stale seed (>120 days = nudge
    the user to refresh)."""
    _, as_of, _ = _load()
    return as_of


def total_symbols() -> int:
    """Count of distinct symbols covered by the seed. Useful in
    diagnostics and tests."""
    table, _, _ = _load()
    return len(table)
