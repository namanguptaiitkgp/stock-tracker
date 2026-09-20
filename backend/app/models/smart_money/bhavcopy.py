from datetime import date

from sqlalchemy import Date, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BhavcopyDaily(Base):
    __tablename__ = "bhavcopy_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "exchange", "symbol", name="uq_bhav_date_exch_symbol"),
        Index("ix_bhav_symbol_date", "symbol", "trade_date"),
        Index("ix_bhav_date", "trade_date"),
    )

    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    exchange: Mapped[str] = mapped_column(String(4), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    series: Mapped[str | None] = mapped_column(String(8), nullable=True)
    open_price: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    high_price: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    low_price: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    close_price: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    prev_close: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    traded_qty: Mapped[int | None] = mapped_column(Numeric(20, 0), nullable=True)
    turnover_inr: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    delivery_qty: Mapped[int | None] = mapped_column(Numeric(20, 0), nullable=True)
    delivery_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
