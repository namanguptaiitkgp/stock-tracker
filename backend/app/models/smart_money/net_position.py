from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NetPosition30d(Base):
    """30-day rolling net positions per (symbol, party). Materialized by
    the smart-money rollup before scoring — one row per non-noise party
    per stock per rollup date.
    """

    __tablename__ = "net_positions_30d"
    __table_args__ = (
        Index("ix_net_pos_symbol_date", "symbol", "as_of"),
        UniqueConstraint("symbol", "as_of", "party_name_norm", name="ix_net_pos_dedup"),
    )

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    party_name_norm: Mapped[str] = mapped_column(String(255), nullable=False)
    party_category: Mapped[str] = mapped_column(String(30), nullable=False)
    net_shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_value_inr: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    distinct_buy_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distinct_sell_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_known_shark: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_circular_suspect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # |net| / gross. ~1.0 = clean directional position; ~0.0 = squaring off.
    # Used by /net-traders to filter out near-square-off noise (default ≥0.2).
    net_to_total_ratio: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
