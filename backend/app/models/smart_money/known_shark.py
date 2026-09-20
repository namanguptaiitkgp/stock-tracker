from sqlalchemy import Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KnownShark(Base):
    __tablename__ = "known_sharks"

    canonical_name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Tier 1 = marquee investors (Jhunjhunwala estate, Kacholia, ...).
    # Tier 2 = institutional heavyweights (Marcellus, Helios, ...).
    # Tier 3 = corporate insiders tracked individually.
    # Used by the conviction scorer to weight named-shark accumulation.
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # "individual" | "family_office" | "pms_aif" | "corporate"
    entity_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="individual", server_default="individual"
    )
