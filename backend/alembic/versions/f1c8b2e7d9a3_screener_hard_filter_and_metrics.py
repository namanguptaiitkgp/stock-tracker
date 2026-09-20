"""screener: is_hard_filter + new metric definitions

Revision ID: f1c8b2e7d9a3
Revises: e9f5a2b8d4c1
Create Date: 2026-05-02 10:00:00.000000

Implements `indian_stock_screener_criteria.md`:
  - `fundamental_rules.is_hard_filter` BOOLEAN — separates the must-pass
    filters that gate the universe from the soft filters that scor the
    rank inside it.
  - Six new metric_definitions for the screener metrics that weren't in
    the catalog yet: operating_cash_flow, roce, cash_flow_margin,
    free_cash_flow, earning_power, ret_1d, pe_premium_vs_sector. Some
    have a yfinance source wired in this PR; ROCE and pe-premium-vs-sector
    are catalog-only until a derivation lands.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1c8b2e7d9a3"
down_revision: Union[str, None] = "e9f5a2b8d4c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Six new metrics from the screener spec. (sort_order keeps them grouped
# next to siblings in the existing categories.)
NEW_METRICS = [
    {
        "key": "operating_cash_flow",
        "display_name": "Operating Cash Flow",
        "category": "cash_flow",
        "unit": "₹ Cr",
        "direction": "higher_better",
        "description_md": (
            "Cash generated from operations. Non-negotiable in the screener — "
            "negative OCF means the business is burning cash even before capex."
        ),
        "formula": "Net income + non-cash items + working-capital changes",
        "default_source": "yfinance",
        "sort_order": 10,
    },
    {
        "key": "free_cash_flow",
        "display_name": "Free Cash Flow",
        "category": "cash_flow",
        "unit": "₹ Cr",
        "direction": "higher_better",
        "description_md": (
            "OCF minus capex. The screener allows small negatives (≥ -10% of OCF) "
            "to accommodate high-capex growth phases."
        ),
        "formula": "operating_cash_flow − capex",
        "default_source": "yfinance",
        "sort_order": 11,
    },
    {
        "key": "cash_flow_margin",
        "display_name": "Cash Flow Margin",
        "category": "cash_flow",
        "unit": "%",
        "direction": "higher_better",
        "description_md": (
            "OCF as a % of revenue. Should roughly track net profit margin; a wide "
            "gap signals poor earnings quality (accruals not converting to cash)."
        ),
        "formula": "operating_cash_flow / total_revenue × 100",
        "default_source": "yfinance",
        "sort_order": 12,
    },
    {
        "key": "roce",
        "display_name": "Return on Capital Employed",
        "category": "profitability",
        "unit": "%",
        "direction": "higher_better",
        "description_md": (
            "EBIT divided by capital employed (debt + equity). More lenient than "
            "ROE — keeps capital-intensive sectors in play. Currently catalog-only "
            "until a derivation from the financial statements lands."
        ),
        "formula": "EBIT / (total_debt + total_equity) × 100",
        "default_source": None,
        "sort_order": 5,
    },
    {
        "key": "earning_power",
        "display_name": "Earnings Yield",
        "category": "valuation",
        "unit": "%",
        "direction": "higher_better",
        "description_md": (
            "1 / PE × 100 — the inverse of P/E. Useful as the earnings-yield "
            "complement when scoring valuation. Derived from pe_ratio at fetch time."
        ),
        "formula": "100 / pe_ratio",
        "default_source": "yfinance",
        "sort_order": 20,
    },
    {
        "key": "ret_1d",
        "display_name": "1-Day Return",
        "category": "trading",
        "unit": "%",
        "direction": "neutral",
        "description_md": (
            "Today's % move. Used as a screening guard — stocks hitting circuits "
            "(±5% / ±10% in tight bands) are excluded from the actionable universe."
        ),
        "formula": "(close − prev_close) / prev_close × 100",
        "default_source": "yfinance",
        "sort_order": 5,
    },
    {
        "key": "pe_premium_vs_sector",
        "display_name": "PE Premium vs Sector",
        "category": "sector_relative",
        "unit": "%",
        "direction": "neutral",
        "description_md": (
            "How much the stock's PE ratio differs from its sector median. ±30% "
            "is the screener's tolerance band; extremes need justification. "
            "Catalog-only until peer-set logic lands."
        ),
        "formula": "(stock_pe − sector_median_pe) / sector_median_pe × 100",
        "default_source": None,
        "sort_order": 10,
    },
]


def upgrade() -> None:
    # 1) is_hard_filter column. Default FALSE so existing rule sets stay
    # in their current "soft scoring" mode until a user opts a rule into
    # the hard-filter gate via the rule editor or a preset load.
    op.execute(
        "ALTER TABLE fundamental_rules "
        "ADD COLUMN IF NOT EXISTS is_hard_filter BOOLEAN NOT NULL DEFAULT FALSE;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fundrules_hard "
        "ON fundamental_rules (rule_set_id, is_hard_filter) "
        "WHERE is_hard_filter = TRUE;"
    )

    # 2) Insert any of the new metric definitions that aren't already
    # there. The metric_catalog auto-loader picks them up on next read.
    bind = op.get_bind()
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
    for m in NEW_METRICS:
        bind.execute(
            sa.text("DELETE FROM metric_definitions WHERE key = :key;"),
            {"key": m["key"]},
        )
    op.execute("DROP INDEX IF EXISTS ix_fundrules_hard;")
    op.execute("ALTER TABLE fundamental_rules DROP COLUMN IF EXISTS is_hard_filter;")
