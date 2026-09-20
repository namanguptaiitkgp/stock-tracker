"""window_days on signals + user_holdings_metadata

Revision ID: a2c8d4f7b1e9
Revises: f1c8b2e7d9a3
Create Date: 2026-05-02 12:00:00.000000

PR 10 prerequisites for the holdings-signal layer:

  - `smart_money_signals.window_days INTEGER NOT NULL DEFAULT 30`. The
    existing unique constraint on (symbol, as_of) is replaced with one
    on (symbol, window_days, as_of) so future 90d/365d rollup rows can
    coexist with the 30d ones the rollup writes today.

  - `user_holdings_metadata` — per-user metadata for owned stocks
    (purchase date + thesis). Required for the holdings signal to
    compute "since you bought" comparisons, and for the Settings
    holdings editor to read/write thesis context.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2c8d4f7b1e9"
down_revision: Union[str, None] = "f1c8b2e7d9a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) window_days column on smart_money_signals.
    op.execute(
        "ALTER TABLE smart_money_signals "
        "ADD COLUMN IF NOT EXISTS window_days INTEGER NOT NULL DEFAULT 30;"
    )

    # Replace the legacy (symbol, as_of) unique constraint with one that
    # includes window_days. Drop-then-create keeps the migration idempotent —
    # the IF EXISTS / IF NOT EXISTS guards mean re-running is a no-op.
    op.execute(
        "ALTER TABLE smart_money_signals "
        "DROP CONSTRAINT IF EXISTS uq_smart_money_signal_symbol_date;"
    )
    op.execute(
        "ALTER TABLE smart_money_signals "
        "ADD CONSTRAINT uq_sm_signals_symbol_window_date "
        "UNIQUE (symbol, window_days, as_of);"
    )
    # The window_days secondary index is small + speeds up the holdings
    # signal endpoint that reads "latest 30d row per holding."
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sm_signals_window_date "
        "ON smart_money_signals (window_days, as_of DESC);"
    )

    # 2) user_holdings_metadata — per-user thesis tracking.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_holdings_metadata (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            symbol VARCHAR(50) NOT NULL,
            first_purchase_date DATE NOT NULL,
            initial_thesis TEXT,
            thesis_tags JSONB,
            target_holding_period_months INTEGER
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_holdings_metadata_user_symbol "
        "ON user_holdings_metadata (user_id, symbol);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_holdings_metadata_user_symbol;")
    op.execute("DROP TABLE IF EXISTS user_holdings_metadata;")
    op.execute("DROP INDEX IF EXISTS ix_sm_signals_window_date;")
    op.execute(
        "ALTER TABLE smart_money_signals "
        "DROP CONSTRAINT IF EXISTS uq_sm_signals_symbol_window_date;"
    )
    # Restore the original constraint name so a downgrade leaves the
    # legacy state intact (matches the model definition before PR 10).
    op.execute(
        "ALTER TABLE smart_money_signals "
        "ADD CONSTRAINT uq_smart_money_signal_symbol_date "
        "UNIQUE (symbol, as_of);"
    )
    op.execute("ALTER TABLE smart_money_signals DROP COLUMN IF EXISTS window_days;")
