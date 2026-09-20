from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScrapeEvent(Base):
    """One row per external HTTP fetch routed through data_cache. Used by
    the activity monitor to track scrape health (success rate, latency)
    per source. Pruned by db_prune after 30 days."""

    __tablename__ = "scrape_events"
    __table_args__ = (
        Index("ix_scrape_events_ts", "ts"),
        Index("ix_scrape_events_source_ts", "source", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
