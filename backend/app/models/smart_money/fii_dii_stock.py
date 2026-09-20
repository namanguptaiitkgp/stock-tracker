from datetime import date

from sqlalchemy import Date, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FiiDiiStockDaily(Base):
    """Per-stock FII/DII activity (₹ crore). Drives the flow-score
    `stock-level FII/DII net` signal.

    NSE participant-wise data is the canonical source. Market-wide
    aggregates live separately in `services/fii_dii.py`.
    """

    __tablename__ = "fii_dii_stock_daily"
    __table_args__ = (
        Index("ix_fii_dii_stock_symbol_date", "symbol", "trade_date"),
        UniqueConstraint("symbol", "trade_date", name="ix_fii_dii_stock_dedup"),
    )

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    fii_buy_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    fii_sell_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    fii_net_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    dii_buy_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    dii_sell_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    dii_net_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
