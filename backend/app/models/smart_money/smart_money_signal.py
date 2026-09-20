from datetime import date

from sqlalchemy import JSON, Date, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SmartMoneySignal(Base):
    __tablename__ = "smart_money_signals"
    __table_args__ = (
        # Re-keyed in PR 10 — `(symbol, window_days, as_of)`. Existing
        # rollup writes window_days=30 by default; future 90d / 365d
        # / since-purchase rows are additive.
        UniqueConstraint(
            "symbol", "window_days", "as_of",
            name="uq_sm_signals_symbol_window_date",
        ),
        Index("ix_sms_symbol_date", "symbol", "as_of"),
        Index("ix_sms_as_of", "as_of"),
        Index("ix_sms_composite", "composite"),
        Index("ix_sm_signals_window_date", "window_days", "as_of"),
    )

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    # Rollup window in days: 30 (default), 90 (quarterly), 365 (annual),
    # or `since_purchase` (encoded as -1 with `meta.actual_window_days`
    # giving the per-holding actual). Multi-window architecture from
    # the long-term-investor spec, schema-only at first ship.
    window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30",
    )
    # Legacy sub-scores — still populated for backwards compatibility
    # (the old UI references them). The revamped scorer fills the
    # conviction/flow/red_flag columns alongside.
    mf_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    pms_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    aif_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    deals_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    delivery_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    composite: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    # New three-stream system. `composite` is now derived from these.
    conviction_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    flow_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    red_flag_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    # Per-signal contributions, available signals, absent signals,
    # triggered red flags. See spec §7E for the JSON shape.
    signal_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    top_adders: Mapped[list | None] = mapped_column(JSON, nullable=True)
    top_reducers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    named_sharks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
