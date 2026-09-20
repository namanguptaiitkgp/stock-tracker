from datetime import datetime

from sqlalchemy import Boolean, JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.security.crypto import EncryptedStr


class User(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    kite_api_key: Mapped[str | None] = mapped_column(EncryptedStr(512), nullable=True)
    kite_api_secret: Mapped[str | None] = mapped_column(EncryptedStr(512), nullable=True)
    kite_access_token: Mapped[str | None] = mapped_column(EncryptedStr(512), nullable=True)
    kite_token_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    gemini_api_key: Mapped[str | None] = mapped_column(EncryptedStr(512), nullable=True)
    anthropic_api_key: Mapped[str | None] = mapped_column(EncryptedStr(512), nullable=True)
    settings_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
