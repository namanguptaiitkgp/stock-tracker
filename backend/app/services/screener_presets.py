"""Built-in fundamental rule-set presets.

Currently ships one preset: the Indian-market screener from
`indian_stock_screener_criteria.md`. Loaded into a user's rule set via
`POST /api/fundamentals/rule-sets/{id}/apply-preset`.

A preset is a list of dicts shaped to match `FundamentalRule` columns,
plus a `is_hard_filter` flag. Note on units: the metric_definitions
catalog stores percentages as fractions (e.g. ROE 0.12 = 12%). Margin
metrics from yfinance come in fraction form too. Thresholds in this
file follow the catalog's unit convention — so the screener spec's
"ROE ≥ 12" becomes `value_num: 0.12` here.

Cash-flow values arrive as ₹ Cr (yfinance INR / 1e7); the spec's
"OCF positive" becomes `> 0` directly. Counts and ratios stay literal.
"""

from __future__ import annotations

INDIAN_SCREENER_PRESET = {
    "name": "Indian Market Screener (default)",
    "description": (
        "Hard filters establish the eligible universe. Soft filters "
        "score and rank inside it. Failing 1–2 soft filters is OK; "
        "failing any hard filter rejects the stock."
    ),
    "rules": [
        # ---- Hard filters (8) ----
        {"metric_key": "pe_ratio",                 "operator": "between", "value_low": 5,    "value_high": 40, "weight": 5, "is_hard_filter": True,  "sort_order": 10},
        {"metric_key": "roe",                      "operator": "gte",     "value_num": 0.12,                   "weight": 5, "is_hard_filter": True,  "sort_order": 11},
        {"metric_key": "net_profit_margin",        "operator": "gte",     "value_num": 0.05,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
        {"metric_key": "operating_cash_flow",      "operator": "is_positive",                                  "weight": 5, "is_hard_filter": True,  "sort_order": 13},
        {"metric_key": "debt_to_equity",           "operator": "between", "value_low": 0,    "value_high": 1.5,"weight": 5, "is_hard_filter": True,  "sort_order": 14},
        {"metric_key": "interest_coverage",        "operator": "gte",     "value_num": 3,                      "weight": 5, "is_hard_filter": True,  "sort_order": 15},
        {"metric_key": "pledged_promoter_holding", "operator": "lte",     "value_num": 15,                     "weight": 5, "is_hard_filter": True,  "sort_order": 16},
        {"metric_key": "revenue_growth_1y",        "operator": "gte",     "value_num": 0.05,                   "weight": 5, "is_hard_filter": True,  "sort_order": 17},

        # ---- Soft filters (12) — used for ranking ----
        {"metric_key": "pb_ratio",                 "operator": "between", "value_low": 0.5,  "value_high": 8,  "weight": 2, "is_hard_filter": False, "sort_order": 30},
        {"metric_key": "forward_pe",               "operator": "between", "value_low": 5,    "value_high": 30, "weight": 2, "is_hard_filter": False, "sort_order": 31},
        {"metric_key": "pe_premium_vs_sector",     "operator": "between", "value_low": -30,  "value_high": 30, "weight": 1, "is_hard_filter": False, "sort_order": 32},
        {"metric_key": "roce",                     "operator": "gte",     "value_num": 10,                     "weight": 2, "is_hard_filter": False, "sort_order": 33},
        {"metric_key": "return_on_assets",         "operator": "gte",     "value_num": 0.04,                   "weight": 2, "is_hard_filter": False, "sort_order": 34},
        {"metric_key": "ebitda_margin",            "operator": "gte",     "value_num": 0.10,                   "weight": 2, "is_hard_filter": False, "sort_order": 35},
        {"metric_key": "cash_flow_margin",         "operator": "gte",     "value_num": 0.05,                   "weight": 2, "is_hard_filter": False, "sort_order": 36},
        {"metric_key": "free_cash_flow",           "operator": "is_positive",                                  "weight": 2, "is_hard_filter": False, "sort_order": 37},
        {"metric_key": "earning_power",            "operator": "gte",     "value_num": 5,                      "weight": 1, "is_hard_filter": False, "sort_order": 38},
        {"metric_key": "promoter_holding_change_3m","operator": "gte",    "value_num": 0,                      "weight": 1, "is_hard_filter": False, "sort_order": 39},
        {"metric_key": "ret_1m",                   "operator": "between", "value_low": -15,  "value_high": 30, "weight": 1, "is_hard_filter": False, "sort_order": 40},
        {"metric_key": "ret_1d",                   "operator": "between", "value_low": -5,   "value_high": 10, "weight": 1, "is_hard_filter": False, "sort_order": 41},
    ],
}


"""Sector-specific presets derived from sector_benchmarks_india.md.

Each sector preset adjusts hard/soft filter thresholds to match
sector-appropriate valuation ranges. Key differences from the
universal preset:
- Financial Services: no D/E or net margin hard filter (banks are
  levered by design; NIM replaces net margin)
- Energy / Basic Materials: wider PE hard range (cyclical earnings
  distort trailing PE)
- Consumer Defensive: tighter quality bars (high ROE is the norm)
- Utilities: D/E up to 2.5 accepted (capital-intensive by design)
"""

SECTOR_PRESETS: dict[str, dict] = {
    "Consumer Cyclical": {
        "name": "Consumer Cyclical Screener",
        "description": "Auto/Durables/Retail/Realty. Revenue growth + ROE through-cycle primary.",
        "rules": [
            # Hard filters
            {"metric_key": "pe_ratio",            "operator": "between", "value_low": 15, "value_high": 80,   "weight": 5, "is_hard_filter": True,  "sort_order": 10},
            {"metric_key": "roe",                 "operator": "gte",     "value_num": 0.10,                   "weight": 5, "is_hard_filter": True,  "sort_order": 11},
            {"metric_key": "net_profit_margin",   "operator": "gte",     "value_num": 0.03,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
            {"metric_key": "operating_cash_flow", "operator": "is_positive",                                  "weight": 5, "is_hard_filter": True,  "sort_order": 13},
            {"metric_key": "debt_to_equity",      "operator": "between", "value_low": 0, "value_high": 1.5,   "weight": 5, "is_hard_filter": True,  "sort_order": 14},
            {"metric_key": "revenue_growth_1y",   "operator": "gte",     "value_num": 0.05,                   "weight": 5, "is_hard_filter": True,  "sort_order": 15},
            # Soft filters
            {"metric_key": "pb_ratio",            "operator": "between", "value_low": 1.5, "value_high": 12,  "weight": 2, "is_hard_filter": False, "sort_order": 30},
            {"metric_key": "dividend_yield",      "operator": "gte",     "value_num": 0.005,                  "weight": 1, "is_hard_filter": False, "sort_order": 31},
            {"metric_key": "roce",                "operator": "gte",     "value_num": 14,                     "weight": 2, "is_hard_filter": False, "sort_order": 32},
            {"metric_key": "ebitda_margin",       "operator": "gte",     "value_num": 0.08,                   "weight": 2, "is_hard_filter": False, "sort_order": 33},
            {"metric_key": "free_cash_flow",      "operator": "is_positive",                                  "weight": 2, "is_hard_filter": False, "sort_order": 34},
        ],
    },
    "Industrials": {
        "name": "Industrials Screener",
        "description": "Capital goods/infra/defence. Order book visibility justifies higher PE. ROCE > ROE.",
        "rules": [
            {"metric_key": "pe_ratio",            "operator": "between", "value_low": 15, "value_high": 100,  "weight": 5, "is_hard_filter": True,  "sort_order": 10},
            {"metric_key": "roe",                 "operator": "gte",     "value_num": 0.08,                   "weight": 5, "is_hard_filter": True,  "sort_order": 11},
            {"metric_key": "net_profit_margin",   "operator": "gte",     "value_num": 0.04,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
            {"metric_key": "operating_cash_flow", "operator": "is_positive",                                  "weight": 5, "is_hard_filter": True,  "sort_order": 13},
            {"metric_key": "debt_to_equity",      "operator": "between", "value_low": 0, "value_high": 1.0,   "weight": 5, "is_hard_filter": True,  "sort_order": 14},
            {"metric_key": "revenue_growth_1y",   "operator": "gte",     "value_num": 0.05,                   "weight": 5, "is_hard_filter": True,  "sort_order": 15},
            {"metric_key": "pb_ratio",            "operator": "between", "value_low": 2, "value_high": 12,    "weight": 2, "is_hard_filter": False, "sort_order": 30},
            {"metric_key": "roce",                "operator": "gte",     "value_num": 12,                     "weight": 3, "is_hard_filter": False, "sort_order": 31},
            {"metric_key": "ebitda_margin",       "operator": "gte",     "value_num": 0.08,                   "weight": 2, "is_hard_filter": False, "sort_order": 32},
            {"metric_key": "free_cash_flow",      "operator": "is_positive",                                  "weight": 2, "is_hard_filter": False, "sort_order": 33},
        ],
    },
    "Basic Materials": {
        "name": "Basic Materials Screener",
        "description": "Metals/cement/chemicals. Cyclical — wider PE band. Through-cycle averages matter.",
        "rules": [
            {"metric_key": "pe_ratio",            "operator": "between", "value_low": 6, "value_high": 50,    "weight": 3, "is_hard_filter": True,  "sort_order": 10},
            {"metric_key": "roe",                 "operator": "gte",     "value_num": 0.06,                   "weight": 5, "is_hard_filter": True,  "sort_order": 11},
            {"metric_key": "net_profit_margin",   "operator": "gte",     "value_num": 0.03,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
            {"metric_key": "debt_to_equity",      "operator": "between", "value_low": 0, "value_high": 1.5,   "weight": 5, "is_hard_filter": True,  "sort_order": 13},
            {"metric_key": "revenue_growth_1y",   "operator": "gte",     "value_num": 0.0,                    "weight": 3, "is_hard_filter": True,  "sort_order": 14},
            {"metric_key": "pb_ratio",            "operator": "between", "value_low": 0.7, "value_high": 10,  "weight": 2, "is_hard_filter": False, "sort_order": 30},
            {"metric_key": "roce",                "operator": "gte",     "value_num": 10,                     "weight": 2, "is_hard_filter": False, "sort_order": 31},
            {"metric_key": "dividend_yield",      "operator": "gte",     "value_num": 0.01,                   "weight": 1, "is_hard_filter": False, "sort_order": 32},
            {"metric_key": "ebitda_margin",       "operator": "gte",     "value_num": 0.10,                   "weight": 2, "is_hard_filter": False, "sort_order": 33},
        ],
    },
    "Consumer Defensive": {
        "name": "Consumer Defensive (FMCG) Screener",
        "description": "Brand-led, asset-light, high ROE. Higher quality bars across the board.",
        "rules": [
            {"metric_key": "pe_ratio",            "operator": "between", "value_low": 25, "value_high": 90,   "weight": 5, "is_hard_filter": True,  "sort_order": 10},
            {"metric_key": "roe",                 "operator": "gte",     "value_num": 0.18,                   "weight": 5, "is_hard_filter": True,  "sort_order": 11},
            {"metric_key": "net_profit_margin",   "operator": "gte",     "value_num": 0.08,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
            {"metric_key": "operating_cash_flow", "operator": "is_positive",                                  "weight": 5, "is_hard_filter": True,  "sort_order": 13},
            {"metric_key": "debt_to_equity",      "operator": "between", "value_low": 0, "value_high": 0.5,   "weight": 5, "is_hard_filter": True,  "sort_order": 14},
            {"metric_key": "revenue_growth_1y",   "operator": "gte",     "value_num": 0.04,                   "weight": 5, "is_hard_filter": True,  "sort_order": 15},
            {"metric_key": "pb_ratio",            "operator": "between", "value_low": 4, "value_high": 25,    "weight": 2, "is_hard_filter": False, "sort_order": 30},
            {"metric_key": "dividend_yield",      "operator": "gte",     "value_num": 0.01,                   "weight": 2, "is_hard_filter": False, "sort_order": 31},
            {"metric_key": "free_cash_flow",      "operator": "is_positive",                                  "weight": 2, "is_hard_filter": False, "sort_order": 32},
            {"metric_key": "ebitda_margin",       "operator": "gte",     "value_num": 0.15,                   "weight": 2, "is_hard_filter": False, "sort_order": 33},
        ],
    },
    "Financial Services": {
        "name": "Financial Services Screener",
        "description": "Banks/NBFCs/Insurance. P/B is primary; D/E and net margin not applicable.",
        "rules": [
            {"metric_key": "pe_ratio",            "operator": "between", "value_low": 6,   "value_high": 35,  "weight": 3, "is_hard_filter": True,  "sort_order": 10},
            {"metric_key": "pb_ratio",            "operator": "between", "value_low": 0.7, "value_high": 5.0, "weight": 5, "is_hard_filter": True,  "sort_order": 11},
            {"metric_key": "roe",                 "operator": "gte",     "value_num": 0.08,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
            # NO debt_to_equity — banks are levered by design
            # NO net_profit_margin — use NIM instead (not in standard metrics)
            {"metric_key": "revenue_growth_1y",   "operator": "gte",     "value_num": 0.08,                   "weight": 3, "is_hard_filter": True,  "sort_order": 13},
            {"metric_key": "dividend_yield",      "operator": "gte",     "value_num": 0.005,                  "weight": 1, "is_hard_filter": False, "sort_order": 30},
            {"metric_key": "roce",                "operator": "gte",     "value_num": 8,                      "weight": 2, "is_hard_filter": False, "sort_order": 31},
            {"metric_key": "promoter_holding",    "operator": "gte",     "value_num": 30,                     "weight": 1, "is_hard_filter": False, "sort_order": 32},
        ],
    },
    "Healthcare": {
        "name": "Healthcare Screener",
        "description": "Pharma/Hospitals/Diagnostics. Wider PE for hospital growth plays.",
        "rules": [
            {"metric_key": "pe_ratio",            "operator": "between", "value_low": 15, "value_high": 80,   "weight": 5, "is_hard_filter": True,  "sort_order": 10},
            {"metric_key": "roe",                 "operator": "gte",     "value_num": 0.10,                   "weight": 5, "is_hard_filter": True,  "sort_order": 11},
            {"metric_key": "net_profit_margin",   "operator": "gte",     "value_num": 0.06,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
            {"metric_key": "operating_cash_flow", "operator": "is_positive",                                  "weight": 5, "is_hard_filter": True,  "sort_order": 13},
            {"metric_key": "debt_to_equity",      "operator": "between", "value_low": 0, "value_high": 1.2,   "weight": 5, "is_hard_filter": True,  "sort_order": 14},
            {"metric_key": "revenue_growth_1y",   "operator": "gte",     "value_num": 0.05,                   "weight": 5, "is_hard_filter": True,  "sort_order": 15},
            {"metric_key": "pb_ratio",            "operator": "between", "value_low": 2, "value_high": 13,    "weight": 2, "is_hard_filter": False, "sort_order": 30},
            {"metric_key": "ebitda_margin",       "operator": "gte",     "value_num": 0.12,                   "weight": 2, "is_hard_filter": False, "sort_order": 31},
            {"metric_key": "free_cash_flow",      "operator": "is_positive",                                  "weight": 2, "is_hard_filter": False, "sort_order": 32},
            {"metric_key": "dividend_yield",      "operator": "gte",     "value_num": 0.004,                  "weight": 1, "is_hard_filter": False, "sort_order": 33},
        ],
    },
    "Communication Services": {
        "name": "Communication Services Screener",
        "description": "Telecom/Media/Internet. Standard PE often misleading; wider tolerance.",
        "rules": [
            {"metric_key": "pe_ratio",            "operator": "between", "value_low": 10, "value_high": 100,  "weight": 3, "is_hard_filter": True,  "sort_order": 10},
            {"metric_key": "roe",                 "operator": "gte",     "value_num": 0.08,                   "weight": 5, "is_hard_filter": True,  "sort_order": 11},
            {"metric_key": "net_profit_margin",   "operator": "gte",     "value_num": 0.05,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
            {"metric_key": "debt_to_equity",      "operator": "between", "value_low": 0, "value_high": 3.0,   "weight": 3, "is_hard_filter": True,  "sort_order": 13},
            {"metric_key": "revenue_growth_1y",   "operator": "gte",     "value_num": 0.08,                   "weight": 5, "is_hard_filter": True,  "sort_order": 14},
            {"metric_key": "pb_ratio",            "operator": "between", "value_low": 1, "value_high": 15,    "weight": 2, "is_hard_filter": False, "sort_order": 30},
            {"metric_key": "ebitda_margin",       "operator": "gte",     "value_num": 0.10,                   "weight": 2, "is_hard_filter": False, "sort_order": 31},
            {"metric_key": "free_cash_flow",      "operator": "is_positive",                                  "weight": 2, "is_hard_filter": False, "sort_order": 32},
        ],
    },
    "Energy": {
        "name": "Energy Screener",
        "description": "Oil & Gas/Coal. Highly cyclical — PE hard filter much wider. Through-cycle ROCE key.",
        "rules": [
            {"metric_key": "pe_ratio",            "operator": "between", "value_low": 5, "value_high": 30,    "weight": 3, "is_hard_filter": True,  "sort_order": 10},
            {"metric_key": "roe",                 "operator": "gte",     "value_num": 0.08,                   "weight": 5, "is_hard_filter": True,  "sort_order": 11},
            {"metric_key": "net_profit_margin",   "operator": "gte",     "value_num": 0.03,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
            {"metric_key": "debt_to_equity",      "operator": "between", "value_low": 0, "value_high": 1.5,   "weight": 5, "is_hard_filter": True,  "sort_order": 13},
            {"metric_key": "pb_ratio",            "operator": "between", "value_low": 0.7, "value_high": 3,   "weight": 2, "is_hard_filter": False, "sort_order": 30},
            {"metric_key": "dividend_yield",      "operator": "gte",     "value_num": 0.02,                   "weight": 2, "is_hard_filter": False, "sort_order": 31},
            {"metric_key": "roce",                "operator": "gte",     "value_num": 10,                     "weight": 3, "is_hard_filter": False, "sort_order": 32},
            {"metric_key": "ebitda_margin",       "operator": "gte",     "value_num": 0.10,                   "weight": 2, "is_hard_filter": False, "sort_order": 33},
        ],
    },
    "Utilities": {
        "name": "Utilities Screener",
        "description": "Power/transmission/renewables. Regulated returns cluster at CERC 15.5% ROE. Higher D/E normal.",
        "rules": [
            {"metric_key": "pe_ratio",            "operator": "between", "value_low": 8, "value_high": 100,   "weight": 5, "is_hard_filter": True,  "sort_order": 10},
            {"metric_key": "roe",                 "operator": "gte",     "value_num": 0.08,                   "weight": 5, "is_hard_filter": True,  "sort_order": 11},
            {"metric_key": "net_profit_margin",   "operator": "gte",     "value_num": 0.06,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
            {"metric_key": "debt_to_equity",      "operator": "between", "value_low": 0, "value_high": 2.5,   "weight": 3, "is_hard_filter": True,  "sort_order": 13},
            {"metric_key": "revenue_growth_1y",   "operator": "gte",     "value_num": 0.03,                   "weight": 5, "is_hard_filter": True,  "sort_order": 14},
            {"metric_key": "pb_ratio",            "operator": "between", "value_low": 0.8, "value_high": 4,   "weight": 2, "is_hard_filter": False, "sort_order": 30},
            {"metric_key": "dividend_yield",      "operator": "gte",     "value_num": 0.015,                  "weight": 2, "is_hard_filter": False, "sort_order": 31},
            {"metric_key": "ebitda_margin",       "operator": "gte",     "value_num": 0.15,                   "weight": 2, "is_hard_filter": False, "sort_order": 32},
        ],
    },
    "Technology": {
        "name": "Technology Screener",
        "description": "IT services/SaaS. Asset-light, high ROE, near-zero debt. FCF yield key.",
        "rules": [
            {"metric_key": "pe_ratio",            "operator": "between", "value_low": 15, "value_high": 50,   "weight": 5, "is_hard_filter": True,  "sort_order": 10},
            {"metric_key": "roe",                 "operator": "gte",     "value_num": 0.18,                   "weight": 5, "is_hard_filter": True,  "sort_order": 11},
            {"metric_key": "net_profit_margin",   "operator": "gte",     "value_num": 0.10,                   "weight": 5, "is_hard_filter": True,  "sort_order": 12},
            {"metric_key": "operating_cash_flow", "operator": "is_positive",                                  "weight": 5, "is_hard_filter": True,  "sort_order": 13},
            {"metric_key": "debt_to_equity",      "operator": "between", "value_low": 0, "value_high": 0.2,   "weight": 5, "is_hard_filter": True,  "sort_order": 14},
            {"metric_key": "revenue_growth_1y",   "operator": "gte",     "value_num": 0.03,                   "weight": 3, "is_hard_filter": True,  "sort_order": 15},
            {"metric_key": "pb_ratio",            "operator": "between", "value_low": 4, "value_high": 15,    "weight": 2, "is_hard_filter": False, "sort_order": 30},
            {"metric_key": "dividend_yield",      "operator": "gte",     "value_num": 0.015,                  "weight": 2, "is_hard_filter": False, "sort_order": 31},
            {"metric_key": "free_cash_flow",      "operator": "is_positive",                                  "weight": 3, "is_hard_filter": False, "sort_order": 32},
            {"metric_key": "ebitda_margin",       "operator": "gte",     "value_num": 0.20,                   "weight": 2, "is_hard_filter": False, "sort_order": 33},
        ],
    },
}


SECTOR_TO_PRESET: dict[str, str] = {
    "Technology": "Technology",
    "Financial Services": "Financial Services",
    "Healthcare": "Healthcare",
    "Consumer Cyclical": "Consumer Cyclical",
    "Consumer Defensive": "Consumer Defensive",
    "Industrials": "Industrials",
    "Basic Materials": "Basic Materials",
    "Communication Services": "Communication Services",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Consumer Cyclical",
}


PRESETS: dict[str, dict] = {
    "indian_screener": INDIAN_SCREENER_PRESET,
    **{f"sector_{k.lower().replace(' ', '_')}": v for k, v in SECTOR_PRESETS.items()},
}


# ─── Canonical sectors + normalization ────────────────────────────────────
# CANONICAL_SECTORS is the source of truth for sector identity. SECTOR_TO_PRESET
# resolves the valuation preset to use for screening (some canonical sectors
# share a preset — e.g. Real Estate uses Consumer Cyclical's rules — but the
# canonical name is what we display).
CANONICAL_SECTORS: list[str] = list(SECTOR_TO_PRESET.keys())

# Long-form → canonical aliases for input from yfinance, Screener.in,
# NSE industry classifications, and other sources. Lower-cased keys; values
# must be members of CANONICAL_SECTORS.
SECTOR_ALIASES: dict[str, str] = {
    # FMCG / consumer staples
    "fmcg": "Consumer Defensive",
    "consumer staples": "Consumer Defensive",
    "food & beverages": "Consumer Defensive",
    "tobacco": "Consumer Defensive",
    "personal care": "Consumer Defensive",
    # Capital goods / industrials
    "industrial goods": "Industrials",
    "capital goods": "Industrials",
    "engineering": "Industrials",
    "construction": "Industrials",
    "logistics": "Industrials",
    "defence": "Industrials",
    "aerospace & defense": "Industrials",
    "transportation": "Industrials",
    # Technology
    "it services": "Technology",
    "it - software": "Technology",
    "software": "Technology",
    "information technology": "Technology",
    "tech": "Technology",
    # Financials
    "banks - private sector": "Financial Services",
    "banks - public sector": "Financial Services",
    "private sector bank": "Financial Services",
    "public sector bank": "Financial Services",
    "nbfc": "Financial Services",
    "finance": "Financial Services",
    "financials": "Financial Services",
    "insurance": "Financial Services",
    "exchanges & data": "Financial Services",
    # Healthcare
    "pharma": "Healthcare",
    "pharmaceuticals": "Healthcare",
    "drugs & pharma": "Healthcare",
    "hospitals": "Healthcare",
    "diagnostics": "Healthcare",
    "healthcare equipment": "Healthcare",
    # Materials
    "metals & mining": "Basic Materials",
    "metals": "Basic Materials",
    "mining": "Basic Materials",
    "cement": "Basic Materials",
    "chemicals": "Basic Materials",
    "specialty chemicals": "Basic Materials",
    "fertilizers": "Basic Materials",
    "paper": "Basic Materials",
    # Energy
    "oil & gas": "Energy",
    "refineries": "Energy",
    "crude oil & natural gas": "Energy",
    "coal": "Energy",
    # Utilities
    "power": "Utilities",
    "electric utilities": "Utilities",
    "gas utilities": "Utilities",
    "renewable energy": "Utilities",
    # Communication
    "telecom": "Communication Services",
    "telecommunication": "Communication Services",
    "telecommunications": "Communication Services",
    "media": "Communication Services",
    "entertainment": "Communication Services",
    "publishing": "Communication Services",
    # Consumer Cyclical
    "auto": "Consumer Cyclical",
    "automobile": "Consumer Cyclical",
    "automobiles": "Consumer Cyclical",
    "auto ancillaries": "Consumer Cyclical",
    "auto parts": "Consumer Cyclical",
    "consumer discretionary": "Consumer Cyclical",
    "retail": "Consumer Cyclical",
    "specialty retail": "Consumer Cyclical",
    "hotels & restaurants": "Consumer Cyclical",
    "hotels": "Consumer Cyclical",
    "travel & tourism": "Consumer Cyclical",
    "textiles": "Consumer Cyclical",
    "apparel": "Consumer Cyclical",
    "consumer durables": "Consumer Cyclical",
    "household appliances": "Consumer Cyclical",
    # Real Estate
    "realty": "Real Estate",
    "real estate development": "Real Estate",
    # Already-canonical (no-op aliases for case drift)
    "technology": "Technology",
    "financial services": "Financial Services",
    "healthcare": "Healthcare",
    "consumer cyclical": "Consumer Cyclical",
    "consumer defensive": "Consumer Defensive",
    "industrials": "Industrials",
    "basic materials": "Basic Materials",
    "communication services": "Communication Services",
    "energy": "Energy",
    "utilities": "Utilities",
    "real estate": "Real Estate",
}


# Nifty sector indices → canonical sector. Used by the sector resolver and the
# /sectors page to overlay sector-index performance on sector mood.
INDEX_TO_SECTOR: dict[str, str] = {
    "nifty_it": "Technology",
    "nifty_auto": "Consumer Cyclical",
    "nifty_fmcg": "Consumer Defensive",
    "nifty_pharma": "Healthcare",
    "nifty_energy": "Energy",
    "nifty_bank": "Financial Services",
    "nifty_metal": "Basic Materials",
    "nifty_realty": "Real Estate",
    "nifty_media": "Communication Services",
    "nifty_pvt_bank": "Financial Services",
    "nifty_psu_bank": "Financial Services",
}


def normalize_sector(s: str | None) -> str | None:
    """Map a free-text sector label (from yfinance, Screener.in, NSE industry,
    etc.) to a canonical 11-sector name.

    Returns None for null/empty input. Returns the aliased canonical name if
    the input (case-insensitive, whitespace-trimmed) matches a known alias.
    Otherwise returns a title-cased version of the input — preserving the
    label so downstream code can log it as "unknown sector" and grow the
    alias map over time. Callers should not assume the return value is in
    CANONICAL_SECTORS unless they explicitly check.
    """
    if not s:
        return None
    key = s.strip().lower()
    if not key:
        return None
    if key in SECTOR_ALIASES:
        return SECTOR_ALIASES[key]
    # Fail-open: clean up case/whitespace drift but don't drop unknown values.
    # `replace(" And ", " & ")` undoes Python's title() converting "and" → "And"
    # mid-string (e.g., "Metals And Mining" → "Metals & Mining").
    return s.strip().title().replace(" And ", " & ")


def is_canonical_sector(s: str | None) -> bool:
    """True iff `s` is one of the 11 canonical sectors. Use for guarding
    valuation-preset lookups; non-canonical sectors fall through to the
    universal Indian-screener preset."""
    return s is not None and s in CANONICAL_SECTORS
