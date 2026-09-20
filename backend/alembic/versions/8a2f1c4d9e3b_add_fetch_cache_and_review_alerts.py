"""add fetch_cache and review_alerts

Revision ID: 8a2f1c4d9e3b
Revises: 44ad42fdce1b
Create Date: 2026-05-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8a2f1c4d9e3b"
down_revision: Union[str, None] = "44ad42fdce1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── fetch_cache ─────────────────────────────────────────────────
    op.create_table(
        "fetch_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cache_key", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cache_key", name="uq_fetch_cache_key"),
    )
    op.create_index("ix_fetch_cache_cache_key", "fetch_cache", ["cache_key"])
    op.create_index("ix_fetch_cache_source", "fetch_cache", ["source"])
    op.create_index("ix_fetch_cache_expires_at", "fetch_cache", ["expires_at"])

    # ── review_alerts ───────────────────────────────────────────────
    op.create_table(
        "review_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("exchange", sa.String(length=10), nullable=False, server_default="NSE"),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("trigger_label", sa.String(length=200), nullable=False),
        sa.Column("suggested_action", sa.String(length=60), nullable=True),
        sa.Column("suggested_lane", sa.String(length=40), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_alerts_user_id", "review_alerts", ["user_id"])
    op.create_index("ix_review_alerts_symbol", "review_alerts", ["symbol"])
    op.create_index("ix_review_alerts_status", "review_alerts", ["status"])

    # Partial unique constraint: at most one pending alert of a given trigger_type
    # per (user, symbol). Once applied/dismissed the trigger can re-fire.
    op.execute("""
        CREATE UNIQUE INDEX uq_review_alerts_pending
        ON review_alerts (user_id, symbol, trigger_type)
        WHERE status = 'pending';
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_review_alerts_pending;")
    op.drop_index("ix_review_alerts_status", table_name="review_alerts")
    op.drop_index("ix_review_alerts_symbol", table_name="review_alerts")
    op.drop_index("ix_review_alerts_user_id", table_name="review_alerts")
    op.drop_table("review_alerts")
    op.drop_index("ix_fetch_cache_expires_at", table_name="fetch_cache")
    op.drop_index("ix_fetch_cache_source", table_name="fetch_cache")
    op.drop_index("ix_fetch_cache_cache_key", table_name="fetch_cache")
    op.drop_table("fetch_cache")
