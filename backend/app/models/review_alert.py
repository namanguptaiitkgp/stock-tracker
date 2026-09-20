"""Pending-for-review alerts.

Symbol-keyed (not watchlist_item-keyed) so we can flag both watchlist stocks
and portfolio-only holdings. When a symbol is removed from BOTH the user's
portfolio and all their watchlists, a cleanup task auto-dismisses pending
alerts for that symbol.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReviewAlert(Base):
    __tablename__ = "review_alerts"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="NSE")

    # "watchlist" | "holding" | "both"
    source: Mapped[str] = mapped_column(String(20), nullable=False)

    # "rule" | "news" | "valuation" | "verdict" | "sentiment"
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_label: Mapped[str] = mapped_column(String(200), nullable=False)
    suggested_action: Mapped[str | None] = mapped_column(String(60), nullable=True)
    suggested_lane: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # "pending" | "applied" | "dismissed"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Note: the partial unique constraint
#   UNIQUE (user_id, symbol, trigger_type) WHERE status = 'pending'
# is added directly in the Alembic migration, since SQLAlchemy doesn't
# express partial indexes in declarative metadata cleanly.
