from datetime import datetime

from sqlalchemy import DateTime, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockFundamentals(Base):
    __tablename__ = "stock_fundamentals"

    symbol: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), default="NSE")
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(150), nullable=True)

    cmp: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    pe_ratio: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    ttm_pe: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    forward_pe: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    pb_ratio: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    revenue_growth_1y: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    eps_growth_1y: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    earnings_growth_forward: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)

    net_profit_margin: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    debt_to_equity: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    dividend_yield: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    roe: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    promoter_holding: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    # Last 6 quarters of shareholding pattern from tickertape:
    # [{q, promoter, mf, fii, dii, retail, pledge}]
    shareholding_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 52w high/low cached from technicals endpoint (used by peers comparison)
    high_52w: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    low_52w: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    data_sources: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
