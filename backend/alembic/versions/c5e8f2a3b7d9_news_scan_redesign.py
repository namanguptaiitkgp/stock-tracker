"""news scan redesign: add dismissed_json, convert News Scan to user watchlist

Revision ID: c5e8f2a3b7d9
Revises: a4dd80bcbb7b
Create Date: 2026-05-10 18:00:00.000000

"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "c5e8f2a3b7d9"
down_revision: Union[str, None] = "a4dd80bcbb7b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "daily_news_reports",
        sa.Column("dismissed_json", JSONB, nullable=True, server_default="[]"),
    )
    op.execute(
        "UPDATE watchlists SET is_system = false WHERE name = 'News Scan' AND is_system = true"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE watchlists SET is_system = true WHERE name = 'News Scan' AND is_system = false"
    )
    op.drop_column("daily_news_reports", "dismissed_json")
