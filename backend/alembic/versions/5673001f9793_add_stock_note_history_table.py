"""add stock_note_history table

Revision ID: 5673001f9793
Revises: 66f49c7b670b
Create Date: 2026-04-30 06:07:34.454900

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5673001f9793'
down_revision: Union[str, None] = '66f49c7b670b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stock_note_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_stock_note_history_user_id', 'stock_note_history', ['user_id'])
    op.create_index('ix_stock_note_history_symbol', 'stock_note_history', ['symbol'])


def downgrade() -> None:
    op.drop_index('ix_stock_note_history_symbol', table_name='stock_note_history')
    op.drop_index('ix_stock_note_history_user_id', table_name='stock_note_history')
    op.drop_table('stock_note_history')
