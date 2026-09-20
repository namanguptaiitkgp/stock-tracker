from datetime import datetime

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IndexQuoteCache(Base):
    __tablename__ = "index_quote_cache"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    source_symbol: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ltp: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    prev_close: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    change: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    day_high: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    day_low: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
