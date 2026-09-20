"""Metric catalog + per-run snapshots + manual overrides.

The Fundamental Analysis engine reads metric values from these tables.
- `MetricDefinition` is the catalog: one row per supported metric (PE,
  D/E, ROE, etc.) with display name, unit, category, and markdown
  description used in the Settings rule-editor tooltip.
- `MetricRun` is a per-refresh audit row (scope, started/finished,
  success counts).
- `MetricSnapshot` is one wide-JSONB row per (symbol, run) — the entire
  metric set for a stock at one point in time. Registered as a
  TimescaleDB hypertable on `fetched_at`; the `values_json` column makes
  adding a new metric a row insert into MetricDefinition rather than
  a schema change.
- `MetricManualOverride` is the place a user-typed value lands when no
  source has it; the engine layers these on top of source-derived
  values before writing each snapshot.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MetricDefinition(Base):
    """Catalog row — one per supported metric. Seeded via Alembic; new
    metrics are added by inserting rows, not by editing code."""

    __tablename__ = "metric_definitions"

    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    description_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    formula: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MetricRun(Base):
    """Per-refresh audit row. Scope is stock | watchlist | portfolio."""

    __tablename__ = "metric_runs"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_symbol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    stocks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stocks_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stocks_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class MetricSnapshot(Base):
    """One wide JSONB row per (symbol, run). Registered as a TimescaleDB
    hypertable on `fetched_at` in the migration. `values_json` is a
    `{metric_key: number_or_string}` map; `sources_json` records the
    provenance (`yfinance`, `tickertape`, `manual:<user_id>`, …)."""

    __tablename__ = "metric_snapshots"

    # BIGSERIAL — these grow forever, even with compression.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("metric_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="NSE")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    values_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sources_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class MetricManualOverride(Base):
    """User-typed values for metrics no automated source provides.
    Composite primary key keeps the table small; one row per
    (user, symbol, metric)."""

    __tablename__ = "metric_manual_overrides"

    # The Base `id` is unused here but required by the inheritance pattern.
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="NSE")
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False)
    value_num: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    value_str: Mapped[str | None] = mapped_column(String(120), nullable=True)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "symbol", "metric_key", name="uq_manual_override_user_symbol_metric"),
    )
