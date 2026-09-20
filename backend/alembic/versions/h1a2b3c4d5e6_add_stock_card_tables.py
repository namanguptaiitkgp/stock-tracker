"""add stock_analyses, sector_analyses, user_stock_reviews tables

Revision ID: h1a2b3c4d5e6
Revises: 5d5548695101
Create Date: 2026-05-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h1a2b3c4d5e6"
down_revision: Union[str, Sequence[str]] = "5d5548695101"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        # Section 1: Valuation
        sa.Column("valuation_verdict", sa.String(20), nullable=True),
        sa.Column("valuation_score", sa.Numeric(5, 1), nullable=True),
        sa.Column("valuation_signals", sa.JSON(), nullable=True),
        sa.Column("valuation_hard_failed", sa.JSON(), nullable=True),
        sa.Column("valuation_last_run_at", sa.DateTime(timezone=True), nullable=True),
        # Section 2: Peer comparison
        sa.Column("peer_verdict", sa.String(20), nullable=True),
        sa.Column("peer_metric_breakdown", sa.JSON(), nullable=True),
        sa.Column("peer_summary", sa.Text(), nullable=True),
        sa.Column("peer_count", sa.Integer(), nullable=True),
        sa.Column("peer_set_weak", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("peer_last_run_at", sa.DateTime(timezone=True), nullable=True),
        # Section 3: News & outlook
        sa.Column("news_verdict", sa.String(20), nullable=True),
        sa.Column("news_stock_signals", sa.JSON(), nullable=True),
        sa.Column("news_source_count", sa.Integer(), nullable=True),
        sa.Column("news_qualitative", sa.JSON(), nullable=True),
        sa.Column("news_last_run_at", sa.DateTime(timezone=True), nullable=True),
        # Card-level
        sa.Column("act_now_score", sa.Integer(), nullable=True),
        sa.Column("summary_line", sa.Text(), nullable=True),
        sa.Column("last_completed_date", sa.Date(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_analyses_symbol", "stock_analyses", ["symbol"], unique=True)

    op.create_table(
        "sector_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sector", sa.String(100), nullable=False),
        sa.Column("mood", sa.String(20), nullable=True),
        sa.Column("signals", sa.JSON(), nullable=True),
        sa.Column("headline_count", sa.Integer(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sector_analyses_sector", "sector_analyses", ["sector"], unique=True)

    op.create_table(
        "user_stock_reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "symbol", name="uq_user_stock_review"),
    )
    op.create_index("ix_user_stock_reviews_user_id", "user_stock_reviews", ["user_id"])
    op.create_index("ix_user_stock_reviews_symbol", "user_stock_reviews", ["symbol"])


def downgrade() -> None:
    op.drop_table("user_stock_reviews")
    op.drop_table("sector_analyses")
    op.drop_table("stock_analyses")
