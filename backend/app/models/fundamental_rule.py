"""Fundamental Analysis rule sets — the user's platform-wide thresholds.

V1 ships with a single `is_default=True` rule set per user (auto-created
on first read). Multiple rule sets is a Phase-2 enhancement; the schema
already supports it.

A `FundamentalRule` is one comparison: `metric_key operator value(s)`
with an integer weight 1–5 used by the scoring formula. The evaluator
in `services/fundamental_analysis.py` reads these rows + the latest
`metric_snapshots` and produces a STRONG/FAIR/WEAK verdict.
"""

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FundamentalRuleSet(Base):
    __tablename__ = "fundamental_rule_sets"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False, default="Defaults")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class FundamentalRule(Base):
    __tablename__ = "fundamental_rules"

    rule_set_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fundamental_rule_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(16), nullable=False)
    value_num: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    value_low: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    value_high: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    weight: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # When TRUE, the rule must pass for the stock to clear the screener
    # gate — failing it returns verdict REJECTED regardless of the soft
    # score. Missing data does NOT auto-fail (per spec §3 of
    # indian_stock_screener_criteria.md). When FALSE the rule
    # contributes to the soft score (X / N passed) used for ranking.
    is_hard_filter: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
