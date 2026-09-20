from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MfHoldingMonthly(Base):
    __tablename__ = "mf_holdings_monthly"
    __table_args__ = (
        UniqueConstraint("scheme_id", "symbol", "report_month", name="uq_mf_holding_scheme_symbol_month"),
        Index("ix_mf_holdings_symbol_month", "symbol", "report_month"),
        Index("ix_mf_holdings_scheme_month", "scheme_id", "report_month"),
    )

    scheme_id: Mapped[int] = mapped_column(ForeignKey("mf_schemes.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    isin: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    instrument_name_raw: Mapped[str] = mapped_column(String(255), nullable=False)
    report_month: Mapped[date] = mapped_column(Date, nullable=False)
    units: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    market_value_inr: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    pct_of_aum: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    prev_units: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    change_units: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    change_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
