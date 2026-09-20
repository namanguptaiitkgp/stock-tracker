from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockAnalysis(Base):
    __tablename__ = "stock_analyses"

    symbol: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    # Section 1: Valuation (sector-specific rule engine verdict)
    valuation_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valuation_score: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    valuation_signals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    valuation_hard_failed: Mapped[list | None] = mapped_column(JSON, nullable=True)
    valuation_last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Section 2: Peer comparison
    peer_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    peer_metric_breakdown: Mapped[list | None] = mapped_column(JSON, nullable=True)
    peer_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    peer_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    peer_set_weak: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    peer_last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Section 3: News & outlook (Vertex AI qualitative)
    news_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    news_stock_signals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    news_source_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    news_qualitative: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    news_last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Card-level derived fields
    act_now_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
