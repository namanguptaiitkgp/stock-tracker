"""add smart money schema

Revision ID: f3e8c9a2b1d4
Revises: 55905dcb95ea
Create Date: 2026-04-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3e8c9a2b1d4"
down_revision: Union[str, None] = "55905dcb95ea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # mf_schemes
    op.create_table(
        "mf_schemes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amfi_scheme_code", sa.String(length=20), nullable=False),
        sa.Column("scheme_name", sa.String(length=512), nullable=False),
        sa.Column("fund_house", sa.String(length=255), nullable=True),
        sa.Column("scheme_type", sa.String(length=120), nullable=True),
        sa.Column("scheme_category", sa.String(length=120), nullable=True),
        sa.Column("isin_growth", sa.String(length=20), nullable=True),
        sa.Column("isin_div_reinvest", sa.String(length=20), nullable=True),
        sa.Column("nav", sa.Numeric(18, 4), nullable=True),
        sa.Column("nav_date", sa.Date(), nullable=True),
        sa.Column("aum_crore", sa.Numeric(18, 2), nullable=True),
        sa.Column("aum_as_of", sa.Date(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("amfi_scheme_code"),
    )
    op.create_index("ix_mf_schemes_amfi_scheme_code", "mf_schemes", ["amfi_scheme_code"], unique=True)
    op.create_index("ix_mf_schemes_fund_house", "mf_schemes", ["fund_house"])
    op.create_index("ix_mf_schemes_scheme_category", "mf_schemes", ["scheme_category"])

    # mf_holdings_monthly
    op.create_table(
        "mf_holdings_monthly",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheme_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("isin", sa.String(length=20), nullable=True),
        sa.Column("instrument_name_raw", sa.String(length=255), nullable=False),
        sa.Column("report_month", sa.Date(), nullable=False),
        sa.Column("units", sa.Numeric(20, 4), nullable=True),
        sa.Column("market_value_inr", sa.Numeric(20, 2), nullable=True),
        sa.Column("pct_of_aum", sa.Numeric(8, 4), nullable=True),
        sa.Column("prev_units", sa.Numeric(20, 4), nullable=True),
        sa.Column("change_units", sa.Numeric(20, 4), nullable=True),
        sa.Column("change_type", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["scheme_id"], ["mf_schemes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scheme_id", "symbol", "report_month", name="uq_mf_holding_scheme_symbol_month"),
    )
    op.create_index("ix_mf_holdings_monthly_symbol", "mf_holdings_monthly", ["symbol"])
    op.create_index("ix_mf_holdings_monthly_isin", "mf_holdings_monthly", ["isin"])
    op.create_index("ix_mf_holdings_symbol_month", "mf_holdings_monthly", ["symbol", "report_month"])
    op.create_index("ix_mf_holdings_scheme_month", "mf_holdings_monthly", ["scheme_id", "report_month"])

    # pms_managers
    op.create_table(
        "pms_managers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sebi_reg_no", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("total_aum_crore", sa.Numeric(18, 2), nullable=True),
        sa.Column("website", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sebi_reg_no"),
    )
    op.create_index("ix_pms_managers_sebi_reg_no", "pms_managers", ["sebi_reg_no"], unique=True)

    # pms_strategy_holdings_quarterly
    op.create_table(
        "pms_strategy_holdings_quarterly",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=False),
        sa.Column("strategy_name", sa.String(length=255), nullable=False),
        sa.Column("strategy_investment_approach", sa.String(length=120), nullable=True),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("isin", sa.String(length=20), nullable=True),
        sa.Column("instrument_name_raw", sa.String(length=255), nullable=False),
        sa.Column("report_quarter", sa.Date(), nullable=False),
        sa.Column("pct_of_strategy", sa.Numeric(8, 4), nullable=True),
        sa.Column("market_value_inr", sa.Numeric(20, 2), nullable=True),
        sa.Column("source_pdf_url", sa.String(length=1024), nullable=True),
        sa.Column("parsed_by", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["manager_id"], ["pms_managers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "manager_id", "strategy_name", "symbol", "report_quarter",
            name="uq_pms_holding_mgr_strat_symbol_q",
        ),
    )
    op.create_index("ix_pms_strategy_holdings_quarterly_symbol", "pms_strategy_holdings_quarterly", ["symbol"])
    op.create_index("ix_pms_holdings_symbol_q", "pms_strategy_holdings_quarterly", ["symbol", "report_quarter"])
    op.create_index("ix_pms_holdings_mgr_q", "pms_strategy_holdings_quarterly", ["manager_id", "report_quarter"])

    # aif_funds
    op.create_table(
        "aif_funds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sebi_reg_no", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=True),
        sa.Column("sponsor", sa.String(length=255), nullable=True),
        sa.Column("scheme_name", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sebi_reg_no"),
    )
    op.create_index("ix_aif_funds_sebi_reg_no", "aif_funds", ["sebi_reg_no"], unique=True)
    op.create_index("ix_aif_funds_category", "aif_funds", ["category"])

    # aif_holdings_quarterly
    op.create_table(
        "aif_holdings_quarterly",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fund_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("isin", sa.String(length=20), nullable=True),
        sa.Column("instrument_name_raw", sa.String(length=255), nullable=False),
        sa.Column("report_quarter", sa.Date(), nullable=False),
        sa.Column("units", sa.Numeric(20, 4), nullable=True),
        sa.Column("market_value_inr", sa.Numeric(20, 2), nullable=True),
        sa.Column("pct_of_corpus", sa.Numeric(8, 4), nullable=True),
        sa.Column("source_pdf_url", sa.String(length=1024), nullable=True),
        sa.Column("parsed_by", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["fund_id"], ["aif_funds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fund_id", "symbol", "report_quarter", name="uq_aif_holding_fund_symbol_q"),
    )
    op.create_index("ix_aif_holdings_quarterly_symbol", "aif_holdings_quarterly", ["symbol"])
    op.create_index("ix_aif_holdings_symbol_q", "aif_holdings_quarterly", ["symbol", "report_quarter"])
    op.create_index("ix_aif_holdings_fund_q", "aif_holdings_quarterly", ["fund_id", "report_quarter"])

    # bulk_block_deals
    op.create_table(
        "bulk_block_deals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("exchange", sa.String(length=4), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("security_name_raw", sa.String(length=255), nullable=True),
        sa.Column("client_name_raw", sa.String(length=255), nullable=False),
        sa.Column("client_name_norm", sa.String(length=255), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 0), nullable=False),
        sa.Column("avg_price", sa.Numeric(16, 4), nullable=False),
        sa.Column("trade_value_inr", sa.Numeric(20, 2), nullable=True),
        sa.Column("deal_type", sa.String(length=8), nullable=False),
        sa.Column("is_known_shark", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bbd_symbol_date", "bulk_block_deals", ["symbol", "trade_date"])
    op.create_index("ix_bbd_client_date", "bulk_block_deals", ["client_name_norm", "trade_date"])
    op.create_index("ix_bbd_date", "bulk_block_deals", ["trade_date"])

    # bhavcopy_daily
    op.create_table(
        "bhavcopy_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("exchange", sa.String(length=4), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("series", sa.String(length=8), nullable=True),
        sa.Column("open_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("high_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("low_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("close_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("prev_close", sa.Numeric(14, 4), nullable=True),
        sa.Column("traded_qty", sa.Numeric(20, 0), nullable=True),
        sa.Column("turnover_inr", sa.Numeric(20, 2), nullable=True),
        sa.Column("delivery_qty", sa.Numeric(20, 0), nullable=True),
        sa.Column("delivery_pct", sa.Numeric(8, 4), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "exchange", "symbol", name="uq_bhav_date_exch_symbol"),
    )
    op.create_index("ix_bhav_symbol_date", "bhavcopy_daily", ["symbol", "trade_date"])
    op.create_index("ix_bhav_date", "bhavcopy_daily", ["trade_date"])

    # smart_money_signals
    op.create_table(
        "smart_money_signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("mf_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("pms_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("aif_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("deals_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("delivery_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("composite", sa.Numeric(6, 2), nullable=True),
        sa.Column("top_adders", sa.JSON(), nullable=True),
        sa.Column("top_reducers", sa.JSON(), nullable=True),
        sa.Column("named_sharks", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "as_of", name="uq_smart_money_signal_symbol_date"),
    )
    op.create_index("ix_sms_symbol_date", "smart_money_signals", ["symbol", "as_of"])
    op.create_index("ix_sms_as_of", "smart_money_signals", ["as_of"])
    op.create_index("ix_sms_composite", "smart_money_signals", ["composite"])

    # known_sharks
    op.create_table(
        "known_sharks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_name"),
    )
    op.create_index("ix_known_sharks_canonical_name", "known_sharks", ["canonical_name"], unique=True)

    # ingestion_runs
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("task_name", sa.String(length=120), nullable=True),
        sa.Column("celery_task_id", sa.String(length=60), nullable=True),
        sa.Column("triggered_by", sa.String(length=20), nullable=False, server_default="beat"),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("records_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_class", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ing_runs_source_started", "ingestion_runs", ["source", "started_at"])
    op.create_index("ix_ing_runs_status", "ingestion_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ing_runs_status", table_name="ingestion_runs")
    op.drop_index("ix_ing_runs_source_started", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")

    op.drop_index("ix_known_sharks_canonical_name", table_name="known_sharks")
    op.drop_table("known_sharks")

    op.drop_index("ix_sms_composite", table_name="smart_money_signals")
    op.drop_index("ix_sms_as_of", table_name="smart_money_signals")
    op.drop_index("ix_sms_symbol_date", table_name="smart_money_signals")
    op.drop_table("smart_money_signals")

    op.drop_index("ix_bhav_date", table_name="bhavcopy_daily")
    op.drop_index("ix_bhav_symbol_date", table_name="bhavcopy_daily")
    op.drop_table("bhavcopy_daily")

    op.drop_index("ix_bbd_date", table_name="bulk_block_deals")
    op.drop_index("ix_bbd_client_date", table_name="bulk_block_deals")
    op.drop_index("ix_bbd_symbol_date", table_name="bulk_block_deals")
    op.drop_table("bulk_block_deals")

    op.drop_index("ix_aif_holdings_fund_q", table_name="aif_holdings_quarterly")
    op.drop_index("ix_aif_holdings_symbol_q", table_name="aif_holdings_quarterly")
    op.drop_index("ix_aif_holdings_quarterly_symbol", table_name="aif_holdings_quarterly")
    op.drop_table("aif_holdings_quarterly")

    op.drop_index("ix_aif_funds_category", table_name="aif_funds")
    op.drop_index("ix_aif_funds_sebi_reg_no", table_name="aif_funds")
    op.drop_table("aif_funds")

    op.drop_index("ix_pms_holdings_mgr_q", table_name="pms_strategy_holdings_quarterly")
    op.drop_index("ix_pms_holdings_symbol_q", table_name="pms_strategy_holdings_quarterly")
    op.drop_index("ix_pms_strategy_holdings_quarterly_symbol", table_name="pms_strategy_holdings_quarterly")
    op.drop_table("pms_strategy_holdings_quarterly")

    op.drop_index("ix_pms_managers_sebi_reg_no", table_name="pms_managers")
    op.drop_table("pms_managers")

    op.drop_index("ix_mf_holdings_scheme_month", table_name="mf_holdings_monthly")
    op.drop_index("ix_mf_holdings_symbol_month", table_name="mf_holdings_monthly")
    op.drop_index("ix_mf_holdings_monthly_isin", table_name="mf_holdings_monthly")
    op.drop_index("ix_mf_holdings_monthly_symbol", table_name="mf_holdings_monthly")
    op.drop_table("mf_holdings_monthly")

    op.drop_index("ix_mf_schemes_scheme_category", table_name="mf_schemes")
    op.drop_index("ix_mf_schemes_fund_house", table_name="mf_schemes")
    op.drop_index("ix_mf_schemes_amfi_scheme_code", table_name="mf_schemes")
    op.drop_table("mf_schemes")
