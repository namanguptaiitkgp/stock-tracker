"""add paper trading tables

Revision ID: 654caa8144d5
Revises: b3d7e9f1a2c4
Create Date: 2026-05-09 10:34:57.988919

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '654caa8144d5'
down_revision: Union[str, None] = 'b3d7e9f1a2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('paper_agents',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('strategy_id', sa.Integer(), nullable=True),
        sa.Column('initial_corpus_inr', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('config_json', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['strategy_id'], ['strategies.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table('paper_events',
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=20), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=True),
        sa.Column('exchange', sa.String(length=10), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('price_inr', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False, server_default=sa.text("'manual'")),
        sa.Column('snapshot_json', sa.JSON(), nullable=True),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['paper_agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_paper_events_agent_created', 'paper_events', ['agent_id', 'created_at'], unique=False)
    op.create_index('ix_paper_events_agent_type', 'paper_events', ['agent_id', 'event_type'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_paper_events_agent_type', table_name='paper_events')
    op.drop_index('ix_paper_events_agent_created', table_name='paper_events')
    op.drop_table('paper_events')
    op.drop_table('paper_agents')
