import datetime as dt

from sqlalchemy import BigInteger, Date, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Stock(Base):
    __tablename__ = "stocks"

    instrument_token: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    exchange_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    segment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    instrument_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    expiry: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    last_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
