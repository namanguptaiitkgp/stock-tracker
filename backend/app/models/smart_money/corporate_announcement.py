from datetime import date

from sqlalchemy import BigInteger, Date, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CorporateAnnouncement(Base):
    """Filtered corporate filings: buybacks, pledge create/release/invoke,
    preferential allotments. Drives the buyback-active flow boost and the
    pledge-invocation red flag.

    Dedup is enforced via a partial unique index on (symbol,
    announcement_type, announcement_date, md5(headline)) at the DB
    layer (defined in the Alembic migration), so we don't need a
    UniqueConstraint declared on this model.
    """

    __tablename__ = "corporate_announcements"
    __table_args__ = (
        Index("ix_corp_ann_symbol_date", "symbol", "announcement_date"),
        Index("ix_corp_ann_type_date", "announcement_type", "announcement_date"),
    )

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    announcement_type: Mapped[str] = mapped_column(String(50), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    detail_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    buyback_size_inr: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    buyback_price_inr: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    pledge_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pledge_pct_of_holding: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    pledge_direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pledgor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    announcement_date: Mapped[date] = mapped_column(Date, nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="NSE")
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
