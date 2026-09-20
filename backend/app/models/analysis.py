from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PortfolioAnalysis(Base):
    __tablename__ = "portfolio_analyses"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    holdings_count: Mapped[int] = mapped_column(Integer, default=0)
    sell_count: Mapped[int] = mapped_column(Integer, default=0)
    hold_count: Mapped[int] = mapped_column(Integer, default=0)
    watchful_count: Mapped[int] = mapped_column(Integer, default=0)
    overall_health: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_prompt_data: Mapped[str | None] = mapped_column(String, nullable=True)
