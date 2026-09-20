"""Pure-rule Fundamental Analysis evaluator.

Reads the latest `metric_snapshots` row for a symbol, applies a user's
`FundamentalRuleSet`, returns a STRONG / FAIR / WEAK / NA verdict plus a
score 0–100 and per-rule breakdown.

Zero AI calls. Cheap to run inline on the watchlist `/detail` handler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fundamental_rule import FundamentalRule, FundamentalRuleSet
from app.models.fundamentals import StockFundamentals
from app.models.metric import MetricSnapshot

VERDICT_STRONG = "STRONG"
VERDICT_FAIR = "FAIR"
VERDICT_WEAK = "WEAK"
VERDICT_REJECTED = "REJECTED"  # any hard filter failed
VERDICT_NA = "NA"


@dataclass
class RuleEval:
    metric_key: str
    operator: str
    threshold: dict[str, float | None]
    weight: int
    is_hard_filter: bool
    actual: float | str | None
    status: str  # "passed" | "failed" | "missing"


@dataclass
class FundamentalVerdict:
    verdict: str
    score: float | None
    rules_total: int
    rules_passed: int
    rules_failed: int
    rules_missing: int
    # Screener hard/soft split (addendum / indian_stock_screener_criteria.md).
    # `hard_passed` means EVERY hard rule either passed or had missing
    # data — per spec §3, missing data does not auto-fail. `hard_failed`
    # lists the metric keys that genuinely failed their hard threshold;
    # if non-empty the verdict is REJECTED.
    hard_passed: bool
    hard_failed: list[str]
    soft_score: int       # count of soft rules passed
    soft_total: int       # count of soft rules with usable data
    breakdown: list[RuleEval]
    evaluated_at: datetime
    snapshot_run_id: int | None
    snapshot_fetched_at: datetime | None
    snapshot_values: dict[str, Any] = field(default_factory=dict)
    snapshot_sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "rules_total": self.rules_total,
            "rules_passed": self.rules_passed,
            "rules_failed": self.rules_failed,
            "rules_missing": self.rules_missing,
            "hard_passed": self.hard_passed,
            "hard_failed": self.hard_failed,
            "soft_score": self.soft_score,
            "soft_total": self.soft_total,
            "breakdown": [
                {
                    "metric_key": r.metric_key,
                    "operator": r.operator,
                    "threshold": r.threshold,
                    "weight": r.weight,
                    "is_hard_filter": r.is_hard_filter,
                    "actual": r.actual,
                    "status": r.status,
                }
                for r in self.breakdown
            ],
            "evaluated_at": self.evaluated_at.isoformat(),
            "snapshot_run_id": self.snapshot_run_id,
            "snapshot_fetched_at": self.snapshot_fetched_at.isoformat() if self.snapshot_fetched_at else None,
            "snapshot_values": self.snapshot_values,
            "snapshot_sources": self.snapshot_sources,
        }


def _coerce_num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# When the actual value is within this tolerance of the threshold we treat
# the rule as passing rather than failing — eliminates "P/B 2.0 below 2.0"-
# style warnings where the displayed value (1dp) rounds to the threshold but
# the underlying float is slightly below it. Two display digits of tolerance
# is enough to cover any visible value at 1dp precision.
_BOUNDARY_TOLERANCE = 0.01


def _evaluate_rule(rule: FundamentalRule, value: Any) -> str:
    """Returns 'passed' | 'failed' | 'missing'."""
    if value is None:
        return "missing"
    actual = _coerce_num(value)
    op = (rule.operator or "").lower()
    if op == "is_positive":
        if actual is None:
            return "missing"
        return "passed" if actual > 0 else "failed"
    # All other operators expect a numeric `actual`.
    if actual is None:
        return "missing"
    if op == "between":
        lo = _coerce_num(rule.value_low)
        hi = _coerce_num(rule.value_high)
        if lo is None or hi is None:
            return "missing"
        return "passed" if (
            lo - _BOUNDARY_TOLERANCE <= actual <= hi + _BOUNDARY_TOLERANCE
        ) else "failed"
    threshold = _coerce_num(rule.value_num)
    if threshold is None:
        return "missing"
    # Boundary tolerance: a value that displays identically to the threshold
    # at 1dp precision shouldn't trigger a fail.
    if abs(actual - threshold) < _BOUNDARY_TOLERANCE:
        return "passed"
    if op in ("gte", ">="):
        return "passed" if actual >= threshold else "failed"
    if op in ("lte", "<="):
        return "passed" if actual <= threshold else "failed"
    if op in ("gt", ">"):
        return "passed" if actual > threshold else "failed"
    if op in ("lt", "<"):
        return "passed" if actual < threshold else "failed"
    if op in ("eq", "=="):
        return "passed" if abs(actual - threshold) < 1e-9 else "failed"
    return "missing"


async def get_default_rule_set(db: AsyncSession, user_id: int) -> FundamentalRuleSet | None:
    res = await db.execute(
        select(FundamentalRuleSet)
        .where(FundamentalRuleSet.user_id == user_id, FundamentalRuleSet.is_default.is_(True))
        .limit(1)
    )
    return res.scalar_one_or_none()


async def get_or_create_default_rule_set(db: AsyncSession, user_id: int) -> FundamentalRuleSet:
    rs = await get_default_rule_set(db, user_id)
    if rs is not None:
        return rs
    rs = FundamentalRuleSet(user_id=user_id, name="Defaults", is_default=True)
    db.add(rs)
    await db.flush()
    return rs


async def _latest_snapshot(db: AsyncSession, symbol: str) -> MetricSnapshot | None:
    res = await db.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.symbol == symbol.upper())
        .order_by(MetricSnapshot.fetched_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


# Fields on StockFundamentals that map 1:1 to metric_keys used by rule sets.
# The metric_engine system writes the same keys to MetricSnapshot.values_json.
# Until both writers are unified (see unify-fundamentals spec), we read from
# StockFundamentals as a fallback so the FA verdict isn't NA just because
# nobody triggered a metric_engine refresh for these symbols.
_FUND_TO_VALUES_FIELDS = (
    "cmp", "market_cap", "pe_ratio", "ttm_pe", "forward_pe", "pb_ratio",
    "revenue_growth_1y", "eps_growth_1y", "earnings_growth_forward",
    "net_profit_margin", "debt_to_equity", "dividend_yield", "roe",
    "promoter_holding",
)


def _fundamentals_to_values(f: StockFundamentals | None) -> dict[str, Any]:
    if not f:
        return {}
    out: dict[str, Any] = {}
    for k in _FUND_TO_VALUES_FIELDS:
        v = getattr(f, k, None)
        if v is None:
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            pass
    return out


async def _values_for_symbol(db: AsyncSession, symbol: str) -> tuple[dict[str, Any], MetricSnapshot | None, datetime | None]:
    """Return (values, snapshot, fetched_at). Falls back to StockFundamentals
    when no MetricSnapshot exists for the symbol or the snapshot is empty."""
    snap = await _latest_snapshot(db, symbol)
    values: dict[str, Any] = (snap.values_json if snap else {}) or {}
    fetched_at = snap.fetched_at if snap else None
    if not values:
        f = (await db.execute(
            select(StockFundamentals).where(StockFundamentals.symbol == symbol.upper())
        )).scalar_one_or_none()
        if f:
            values = _fundamentals_to_values(f)
            if f.fetched_at and not fetched_at:
                fetched_at = f.fetched_at
    return values, snap, fetched_at


async def _values_for_symbols_bulk(
    db: AsyncSession, symbols: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, MetricSnapshot]]:
    """Bulk variant. Returns (values_by_sym, snapshot_by_sym)."""
    sym_uppers = [s.upper() for s in symbols]
    snap_res = await db.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.symbol.in_(sym_uppers))
        .order_by(MetricSnapshot.symbol, MetricSnapshot.fetched_at.desc())
        .distinct(MetricSnapshot.symbol)
    )
    latest_by_sym: dict[str, MetricSnapshot] = {s.symbol: s for s in snap_res.scalars().all()}

    values_by_sym: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for sym in sym_uppers:
        snap = latest_by_sym.get(sym)
        v = (snap.values_json if snap else {}) or {}
        if v:
            values_by_sym[sym] = v
        else:
            missing.append(sym)

    if missing:
        funds_res = await db.execute(
            select(StockFundamentals).where(StockFundamentals.symbol.in_(missing))
        )
        for f in funds_res.scalars().all():
            v = _fundamentals_to_values(f)
            if v:
                values_by_sym[f.symbol] = v

    return values_by_sym, latest_by_sym


async def evaluate(
    db: AsyncSession,
    symbol: str,
    rule_set: FundamentalRuleSet,
) -> FundamentalVerdict:
    """Apply a rule set to the latest snapshot for `symbol`."""
    res = await db.execute(
        select(FundamentalRule)
        .where(FundamentalRule.rule_set_id == rule_set.id, FundamentalRule.enabled.is_(True))
        .order_by(FundamentalRule.sort_order)
    )
    rules = list(res.scalars().all())
    values, snap, _fetched_at = await _values_for_symbol(db, symbol)

    breakdown: list[RuleEval] = []
    weighted_passed = 0.0
    weighted_eligible = 0.0  # passed + failed
    n_passed = n_failed = n_missing = 0

    # Screener hard/soft accounting (per indian_stock_screener_criteria.md):
    hard_failed: list[str] = []
    soft_score = 0
    soft_total = 0

    for r in rules:
        actual = values.get(r.metric_key)
        status = _evaluate_rule(r, actual)
        is_hard = bool(getattr(r, "is_hard_filter", False))
        if status == "passed":
            n_passed += 1
            weighted_passed += r.weight
            weighted_eligible += r.weight
            if not is_hard:
                soft_score += 1
                soft_total += 1
        elif status == "failed":
            n_failed += 1
            weighted_eligible += r.weight
            if is_hard:
                # Hard rule failed with real data — gate breach.
                hard_failed.append(r.metric_key)
            else:
                soft_total += 1
        else:
            # missing — counts toward neither score nor hard-fail (spec §3)
            n_missing += 1
        breakdown.append(RuleEval(
            metric_key=r.metric_key,
            operator=r.operator,
            threshold={"value": _coerce_num(r.value_num), "low": _coerce_num(r.value_low), "high": _coerce_num(r.value_high)},
            weight=int(r.weight),
            is_hard_filter=is_hard,
            actual=actual if not isinstance(actual, dict) else None,
            status=status,
        ))

    rules_total = len(rules)
    hard_passed = len(hard_failed) == 0

    # Verdict logic:
    #   1. Any rule set with hard filters: a single hard-fail → REJECTED.
    #      Doesn't matter how the soft score looks; the user told us this
    #      stock should not enter the universe.
    #   2. Otherwise the soft score (X/N passed) drives bands:
    #        ≥75% soft passed → STRONG
    #        ≥50% soft passed → FAIR
    #        else            → WEAK
    #      For pure-soft (legacy) rule sets the soft denominator equals
    #      eligible-rules-with-data, so the bands match the legacy
    #      weighted-pass% calculation within rounding.
    if rules_total == 0:
        verdict = VERDICT_NA
        score = None
    elif not hard_passed:
        verdict = VERDICT_REJECTED
        score = round((soft_score / soft_total) * 100.0, 1) if soft_total > 0 else None
    elif (n_passed + n_failed) < max(1, rules_total // 2):
        # Need at least half the rules to have usable data to call it.
        verdict = VERDICT_NA
        score = None
    else:
        if soft_total > 0:
            soft_pct = (soft_score / soft_total) * 100.0
        elif weighted_eligible > 0:
            soft_pct = (weighted_passed / weighted_eligible) * 100.0
        else:
            soft_pct = None
        score = round(soft_pct, 1) if soft_pct is not None else None
        if soft_pct is None:
            verdict = VERDICT_NA
        elif soft_pct >= 75:
            verdict = VERDICT_STRONG
        elif soft_pct >= 50:
            verdict = VERDICT_FAIR
        else:
            verdict = VERDICT_WEAK

    return FundamentalVerdict(
        verdict=verdict,
        score=score,
        rules_total=rules_total,
        rules_passed=n_passed,
        rules_failed=n_failed,
        rules_missing=n_missing,
        hard_passed=hard_passed,
        hard_failed=hard_failed,
        soft_score=soft_score,
        soft_total=soft_total,
        breakdown=breakdown,
        evaluated_at=datetime.utcnow(),
        snapshot_run_id=snap.run_id if snap else None,
        snapshot_fetched_at=snap.fetched_at if snap else None,
        snapshot_values=values,
        snapshot_sources=(snap.sources_json if snap else {}) or {},
    )


async def evaluate_from_preset(
    db: AsyncSession,
    symbol: str,
    preset_rules: list[dict],
) -> FundamentalVerdict:
    """Evaluate using in-memory rules from a preset dict list.

    Same logic as evaluate() but skips the DB rule-set query — rules
    are converted to SimpleNamespace objects with the same attributes
    as FundamentalRule so _evaluate_rule() works unchanged.
    """
    from types import SimpleNamespace

    rules = [
        SimpleNamespace(
            metric_key=r["metric_key"],
            operator=r["operator"],
            value_num=r.get("value_num"),
            value_low=r.get("value_low"),
            value_high=r.get("value_high"),
            weight=r.get("weight", 3),
            is_hard_filter=r.get("is_hard_filter", False),
            enabled=True,
            sort_order=r.get("sort_order", 0),
        )
        for r in preset_rules
    ]
    rules.sort(key=lambda r: r.sort_order)

    values, snap, _fetched_at = await _values_for_symbol(db, symbol)

    breakdown: list[RuleEval] = []
    weighted_passed = 0.0
    weighted_eligible = 0.0
    n_passed = n_failed = n_missing = 0
    hard_failed: list[str] = []
    soft_score = 0
    soft_total = 0

    for r in rules:
        actual = values.get(r.metric_key)
        status = _evaluate_rule(r, actual)
        is_hard = bool(r.is_hard_filter)
        if status == "passed":
            n_passed += 1
            weighted_passed += r.weight
            weighted_eligible += r.weight
            if not is_hard:
                soft_score += 1
                soft_total += 1
        elif status == "failed":
            n_failed += 1
            weighted_eligible += r.weight
            if is_hard:
                hard_failed.append(r.metric_key)
            else:
                soft_total += 1
        else:
            n_missing += 1
        breakdown.append(RuleEval(
            metric_key=r.metric_key,
            operator=r.operator,
            threshold={"value": _coerce_num(r.value_num), "low": _coerce_num(r.value_low), "high": _coerce_num(r.value_high)},
            weight=int(r.weight),
            is_hard_filter=is_hard,
            actual=actual if not isinstance(actual, dict) else None,
            status=status,
        ))

    rules_total = len(rules)
    hard_passed = len(hard_failed) == 0

    if rules_total == 0:
        verdict = VERDICT_NA
        score = None
    elif not hard_passed:
        verdict = VERDICT_REJECTED
        score = round((soft_score / soft_total) * 100.0, 1) if soft_total > 0 else None
    elif (n_passed + n_failed) < max(1, rules_total // 2):
        verdict = VERDICT_NA
        score = None
    else:
        if soft_total > 0:
            soft_pct = (soft_score / soft_total) * 100.0
        elif weighted_eligible > 0:
            soft_pct = (weighted_passed / weighted_eligible) * 100.0
        else:
            soft_pct = None
        score = round(soft_pct, 1) if soft_pct is not None else None
        if soft_pct is None:
            verdict = VERDICT_NA
        elif soft_pct >= 75:
            verdict = VERDICT_STRONG
        elif soft_pct >= 50:
            verdict = VERDICT_FAIR
        else:
            verdict = VERDICT_WEAK

    return FundamentalVerdict(
        verdict=verdict,
        score=score,
        rules_total=rules_total,
        rules_passed=n_passed,
        rules_failed=n_failed,
        rules_missing=n_missing,
        hard_passed=hard_passed,
        hard_failed=hard_failed,
        soft_score=soft_score,
        soft_total=soft_total,
        breakdown=breakdown,
        evaluated_at=datetime.utcnow(),
        snapshot_run_id=snap.run_id if snap else None,
        snapshot_fetched_at=snap.fetched_at if snap else None,
        snapshot_values=values,
        snapshot_sources=(snap.sources_json if snap else {}) or {},
    )


async def evaluate_for_user(
    db: AsyncSession, user_id: int, symbol: str,
) -> FundamentalVerdict:
    """Convenience: load the user's default rule set and evaluate."""
    rs = await get_or_create_default_rule_set(db, user_id)
    return await evaluate(db, symbol, rs)


