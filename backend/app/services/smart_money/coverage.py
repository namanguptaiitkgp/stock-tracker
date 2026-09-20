"""Per-symbol coverage diagnostic for the smart-money subsystem.

The user's stated requirement: when a holding has weak or absent
smart-money data, the stock-detail UI should say so explicitly. This
service answers "do we actually have enough data on this symbol to
produce reliable smart-money output?" — used by:

  * `SmartMoneyPanel` — renders a callout when score < 50.
  * `holdings_signal.compute()` — returns NO_SIGNAL when score < 50
    rather than producing a misleading direction from sparse data.

Weights chosen to reflect signal importance:

  * `bhavcopy` (0.30) — without delivery / volume context every
    other signal is weakly grounded.
  * `signal` (0.30) — having a smart_money_signals row in the last
    7 days means the rollup has *something* to work with.
  * `deals` (0.15), `insider` (0.15) — the two main "who's actively
    moving" inputs.
  * `shareholding` (0.05), `mf_holdings` (0.05) — high-quality but
    quarterly / monthly cadence; absence is normal in a 30-day view.
  * `corporate_announcements` (0.00) — buybacks/pledges are rare
    events; absence carries no information about coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.smart_money import (
    BhavcopyDaily,
    BulkBlockDeal,
    CorporateAnnouncement,
    InsiderDisclosure,
    MfHoldingMonthly,
    ShareholdingPattern,
    SmartMoneySignal,
)


_WEIGHTS: dict[str, float] = {
    "bhavcopy": 0.30,
    "signal": 0.30,
    "deals": 0.15,
    "insider": 0.15,
    "shareholding": 0.05,
    "mf_holdings": 0.05,
    "corporate_announcements": 0.00,
}

_SOURCE_LABELS: dict[str, str] = {
    "bhavcopy": "bhavcopy & delivery",
    "signal": "smart-money rollup",
    "deals": "bulk/block deals",
    "insider": "insider disclosures",
    "shareholding": "shareholding pattern",
    "mf_holdings": "mutual fund holdings",
    "corporate_announcements": "corporate announcements (buybacks / pledges)",
}

# Per-source human-readable explanation for `gap_explanation` when
# a source is absent. Only sources with non-zero weight contribute.
_GAP_TEXT: dict[str, str] = {
    "bhavcopy": "No recent bhavcopy or delivery data",
    "signal": "Stock not in the smart-money rollup universe",
    "deals": "No bulk/block deals in last 30 days (NSE coverage thin for this stock)",
    "insider": "No insider disclosures in last 90 days",
    "shareholding": "Shareholding pattern not yet ingested for this stock",
    "mf_holdings": "Mutual fund holdings parser not yet active",
}


@dataclass
class SmartMoneyCoverage:
    symbol: str
    has_recent_bhavcopy: bool
    has_deals_30d: bool
    has_insider_90d: bool
    has_corporate_announcements_90d: bool
    has_shareholding_pattern: bool
    has_mf_holdings: bool
    has_signal: bool
    sources_with_data: list[str] = field(default_factory=list)
    sources_missing: list[str] = field(default_factory=list)
    coverage_score: int = 0
    gap_explanation: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "has_recent_bhavcopy": self.has_recent_bhavcopy,
            "has_deals_30d": self.has_deals_30d,
            "has_insider_90d": self.has_insider_90d,
            "has_corporate_announcements_90d": self.has_corporate_announcements_90d,
            "has_shareholding_pattern": self.has_shareholding_pattern,
            "has_mf_holdings": self.has_mf_holdings,
            "has_signal": self.has_signal,
            "sources_with_data": self.sources_with_data,
            "sources_missing": self.sources_missing,
            "coverage_score": self.coverage_score,
            "gap_explanation": self.gap_explanation,
        }


async def compute_coverage(symbol: str, db: AsyncSession) -> SmartMoneyCoverage:
    """Build a coverage summary for one symbol.

    All seven sources are checked with a single query each. The whole
    function is one round-trip per source — cheap; called per-stock by
    the SmartMoneyPanel so total cost is dominated by the panel not
    this service.
    """
    sym = symbol.upper().strip()
    today = datetime.now().date()
    since_30d = today - timedelta(days=30)
    since_90d = today - timedelta(days=90)
    since_7d_signal = today - timedelta(days=7)

    has_bhavcopy = bool(
        (await db.execute(
            select(func.count())
            .select_from(BhavcopyDaily)
            .where(BhavcopyDaily.symbol == sym, BhavcopyDaily.trade_date >= since_30d)
        )).scalar_one()
    )
    has_deals = bool(
        (await db.execute(
            select(func.count())
            .select_from(BulkBlockDeal)
            .where(BulkBlockDeal.symbol == sym, BulkBlockDeal.trade_date >= since_30d)
        )).scalar_one()
    )
    has_insider = bool(
        (await db.execute(
            select(func.count())
            .select_from(InsiderDisclosure)
            .where(
                InsiderDisclosure.symbol == sym,
                InsiderDisclosure.transaction_date >= since_90d,
                InsiderDisclosure.is_intra_group_transfer.is_(False),
            )
        )).scalar_one()
    )
    has_corp_ann = bool(
        (await db.execute(
            select(func.count())
            .select_from(CorporateAnnouncement)
            .where(
                CorporateAnnouncement.symbol == sym,
                CorporateAnnouncement.announcement_date >= since_90d,
            )
        )).scalar_one()
    )
    has_shp = bool(
        (await db.execute(
            select(func.count())
            .select_from(ShareholdingPattern)
            .where(ShareholdingPattern.symbol == sym)
        )).scalar_one()
    )
    has_mf = bool(
        (await db.execute(
            select(func.count())
            .select_from(MfHoldingMonthly)
            .where(MfHoldingMonthly.symbol == sym)
        )).scalar_one()
    )
    has_signal = bool(
        (await db.execute(
            select(func.count())
            .select_from(SmartMoneySignal)
            .where(SmartMoneySignal.symbol == sym, SmartMoneySignal.as_of >= since_7d_signal)
        )).scalar_one()
    )

    presence: dict[str, bool] = {
        "bhavcopy": has_bhavcopy,
        "signal": has_signal,
        "deals": has_deals,
        "insider": has_insider,
        "shareholding": has_shp,
        "mf_holdings": has_mf,
        "corporate_announcements": has_corp_ann,
    }

    sources_with_data: list[str] = []
    sources_missing: list[str] = []
    weighted = 0.0
    for src, present in presence.items():
        label = _SOURCE_LABELS[src]
        if present:
            sources_with_data.append(label)
            weighted += _WEIGHTS[src]
        else:
            sources_missing.append(label)

    score = int(round(weighted * 100))

    gap_explanation: str | None = None
    if score < 50:
        # Build an explanation from the missing weighted sources, biggest gaps first.
        gaps = sorted(
            ((src, _WEIGHTS[src]) for src in presence if not presence[src] and _WEIGHTS[src] > 0),
            key=lambda x: -x[1],
        )
        bullets = [_GAP_TEXT[src] for src, _ in gaps[:3] if src in _GAP_TEXT]
        if bullets:
            gap_explanation = "\n".join(f"• {b}" for b in bullets)

    return SmartMoneyCoverage(
        symbol=sym,
        has_recent_bhavcopy=has_bhavcopy,
        has_deals_30d=has_deals,
        has_insider_90d=has_insider,
        has_corporate_announcements_90d=has_corp_ann,
        has_shareholding_pattern=has_shp,
        has_mf_holdings=has_mf,
        has_signal=has_signal,
        sources_with_data=sources_with_data,
        sources_missing=sources_missing,
        coverage_score=score,
        gap_explanation=gap_explanation,
    )
