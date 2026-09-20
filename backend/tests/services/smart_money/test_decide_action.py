"""Decision-matrix tests — spec §10."""

import pytest

from app.api.today import decide_action_v2


def _call(**overrides):
    base = dict(
        ai_decision="HOLD",
        ai_confidence=50,
        news_sentiment=None,
        conviction_score=0.0,
        flow_score=0.0,
        red_flag_score=0.0,
        signal_breakdown=None,
    )
    base.update(overrides)
    return decide_action_v2(**base)


# Row 1: BUY + conf >= 70 + conv >= +60 + RF > -20 → HIGH CONVICTION BUY
def test_high_conviction_buy_when_all_aligned():
    r = _call(ai_decision="INVEST", ai_confidence=80, conviction_score=70, red_flag_score=-10)
    assert r.action == "HIGH CONVICTION BUY"
    assert r.confidence_tag == "HIGH CONVICTION"
    assert r.binding_signal == "conviction"


# Row 2: BUY + conv >= +30 + RF > -20 → BUY (confirmed)
def test_buy_confirmed_when_moderate_conviction():
    r = _call(ai_decision="INVEST", ai_confidence=60, conviction_score=40, red_flag_score=-5)
    assert r.action == "BUY"
    assert r.confidence_tag == "CONFIRMED"


# Row 3: BUY + conv < +30 + RF > -20 → BUY (unconfirmed)
def test_buy_unconfirmed_when_no_smart_money_backing():
    r = _call(ai_decision="INVEST", ai_confidence=60, conviction_score=10, red_flag_score=0)
    assert r.action == "BUY"
    assert r.confidence_tag == "UNCONFIRMED"
    assert r.binding_signal == "ai"


# Row 4: BUY (any) + RF <= -30 → REVIEW (red flag override)
def test_buy_with_red_flag_overrides_to_review():
    r = _call(ai_decision="INVEST", ai_confidence=80, conviction_score=70, red_flag_score=-40)
    assert r.action == "REVIEW"
    assert r.binding_signal == "red_flag"


def test_red_flag_override_surfaces_specific_flag_text():
    breakdown = {
        "red_flags": {
            "triggered": ["high_pledge"],
            "detail": {"high_pledge": {"penalty": -32, "pledge_pct": 52, "quarter": "Q4-2025"}},
        }
    }
    r = _call(
        ai_decision="INVEST",
        ai_confidence=70,
        conviction_score=50,
        red_flag_score=-32,
        signal_breakdown=breakdown,
    )
    assert r.action == "REVIEW"
    assert r.binding_signal == "red_flag"
    assert "pledge" in (r.red_flag_detail or "").lower()


# Row 5: HOLD + conv >= +60 + RF > -20 → ACCUMULATE
def test_hold_with_strong_conviction_promotes_to_accumulate():
    r = _call(ai_decision="WAIT", ai_confidence=40, conviction_score=70, red_flag_score=0)
    assert r.action == "ACCUMULATE"
    assert r.binding_signal == "conviction"


# Row 6: HOLD + conv <= -50 → WATCHFUL
def test_hold_with_negative_conviction_to_watchful():
    r = _call(ai_decision="WAIT", ai_confidence=40, conviction_score=-60, red_flag_score=0)
    assert r.action == "WATCHFUL"


# Row 7: SELL + conv <= -30 → STRONG SELL
def test_sell_confirmed_by_negative_conviction():
    r = _call(ai_decision="AVOID", ai_confidence=70, conviction_score=-50, red_flag_score=-10)
    assert r.action == "STRONG SELL"


# Row 8: SELL + conv >= +30 → REVIEW (institutions buying contradicts)
def test_sell_with_positive_conviction_flags_review():
    r = _call(ai_decision="AVOID", ai_confidence=70, conviction_score=40, red_flag_score=0)
    assert r.action == "REVIEW"
    assert r.binding_signal == "conviction"


# Row 9: WATCH + conv >= +60 → WATCH (INTERESTING)
def test_watch_with_strong_conviction_marks_interesting():
    r = _call(ai_decision="WAIT", ai_confidence=30, conviction_score=70, red_flag_score=-5)
    # WAIT maps to WATCH; +70 conv with mild RF → WATCH (INTERESTING).
    # But our matrix routes HOLD before WATCH; "WAIT" specifically maps to WATCH.
    # Override the AI decision explicitly for clarity:
    r2 = decide_action_v2(
        ai_decision="WATCH",
        ai_confidence=30,
        news_sentiment=None,
        conviction_score=70,
        flow_score=0,
        red_flag_score=-5,
        signal_breakdown=None,
    )
    assert r2.action == "WATCH (INTERESTING)"


# Edge: missing AI verdict defaults to HOLD path
def test_missing_ai_verdict_defaults_to_hold():
    r = _call(ai_decision=None, ai_confidence=None, conviction_score=0, red_flag_score=0)
    assert r.action == "HOLD"


# Edge: red flag = 0 should not trip the override path even on a buy
def test_buy_with_zero_red_flag_does_not_override():
    r = _call(ai_decision="BUY", ai_confidence=60, conviction_score=40, red_flag_score=0)
    assert r.action == "BUY"
    assert r.binding_signal != "red_flag"


# Confirm BUY verdicts (English form) are accepted equally
def test_uppercase_buy_verdict_accepted():
    r = _call(ai_decision="BUY", ai_confidence=80, conviction_score=70, red_flag_score=-5)
    assert r.action == "HIGH CONVICTION BUY"


# Sell with no smart-money signal still resolves to SELL
def test_sell_with_no_smart_money_resolves_to_sell():
    r = _call(ai_decision="AVOID", ai_confidence=60, conviction_score=0, red_flag_score=0)
    assert r.action == "SELL"
    assert r.binding_signal == "ai"
