"""add data_sources to stock_fundamentals

Revision ID: c3a1f5e82d01
Revises: bbca204e9fa0
Create Date: 2026-04-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3a1f5e82d01'
down_revision: Union[str, None] = 'bbca204e9fa0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stock_fundamentals', sa.Column('data_sources', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('stock_fundamentals', 'data_sources')
