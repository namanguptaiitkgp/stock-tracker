"""add stock_peers table

Revision ID: 7fa1f5b0faa0
Revises: a2c8d4f7b1e9
Create Date: 2026-05-02 06:39:20.467600

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7fa1f5b0faa0'
down_revision: Union[str, None] = 'a2c8d4f7b1e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stock_peers',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('symbol', sa.String(50), nullable=False),
        sa.Column('peer_symbol', sa.String(50), nullable=False),
        sa.Column('source', sa.String(30), nullable=False, server_default='gemini'),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('symbol', 'peer_symbol', name='uq_stock_peer'),
    )
    op.create_index('ix_stock_peers_symbol', 'stock_peers', ['symbol'])
    op.create_index('ix_stock_peers_peer_symbol', 'stock_peers', ['peer_symbol'])


def downgrade() -> None:
    op.drop_index('ix_stock_peers_peer_symbol', table_name='stock_peers')
    op.drop_index('ix_stock_peers_symbol', table_name='stock_peers')
    op.drop_table('stock_peers')
