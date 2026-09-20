from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InsiderDisclosure(Base):
    """One row per insider transaction filed under PIT Reg 7 / SAST.

    Fed by `services/smart_money/insider_disclosures.py`. Read by the
    revamped composite scorer (promoter-buying conviction signal,
    promoter-selling red flag).
    """

    __tablename__ = "insider_disclosures"
    __table_args__ = (
        Index("ix_insider_symbol_date", "symbol", "transaction_date"),
        Index("ix_insider_category_date", "category", "transaction_date"),
        UniqueConstraint(
            "symbol",
            "person_name_norm",
            "transaction_date",
            "transaction_type",
            "shares",
            name="ix_insider_dedup",
        ),
    )

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    person_name: Mapped[str] = mapped_column(String(255), nullable=False)
    person_name_norm: Mapped[str] = mapped_column(String(255), nullable=False)
    relation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(10), nullable=False)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    value_inr: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    intimation_date: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pre_holding_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    post_holding_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="NSE")
    is_known_shark: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Set by `detect_intra_group_transfers()` after ingestion. When True the
    # row is excluded from conviction (promoter-buying) and red-flag
    # (promoter-selling) scoring — it's a transfer between related entities,
    # not a directional position change.
    is_intra_group_transfer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
