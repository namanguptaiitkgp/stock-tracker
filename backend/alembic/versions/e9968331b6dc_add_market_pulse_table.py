"""add_market_pulse_table

Revision ID: e9968331b6dc
Revises: 5673001f9793
Create Date: 2026-04-30 12:48:23.723967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9968331b6dc'
down_revision: Union[str, None] = '5673001f9793'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'market_pulse',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('direction', sa.String(length=12), nullable=True),
        sa.Column('magnitude', sa.String(length=12), nullable=True),
        sa.Column('label', sa.String(length=40), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('breadth', sa.Float(), nullable=True),
        sa.Column('components', sa.JSON(), nullable=True),
        sa.Column('vix', sa.JSON(), nullable=True),
        sa.Column('one_liner', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('drivers', sa.JSON(), nullable=True),
        sa.Column('top_headlines', sa.JSON(), nullable=True),
        sa.Column('news_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('model_used', sa.String(length=60), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_market_pulse_generated_at'), 'market_pulse', ['generated_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_market_pulse_generated_at'), table_name='market_pulse')
    op.drop_table('market_pulse')
