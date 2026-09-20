"""Smart market-trend computation from index quotes.

Combines:
- Major-cap weighted score (Nifty 50, Sensex, Bank Nifty, Midcap, Smallcap, sectorals)
- Breadth (fraction of indices with positive change_pct, excl. VIX)
- VIX modifier (rising VIX = risk-off; subtract from score)

Returns a structured trend snapshot consumed by the dashboard MarketPulse widget
and as input to the Gemini market-pulse prompt.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

# Index weights — sum to 1.00 (excluding VIX which is used as a modifier).
INDEX_WEIGHTS: dict[str, float] = {
    "nifty50":          0.40,  # broadest large-cap, headline
    "sensex":           0.25,  # most-cited
    "banknifty":        0.15,  # financials drive market
    "nifty_midcap100":  0.10,  # broader market
    "nifty_smlcap100":  0.05,  # risk-on/off proxy
    "nifty_it":         0.01,  # sectorals — distributed 0.05 across 5 sectors
    "nifty_fmcg":       0.01,
    "nifty_auto":       0.01,
    "nifty_pharma":     0.01,
    "nifty_energy":     0.01,
}


def _classify(score: float) -> tuple[str, str, str]:
    """Map adjusted score to (direction, magnitude, label)."""
    abs_s = abs(score)
    if abs_s < 0.20:
        return ("flat", "neutral", "Mostly Flat")
    if score > 0:
        if abs_s < 0.75: return ("up", "mild", "Mildly Rising")
        if abs_s < 1.50: return ("up", "moderate", "Moderately Rising")
        return ("up", "strong", "Sharply Rising")
    else:
        if abs_s < 0.75: return ("down", "mild", "Mildly Falling")
        if abs_s < 1.50: return ("down", "moderate", "Moderately Falling")
        return ("down", "strong", "Sharply Falling")


def compute_market_trend(indices: Iterable[dict]) -> dict:
    """Compute a market trend snapshot from a list of index quote dicts.

    Each input dict is the shape produced by `read_cached_quotes()` — needs
    `slug`, `change_pct`, optionally `ltp`, `display_name`, `short_name`.
    """
    by_slug: dict[str, dict] = {q["slug"]: q for q in indices}

    # SCORE — only weighted indices contribute. INDEX_WEIGHTS is the
    # curated set used for the macro-trend headline; sectorals at 0.01
    # each keep their tiny voice without letting a single sector skew
    # the verdict.
    weighted_sum = 0.0
    weight_used = 0.0
    for slug, weight in INDEX_WEIGHTS.items():
        q = by_slug.get(slug)
        if not q:
            continue
        cp = q.get("change_pct")
        if cp is None:
            continue
        weighted_sum += weight * float(cp)
        weight_used += weight

    # Normalize by used weight so a missing index doesn't shrink the score
    base_score = (weighted_sum / weight_used) if weight_used > 0 else 0.0

    # COMPONENTS — every index with a valid quote becomes a display card.
    # Decoupled from INDEX_WEIGHTS so newly-registered sectorals (Gift
    # Nifty, Nifty Metal, Nifty Realty, etc.) show up in the Market
    # Brief grid even though they don't carry weight in the score math.
    # VIX is handled separately below as a modifier, not a card.
    components: list[dict] = []
    for slug, q in by_slug.items():
        if slug == "india_vix":
            continue
        cp = q.get("change_pct")
        if cp is None:
            continue
        components.append({
            "slug": slug,
            "name": q.get("display_name") or q.get("short_name") or slug,
            "short_name": q.get("short_name") or slug,
            "ltp": float(q["ltp"]) if q.get("ltp") is not None else None,
            "change_pct": round(float(cp), 2),
            "weight": INDEX_WEIGHTS.get(slug, 0.0),
        })

    # Breadth: fraction of non-VIX indices with positive change_pct
    breadth_total = 0
    breadth_up = 0
    for q in by_slug.values():
        if q["slug"] == "india_vix":
            continue
        cp = q.get("change_pct")
        if cp is None:
            continue
        breadth_total += 1
        if float(cp) > 0:
            breadth_up += 1
    breadth = (breadth_up / breadth_total) if breadth_total else 0.0

    # VIX modifier
    vix_q = by_slug.get("india_vix")
    vix_change = float(vix_q["change_pct"]) if vix_q and vix_q.get("change_pct") is not None else None
    vix_adjustment = 0.0
    if vix_change is not None:
        if vix_change > 5.0:
            vix_adjustment = -0.15  # fear
        elif vix_change < -5.0:
            vix_adjustment = 0.05   # calm

    adjusted_score = base_score + vix_adjustment

    direction, magnitude, label = _classify(adjusted_score)

    return {
        "direction": direction,
        "magnitude": magnitude,
        "label": label,
        "score": round(base_score, 3),
        "adjusted_score": round(adjusted_score, 3),
        "breadth": round(breadth, 3),
        "breadth_up": breadth_up,
        "breadth_total": breadth_total,
        "vix": ({
            "ltp": float(vix_q["ltp"]) if vix_q.get("ltp") is not None else None,
            "change_pct": vix_change,
        } if vix_q else None),
        "components": components,
        "as_of": datetime.now(tz=timezone.utc).isoformat(),
    }
