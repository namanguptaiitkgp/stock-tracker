"""add watchlist is_system flag

Revision ID: b3d7e9f1a2c4
Revises: a1b2c3d4e5f6
Create Date: 2026-05-05 12:00:00.000000

"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3d7e9f1a2c4"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watchlists",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("watchlists", "is_system")
