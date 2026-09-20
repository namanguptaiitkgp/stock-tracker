from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LlmCall(Base):
    """One row per LLM API call (Gemini, Anthropic). Used by the activity
    monitor to surface cost/latency/failure rate per purpose + per
    credential. Pruned by db_prune after 30 days."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_ts", "ts"),
        Index("ix_llm_calls_purpose_ts", "purpose", "ts"),
        Index("ix_llm_calls_symbol_ts", "symbol", "ts"),
    )

    # Override Base's `id` to use BigInteger — these grow fast.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    credential_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
