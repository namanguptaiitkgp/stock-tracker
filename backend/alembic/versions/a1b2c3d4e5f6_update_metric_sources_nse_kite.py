"""update metric_definitions: default_source for NSE/kite/yfinance sources

Revision ID: a1b2c3d4e5f6
Revises: 7fa1f5b0faa0
Create Date: 2026-05-02 18:00:00.000000

Updates default_source for metrics now served by yfinance DataFrames,
NSE XBRL ownership, or Kite computed returns. Adds new metric
definitions for ret_1m, ret_1y, pct_from_52w_high, eps_growth_5y,
ev_ebitda, current_ratio, quick_ratio that weren't in the catalog.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "7fa1f5b0faa0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SOURCE_UPDATES = {
    "current_ratio": "yfinance",
    "quick_ratio": "yfinance",
    "interest_coverage": "yfinance",
    "ev_ebitda": "yfinance",
    "eps_growth_5y": "yfinance",
    "roce": "yfinance",
    "free_cash_flow": "yfinance",
    "promoter_holding": "nse_ownership",
    "fii_holding": "nse_ownership",
    "dii_holding": "nse_ownership",
    "mf_holding": "nse_ownership",
    "pledged_promoter_holding": "nse_ownership",
    "promoter_holding_change_3m": "nse_ownership",
    "fii_holding_change_3m": "nse_ownership",
}


NEW_METRICS = [
    {
        "key": "ret_1m",
        "display_name": "1-Month Return",
        "category": "trading",
        "unit": "%",
        "direction": "neutral",
        "description_md": "Price return over the last ~22 trading days.",
        "formula": "(close_now − close_22d_ago) / close_22d_ago × 100",
        "default_source": "kite",
        "sort_order": 6,
    },
    {
        "key": "ret_1y",
        "display_name": "1-Year Return",
        "category": "trading",
        "unit": "%",
        "direction": "neutral",
        "description_md": "Price return over the last ~252 trading days.",
        "formula": "(close_now − close_252d_ago) / close_252d_ago × 100",
        "default_source": "kite",
        "sort_order": 7,
    },
    {
        "key": "pct_from_52w_high",
        "display_name": "% from 52W High",
        "category": "trading",
        "unit": "%",
        "direction": "neutral",
        "description_md": "How far the current price is from the 52-week high. Negative means below the high.",
        "formula": "(close − 52w_high) / 52w_high × 100",
        "default_source": "kite",
        "sort_order": 8,
    },
    {
        "key": "current_ratio",
        "display_name": "Current Ratio",
        "category": "financial_ratios",
        "unit": "x",
        "direction": "higher_better",
        "description_md": "Current Assets / Current Liabilities. Measures short-term liquidity.",
        "formula": "current_assets / current_liabilities",
        "default_source": "yfinance",
        "sort_order": 1,
    },
    {
        "key": "quick_ratio",
        "display_name": "Quick Ratio",
        "category": "financial_ratios",
        "unit": "x",
        "direction": "higher_better",
        "description_md": "Acid-test ratio: (Current Assets − Inventory) / Current Liabilities.",
        "formula": "(current_assets − inventory) / current_liabilities",
        "default_source": "yfinance",
        "sort_order": 2,
    },
    {
        "key": "ev_ebitda",
        "display_name": "EV/EBITDA",
        "category": "valuation",
        "unit": "x",
        "direction": "lower_better",
        "description_md": "Enterprise Value / EBITDA. Debt-neutral valuation multiple.",
        "formula": "enterprise_value / ebitda",
        "default_source": "yfinance",
        "sort_order": 15,
    },
    {
        "key": "eps_growth_5y",
        "display_name": "EPS 5Y CAGR",
        "category": "growth",
        "unit": "%",
        "direction": "higher_better",
        "description_md": "Compound annual growth rate of EPS over the last 4-5 years.",
        "formula": "(eps_latest / eps_oldest)^(1/n) − 1",
        "default_source": "yfinance",
        "sort_order": 5,
    },
    {
        "key": "promoter_holding",
        "display_name": "Promoter Holding",
        "category": "ownership",
        "unit": "%",
        "direction": "higher_better",
        "description_md": "Percentage of shares held by promoters and promoter group.",
        "formula": None,
        "default_source": "nse_ownership",
        "sort_order": 1,
    },
    {
        "key": "fii_holding",
        "display_name": "FII Holding",
        "category": "ownership",
        "unit": "%",
        "direction": "neutral",
        "description_md": "Percentage of shares held by Foreign Institutional Investors.",
        "formula": None,
        "default_source": "nse_ownership",
        "sort_order": 2,
    },
    {
        "key": "dii_holding",
        "display_name": "DII Holding",
        "category": "ownership",
        "unit": "%",
        "direction": "neutral",
        "description_md": "Percentage of shares held by Domestic Institutional Investors.",
        "formula": None,
        "default_source": "nse_ownership",
        "sort_order": 3,
    },
    {
        "key": "mf_holding",
        "display_name": "Mutual Fund Holding",
        "category": "ownership",
        "unit": "%",
        "direction": "neutral",
        "description_md": "Percentage of shares held by Mutual Funds.",
        "formula": None,
        "default_source": "nse_ownership",
        "sort_order": 4,
    },
    {
        "key": "pledged_promoter_holding",
        "display_name": "Pledged Promoter Shares",
        "category": "ownership",
        "unit": "%",
        "direction": "lower_better",
        "description_md": "Percentage of promoter shares pledged or encumbered.",
        "formula": None,
        "default_source": "nse_ownership",
        "sort_order": 5,
    },
    {
        "key": "promoter_holding_change_3m",
        "display_name": "Promoter Δ 3M",
        "category": "ownership",
        "unit": "pp",
        "direction": "higher_better",
        "description_md": "Change in promoter holding vs previous quarter (percentage points).",
        "formula": "promoter_pct_current − promoter_pct_previous",
        "default_source": "nse_ownership",
        "sort_order": 6,
    },
    {
        "key": "fii_holding_change_3m",
        "display_name": "FII Δ 3M",
        "category": "ownership",
        "unit": "pp",
        "direction": "neutral",
        "description_md": "Change in FII holding vs previous quarter (percentage points).",
        "formula": "fii_pct_current − fii_pct_previous",
        "default_source": "nse_ownership",
        "sort_order": 7,
    },
]


def upgrade() -> None:
    bind = op.get_bind()

    # Update default_source for existing metrics
    for key, source in SOURCE_UPDATES.items():
        bind.execute(
            sa.text(
                "UPDATE metric_definitions SET default_source = :source WHERE key = :key;"
            ),
            {"key": key, "source": source},
        )

    # Insert new metric definitions (ON CONFLICT DO NOTHING)
    for m in NEW_METRICS:
        bind.execute(
            sa.text(
                """
                INSERT INTO metric_definitions
                  (key, display_name, category, unit, direction, description_md, formula,
                   default_source, is_active, sort_order, created_at)
                VALUES
                  (:key, :display_name, :category, :unit, :direction, :description_md, :formula,
                   :default_source, TRUE, :sort_order, NOW())
                ON CONFLICT (key) DO NOTHING;
                """
            ),
            m,
        )


def downgrade() -> None:
    bind = op.get_bind()

    # Revert source updates
    for key in SOURCE_UPDATES:
        bind.execute(
            sa.text(
                "UPDATE metric_definitions SET default_source = NULL WHERE key = :key;"
            ),
            {"key": key},
        )

    # Remove new metrics
    for m in NEW_METRICS:
        bind.execute(
            sa.text("DELETE FROM metric_definitions WHERE key = :key;"),
            {"key": m["key"]},
        )
