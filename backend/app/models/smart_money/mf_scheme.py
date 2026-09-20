from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MfScheme(Base):
    __tablename__ = "mf_schemes"

    amfi_scheme_code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    scheme_name: Mapped[str] = mapped_column(String(512), nullable=False)
    fund_house: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    scheme_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scheme_category: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    isin_growth: Mapped[str | None] = mapped_column(String(20), nullable=True)
    isin_div_reinvest: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nav: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    nav_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    aum_crore: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    aum_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
