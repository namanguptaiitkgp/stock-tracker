"""add reviewed_at to investment_decisions

Revision ID: 5d5548695101
Revises: g1a2b3c4d5e6
Create Date: 2026-05-13 03:35:20.276671

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '5d5548695101'
down_revision: Union[str, None] = 'g1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('investment_decisions', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('investment_decisions', 'reviewed_at')
