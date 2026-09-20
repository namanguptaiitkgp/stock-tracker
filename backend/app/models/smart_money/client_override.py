from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ClientOverride(Base):
    """Per-user override for the bulk/block client classifier.

    Lets the user teach the system over time — e.g. "AUTHUM INVESTMENT
    is a value fund, not CORP_OTHER." The classifier reads overrides
    first, then `known_sharks`, then keyword heuristics.
    """

    __tablename__ = "client_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "client_name_norm", name="ix_client_override"),
    )

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_name_norm: Mapped[str] = mapped_column(String(255), nullable=False)
    override_category: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