async def evaluate_batch(
    db: AsyncSession, user_id: int, symbols: list[str],
) -> dict[str, FundamentalVerdict]:
    """Evaluate the user's default rule set against many symbols in
    one shot — used by the watchlist /detail handlers to avoid N+1
    snapshot queries."""
    if not symbols:
        return {}
    rs = await get_or_create_default_rule_set(db, user_id)

    # Load rules once.
    rules_res = await db.execute(
        select(FundamentalRule)
        .where(FundamentalRule.rule_set_id == rs.id, FundamentalRule.enabled.is_(True))
        .order_by(FundamentalRule.sort_order)
    )
    rules = list(rules_res.scalars().all())

    # Latest snapshot per symbol + fallback to StockFundamentals when missing.
    sym_uppers = [s.upper() for s in symbols]
    values_by_sym, latest_by_sym = await _values_for_symbols_bulk(db, sym_uppers)

    out: dict[str, FundamentalVerdict] = {}
    now = datetime.utcnow()
    for sym in sym_uppers:
        snap = latest_by_sym.get(sym)
        values = values_by_sym.get(sym, {})

        breakdown: list[RuleEval] = []
        weighted_passed = 0.0
        weighted_eligible = 0.0
        n_passed = n_failed = n_missing = 0

        for r in rules:
            actual = values.get(r.metric_key)
            status = _evaluate_rule(r, actual)
            if status == "passed":
                n_passed += 1
                weighted_passed += r.weight
                weighted_eligible += r.weight
            elif status == "failed":
                n_failed += 1
                weighted_eligible += r.weight
            else:
                n_missing += 1
            breakdown.append(RuleEval(
                metric_key=r.metric_key, operator=r.operator,
                threshold={"value": _coerce_num(r.value_num), "low": _coerce_num(r.value_low), "high": _coerce_num(r.value_high)},
                weight=int(r.weight),
                is_hard_filter=bool(r.is_hard_filter),
                actual=actual if not isinstance(actual, dict) else None,
                status=status,
            ))

        rules_total = len(rules)
        if rules_total == 0 or (n_passed + n_failed) < max(1, rules_total // 2):
            verdict = VERDICT_NA
            score = None
        else:
            score = (weighted_passed / weighted_eligible) * 100.0 if weighted_eligible > 0 else None
            if score is None:
                verdict = VERDICT_NA
            elif score >= 70:
                verdict = VERDICT_STRONG
            elif score >= 40:
                verdict = VERDICT_FAIR
            else:
                verdict = VERDICT_WEAK

        hard_failed_keys = [
            b.metric_key for b in breakdown
            if b.is_hard_filter and b.status == "failed"
        ]
        if hard_failed_keys:
            verdict = VERDICT_REJECTED

        out[sym] = FundamentalVerdict(
            verdict=verdict,
            score=round(score, 1) if score is not None else None,
            rules_total=rules_total,
            rules_passed=n_passed,
            rules_failed=n_failed,
            rules_missing=n_missing,
            hard_passed=len(hard_failed_keys) == 0,
            hard_failed=hard_failed_keys,
            soft_score=sum(1 for b in breakdown if not b.is_hard_filter and b.status == "passed"),
            soft_total=sum(1 for b in breakdown if not b.is_hard_filter and b.status != "missing"),
            breakdown=breakdown,
            evaluated_at=now,
            snapshot_run_id=snap.run_id if snap else None,
            snapshot_fetched_at=snap.fetched_at if snap else None,
        )
    return out
