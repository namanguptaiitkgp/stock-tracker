from datetime import datetime

from sqlalchemy import DateTime, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockPeer(Base):
    __tablename__ = "stock_peers"

    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    peer_symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(30), default="gemini")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Gemini's relevance order: 0 = closest peer. NULL for reverse-stored
    # rows where we don't know the originating symbol's ranking.
    rank: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # When this peer relationship was last generated. Used to surface
    # "peers refreshed N days ago" in the UI and to flag stale cohorts.
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("symbol", "peer_symbol", name="uq_stock_peer"),
        Index("ix_stock_peers_symbol_rank", "symbol", "rank"),
    )
