"""add shareholding_history + 52w fields to fundamentals + price_target on watchlist_items

Revision ID: c5b9a7e2f4d1
Revises: 8a2f1c4d9e3b
Create Date: 2026-05-01 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5b9a7e2f4d1"
down_revision: Union[str, None] = "8a2f1c4d9e3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-fundamentals shareholding history snapshot (4-6 quarters from tickertape)
    op.add_column("stock_fundamentals", sa.Column("shareholding_history", sa.JSON(), nullable=True))
    # 52w fields cached for peers comparison (avoids re-fetching technicals per-peer)
    op.add_column("stock_fundamentals", sa.Column("high_52w", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("stock_fundamentals", sa.Column("low_52w", sa.Numeric(precision=12, scale=2), nullable=True))

    # Per-item price target on watchlist
    op.add_column("watchlist_items", sa.Column("price_target", sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column("watchlist_items", "price_target")
    op.drop_column("stock_fundamentals", "low_52w")
    op.drop_column("stock_fundamentals", "high_52w")
    op.drop_column("stock_fundamentals", "shareholding_history")
