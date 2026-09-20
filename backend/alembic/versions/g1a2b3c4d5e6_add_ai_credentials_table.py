"""add ai_credentials table

Revision ID: g1a2b3c4d5e6
Revises: a2c8d4f7b1e9, c5e8f2a3b7d9, b3d7e9f1a2c4, b2d3e4f5a6b7
Create Date: 2026-05-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, Sequence[str]] = (
    "a2c8d4f7b1e9",
    "c5e8f2a3b7d9",
    "b3d7e9f1a2c4",
    "b2d3e4f5a6b7",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_credentials",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("credential_type", sa.String(30), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("default_model", sa.String(100), nullable=False, server_default="gemini-2.5-flash-lite"),
        sa.Column("encrypted_api_key", sa.String(1024), nullable=True),
        sa.Column("project_id", sa.String(200), nullable=True),
        sa.Column("location", sa.String(100), nullable=True),
        sa.Column("client_email", sa.String(300), nullable=True),
        sa.Column("private_key_id", sa.String(200), nullable=True),
        sa.Column("encrypted_private_key", sa.String(8192), nullable=True),
        sa.Column("token_uri", sa.String(300), nullable=True, server_default="https://oauth2.googleapis.com/token"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_credentials_user_active",
        "ai_credentials",
        ["user_id", "is_active", "priority"],
    )

    # Backfill: copy existing gemini_api_key from users into ai_credentials
    op.execute("""
        INSERT INTO ai_credentials (user_id, credential_type, label, priority, is_active, default_model, encrypted_api_key, created_at)
        SELECT id, 'gemini_api_key', 'Default Gemini Key', 1, TRUE,
               COALESCE(
                   settings_json->>'gemini_model',
                   'gemini-2.5-flash-lite'
               ),
               gemini_api_key,
               now()
        FROM users
        WHERE gemini_api_key IS NOT NULL AND gemini_api_key != ''
    """)


def downgrade() -> None:
    op.drop_index("ix_ai_credentials_user_active", table_name="ai_credentials")
    op.drop_table("ai_credentials")
