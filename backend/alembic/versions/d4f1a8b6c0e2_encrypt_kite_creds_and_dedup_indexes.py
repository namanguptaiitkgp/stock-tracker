"""encrypt user credentials at rest + add dedup indexes

Revision ID: d4f1a8b6c0e2
Revises: c5b9a7e2f4d1
Create Date: 2026-04-30 12:00:00.000000

Widens the per-user credential columns (kite_api_key, kite_api_secret,
kite_access_token, gemini_api_key, anthropic_api_key) from String(255) to
String(512) to fit Fernet ciphertext, and re-encrypts any existing plaintext
rows in place. Also adds two indexes that the dedup work in api/today.py and
api/news_inbox.py relies on.

The data migration uses app.security.crypto.encrypt(), which is idempotent —
already-encrypted rows pass through unchanged.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4f1a8b6c0e2"
down_revision: Union[str, None] = "c5b9a7e2f4d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CREDENTIAL_COLUMNS = (
    "kite_api_key",
    "kite_api_secret",
    "kite_access_token",
    "gemini_api_key",
    "anthropic_api_key",
)


def upgrade() -> None:
    # 1. Widen the credential columns to hold Fernet ciphertext (~100-180 chars
    # for short inputs; 512 leaves headroom).
    for col in CREDENTIAL_COLUMNS:
        op.alter_column(
            "users",
            col,
            existing_type=sa.String(length=255),
            type_=sa.String(length=512),
            existing_nullable=True,
        )

    # 2. Encrypt any existing plaintext values in place. encrypt() is a no-op
    # when the value already looks like a Fernet token, so re-running this
    # migration is safe.
    from app.security.crypto import encrypt  # local import — needs app context

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, " + ", ".join(CREDENTIAL_COLUMNS) + " FROM users"
        )
    ).fetchall()
    for row in rows:
        updates = {}
        for col in CREDENTIAL_COLUMNS:
            current = getattr(row, col)
            new = encrypt(current)
            if new != current:
                updates[col] = new
        if updates:
            set_clause = ", ".join(f"{c} = :{c}" for c in updates)
            conn.execute(
                sa.text(f"UPDATE users SET {set_clause} WHERE id = :id"),
                {**updates, "id": row.id},
            )

    # 3. Indexes that the Phase-3 batched queries rely on. IF NOT EXISTS so
    #    re-running on a DB that already auto-created them via model
    #    `index=True` declarations is safe.
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_investment_decisions_user_symbol "
        "ON investment_decisions (user_id, symbol)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_news_sentiment_cache_symbol "
        "ON news_sentiment_cache (symbol)"
    ))

    # 4. Housekeeping — clear stale fetch_cache rows older than 7 days. Idempotent.
    conn.execute(
        sa.text(
            "DELETE FROM fetch_cache WHERE expires_at IS NOT NULL "
            "AND expires_at < (NOW() - INTERVAL '7 days')"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_news_sentiment_cache_symbol", table_name="news_sentiment_cache")
    op.drop_index(
        "ix_investment_decisions_user_symbol", table_name="investment_decisions"
    )

    # Best-effort decrypt back to plaintext so a downgrade leaves the rows usable.
    from app.security.crypto import decrypt  # local import

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, " + ", ".join(CREDENTIAL_COLUMNS) + " FROM users")
    ).fetchall()
    for row in rows:
        updates = {}
        for col in CREDENTIAL_COLUMNS:
            current = getattr(row, col)
            try:
                new = decrypt(current)
            except Exception:  # noqa: BLE001
                new = current
            if new != current:
                updates[col] = new
        if updates:
            set_clause = ", ".join(f"{c} = :{c}" for c in updates)
            conn.execute(
                sa.text(f"UPDATE users SET {set_clause} WHERE id = :id"),
                {**updates, "id": row.id},
            )

    for col in CREDENTIAL_COLUMNS:
        op.alter_column(
            "users",
            col,
            existing_type=sa.String(length=512),
            type_=sa.String(length=255),
            existing_nullable=True,
        )
