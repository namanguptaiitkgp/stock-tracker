"""add promoter_holding to stock_fundamentals

Revision ID: 66f49c7b670b
Revises: b2d3e4f5a6b7
Create Date: 2026-04-29 18:51:15.579929

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '66f49c7b670b'
down_revision: Union[str, None] = 'b2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stock_fundamentals', sa.Column('promoter_holding', sa.Numeric(precision=10, scale=4), nullable=True))


def downgrade() -> None:
    op.drop_column('stock_fundamentals', 'promoter_holding')
