from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PmsManager(Base):
    __tablename__ = "pms_managers"

    sebi_reg_no: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_aum_crore: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
