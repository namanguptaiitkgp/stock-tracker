from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.security.crypto import EncryptedStr


class AiCredential(Base):
    __tablename__ = "ai_credentials"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_model: Mapped[str] = mapped_column(String(100), nullable=False, default="gemini-2.5-flash-lite")

    encrypted_api_key: Mapped[str | None] = mapped_column(EncryptedStr(1024), nullable=True)

    project_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    client_email: Mapped[str | None] = mapped_column(String(300), nullable=True)
    private_key_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    encrypted_private_key: Mapped[str | None] = mapped_column(EncryptedStr(8192), nullable=True)
    token_uri: Mapped[str | None] = mapped_column(String(300), nullable=True, default="https://oauth2.googleapis.com/token")
