from sqlalchemy import Boolean, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PaperAgent(Base):
    __tablename__ = "paper_agents"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True
    )
    initial_corpus_inr: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PaperEvent(Base):
    __tablename__ = "paper_events"
    __table_args__ = (
        Index("ix_paper_events_agent_created", "agent_id", "created_at"),
        Index("ix_paper_events_agent_type", "agent_id", "event_type"),
    )

    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_agents.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(10), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_inr: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
