"""sector_override on user_holdings_metadata + relax first_purchase_date

Adds:
  • `sector_override VARCHAR(80) NULL` — user-supplied manual sector tag.
    Read by the sector resolver as the highest-priority source of truth
    (above Screener.in, Nifty membership, NSE industry, yfinance).

  • Relaxes `first_purchase_date` to NULL. Lets users set just a sector
    override without also having to commit to a purchase date. Existing
    rows are unaffected (already have a value); future rows can omit it.

Idempotent via IF NOT EXISTS / DROP NOT NULL.

Revision ID: ca1a1eaf00a4
Revises: 51a7711ad35e
Create Date: 2026-05-17 09:45:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "ca1a1eaf00a4"
down_revision: Union[str, None] = "51a7711ad35e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add sector_override column (idempotent).
    op.execute(
        "ALTER TABLE user_holdings_metadata "
        "ADD COLUMN IF NOT EXISTS sector_override VARCHAR(80) NULL"
    )

    # Relax first_purchase_date to nullable so users can record metadata
    # (e.g., sector_override) without committing to a purchase date.
    # `DROP NOT NULL` is idempotent — Postgres no-ops when already nullable.
    op.execute(
        "ALTER TABLE user_holdings_metadata "
        "ALTER COLUMN first_purchase_date DROP NOT NULL"
    )


def downgrade() -> None:
    # NOTE: downgrade restores NOT NULL on first_purchase_date which will
    # fail if any rows have a NULL value. Caller must clean those up first
    # (e.g., `UPDATE ... SET first_purchase_date = '2020-01-01' WHERE ...`).
    op.execute(
        "ALTER TABLE user_holdings_metadata "
        "ALTER COLUMN first_purchase_date SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE user_holdings_metadata DROP COLUMN IF EXISTS sector_override"
    )
