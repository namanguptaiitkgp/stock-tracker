from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PmsStrategyHoldingQuarterly(Base):
    __tablename__ = "pms_strategy_holdings_quarterly"
    __table_args__ = (
        UniqueConstraint(
            "manager_id", "strategy_name", "symbol", "report_quarter",
            name="uq_pms_holding_mgr_strat_symbol_q",
        ),
        Index("ix_pms_holdings_symbol_q", "symbol", "report_quarter"),
        Index("ix_pms_holdings_mgr_q", "manager_id", "report_quarter"),
    )

    manager_id: Mapped[int] = mapped_column(ForeignKey("pms_managers.id", ondelete="CASCADE"), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(255), nullable=False)
    strategy_investment_approach: Mapped[str | None] = mapped_column(String(120), nullable=True)
    symbol: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    instrument_name_raw: Mapped[str] = mapped_column(String(255), nullable=False)
    report_quarter: Mapped[date] = mapped_column(Date, nullable=False)
    pct_of_strategy: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    market_value_inr: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    source_pdf_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    parsed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
