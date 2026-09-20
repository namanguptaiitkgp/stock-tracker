DEFAULT_STRATEGIES = [
    {
        "name": "Benjamin Graham — Defensive Value",
        "strategy_type": "value",
        "description": "The classic value investing strategy from 'The Intelligent Investor'. Looks for financially stable, undervalued companies with a margin of safety.",
        "config_json": {
            "filters": {
                "pe_ratio_max": 15,
                "pb_ratio_max": 1.5,
                "debt_to_equity_max": 0.5,
                "net_profit_margin_min": 0.05,
                "market_cap_min_cr": 1000,
            },
            "weights": {"pe": 0.25, "pb": 0.25, "debt": 0.2, "margin": 0.15, "market_cap": 0.15},
            "signal_rules": "BUY if PE<15 AND PB<1.5 AND D/E<0.5. SELL if PE>25 OR overvalued by 40%.",
        },
    },
    {
        "name": "Warren Buffett — Quality Moat",
        "strategy_type": "quality",
        "description": "Buffett's approach: buy wonderful companies at fair prices. Focus on sustainable competitive advantages, high ROE, low debt, consistent earnings.",
        "config_json": {
            "filters": {
                "roe_min": 0.15,
                "net_profit_margin_min": 0.10,
                "debt_to_equity_max": 0.7,
                "revenue_growth_1y_min": 0.08,
                "eps_growth_1y_min": 0.10,
            },
            "weights": {"roe": 0.3, "margin": 0.25, "growth": 0.2, "debt": 0.15, "pe": 0.1},
            "signal_rules": "BUY quality compounders held long-term. SELL only if moat erodes or overvalued.",
        },
    },
    {
        "name": "Peter Lynch — GARP",
        "strategy_type": "growth",
        "description": "Growth At Reasonable Price. Looks for PEG ratio < 1, strong earnings growth, manageable debt. Classic from 'One Up On Wall Street'.",
        "config_json": {
            "filters": {
                "peg_ratio_max": 1.0,
                "eps_growth_1y_min": 0.15,
                "debt_to_equity_max": 1.0,
                "pe_ratio_max": 25,
            },
            "weights": {"peg": 0.35, "eps_growth": 0.3, "revenue_growth": 0.2, "debt": 0.15},
            "signal_rules": "BUY if PEG<1 AND EPS growth>15%. SELL if PEG>2 or growth slows.",
        },
    },
    {
        "name": "William O'Neil — CANSLIM",
        "strategy_type": "momentum",
        "description": "Combines fundamental + technical momentum. High EPS growth, sales growth, strong price relative strength. From Investor's Business Daily founder.",
        "config_json": {
            "filters": {
                "eps_growth_1y_min": 0.25,
                "revenue_growth_1y_min": 0.20,
                "roe_min": 0.17,
                "near_52w_high_pct": 0.85,
            },
            "weights": {"eps_growth": 0.35, "revenue_growth": 0.25, "momentum": 0.25, "quality": 0.15},
            "signal_rules": "BUY on breakout with volume. SELL on 7-8% drop below entry (strict stop-loss).",
        },
    },
    {
        "name": "Joel Greenblatt — Magic Formula",
        "strategy_type": "value",
        "description": "Rank stocks by combined earnings yield + ROIC. From 'The Little Book That Beats the Market'.",
        "config_json": {
            "filters": {
                "market_cap_min_cr": 500,
                "roe_min": 0.20,
                "earnings_yield_min": 0.08,
            },
            "weights": {"earnings_yield": 0.5, "roe": 0.5},
            "signal_rules": "BUY top 20-30 ranked. Hold 1 year. Rebalance annually.",
        },
    },
    {
        "name": "John Neff — Low P/E Contrarian",
        "strategy_type": "value",
        "description": "Contrarian low-PE strategy with growth + yield. Buy what others dislike but fundamentals are sound.",
        "config_json": {
            "filters": {
                "pe_ratio_max": 12,
                "eps_growth_1y_min": 0.07,
                "dividend_yield_min": 0.02,
                "debt_to_equity_max": 1.0,
            },
            "weights": {"low_pe": 0.35, "growth": 0.3, "dividend": 0.2, "debt": 0.15},
            "signal_rules": "BUY low-PE with decent growth+dividend. SELL when PE normalizes to sector average.",
        },
    },
    {
        "name": "Indian Small-Cap Momentum",
        "strategy_type": "momentum",
        "description": "India-specific: mid/small-cap with accelerating earnings, strong revenue growth, manageable debt. Benefits from India's growth story.",
        "config_json": {
            "filters": {
                "market_cap_min_cr": 500,
                "market_cap_max_cr": 30000,
                "revenue_growth_1y_min": 0.20,
                "eps_growth_1y_min": 0.25,
                "debt_to_equity_max": 1.0,
                "roe_min": 0.15,
            },
            "weights": {"revenue_growth": 0.3, "eps_growth": 0.3, "roe": 0.2, "momentum": 0.2},
            "signal_rules": "BUY accelerating growth stocks. Strict 15% trailing stop. Exit if quarterly growth falters.",
        },
    },
    {
        "name": "Nifty Quality 30 Replica",
        "strategy_type": "quality",
        "description": "Replicates Nifty Quality 30 index methodology — high ROE, low leverage, stable earnings growth.",
        "config_json": {
            "filters": {
                "roe_min": 0.18,
                "debt_to_equity_max": 0.5,
                "net_profit_margin_min": 0.08,
                "revenue_growth_1y_min": 0.05,
                "market_cap_min_cr": 5000,
            },
            "weights": {"roe": 0.35, "stability": 0.3, "low_debt": 0.2, "growth": 0.15},
            "signal_rules": "Buy and hold quality. Rebalance semi-annually.",
        },
    },
    {
        "name": "Dividend Aristocrat",
        "strategy_type": "dividend",
        "description": "Stocks with consistent dividend history, high yield, and stable earnings. Good for steady income.",
        "config_json": {
            "filters": {
                "dividend_yield_min": 0.025,
                "net_profit_margin_min": 0.10,
                "debt_to_equity_max": 1.0,
                "market_cap_min_cr": 2000,
            },
            "weights": {"dividend_yield": 0.4, "profit_stability": 0.3, "low_debt": 0.2, "pe": 0.1},
            "signal_rules": "BUY and hold for yield. SELL only if dividend is cut or company deteriorates.",
        },
    },
]
