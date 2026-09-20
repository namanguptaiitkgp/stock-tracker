"""phase 5/6 follow-up: is_admin + invite_codes + review_alerts composite index

Revision ID: e7c2a91d4f3b
Revises: d4f1a8b6c0e2
Create Date: 2026-05-01 03:30:00.000000

Adds the multi-tenant + observability schema bits that were deferred when
phase-1 shipped:

* `users.is_admin` — gates the admin invite endpoints. The oldest existing
  user gets True so they can issue codes after upgrade.
* `invite_codes` — closed-beta registration table.
* `ix_review_alerts_user_status_source` — speeds the `/review-alerts/count`
  and dashboard badge queries which filter on (user_id, status, source).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7c2a91d4f3b"
down_revision: Union[str, None] = "d4f1a8b6c0e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. is_admin column on users.
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Backfill: oldest user becomes admin so they can issue invites.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE users SET is_admin = TRUE "
            "WHERE id = (SELECT id FROM users ORDER BY created_at ASC, id ASC LIMIT 1)"
        )
    )

    # 2. invite_codes table.
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "redeemed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_invite_codes_code", "invite_codes", ["code"], unique=True)
    op.create_index(
        "ix_invite_codes_created_by_user_id",
        "invite_codes",
        ["created_by_user_id"],
    )

    # 3. Composite index that the review-alerts endpoint scans. IF NOT
    #    EXISTS guards against re-runs / partial-fail recoveries.
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_review_alerts_user_status_source "
        "ON review_alerts (user_id, status, source)"
    ))


def downgrade() -> None:
    op.drop_index("ix_review_alerts_user_status_source", table_name="review_alerts")
    op.drop_index("ix_invite_codes_created_by_user_id", table_name="invite_codes")
    op.drop_index("ix_invite_codes_code", table_name="invite_codes")
    op.drop_table("invite_codes")
    op.drop_column("users", "is_admin")
