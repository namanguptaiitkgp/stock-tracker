"""Tests for the hard/soft filter logic in the fundamental evaluator
(PR 9 — `indian_stock_screener_criteria.md`).

The DB-roundtrip path is exercised by the live `apply-preset` smoke
test. Here we lock down the gate semantics: hard-fail rejects the
stock; missing data never auto-fails; soft-only verdicts use the
75/50/0 banding.
"""

from datetime import datetime
from types import SimpleNamespace

from app.services.fundamental_analysis import (
    VERDICT_FAIR,
    VERDICT_REJECTED,
    VERDICT_STRONG,
    VERDICT_WEAK,
    _evaluate_rule,
)


def _rule(*, key: str, op: str = "gte", val: float | None = None,
          low: float | None = None, high: float | None = None,
          weight: int = 1, hard: bool = False, enabled: bool = True):
    return SimpleNamespace(
        metric_key=key,
        operator=op,
        value_num=val,
        value_low=low,
        value_high=high,
        weight=weight,
        is_hard_filter=hard,
        enabled=enabled,
    )


# Reproduce the in-memory part of `evaluate()` so we don't need a DB.
def _verdict(rules, values):
    n_passed = n_failed = n_missing = 0
    weighted_passed = 0.0
    weighted_eligible = 0.0
    hard_failed: list[str] = []
    soft_score = 0
    soft_total = 0
    for r in rules:
        actual = values.get(r.metric_key)
        status = _evaluate_rule(r, actual)
        if status == "passed":
            n_passed += 1
            weighted_passed += r.weight
            weighted_eligible += r.weight
            if not r.is_hard_filter:
                soft_score += 1
                soft_total += 1
        elif status == "failed":
            n_failed += 1
            weighted_eligible += r.weight
            if r.is_hard_filter:
                hard_failed.append(r.metric_key)
            else:
                soft_total += 1
        else:
            n_missing += 1

    rules_total = len(rules)
    hard_passed = len(hard_failed) == 0

    if rules_total == 0:
        return ("NA", None, hard_passed, hard_failed, soft_score, soft_total)
    if not hard_passed:
        score = round((soft_score / soft_total) * 100.0, 1) if soft_total > 0 else None
        return (VERDICT_REJECTED, score, hard_passed, hard_failed, soft_score, soft_total)
    if (n_passed + n_failed) < max(1, rules_total // 2):
        return ("NA", None, hard_passed, hard_failed, soft_score, soft_total)

    if soft_total > 0:
        soft_pct = (soft_score / soft_total) * 100.0
    elif weighted_eligible > 0:
        soft_pct = (weighted_passed / weighted_eligible) * 100.0
    else:
        soft_pct = None
    score = round(soft_pct, 1) if soft_pct is not None else None
    if soft_pct is None:
        verdict = "NA"
    elif soft_pct >= 75:
        verdict = VERDICT_STRONG
    elif soft_pct >= 50:
        verdict = VERDICT_FAIR
    else:
        verdict = VERDICT_WEAK
    return (verdict, score, hard_passed, hard_failed, soft_score, soft_total)


# ---------------------------------------------------------------------------


def test_hard_fail_rejects_regardless_of_soft_score():
    rules = [
        _rule(key="pe_ratio", op="lte", val=40, hard=True),
        _rule(key="roe", op="gte", val=0.12, hard=True),
        _rule(key="net_profit_margin", op="gte", val=0.05, hard=False),
        _rule(key="debt_to_equity", op="lte", val=1.5, hard=False),
    ]
    values = {"pe_ratio": 50, "roe": 0.15, "net_profit_margin": 0.10, "debt_to_equity": 1.0}
    verdict, score, hard_passed, hard_failed, ss, st = _verdict(rules, values)
    assert verdict == VERDICT_REJECTED
    assert hard_passed is False
    assert hard_failed == ["pe_ratio"]
    # Soft score still computed: both soft rules pass → 2/2
    assert (ss, st) == (2, 2)


def test_missing_data_does_not_auto_fail_hard():
    """Per spec §3 — null metrics are skipped, not failed.
    The presence of a missing metric must NOT push the stock to
    REJECTED. Here only `pe_ratio` has data; `roe` is missing.
    Hard-passed must be True (no genuine fail) and the verdict
    should be driven by whatever soft data exists.
    """
    rules = [
        _rule(key="pe_ratio", op="lte", val=40, hard=True),
        _rule(key="roe", op="gte", val=0.12, hard=True),
    ]
    values = {"pe_ratio": 25}  # roe missing
    verdict, _, hard_passed, hard_failed, _, _ = _verdict(rules, values)
    assert hard_passed is True
    assert hard_failed == []
    # No soft rules → falls back to weighted-pass percentage of the
    # one eligible hard rule (pe_ratio passed) = 100% → STRONG.
    # The crucial guarantee is REJECTED is NOT returned.
    assert verdict != VERDICT_REJECTED


def test_all_hard_pass_with_soft_above_75_yields_strong():
    rules = [
        _rule(key="roe", op="gte", val=0.12, hard=True),
        _rule(key="net_profit_margin", op="gte", val=0.05, hard=True),
        _rule(key="pb_ratio", op="lte", val=8, hard=False),
        _rule(key="forward_pe", op="lte", val=30, hard=False),
        _rule(key="ebitda_margin", op="gte", val=0.10, hard=False),
        _rule(key="cash_flow_margin", op="gte", val=0.05, hard=False),
    ]
    values = {
        "roe": 0.18, "net_profit_margin": 0.12,
        "pb_ratio": 4, "forward_pe": 22,
        "ebitda_margin": 0.18, "cash_flow_margin": 0.08,
    }
    verdict, score, hard_passed, _, ss, st = _verdict(rules, values)
    assert hard_passed is True
    assert (ss, st) == (4, 4)
    assert score == 100.0
    assert verdict == VERDICT_STRONG


def test_soft_at_50_to_74_pct_yields_fair():
    rules = [
        _rule(key="roe", op="gte", val=0.12, hard=True),
        _rule(key="pb_ratio", op="lte", val=8, hard=False),
        _rule(key="forward_pe", op="lte", val=30, hard=False),
        _rule(key="ebitda_margin", op="gte", val=0.10, hard=False),
        _rule(key="cash_flow_margin", op="gte", val=0.05, hard=False),
    ]
    # 2 of 4 soft pass → 50%
    values = {
        "roe": 0.20,
        "pb_ratio": 4, "forward_pe": 22,
        "ebitda_margin": 0.05, "cash_flow_margin": 0.02,
    }
    verdict, score, _, _, ss, st = _verdict(rules, values)
    assert (ss, st) == (2, 4)
    assert score == 50.0
    assert verdict == VERDICT_FAIR


def test_soft_below_50_pct_yields_weak():
    rules = [
        _rule(key="roe", op="gte", val=0.12, hard=True),
        _rule(key="pb_ratio", op="lte", val=8, hard=False),
        _rule(key="forward_pe", op="lte", val=30, hard=False),
        _rule(key="ebitda_margin", op="gte", val=0.10, hard=False),
        _rule(key="cash_flow_margin", op="gte", val=0.05, hard=False),
    ]
    # 1 of 4 soft pass → 25%
    values = {
        "roe": 0.20,
        "pb_ratio": 4, "forward_pe": 35,
        "ebitda_margin": 0.05, "cash_flow_margin": 0.02,
    }
    verdict, score, _, _, ss, st = _verdict(rules, values)
    assert (ss, st) == (1, 4)
    assert score == 25.0
    assert verdict == VERDICT_WEAK


def test_between_operator_used_for_pe_band():
    rules = [_rule(key="pe_ratio", op="between", low=5, high=40, hard=True)]
    # 50 is above the band → fail
    v1, _, hp1, hf1, _, _ = _verdict(rules, {"pe_ratio": 50})
    assert hp1 is False and hf1 == ["pe_ratio"]
    # 25 is inside the band → pass
    v2, _, hp2, hf2, _, _ = _verdict(rules, {"pe_ratio": 25})
    assert hp2 is True and hf2 == []
    # 3 is below the band → fail (the screener excludes distressed PE)
    v3, _, hp3, hf3, _, _ = _verdict(rules, {"pe_ratio": 3})
    assert hp3 is False and hf3 == ["pe_ratio"]


def test_is_positive_operator_for_ocf():
    rules = [_rule(key="operating_cash_flow", op="is_positive", hard=True)]
    # OCF +50 Cr → pass
    _, _, hp, _, _, _ = _verdict(rules, {"operating_cash_flow": 50.0})
    assert hp is True
    # OCF -10 Cr → hard fail
    _, _, hp2, hf2, _, _ = _verdict(rules, {"operating_cash_flow": -10.0})
    assert hp2 is False and hf2 == ["operating_cash_flow"]


def test_no_hard_rules_falls_back_to_soft_only_path():
    """A user running the legacy all-soft rule set still gets a verdict
    via the soft-percentage banding."""
    rules = [
        _rule(key="roe", op="gte", val=0.12, hard=False),
        _rule(key="pb_ratio", op="lte", val=8, hard=False),
    ]
    # 2/2 → STRONG
    values = {"roe": 0.20, "pb_ratio": 4}
    verdict, _, hp, hf, _, _ = _verdict(rules, values)
    assert hp is True and hf == []
    assert verdict == VERDICT_STRONG
