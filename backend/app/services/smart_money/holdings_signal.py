"""Per-holding smart-money signal — ADD / HOLD / TRIM / REVIEW / NO_SIGNAL.

For each stock the user owns, this service produces a single-direction
signal driven by the existing PR 2 conviction / flow / red-flag scores
(via `smart_money_signals`) plus the coverage diagnostic. Designed to
be conservative: when data is thin the signal is NO_SIGNAL rather than
a misleading direction.

The output feeds the "Your Holdings" section on /smart-money. Each row
carries:
  - direction (ADD / HOLD / TRIM / REVIEW / NO_SIGNAL)
  - confidence (HIGH / MEDIUM / LOW)
  - one-line headline + 1–3 driver bullets
  - coverage_score so the UI can render "based on X% coverage"
  - days_held (when user_holdings_metadata is recorded)

Trajectory ("strengthening / weakening") is part of the long-term spec
but needs ≥30 days of `smart_money_signals` history per symbol to
compute reliably. Until that history accumulates, the v1 logic skips
the trajectory branch — every other rule still works against today's
data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.smart_money import SmartMoneySignal
from app.models.user_holdings_metadata import UserHoldingsMetadata
from app.services.smart_money.coverage import compute_coverage


@dataclass
class HoldingSignal:
    symbol: str
    direction: str           # "ADD" | "HOLD" | "TRIM" | "REVIEW" | "NO_SIGNAL"
    confidence: str          # "HIGH" | "MEDIUM" | "LOW"
    headline: str
    drivers: list[str] = field(default_factory=list)
    conviction_score: float | None = None
    flow_score: float | None = None
    red_flag_score: float | None = None
    coverage_score: int = 0
    days_held: int | None = None
    binding_signal: str | None = None  # "conviction" | "red_flag" | "coverage" | "ai"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "confidence": self.confidence,
            "headline": self.headline,
            "drivers": self.drivers,
            "conviction_score": self.conviction_score,
            "flow_score": self.flow_score,
            "red_flag_score": self.red_flag_score,
            "coverage_score": self.coverage_score,
            "days_held": self.days_held,
            "binding_signal": self.binding_signal,
        }


# Coverage threshold below which we refuse to produce a direction.
# 50/100 maps roughly to "fewer than half of the weighted sources are
# present" given the weights in services/smart_money/coverage.py.
_COVERAGE_FLOOR = 50

# Confidence buckets — HIGH only when both signal magnitude and coverage
# are strong; MEDIUM when one of them is; LOW for thin-coverage reads
# even when the signal is loud.
def _confidence_for(coverage: int, signal_magnitude: float) -> str:
    if coverage >= 70 and signal_magnitude >= 40:
        return "HIGH"
    if coverage >= 50 and signal_magnitude >= 25:
        return "MEDIUM"
    return "LOW"


def _red_flag_label(breakdown: dict | None) -> str:
    if not breakdown:
        return "Red flags active"
    triggered = (breakdown.get("red_flags") or {}).get("triggered") or []
    if not triggered:
        return "Red flags active"
    label_map = {
        "circular_trading": "Circular trading suspected",
        "pump_pattern": "Pump pattern detected",
        "promoter_selling": "Promoter selling",
        "high_pledge": "High promoter pledge",
        "pledge_invocation": "Pledge invocation",
    }
    return label_map.get(triggered[0], triggered[0].replace("_", " ").title())


def _conviction_drivers(breakdown: dict | None) -> list[str]:
    if not breakdown:
        return []
    conv = breakdown.get("conviction") or {}
    out: list[str] = []
    pb = conv.get("promoter_buying") or {}
    if pb.get("raw"):
        out.append(f"Promoter market buying: {int(pb['raw']):,} shares")
    sa = conv.get("shark_accumulation") or {}
    if sa.get("raw"):
        out.append(f"Tracked-investor accumulation across {sa.get('source_rows', 0)} parties")
    mc = conv.get("mf_consensus") or {}
    if mc.get("raw"):
        out.append(f"{mc.get('increased', 0)} MF houses adding")
    sd = conv.get("shareholding_delta") or {}
    if sd.get("raw"):
        out.append(f"Promoter holding {sd['raw']:+.2f}% QoQ")
    return out


async def compute_holding_signal(
    symbol: str,
    db: AsyncSession,
    user_id: int,
) -> HoldingSignal:
    """Compute the signal for one symbol owned by `user_id`.

    The decision tree applies coverage gating first (NO_SIGNAL fast
    path), then red flags (REVIEW), then conviction direction
    (ADD/TRIM), defaulting to HOLD when nothing strong fires.
    """
    sym = symbol.upper().strip()

    # 1) Coverage — gate everything else on this.
    cov = await compute_coverage(sym, db)
    coverage = cov.coverage_score

    if coverage < _COVERAGE_FLOOR:
        return HoldingSignal(
            symbol=sym,
            direction="NO_SIGNAL",
            confidence="LOW",
            headline="Insufficient smart-money data",
            drivers=cov.sources_with_data[:3] or ["No tracked sources active"],
            coverage_score=coverage,
            binding_signal="coverage",
            days_held=None,
        )

    # 2) Latest signal row for this symbol (window_days=30 by default).
    sig_q = await db.execute(
        select(SmartMoneySignal)
        .where(SmartMoneySignal.symbol == sym, SmartMoneySignal.window_days == 30)
        .order_by(desc(SmartMoneySignal.as_of))
        .limit(1)
    )
    sig = sig_q.scalar_one_or_none()
    if sig is None:
        # Coverage said we have a signal, but we couldn't fetch one — be
        # safe and treat as NO_SIGNAL.
        return HoldingSignal(
            symbol=sym,
            direction="NO_SIGNAL",
            confidence="LOW",
            headline="Smart-money signal not yet computed",
            coverage_score=coverage,
            binding_signal="coverage",
        )

    breakdown = sig.signal_breakdown or {}
    conv = float(sig.conviction_score) if sig.conviction_score is not None else None
    flow = float(sig.flow_score) if sig.flow_score is not None else None
    rf = float(sig.red_flag_score) if sig.red_flag_score is not None else None

    # 3) Days held — informational; doesn't gate the direction in v1.
    days_held: int | None = None
    md_q = await db.execute(
        select(UserHoldingsMetadata).where(
            UserHoldingsMetadata.user_id == user_id,
            UserHoldingsMetadata.symbol == sym,
        )
    )
    md = md_q.scalar_one_or_none()
    if md is not None and md.first_purchase_date is not None:
        days_held = (date.today() - md.first_purchase_date).days

    base_kwargs = dict(
        symbol=sym,
        conviction_score=conv,
        flow_score=flow,
        red_flag_score=rf,
        coverage_score=coverage,
        days_held=days_held,
    )

    # 4) Red-flag override — strong red flag wins over any conviction.
    if rf is not None and rf <= -30:
        return HoldingSignal(
            **base_kwargs,
            direction="REVIEW",
            confidence=_confidence_for(coverage, abs(rf)),
            headline=_red_flag_label(breakdown),
            drivers=[f"Red-flag score {int(rf)}", *( _conviction_drivers(breakdown)[:1] or [] )],
            binding_signal="red_flag",
        )

    # 5) Strong negative conviction → TRIM (institutions exiting / selling).
    if conv is not None and conv <= -30:
        return HoldingSignal(
            **base_kwargs,
            direction="TRIM",
            confidence=_confidence_for(coverage, abs(conv)),
            headline="Institutional accumulation reversed",
            drivers=[f"Conviction {int(conv)}", *( _conviction_drivers(breakdown)[:1] or [] )],
            binding_signal="conviction",
        )

    # 6) Strong positive conviction → ADD.
    if conv is not None and conv >= 40 and (rf is None or rf > -20):
        drivers = _conviction_drivers(breakdown)[:2] or [f"Conviction {int(conv)}"]
        if days_held and days_held >= 90:
            drivers.append(f"Held {days_held} days")
        return HoldingSignal(
            **base_kwargs,
            direction="ADD",
            confidence=_confidence_for(coverage, conv),
            headline=drivers[0] if drivers else "Smart money accumulating",
            drivers=drivers,
            binding_signal="conviction",
        )

    # 7) Default: HOLD.
    headline_bits = []
    if conv is not None:
        headline_bits.append(f"Conviction {int(conv):+d}")
    if rf is not None and rf < 0:
        headline_bits.append(f"RF {int(rf)}")
    if flow is not None:
        headline_bits.append(f"Flow {int(flow):+d}")
    headline = " · ".join(headline_bits) if headline_bits else "Mixed / weak signal"
    return HoldingSignal(
        **base_kwargs,
        direction="HOLD",
        confidence=_confidence_for(coverage, abs(conv) if conv is not None else 0),
        headline=headline,
        drivers=_conviction_drivers(breakdown)[:2],
        binding_signal="ai",
    )
