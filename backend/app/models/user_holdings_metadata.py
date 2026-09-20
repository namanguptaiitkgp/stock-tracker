from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserHoldingsMetadata(Base):
    """Per-user metadata for owned stocks: purchase date, thesis, and sector
    override.

    The user records this via the Settings editor; consumers include:
      • holdings-signal layer (reads `first_purchase_date` + `initial_thesis`
        to compute "since you bought" drift)
      • sector resolver (reads `sector_override` as the highest-priority
        source of truth before any auto-detected sector)

    Per-user FK CASCADE per CLAUDE.md. `thesis_tags` is a free-form JSON
    array of short labels (e.g. `["turnaround", "compounder"]`) used for
    filtering/grouping in future views.

    All fields except (user_id, symbol) are optional — users can record
    any subset (e.g. set sector_override without committing to a purchase
    date).
    """

    __tablename__ = "user_holdings_metadata"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="ix_holdings_metadata_user_symbol"),
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    first_purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    initial_thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    thesis_tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    target_holding_period_months: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # Manual sector override — when set, takes precedence over Screener.in,
    # Nifty index membership, NSE industry, and yfinance in the sector
    # resolver (`services/sector_resolver.py`). Stored as the canonical
    # sector name (one of CANONICAL_SECTORS); the UI dropdown enforces this.
    sector_override: Mapped[str | None] = mapped_column(String(80), nullable=True)
