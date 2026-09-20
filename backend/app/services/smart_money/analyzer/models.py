from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class DealRow:
    """Normalized deal row. One of bulk / block / insider."""
    symbol: str
    trade_date: date
    party_raw: str
    party_norm: str  # normalized key
    category: str  # one of party_classifier constants
    side: str  # BUY | SELL
    quantity: int
    price: float
    value_inr: float
    mode: str  # "BULK" | "BLOCK" | "INSIDER"
    source_file: str | None = None
    csv_category: str | None = None  # raw hint from source CSV
    holdings_change_pct: float | None = None  # for insider filings


# Signal type constants
SIG_VC_EXIT = "VC_PE_EXIT_BLOCK"
SIG_STRONG_BUY_PROMOTER = "STRONG_BUY_PROMOTER_ACCUMULATION"
SIG_STRONG_BUY_CONSENSUS = "STRONG_BUY_INSTITUTIONAL_CONSENSUS"
SIG_MODERATE_BUY = "MODERATE_BUY_SINGLE_NAME_QUALITY"
SIG_STRONG_SELL_PROMOTER = "STRONG_SELL_PROMOTER_DISTRIBUTION"
SIG_STRONG_SELL_QUALITY = "STRONG_SELL_QUALITY_DISTRIBUTION"
SIG_WEAK_BUY = "WEAK_BUY"
SIG_WEAK_SELL = "WEAK_SELL"
SIG_NEUTRAL = "NEUTRAL"
SIG_NOISE = "NOISE"

# Direction mapping
DIR_BUY = "BUY"
DIR_SELL = "SELL"
DIR_NEUTRAL = "NEUTRAL"
DIR_NOISE = "NOISE"


SIGNAL_TO_DIRECTION = {
    SIG_VC_EXIT: DIR_NEUTRAL,  # informational, not directional
    SIG_STRONG_BUY_PROMOTER: DIR_BUY,
    SIG_STRONG_BUY_CONSENSUS: DIR_BUY,
    SIG_MODERATE_BUY: DIR_BUY,
    SIG_STRONG_SELL_PROMOTER: DIR_SELL,
    SIG_STRONG_SELL_QUALITY: DIR_SELL,
    SIG_WEAK_BUY: DIR_BUY,
    SIG_WEAK_SELL: DIR_SELL,
    SIG_NEUTRAL: DIR_NEUTRAL,
    SIG_NOISE: DIR_NOISE,
}


@dataclass
class StockSignal:
    stock: str
    signal: str
    direction: str
    tier: str | None  # "Sizeable" | "Symbolic" | None
    confidence: str  # descriptive label
    net_cr: float
    days: int
    primary_evidence: str
    modifiers: list[str] = field(default_factory=list)
    # For transparency / audit
    gross_value_inr: float = 0.0
    prop_share: float = 0.0
    top_parties: list[dict] = field(default_factory=list)
    reason_notes: list[str] = field(default_factory=list)


@dataclass
class AnalyzerReport:
    window_start: date | None
    window_end: date | None
    total_rows: int
    dropped_rows: int
    stocks_seen: int
    signals: list[StockSignal]  # real BUY/SELL + VC_EXIT
    neutral: list[StockSignal]
    noise: list[StockSignal]
    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
