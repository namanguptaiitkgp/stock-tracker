from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StrategyRun(Base):
    __tablename__ = "strategy_runs"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)  # holdings | watchlist | nifty50
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # watchlist_id if target_type=watchlist
    target_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    symbols_count: Mapped[int] = mapped_column(Integer, default=0)
    pass_count: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
