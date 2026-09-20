from datetime import date

from sqlalchemy import Boolean, Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BulkBlockDeal(Base):
    __tablename__ = "bulk_block_deals"
    __table_args__ = (
        Index("ix_bbd_symbol_date", "symbol", "trade_date"),
        Index("ix_bbd_client_date", "client_name_norm", "trade_date"),
        Index("ix_bbd_date", "trade_date"),
    )

    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    exchange: Mapped[str] = mapped_column(String(4), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    security_name_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_name_raw: Mapped[str] = mapped_column(String(255), nullable=False)
    client_name_norm: Mapped[str] = mapped_column(String(255), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Numeric(18, 0), nullable=False)
    avg_price: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False)
    trade_value_inr: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    deal_type: Mapped[str] = mapped_column(String(8), nullable=False)
    is_known_shark: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Populated at ingest by `services/smart_money/deals.py` using
    # `analyzer/party_classifier.py`. One of: QUALITY_MF_FPI, VC_PE,
    # PROMOTER, INSIDER_OTHER, PROP_HFT, OTHER_FUND, BROKER,
    # CORP_OTHER, INDIVIDUAL. Nullable so legacy pre-A1c rows don't
    # break — backfilled by a one-off `reclassify_existing_deals()` task.
    client_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
