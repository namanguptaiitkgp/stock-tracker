from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AifHoldingQuarterly(Base):
    __tablename__ = "aif_holdings_quarterly"
    __table_args__ = (
        UniqueConstraint("fund_id", "symbol", "report_quarter", name="uq_aif_holding_fund_symbol_q"),
        Index("ix_aif_holdings_symbol_q", "symbol", "report_quarter"),
        Index("ix_aif_holdings_fund_q", "fund_id", "report_quarter"),
    )

    fund_id: Mapped[int] = mapped_column(ForeignKey("aif_funds.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    instrument_name_raw: Mapped[str] = mapped_column(String(255), nullable=False)
    report_quarter: Mapped[date] = mapped_column(Date, nullable=False)
    units: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    market_value_inr: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    pct_of_corpus: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    source_pdf_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    parsed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
