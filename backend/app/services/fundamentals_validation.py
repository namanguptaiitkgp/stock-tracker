"""Sanity-bounds validation for fundamental metrics.

Catches yfinance / Screener / Gemini garbage at the write boundary so it
doesn't reach the database (where `NUMERIC(p, s)` columns silently
overflow into PendingRollbackError cascades) and doesn't reach the AI
prompt or peer ranker (where a P/E of 1.17 billion silently produces
hallucinated verdicts).

History — prior fixes in this codebase were field-specific inline
lambdas applied at one source:
  - 070b6ca: market_cap / 1e7 in _fetch_from_yfinance (raw rupees → crores)
  - a714cbe: D/E clamp >50x → None (near-zero-equity blow-ups)
This module centralises the pattern so the next yfinance quirk only
needs a bounds entry, not another inline lambda. Bounds live here and
every write path calls clamp_fundamentals() before db.add().

Bounds are deliberately wide. Goal is to catch real outages (FINOLEXIND
returning ₹30B as a share price) without filtering legitimate
extremes (loss-making small-caps with trailing P/E in the thousands).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# (lo, hi) inclusive. Values outside are dropped to None.
SANITY_BOUNDS: dict[str, tuple[float, float]] = {
    # Prices
    "cmp":                      (0.01, 1_000_000),
    "high_52w":                 (0.01, 1_000_000),
    "low_52w":                  (0.01, 1_000_000),
    # Market cap (stored in crores per 070b6ca normalisation)
    "market_cap":               (1, 50_000_000),
    # Multiples — generous to allow loss-makers (negative P/E) and
    # pre-profitability tech names (large positive P/E).
    "pe_ratio":                 (-1000, 10_000),
    "ttm_pe":                   (-1000, 10_000),
    "forward_pe":               (-1000, 10_000),
    "pb_ratio":                 (0, 500),
    # Returns / margins (percent or ratio, codebase varies — these
    # bounds cover both interpretations)
    "roe":                      (-100, 200),
    "net_profit_margin":        (-100, 100),
    # Leverage
    "debt_to_equity":           (0, 100),
    # Yield / holdings (percent, 0–100)
    "dividend_yield":           (0, 50),
    "promoter_holding":         (0, 100),
    # Growth rates — wide because trailing 1y growth on small-caps can
    # legitimately swing 1000%+ on base-effect quarters.
    "revenue_growth_1y":        (-100, 1000),
    "eps_growth_1y":            (-1000, 10_000),
    "earnings_growth_forward":  (-1000, 10_000),
}


def clamp_fundamentals(values: dict[str, Any], *, source: str = "unknown") -> dict[str, Any]:
    """Return a copy of `values` with out-of-range fields set to None.

    Each rejected field is logged with `source` so we can grep
    `fundamentals_validation:` in worker logs to spot a misbehaving
    upstream (per-symbol, per-field, per-source).

    Fields not in `SANITY_BOUNDS` pass through untouched — e.g.
    string fields like name/sector/industry.
    """
    out = dict(values)
    for key, val in list(out.items()):
        bounds = SANITY_BOUNDS.get(key)
        if val is None or bounds is None:
            continue
        try:
            f = float(val)
        except (TypeError, ValueError):
            logger.warning(
                "fundamentals_validation: non-numeric %s=%r dropped (source=%s)",
                key, val, source,
            )
            out[key] = None
            continue
        if f != f:  # NaN
            out[key] = None
            continue
        lo, hi = bounds
        if not (lo <= f <= hi):
            logger.warning(
                "fundamentals_validation: dropped %s=%s (out of [%s, %s], source=%s)",
                key, val, lo, hi, source,
            )
            out[key] = None
    return out
