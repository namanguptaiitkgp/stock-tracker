from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AifFund(Base):
    __tablename__ = "aif_funds"

    sebi_reg_no: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    sponsor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scheme_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
