"""Unified fetch cache for raw external data (RSS feeds, BSE API, Google News,
NSE option chain, Gemini batch responses, etc.).

Lives in Postgres so it survives backend restarts. Default TTL 2 hours per
the user's "recent" rule. Manual refresh = invalidate the key/prefix.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FetchCache(Base):
    __tablename__ = "fetch_cache"

    cache_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payload: Mapped[dict | list] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    refresh_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
