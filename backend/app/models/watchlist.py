from datetime import date as date_type, datetime

from sqlalchemy import Boolean, JSON, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Watchlist(Base):
    __tablename__ = "watchlists"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_symbol"),)

    watchlist_id: Mapped[int] = mapped_column(Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    exchange: Mapped[str] = mapped_column(String(10), default="NSE")
    stock_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Researching-card fields
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)             # short investment thesis
    pe_target: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_target: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    peer_symbols: Mapped[list | None] = mapped_column(JSON, nullable=True)       # ["TCS","INFY"...]
    watch_rules: Mapped[list | None] = mapped_column(JSON, nullable=True)        # [{type, value, label}]
    lane: Mapped[str | None] = mapped_column(String(40), nullable=True)          # "researching" | "awaiting" | "exit"


class WatchlistJournalEntry(Base):
    """Free-text log per watchlist item — observations, thesis updates, events."""
    __tablename__ = "watchlist_journal_entries"

    watchlist_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("watchlist_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


class WatchlistValuationSnapshot(Base):
    """Daily snapshot of valuation metrics — logged after market close."""
    __tablename__ = "watchlist_valuation_snapshots"
    __table_args__ = (
        UniqueConstraint("watchlist_item_id", "snapshot_date", name="uq_wl_item_snapshot_date"),
    )

    watchlist_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("watchlist_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    cmp: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    pct_from_52w_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    pct_from_52w_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_52w: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_52w: Mapped[float | None] = mapped_column(Float, nullable=True)
