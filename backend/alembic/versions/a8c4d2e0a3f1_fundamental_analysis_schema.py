"""fundamental analysis schema — metric catalog + snapshots + rules + seed metrics

Revision ID: a8c4d2e0a3f1
Revises: e7c2a91d4f3b
Create Date: 2026-05-01 14:00:00.000000

Six new tables, one TimescaleDB hypertable, ~30 seeded metric definitions.
Fundamental analysis schema.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "a8c4d2e0a3f1"
down_revision: Union[str, None] = "e7c2a91d4f3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_METRICS: list[dict] = [
    # ---------- Profitability ----------
    {"key": "net_profit_margin", "display_name": "Net Profit Margin", "category": "profitability",
     "unit": "%", "direction": "higher_better", "default_source": "yfinance",
     "formula": "Net Income / Revenue",
     "description_md": "Bottom-line profitability — what % of revenue ends up as net income. **Higher is better**; values below 5 % are typical for thin-margin businesses, above 15 % is strong."},
    {"key": "roe", "display_name": "Return on Equity", "category": "profitability",
     "unit": "%", "direction": "higher_better", "default_source": "yfinance",
     "formula": "Net Income / Shareholder Equity",
     "description_md": "How efficiently the company generates profit from shareholder capital. **Higher is better**. Indian large caps usually 12–20 %; below 10 % is weak, above 20 % is strong."},
    {"key": "ebitda_margin", "display_name": "EBITDA Margin", "category": "profitability",
     "unit": "%", "direction": "higher_better", "default_source": "yfinance",
     "formula": "EBITDA / Revenue",
     "description_md": "Operating profitability before interest, tax, depreciation. **Higher is better** within a sector — comparison across sectors is misleading."},
    {"key": "return_on_assets", "display_name": "Return on Assets", "category": "profitability",
     "unit": "%", "direction": "higher_better", "default_source": "yfinance",
     "formula": "Net Income / Total Assets",
     "description_md": "How much profit per rupee of assets. **Higher is better**. Useful for capital-heavy industries where ROE is inflated by leverage."},

    # ---------- Growth ----------
    {"key": "revenue_growth_1y", "display_name": "Revenue Growth (1Y)", "category": "growth",
     "unit": "%", "direction": "higher_better", "default_source": "yfinance",
     "description_md": "Year-over-year revenue growth. **Higher is better**, but compare to sector — 10 % YoY is mediocre for a tech company, strong for a utility."},
    {"key": "eps_growth_1y", "display_name": "EPS Growth (1Y)", "category": "growth",
     "unit": "%", "direction": "higher_better", "default_source": "yfinance",
     "description_md": "Year-over-year earnings-per-share growth. Captures both top-line growth and margin expansion. **Higher is better**."},
    {"key": "earnings_growth_forward", "display_name": "Forward Earnings Growth", "category": "growth",
     "unit": "%", "direction": "higher_better", "default_source": "yfinance",
     "description_md": "Analyst-estimated EPS growth for the next year. Forward-looking — directional, not precise."},
    {"key": "eps_growth_5y", "display_name": "EPS Growth (5Y CAGR)", "category": "growth",
     "unit": "%", "direction": "higher_better", "default_source": "tickertape",
     "description_md": "5-year compounded EPS growth. Smooths cyclicality. **Higher is better**; > 15 % is strong for Indian large caps."},

    # ---------- Valuation ----------
    {"key": "pe_ratio", "display_name": "P/E Ratio (TTM)", "category": "valuation",
     "unit": "x", "direction": "lower_better", "default_source": "yfinance",
     "formula": "Price / Trailing 12-month EPS",
     "description_md": "Trailing price-to-earnings. **Lower is better** *within sector*. Indian benchmark Nifty trades around 22–25× historically."},
    {"key": "forward_pe", "display_name": "Forward P/E", "category": "valuation",
     "unit": "x", "direction": "lower_better", "default_source": "yfinance",
     "description_md": "P/E using next year's estimated EPS. Lower than trailing P/E means analysts expect earnings growth."},
    {"key": "pb_ratio", "display_name": "P/B Ratio", "category": "valuation",
     "unit": "x", "direction": "lower_better", "default_source": "yfinance",
     "formula": "Price / Book Value per Share",
     "description_md": "Price relative to balance-sheet book value. **Below 1× implies trading below liquidation value** — often a value flag, sometimes a distress signal. > 5× is rich."},
    {"key": "ev_ebitda", "display_name": "EV / EBITDA", "category": "valuation",
     "unit": "x", "direction": "lower_better", "default_source": "tickertape",
     "description_md": "Enterprise-value-to-EBITDA. Capital-structure neutral, so comparable across firms with different debt loads."},
    {"key": "ps_ratio", "display_name": "P/S Ratio", "category": "valuation",
     "unit": "x", "direction": "lower_better", "default_source": "yfinance",
     "description_md": "Price-to-sales. Useful for unprofitable-but-growing names where P/E is meaningless."},
    {"key": "dividend_yield", "display_name": "Dividend Yield", "category": "valuation",
     "unit": "%", "direction": "higher_better", "default_source": "yfinance",
     "description_md": "Annual dividend / current price. **Higher is better** for income-focused investing; very high yields can flag distress."},
    {"key": "pct_from_52w_high", "display_name": "% from 52-week High", "category": "valuation",
     "unit": "%", "direction": "neutral", "default_source": "computed",
     "description_md": "How far below the 52-week high the price is. **Negative number**; -10 % means stock is 10 % below its peak."},

    # ---------- Financial Ratios ----------
    {"key": "debt_to_equity", "display_name": "Debt / Equity", "category": "financial_ratios",
     "unit": "x", "direction": "lower_better", "default_source": "yfinance",
     "formula": "Total Debt / Shareholder Equity",
     "description_md": "Leverage ratio. **Lower is better**. < 0.5× is conservative, > 1.5× is aggressive. Some sectors (NBFCs, utilities) run higher D/E by nature. **The platform clamps values > 50× to null** since those are nearly always equity-anomaly artifacts."},
    {"key": "current_ratio", "display_name": "Current Ratio", "category": "financial_ratios",
     "unit": "x", "direction": "higher_better", "default_source": "tickertape",
     "formula": "Current Assets / Current Liabilities",
     "description_md": "Short-term liquidity check. > 1× means assets cover 12-month liabilities. Below 1 is a yellow flag."},
    {"key": "quick_ratio", "display_name": "Quick Ratio", "category": "financial_ratios",
     "unit": "x", "direction": "higher_better", "default_source": "tickertape",
     "formula": "(Current Assets - Inventory) / Current Liabilities",
     "description_md": "Tighter liquidity check that excludes inventory (which may be hard to sell quickly)."},
    {"key": "interest_coverage", "display_name": "Interest Coverage", "category": "financial_ratios",
     "unit": "x", "direction": "higher_better", "default_source": "tickertape",
     "formula": "EBIT / Interest Expense",
     "description_md": "How many times operating income covers interest payments. **Higher is better**. < 2× is concerning."},

    # ---------- Ownership ----------
    {"key": "promoter_holding", "display_name": "Promoter Holding", "category": "ownership",
     "unit": "%", "direction": "higher_better", "default_source": "tickertape",
     "description_md": "% of shares held by company promoters. **Higher generally signals skin-in-the-game**. Below 25 % is low conviction; falling promoter holding is a yellow flag."},
    {"key": "promoter_holding_change_3m", "display_name": "Promoter Holding Δ (3M)", "category": "ownership",
     "unit": "%", "direction": "higher_better", "default_source": "tickertape",
     "description_md": "Change in promoter holding over the last 3 months. Increases are bullish, decreases are bearish."},
    {"key": "fii_holding", "display_name": "FII Holding", "category": "ownership",
     "unit": "%", "direction": "neutral", "default_source": "tickertape",
     "description_md": "Foreign institutional investors' stake."},
    {"key": "fii_holding_change_3m", "display_name": "FII Holding Δ (3M)", "category": "ownership",
     "unit": "%", "direction": "higher_better", "default_source": "tickertape",
     "description_md": "Change in FII holding over the last 3 months. FII inflows are typically bullish for the stock and often correlate with index inclusion or upgrades."},
    {"key": "dii_holding", "display_name": "DII Holding", "category": "ownership",
     "unit": "%", "direction": "neutral", "default_source": "tickertape",
     "description_md": "Domestic institutional investors (mutual funds, insurance, pensions)."},
    {"key": "mf_holding", "display_name": "Mutual Fund Holding", "category": "ownership",
     "unit": "%", "direction": "neutral", "default_source": "tickertape",
     "description_md": "Subset of DII — total stake held by Indian mutual funds."},
    {"key": "pledged_promoter_holding", "display_name": "Pledged Promoter Holding", "category": "ownership",
     "unit": "%", "direction": "lower_better", "default_source": "tickertape",
     "description_md": "% of promoter shares pledged as collateral. **Higher is worse** — promoters with pledged shares can face forced selling. Ideally 0 %; > 10 % is a serious flag."},

    # ---------- Trading / Technical ----------
    {"key": "market_cap", "display_name": "Market Cap", "category": "trading",
     "unit": "₹ Cr", "direction": "neutral", "default_source": "yfinance",
     "description_md": "Market capitalisation in crore rupees. Used to filter for size — large/mid/small cap."},
    {"key": "ret_1m", "display_name": "1-Month Return", "category": "trading",
     "unit": "%", "direction": "neutral", "default_source": "computed",
     "description_md": "Price return over the last month."},
    {"key": "ret_1y", "display_name": "1-Year Return", "category": "trading",
     "unit": "%", "direction": "neutral", "default_source": "computed",
     "description_md": "Price return over the last 12 months."},
]


def upgrade() -> None:
    # 1. metric_definitions — catalog
    op.create_table(
        "metric_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("direction", sa.String(16), nullable=False, server_default="neutral"),
        sa.Column("description_md", sa.Text(), nullable=True),
        sa.Column("formula", sa.Text(), nullable=True),
        sa.Column("default_source", sa.String(40), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_metric_definitions_category", "metric_definitions", ["category"])
    op.create_index("ix_metric_definitions_key", "metric_definitions", ["key"])

    # 2. metric_runs — audit
    op.create_table(
        "metric_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("target_symbol", sa.String(50), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("stocks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stocks_ok", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stocks_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
    )
    op.create_index("ix_metric_runs_user_id", "metric_runs", ["user_id"])
    op.create_index("ix_metric_runs_started_at", "metric_runs", ["started_at"])

    # 3. metric_snapshots — wide JSONB, one row per (symbol, run)
    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("metric_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False, server_default="NSE"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("values_json", JSONB(), nullable=False),
        sa.Column("sources_json", JSONB(), nullable=True),
        # TimescaleDB hypertables require the partition column to be part
        # of the primary key. Composite PK on (id, fetched_at).
        sa.PrimaryKeyConstraint("id", "fetched_at"),
    )
    op.create_index("ix_snap_symbol_time", "metric_snapshots", ["symbol", "fetched_at"], unique=False)
    op.create_index("ix_snap_run_id", "metric_snapshots", ["run_id"])

    # Make it a TimescaleDB hypertable. `if_not_exists` so re-running on
    # an already-converted table doesn't blow up.
    op.execute(
        "SELECT create_hypertable('metric_snapshots', 'fetched_at', "
        "chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);"
    )

    # 4. metric_manual_overrides — user-typed values
    op.create_table(
        "metric_manual_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False, server_default="NSE"),
        sa.Column("metric_key", sa.String(64), nullable=False),
        sa.Column("value_num", sa.Numeric(20, 6), nullable=True),
        sa.Column("value_str", sa.String(120), nullable=True),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("user_id", "symbol", "metric_key", name="uq_manual_override_user_symbol_metric"),
    )
    op.create_index("ix_manual_overrides_user_id", "metric_manual_overrides", ["user_id"])

    # 5. fundamental_rule_sets
    op.create_table(
        "fundamental_rule_sets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False, server_default="Defaults"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_rule_sets_user_id", "fundamental_rule_sets", ["user_id"])

    # 6. fundamental_rules
    op.create_table(
        "fundamental_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rule_set_id", sa.Integer(), sa.ForeignKey("fundamental_rule_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_key", sa.String(64), nullable=False),
        sa.Column("operator", sa.String(16), nullable=False),
        sa.Column("value_num", sa.Numeric(20, 6), nullable=True),
        sa.Column("value_low", sa.Numeric(20, 6), nullable=True),
        sa.Column("value_high", sa.Numeric(20, 6), nullable=True),
        sa.Column("weight", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_rules_rule_set_id", "fundamental_rules", ["rule_set_id"])

    # ---------- Seed metric_definitions ----------
    metric_def_table = sa.table(
        "metric_definitions",
        sa.column("key", sa.String),
        sa.column("display_name", sa.String),
        sa.column("category", sa.String),
        sa.column("unit", sa.String),
        sa.column("direction", sa.String),
        sa.column("description_md", sa.Text),
        sa.column("formula", sa.Text),
        sa.column("default_source", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    rows = []
    for i, m in enumerate(SEED_METRICS):
        rows.append({
            "key": m["key"],
            "display_name": m["display_name"],
            "category": m["category"],
            "unit": m.get("unit"),
            "direction": m.get("direction", "neutral"),
            "description_md": m.get("description_md"),
            "formula": m.get("formula"),
            "default_source": m.get("default_source"),
            "sort_order": i,
        })
    op.bulk_insert(metric_def_table, rows)


def downgrade() -> None:
    op.drop_index("ix_rules_rule_set_id", table_name="fundamental_rules")
    op.drop_table("fundamental_rules")
    op.drop_index("ix_rule_sets_user_id", table_name="fundamental_rule_sets")
    op.drop_table("fundamental_rule_sets")
    op.drop_index("ix_manual_overrides_user_id", table_name="metric_manual_overrides")
    op.drop_table("metric_manual_overrides")
    op.drop_index("ix_snap_run_id", table_name="metric_snapshots")
    op.drop_index("ix_snap_symbol_time", table_name="metric_snapshots")
    op.drop_table("metric_snapshots")
    op.drop_index("ix_metric_runs_started_at", table_name="metric_runs")
    op.drop_index("ix_metric_runs_user_id", table_name="metric_runs")
    op.drop_table("metric_runs")
    op.drop_index("ix_metric_definitions_key", table_name="metric_definitions")
    op.drop_index("ix_metric_definitions_category", table_name="metric_definitions")
    op.drop_table("metric_definitions")
