"""smart money revamp: conviction / flow / red-flags schema

Revision ID: c7a3b8e1d5f9
Revises: b9e1f4d3c2a5
Create Date: 2026-05-01 18:00:00.000000

Adds the new tables and columns needed by the smart-money revamp:
  - insider_disclosures
  - shareholding_patterns
  - corporate_announcements
  - fii_dii_stock_daily
  - net_positions_30d
  - smart_money_signals  +conviction_score, +flow_score, +red_flag_score, +signal_breakdown
  - known_sharks         +tier, +entity_type

Idempotent (CREATE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS) so re-runs
on a partially-migrated DB don't fail. New columns default to NULL or
the safe-backfill default; rollup populates on its next run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7a3b8e1d5f9"
down_revision: Union[str, None] = "b9e1f4d3c2a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- insider_disclosures (NSE/BSE PIT Reg 7 filings) -------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS insider_disclosures (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            symbol VARCHAR(50) NOT NULL,
            isin VARCHAR(12),
            company_name VARCHAR(255),
            category VARCHAR(50) NOT NULL,
            person_name VARCHAR(255) NOT NULL,
            person_name_norm VARCHAR(255) NOT NULL,
            relation VARCHAR(100),
            transaction_type VARCHAR(10) NOT NULL,
            shares BIGINT NOT NULL,
            value_inr NUMERIC(18,2),
            transaction_date DATE NOT NULL,
            intimation_date DATE NOT NULL,
            mode VARCHAR(50),
            pre_holding_pct NUMERIC(8,4),
            post_holding_pct NUMERIC(8,4),
            exchange VARCHAR(10) NOT NULL DEFAULT 'NSE',
            is_known_shark BOOLEAN NOT NULL DEFAULT FALSE,
            raw_json JSONB
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_insider_symbol_date ON insider_disclosures (symbol, transaction_date DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_insider_category_date ON insider_disclosures (category, transaction_date DESC);")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_insider_dedup
        ON insider_disclosures (symbol, person_name_norm, transaction_date, transaction_type, shares);
        """
    )

    # ---- shareholding_patterns (quarterly) --------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shareholding_patterns (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            symbol VARCHAR(50) NOT NULL,
            isin VARCHAR(12),
            quarter VARCHAR(10) NOT NULL,
            quarter_end_date DATE NOT NULL,
            promoter_pct NUMERIC(8,4),
            promoter_pledge_pct NUMERIC(8,4),
            fii_pct NUMERIC(8,4),
            dii_pct NUMERIC(8,4),
            mf_pct NUMERIC(8,4),
            insurance_pct NUMERIC(8,4),
            public_pct NUMERIC(8,4),
            promoter_delta NUMERIC(8,4),
            fii_delta NUMERIC(8,4),
            dii_delta NUMERIC(8,4),
            pledge_delta NUMERIC(8,4),
            exchange VARCHAR(10) NOT NULL DEFAULT 'BSE',
            raw_json JSONB
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_shp_symbol_quarter ON shareholding_patterns (symbol, quarter_end_date DESC);")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_shp_dedup
        ON shareholding_patterns (symbol, quarter_end_date, exchange);
        """
    )

    # ---- corporate_announcements (buyback / pledge) -----------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS corporate_announcements (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            symbol VARCHAR(50) NOT NULL,
            announcement_type VARCHAR(50) NOT NULL,
            headline TEXT NOT NULL,
            detail_json JSONB,
            buyback_size_inr NUMERIC(18,2),
            buyback_price_inr NUMERIC(12,2),
            pledge_shares BIGINT,
            pledge_pct_of_holding NUMERIC(8,4),
            pledge_direction VARCHAR(20),
            pledgor_name VARCHAR(255),
            announcement_date DATE NOT NULL,
            exchange VARCHAR(10) NOT NULL DEFAULT 'NSE',
            raw_json JSONB
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_corp_ann_symbol_date ON corporate_announcements (symbol, announcement_date DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_corp_ann_type_date ON corporate_announcements (announcement_type, announcement_date DESC);")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_corp_ann_dedup
        ON corporate_announcements (symbol, announcement_type, announcement_date, md5(headline));
        """
    )

    # ---- fii_dii_stock_daily ----------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fii_dii_stock_daily (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            symbol VARCHAR(50) NOT NULL,
            trade_date DATE NOT NULL,
            fii_buy_value NUMERIC(18,2),
            fii_sell_value NUMERIC(18,2),
            fii_net_value NUMERIC(18,2),
            dii_buy_value NUMERIC(18,2),
            dii_sell_value NUMERIC(18,2),
            dii_net_value NUMERIC(18,2)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_fii_dii_stock_symbol_date ON fii_dii_stock_daily (symbol, trade_date DESC);")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_fii_dii_stock_dedup
        ON fii_dii_stock_daily (symbol, trade_date);
        """
    )

    # ---- net_positions_30d (rollup-materialized) --------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS net_positions_30d (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            symbol VARCHAR(50) NOT NULL,
            as_of DATE NOT NULL,
            party_name_norm VARCHAR(255) NOT NULL,
            party_category VARCHAR(30) NOT NULL,
            net_shares BIGINT NOT NULL,
            net_value_inr NUMERIC(18,2),
            distinct_buy_days INT,
            distinct_sell_days INT,
            is_known_shark BOOLEAN NOT NULL DEFAULT FALSE,
            is_circular_suspect BOOLEAN NOT NULL DEFAULT FALSE
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_net_pos_symbol_date ON net_positions_30d (symbol, as_of DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_net_pos_shark ON net_positions_30d (is_known_shark, as_of DESC) WHERE is_known_shark = TRUE;")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_net_pos_dedup
        ON net_positions_30d (symbol, as_of, party_name_norm);
        """
    )

    # ---- smart_money_signals: new score columns ---------------------------
    op.execute("ALTER TABLE smart_money_signals ADD COLUMN IF NOT EXISTS conviction_score NUMERIC(6,2);")
    op.execute("ALTER TABLE smart_money_signals ADD COLUMN IF NOT EXISTS flow_score NUMERIC(6,2);")
    op.execute("ALTER TABLE smart_money_signals ADD COLUMN IF NOT EXISTS red_flag_score NUMERIC(6,2);")
    op.execute("ALTER TABLE smart_money_signals ADD COLUMN IF NOT EXISTS signal_breakdown JSONB;")

    # ---- known_sharks: tier + entity_type ---------------------------------
    op.execute("ALTER TABLE known_sharks ADD COLUMN IF NOT EXISTS tier INTEGER NOT NULL DEFAULT 1;")
    op.execute(
        "ALTER TABLE known_sharks ADD COLUMN IF NOT EXISTS entity_type VARCHAR(30) NOT NULL DEFAULT 'individual';"
    )
    # Existing rows backfilled by the DEFAULT clause — verify no NULLs.
    # Future seed expansion will explicitly set tier (1/2/3) and entity_type.


def downgrade() -> None:
    # Drop only what this migration introduced. Don't touch existing columns
    # we'd alter in production. Indexes drop with their tables.
    op.execute("DROP TABLE IF EXISTS net_positions_30d;")
    op.execute("DROP TABLE IF EXISTS fii_dii_stock_daily;")
    op.execute("DROP TABLE IF EXISTS corporate_announcements;")
    op.execute("DROP TABLE IF EXISTS shareholding_patterns;")
    op.execute("DROP TABLE IF EXISTS insider_disclosures;")

    op.execute("ALTER TABLE smart_money_signals DROP COLUMN IF EXISTS signal_breakdown;")
    op.execute("ALTER TABLE smart_money_signals DROP COLUMN IF EXISTS red_flag_score;")
    op.execute("ALTER TABLE smart_money_signals DROP COLUMN IF EXISTS flow_score;")
    op.execute("ALTER TABLE smart_money_signals DROP COLUMN IF EXISTS conviction_score;")

    op.execute("ALTER TABLE known_sharks DROP COLUMN IF EXISTS entity_type;")
    op.execute("ALTER TABLE known_sharks DROP COLUMN IF EXISTS tier;")
