"""Extend sector_analyses with score / confidence / summary / drivers / etc.

Persists the richer 7-field LLM output from the rewritten
`SECTOR_SENTIMENT_PROMPT` (Market Brief — Sectors panel v1). Previously
only `mood` (uppercased sentiment) and `signals` (top-3 key_themes) were
kept; score, confidence, the 5-sentence summary, macro drivers, and
"what to watch" events were dropped on persist.

Six additive columns, all NULL — existing rows stay valid and continue
to feed the dashboard's per-holding sector-mood chip via the existing
`mood` column. Idempotent via `ADD COLUMN IF NOT EXISTS` so re-running
on a partially-migrated DB is safe.

Revision ID: d2f8a4b6c1e7
Revises: ca1a1eaf00a4
Create Date: 2026-05-17 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d2f8a4b6c1e7"
down_revision: Union[str, None] = "ca1a1eaf00a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All six adds are independent; emit as separate idempotent statements
    # so a partial-failure mid-migration leaves the rest applied.
    op.execute(
        "ALTER TABLE sector_analyses ADD COLUMN IF NOT EXISTS score INTEGER NULL"
    )
    op.execute(
        "ALTER TABLE sector_analyses ADD COLUMN IF NOT EXISTS confidence VARCHAR(10) NULL"
    )
    op.execute(
        "ALTER TABLE sector_analyses ADD COLUMN IF NOT EXISTS summary TEXT NULL"
    )
    op.execute(
        "ALTER TABLE sector_analyses ADD COLUMN IF NOT EXISTS macro_drivers JSON NULL"
    )
    op.execute(
        "ALTER TABLE sector_analyses ADD COLUMN IF NOT EXISTS what_to_watch JSON NULL"
    )
    op.execute(
        "ALTER TABLE sector_analyses ADD COLUMN IF NOT EXISTS top_headlines JSON NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sector_analyses DROP COLUMN IF EXISTS top_headlines")
    op.execute("ALTER TABLE sector_analyses DROP COLUMN IF EXISTS what_to_watch")
    op.execute("ALTER TABLE sector_analyses DROP COLUMN IF EXISTS macro_drivers")
    op.execute("ALTER TABLE sector_analyses DROP COLUMN IF EXISTS summary")
    op.execute("ALTER TABLE sector_analyses DROP COLUMN IF EXISTS confidence")
    op.execute("ALTER TABLE sector_analyses DROP COLUMN IF EXISTS score")
