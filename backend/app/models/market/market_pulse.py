from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MarketPulse(Base):
    """Cache for the dashboard MarketPulse widget — Gemini-generated narrative
    explaining the current market direction and key drivers.

    Single live row pattern (we only keep recent ones; consumers query newest).
    TTL controlled via `expires_at`.
    """

    __tablename__ = "market_pulse"

    direction: Mapped[str | None] = mapped_column(String(12), nullable=True)         # up/down/flat
    magnitude: Mapped[str | None] = mapped_column(String(12), nullable=True)          # neutral/mild/moderate/strong
    label: Mapped[str | None] = mapped_column(String(40), nullable=True)              # human label
    score: Mapped[float | None] = mapped_column(Float, nullable=True)                  # weighted change_pct
    breadth: Mapped[float | None] = mapped_column(Float, nullable=True)                # 0-1
    components: Mapped[list | None] = mapped_column(JSON, nullable=True)               # per-index score
    vix: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    one_liner: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    drivers: Mapped[list | None] = mapped_column(JSON, nullable=True)                  # [{label, weight, sentiment}]
    top_headlines: Mapped[list | None] = mapped_column(JSON, nullable=True)            # [{title, source, url, impact}]
    news_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(60), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
