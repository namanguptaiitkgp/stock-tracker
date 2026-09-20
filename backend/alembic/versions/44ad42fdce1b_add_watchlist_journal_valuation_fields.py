"""add_watchlist_journal_valuation_fields

Revision ID: 44ad42fdce1b
Revises: e9968331b6dc
Create Date: 2026-04-30 19:17:31.691741

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '44ad42fdce1b'
down_revision: Union[str, None] = 'e9968331b6dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New fields on watchlist_items for the Researching card
    op.add_column('watchlist_items', sa.Column('reason', sa.Text(), nullable=True))
    op.add_column('watchlist_items', sa.Column('pe_target', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('watchlist_items', sa.Column('peer_symbols', sa.JSON(), nullable=True))
    op.add_column('watchlist_items', sa.Column('watch_rules', sa.JSON(), nullable=True))
    op.add_column('watchlist_items', sa.Column('lane', sa.String(length=40), nullable=True))

    # Journal entries (free-text log per item)
    op.create_table(
        'watchlist_journal_entries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('watchlist_item_id', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['watchlist_item_id'], ['watchlist_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_watchlist_journal_entries_watchlist_item_id', 'watchlist_journal_entries', ['watchlist_item_id'])

    # Daily valuation snapshots (post-market close cron job)
    op.create_table(
        'watchlist_valuation_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('watchlist_item_id', sa.Integer(), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('cmp', sa.Float(), nullable=True),
        sa.Column('pe_ratio', sa.Float(), nullable=True),
        sa.Column('pb_ratio', sa.Float(), nullable=True),
        sa.Column('pct_from_52w_high', sa.Float(), nullable=True),
        sa.Column('pct_from_52w_low', sa.Float(), nullable=True),
        sa.Column('high_52w', sa.Float(), nullable=True),
        sa.Column('low_52w', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['watchlist_item_id'], ['watchlist_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('watchlist_item_id', 'snapshot_date', name='uq_wl_item_snapshot_date'),
    )
    op.create_index('ix_watchlist_valuation_snapshots_watchlist_item_id', 'watchlist_valuation_snapshots', ['watchlist_item_id'])
    op.create_index('ix_watchlist_valuation_snapshots_snapshot_date', 'watchlist_valuation_snapshots', ['snapshot_date'])


def downgrade() -> None:
    op.drop_index('ix_watchlist_valuation_snapshots_snapshot_date', table_name='watchlist_valuation_snapshots')
    op.drop_index('ix_watchlist_valuation_snapshots_watchlist_item_id', table_name='watchlist_valuation_snapshots')
    op.drop_table('watchlist_valuation_snapshots')
    op.drop_index('ix_watchlist_journal_entries_watchlist_item_id', table_name='watchlist_journal_entries')
    op.drop_table('watchlist_journal_entries')
    op.drop_column('watchlist_items', 'lane')
    op.drop_column('watchlist_items', 'watch_rules')
    op.drop_column('watchlist_items', 'peer_symbols')
    op.drop_column('watchlist_items', 'pe_target')
    op.drop_column('watchlist_items', 'reason')
