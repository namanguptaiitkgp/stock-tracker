from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SectorAnalysis(Base):
    __tablename__ = "sector_analyses"

    sector: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    mood: Mapped[str | None] = mapped_column(String(20), nullable=True)
    signals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    headline_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Richer columns introduced with the Market Brief — Sectors panel v1.
    # All NULL on legacy rows; backfilled on the next morning-pipeline
    # refresh per sector. See migration d2f8a4b6c1e7.
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    macro_drivers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    what_to_watch: Mapped[list | None] = mapped_column(JSON, nullable=True)
    top_headlines: Mapped[list | None] = mapped_column(JSON, nullable=True)
