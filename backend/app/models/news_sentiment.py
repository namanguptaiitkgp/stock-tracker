from datetime import datetime
from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class NewsSentimentCache(Base):
    __tablename__ = "news_sentiment_cache"

    symbol: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
