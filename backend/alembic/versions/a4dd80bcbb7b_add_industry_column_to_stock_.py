"""add industry column to stock_fundamentals

Revision ID: a4dd80bcbb7b
Revises: 654caa8144d5
Create Date: 2026-05-10 02:03:54.968031

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a4dd80bcbb7b'
down_revision: Union[str, None] = '654caa8144d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stock_fundamentals', sa.Column('industry', sa.String(length=150), nullable=True))


def downgrade() -> None:
    op.drop_column('stock_fundamentals', 'industry')
