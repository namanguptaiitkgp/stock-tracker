"""Tests for the holdings-signal decision tree (PR 10).

The DB-roundtrip half of `compute_holding_signal` runs against the
live DB in a smoke test; here we exercise the pure decision logic by
calling the `_confidence_for` helper and the direction-priority
sorting that the endpoint relies on.
"""

from app.services.smart_money.holdings_signal import (
    _confidence_for,
    _conviction_drivers,
    _red_flag_label,
)


# ---- _confidence_for --------------------------------------------------------


def test_high_when_coverage_and_signal_both_strong():
    assert _confidence_for(75, 50) == "HIGH"


def test_medium_when_coverage_decent_signal_modest():
    assert _confidence_for(60, 30) == "MEDIUM"


def test_low_when_coverage_thin_even_with_strong_signal():
    """Coverage is the binding constraint — a loud signal on thin data
    is still LOW confidence. Catches the spec's 'don't promise more
    than the data supports' rule."""
    assert _confidence_for(30, 80) == "LOW"


def test_low_when_signal_is_weak_regardless_of_coverage():
    assert _confidence_for(80, 5) == "LOW"


def test_medium_threshold_boundary():
    # 50/25 should hit the MEDIUM band exactly.
    assert _confidence_for(50, 25) == "MEDIUM"
    # Just below either threshold falls to LOW.
    assert _confidence_for(49, 25) == "LOW"
    assert _confidence_for(50, 24) == "LOW"


# ---- _red_flag_label --------------------------------------------------------


def test_red_flag_label_known_types():
    bd = {"red_flags": {"triggered": ["circular_trading"]}}
    assert _red_flag_label(bd) == "Circular trading suspected"
    bd = {"red_flags": {"triggered": ["high_pledge"]}}
    assert _red_flag_label(bd) == "High promoter pledge"
    bd = {"red_flags": {"triggered": ["pump_pattern"]}}
    assert _red_flag_label(bd) == "Pump pattern detected"


def test_red_flag_label_picks_first_when_multiple():
    bd = {"red_flags": {"triggered": ["promoter_selling", "high_pledge"]}}
    assert _red_flag_label(bd) == "Promoter selling"


def test_red_flag_label_handles_missing_breakdown():
    assert _red_flag_label(None) == "Red flags active"
    assert _red_flag_label({}) == "Red flags active"
    assert _red_flag_label({"red_flags": {"triggered": []}}) == "Red flags active"


def test_red_flag_label_falls_back_for_unknown_type():
    bd = {"red_flags": {"triggered": ["future_unknown_flag"]}}
    # Not in the label_map — falls back to title-cased key
    assert _red_flag_label(bd) == "Future Unknown Flag"


# ---- _conviction_drivers ----------------------------------------------------


def test_conviction_drivers_extracts_promoter_buying():
    bd = {"conviction": {"promoter_buying": {"raw": 183673, "normalized": 45, "source_rows": 1}}}
    drivers = _conviction_drivers(bd)
    assert any("Promoter market buying" in d for d in drivers)
    assert any("183,673" in d for d in drivers)


def test_conviction_drivers_extracts_mf_consensus():
    bd = {"conviction": {"mf_consensus": {"raw": 4, "normalized": 60, "increased": 4, "decreased": 1}}}
    drivers = _conviction_drivers(bd)
    assert any("4 MF houses adding" in d for d in drivers)


def test_conviction_drivers_extracts_shareholding_delta():
    bd = {"conviction": {"shareholding_delta": {"raw": 1.5, "normalized": 15, "quarter": "Q4-2025"}}}
    drivers = _conviction_drivers(bd)
    assert any("+1.50%" in d or "+1.5%" in d.replace(" QoQ", "").replace(" ", "") or "1.50" in d for d in drivers)


def test_conviction_drivers_skips_no_data_signals():
    bd = {
        "conviction": {
            "promoter_buying": {"raw": None, "note": "no data"},
            "mf_consensus": {"raw": 3, "normalized": 40, "increased": 3, "decreased": 0},
        }
    }
    drivers = _conviction_drivers(bd)
    assert len(drivers) == 1
    assert "MF houses" in drivers[0]


def test_conviction_drivers_handles_empty_breakdown():
    assert _conviction_drivers(None) == []
    assert _conviction_drivers({}) == []
    assert _conviction_drivers({"conviction": {}}) == []
