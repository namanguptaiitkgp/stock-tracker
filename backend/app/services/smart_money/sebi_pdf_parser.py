"""Two-tier SEBI PDF parser: pdfplumber first, Gemini multimodal fallback.

Used by `sebi_pms.py` and `sebi_aif.py` for quarterly disclosure PDFs.

Primary path (cheap, deterministic):
- Open with `pdfplumber`, extract tables page-by-page.
- Heuristic: a holdings table has header row containing any of
  {"isin", "scrip", "instrument", "symbol"} and any of
  {"quantity", "units", "market value", "%"}.
- Normalize column names, parse numbers, return list of rows.

Fallback path (robust, costs Gemini tokens):
- When pdfplumber returns fewer than MIN_ROWS_HEURISTIC or no tables,
  send the PDF to Gemini (multimodal) with a structured-extraction prompt
  that asks for {entity, strategy_or_category, as_of, holdings: [...]}.

Callers pass a PDF URL (or bytes) and an `entity` (PMS manager name / AIF
fund name). Returns the normalized payload:

    {
      "entity": str,
      "strategy_or_category": str | None,
      "as_of": date,                # quarter-end
      "holdings": [
        {
          "instrument_name_raw": str,
          "isin": str | None,
          "symbol": str | None,      # resolved via stock_resolver
          "units": float | None,
          "market_value_inr": float | None,
          "pct_of_total": float | None,
        },
        ...
      ],
      "source_url": str | None,
      "parsed_by": "pdfplumber" | "gemini",
    }

This module is currently a scaffolded stub. Implement when you have real
SEBI PMS / AIF PDFs to test against.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


MIN_ROWS_HEURISTIC = 5


async def parse_pdf(
    pdf_bytes: bytes,
    *,
    entity: str,
    as_of: date,
    source_url: str | None = None,
    strategy_or_category: str | None = None,
) -> dict[str, Any]:
    """Parse a SEBI PMS/AIF disclosure PDF. Stub raises NotImplementedError."""
    raise NotImplementedError(
        "SEBI PDF parsing not implemented yet. "
        "Ship real fixture PDFs, then wire pdfplumber (see module docstring)."
    )


async def _parse_with_pdfplumber(pdf_bytes: bytes) -> list[dict[str, Any]]:
    """Extract holdings rows via pdfplumber. Returns [] on failure."""
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        logger.warning("pdfplumber not installed; install via requirements.txt")
        return []
    # Implementation pending — see module docstring
    return []


async def _parse_with_gemini(pdf_bytes: bytes, prompt: str) -> list[dict[str, Any]]:
    """Multimodal Gemini call for PDFs that pdfplumber can't parse."""
    # Implementation pending — see module docstring
    return []
