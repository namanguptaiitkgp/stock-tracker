from datetime import date

from sqlalchemy import Date, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ShareholdingPattern(Base):
    """Quarterly shareholding pattern snapshot per stock.

    Source: BSE / NSE corporate-action APIs. Deltas vs the most recent
    previous quarter are computed at ingest time so the scorer can read
    them directly.
    """

    __tablename__ = "shareholding_patterns"
    __table_args__ = (
        Index("ix_shp_symbol_quarter", "symbol", "quarter_end_date"),
        UniqueConstraint("symbol", "quarter_end_date", "exchange", name="ix_shp_dedup"),
    )

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    quarter: Mapped[str] = mapped_column(String(10), nullable=False)
    quarter_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    promoter_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    promoter_pledge_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    fii_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    dii_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    mf_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    insurance_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    public_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    promoter_delta: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    fii_delta: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    dii_delta: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    pledge_delta: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="BSE")
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
