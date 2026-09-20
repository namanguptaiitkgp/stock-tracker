from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InvestmentDecision(Base):
    __tablename__ = "investment_decisions"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), default="NSE")
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)  # INVEST, WAIT, AVOID
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    strategies_passed: Mapped[int] = mapped_column(Integer, default=0)
    strategies_total: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
