from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IndexNewsSummary(Base):
    __tablename__ = "index_news_summary"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    direction: Mapped[str | None] = mapped_column(String(12), nullable=True)
    magnitude: Mapped[str | None] = mapped_column(String(12), nullable=True)
    one_liner: Mapped[str | None] = mapped_column(Text, nullable=True)
    drivers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    what_to_watch: Mapped[str | None] = mapped_column(Text, nullable=True)
    top_headlines: Mapped[list | None] = mapped_column(JSON, nullable=True)
    news_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(60), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
