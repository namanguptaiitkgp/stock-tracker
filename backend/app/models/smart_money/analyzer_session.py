from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalyzerSession(Base):
    __tablename__ = "analyzer_sessions"
    __table_args__ = (
        Index("ix_analyzer_sessions_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stocks_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    neutral_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    noise_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_meta: Mapped[list | None] = mapped_column(JSON, nullable=True)
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False)


class AnalyzerSessionFile(Base):
    __tablename__ = "analyzer_session_files"
    __table_args__ = (
        Index("ix_analyzer_files_session", "session_id"),
    )

    session_id: Mapped[int] = mapped_column(
        ForeignKey("analyzer_sessions.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
