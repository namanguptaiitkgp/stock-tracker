"""client_overrides — per-user category teaching for smart-money

Revision ID: e9f5a2b8d4c1
Revises: d8f4c5b9a2e3
Create Date: 2026-05-02 09:30:00.000000

Per addendum §A2e. The user can reclassify a client whose category
the heuristic classifier got wrong (e.g. "AUTHUM INVESTMENT is a value
fund, not CORP_OTHER"). Stored per-user so two admins can hold
different opinions without one stepping on the other.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9f5a2b8d4c1"
down_revision: Union[str, None] = "d8f4c5b9a2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_overrides (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_name_norm VARCHAR(255) NOT NULL,
            override_category VARCHAR(30) NOT NULL,
            notes TEXT
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_client_override "
        "ON client_overrides (user_id, client_name_norm);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_client_override;")
    op.execute("DROP TABLE IF EXISTS client_overrides;")
