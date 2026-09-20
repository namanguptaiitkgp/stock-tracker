"""Manual override adapter.

Reads `metric_manual_overrides` for the (user, symbol) and returns the
typed-in values. Layered on top of source-derived values by the metric
engine so user overrides survive every refresh.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric import MetricManualOverride


async def fetch(db: AsyncSession, user_id: int, symbol: str) -> dict[str, float | str]:
    res = await db.execute(
        select(MetricManualOverride).where(
            MetricManualOverride.user_id == user_id,
            MetricManualOverride.symbol == symbol.upper(),
        )
    )
    out: dict[str, float | str] = {}
    for row in res.scalars().all():
        if row.value_num is not None:
            out[row.metric_key] = float(row.value_num)
        elif row.value_str is not None:
            out[row.metric_key] = row.value_str
    return out
