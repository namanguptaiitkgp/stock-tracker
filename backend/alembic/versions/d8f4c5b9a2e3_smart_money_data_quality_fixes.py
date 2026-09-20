"""smart-money data-quality fixes (addendum A1a/c/d)

Revision ID: d8f4c5b9a2e3
Revises: c7a3b8e1d5f9
Create Date: 2026-05-02 09:00:00.000000

Adds three columns to support the addendum's data-quality work:
  - insider_disclosures.is_intra_group_transfer  (A1a)
  - bulk_block_deals.client_category             (A1c)
  - net_positions_30d.net_to_total_ratio         (A1d)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8f4c5b9a2e3"
down_revision: Union[str, None] = "c7a3b8e1d5f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A1a: tag intra-group transfers so the scorer can skip them.
    # Detector runs post-ingest and marks both sides of the pair.
    op.execute(
        "ALTER TABLE insider_disclosures "
        "ADD COLUMN IF NOT EXISTS is_intra_group_transfer BOOLEAN NOT NULL DEFAULT FALSE;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_insider_intra_group "
        "ON insider_disclosures (symbol, transaction_date) "
        "WHERE is_intra_group_transfer = TRUE;"
    )

    # A1c: classify each deal at ingestion time so the active-traders
    # table can default-hide PROP_HFT / BROKER without re-running the
    # classifier on every query. Existing rows backfilled by a one-off
    # task in services/smart_money/deals.py:reclassify_existing_deals.
    op.execute(
        "ALTER TABLE bulk_block_deals "
        "ADD COLUMN IF NOT EXISTS client_category VARCHAR(30);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bbd_category_date "
        "ON bulk_block_deals (client_category, trade_date DESC) "
        "WHERE client_category IS NOT NULL;"
    )

    # A1d: net/total ratio. Stored alongside the net so the active-
    # traders endpoint can filter by ratio without re-aggregating.
    op.execute(
        "ALTER TABLE net_positions_30d "
        "ADD COLUMN IF NOT EXISTS net_to_total_ratio NUMERIC(6,4);"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE net_positions_30d DROP COLUMN IF EXISTS net_to_total_ratio;")
    op.execute("DROP INDEX IF EXISTS ix_bbd_category_date;")
    op.execute("ALTER TABLE bulk_block_deals DROP COLUMN IF EXISTS client_category;")
    op.execute("DROP INDEX IF EXISTS ix_insider_intra_group;")
    op.execute("ALTER TABLE insider_disclosures DROP COLUMN IF EXISTS is_intra_group_transfer;")
