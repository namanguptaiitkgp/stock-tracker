from datetime import date as date_type
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailyNewsReport(Base):
    __tablename__ = "daily_news_reports"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    report_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    total_headlines: Mapped[int] = mapped_column(Integer, default=0)
    companies_found: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    dismissed_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
