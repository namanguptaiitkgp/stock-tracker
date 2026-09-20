"""add index_quote_cache + index_news_summary

Revision ID: b2d3e4f5a6b7
Revises: a1c2d3e4f5a6
Create Date: 2026-04-22 11:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2d3e4f5a6b7"
down_revision: Union[str, None] = "a1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "index_quote_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("source_symbol", sa.String(length=80), nullable=True),
        sa.Column("ltp", sa.Numeric(14, 4), nullable=True),
        sa.Column("prev_close", sa.Numeric(14, 4), nullable=True),
        sa.Column("change", sa.Numeric(14, 4), nullable=True),
        sa.Column("change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("day_high", sa.Numeric(14, 4), nullable=True),
        sa.Column("day_low", sa.Numeric(14, 4), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_index_quote_cache_slug", "index_quote_cache", ["slug"], unique=True)

    op.create_table(
        "index_news_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=12), nullable=True),
        sa.Column("magnitude", sa.String(length=12), nullable=True),
        sa.Column("one_liner", sa.Text(), nullable=True),
        sa.Column("drivers", sa.JSON(), nullable=True),
        sa.Column("what_to_watch", sa.Text(), nullable=True),
        sa.Column("top_headlines", sa.JSON(), nullable=True),
        sa.Column("news_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_used", sa.String(length=60), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_index_news_summary_slug", "index_news_summary", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_index_news_summary_slug", table_name="index_news_summary")
    op.drop_table("index_news_summary")
    op.drop_index("ix_index_quote_cache_slug", table_name="index_quote_cache")
    op.drop_table("index_quote_cache")
