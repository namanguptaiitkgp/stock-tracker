"""NSE ownership metrics from ShareholdingPattern table.

DB-only read — no external calls. Queries the latest row for the symbol
and returns ownership metrics + deltas for the metric engine.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.smart_money import ShareholdingPattern


async def fetch(db: AsyncSession, symbol: str) -> dict[str, float | None]:
    result = await db.execute(
        select(ShareholdingPattern)
        .where(ShareholdingPattern.symbol == symbol.upper())
        .order_by(ShareholdingPattern.quarter_end_date.desc())
        .limit(1)
    )
    sp = result.scalar_one_or_none()
    if not sp:
        return {}

    return {
        "promoter_holding": float(sp.promoter_pct) if sp.promoter_pct is not None else None,
        "fii_holding": float(sp.fii_pct) if sp.fii_pct is not None else None,
        "dii_holding": float(sp.dii_pct) if sp.dii_pct is not None else None,
        "mf_holding": float(sp.mf_pct) if sp.mf_pct is not None else None,
        "pledged_promoter_holding": float(sp.promoter_pledge_pct) if sp.promoter_pledge_pct is not None else None,
        "promoter_holding_change_3m": float(sp.promoter_delta) if sp.promoter_delta is not None else None,
        "fii_holding_change_3m": float(sp.fii_delta) if sp.fii_delta is not None else None,
        "_ownership_quarter_end": sp.quarter_end_date.isoformat() if sp.quarter_end_date else None,
    }
