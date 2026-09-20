"""add today_brief_cache + analyzer_sessions + analyzer_session_files

Revision ID: a1c2d3e4f5a6
Revises: f3e8c9a2b1d4
Create Date: 2026-04-22 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c2d3e4f5a6"
down_revision: Union[str, None] = "f3e8c9a2b1d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "today_brief_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("compute_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_today_brief_cache_user_id", "today_brief_cache", ["user_id"], unique=True)

    op.create_table(
        "analyzer_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stocks_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("signal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("neutral_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("noise_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_meta", sa.JSON(), nullable=True),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analyzer_sessions_user_id", "analyzer_sessions", ["user_id"])
    op.create_index("ix_analyzer_sessions_user_created", "analyzer_sessions", ["user_id", "created_at"])

    op.create_table(
        "analyzer_session_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["analyzer_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analyzer_files_session", "analyzer_session_files", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_analyzer_files_session", table_name="analyzer_session_files")
    op.drop_table("analyzer_session_files")
    op.drop_index("ix_analyzer_sessions_user_created", table_name="analyzer_sessions")
    op.drop_index("ix_analyzer_sessions_user_id", table_name="analyzer_sessions")
    op.drop_table("analyzer_sessions")
    op.drop_index("ix_today_brief_cache_user_id", table_name="today_brief_cache")
    op.drop_table("today_brief_cache")
