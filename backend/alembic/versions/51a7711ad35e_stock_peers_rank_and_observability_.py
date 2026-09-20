"""stock_peers_rank_and_observability_tables

Phase B: add rank + generated_at to stock_peers so the table presents
peers in Gemini's relevance order and we can detect stale peer sets.

Phase F: create llm_calls + scrape_events audit tables for the activity
monitor (LLM cost tracking + scrape health metrics).

Revision ID: 51a7711ad35e
Revises: h1a2b3c4d5e6
Create Date: 2026-05-14 16:53:43.937031
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '51a7711ad35e'
down_revision: Union[str, None] = 'h1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Phase B: stock_peers rank + generated_at ──────────────────────
    op.add_column(
        "stock_peers",
        sa.Column("rank", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "stock_peers",
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill existing rows so the staleness query has something to read.
    op.execute("UPDATE stock_peers SET generated_at = NOW() WHERE generated_at IS NULL")
    op.create_index(
        "ix_stock_peers_symbol_rank",
        "stock_peers", ["symbol", "rank"],
        unique=False,
    )

    # ── Phase F: llm_calls audit table ────────────────────────────────
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("model", sa.String(60), nullable=True),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("credential_id", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error_class", sa.String(80), nullable=True),
    )
    op.create_index("ix_llm_calls_ts", "llm_calls", [sa.text("ts DESC")])
    op.create_index("ix_llm_calls_purpose_ts", "llm_calls", ["purpose", sa.text("ts DESC")])
    op.create_index("ix_llm_calls_symbol_ts", "llm_calls", ["symbol", sa.text("ts DESC")])

    # ── Phase F: scrape_events audit table ────────────────────────────
    op.create_table(
        "scrape_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=True),
        sa.Column("status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error_class", sa.String(80), nullable=True),
    )
    op.create_index("ix_scrape_events_ts", "scrape_events", [sa.text("ts DESC")])
    op.create_index("ix_scrape_events_source_ts", "scrape_events", ["source", sa.text("ts DESC")])


def downgrade() -> None:
    op.drop_index("ix_scrape_events_source_ts", table_name="scrape_events")
    op.drop_index("ix_scrape_events_ts", table_name="scrape_events")
    op.drop_table("scrape_events")

    op.drop_index("ix_llm_calls_symbol_ts", table_name="llm_calls")
    op.drop_index("ix_llm_calls_purpose_ts", table_name="llm_calls")
    op.drop_index("ix_llm_calls_ts", table_name="llm_calls")
    op.drop_table("llm_calls")

    op.drop_index("ix_stock_peers_symbol_rank", table_name="stock_peers")
    op.drop_column("stock_peers", "generated_at")
    op.drop_column("stock_peers", "rank")
