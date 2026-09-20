"""In-memory mirror of `metric_definitions` for fast lookups.

The catalog is small (~30 rows in Phase 1, ~80 in Phase 3) and changes
only via Alembic migration, so we cache it once at first read and
expose `refresh()` for tests / hot reloads.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric import MetricDefinition


@dataclass(frozen=True)
class MetricDef:
    key: str
    display_name: str
    category: str
    unit: str | None
    direction: str
    description_md: str | None
    formula: str | None
    default_source: str | None
    is_active: bool
    sort_order: int


_cache: dict[str, MetricDef] | None = None
_by_category: dict[str, list[MetricDef]] | None = None
_lock = threading.Lock()


def _from_row(row: MetricDefinition) -> MetricDef:
    return MetricDef(
        key=row.key,
        display_name=row.display_name,
        category=row.category,
        unit=row.unit,
        direction=row.direction,
        description_md=row.description_md,
        formula=row.formula,
        default_source=row.default_source,
        is_active=row.is_active,
        sort_order=row.sort_order,
    )


async def _load(db: AsyncSession) -> None:
    global _cache, _by_category
    res = await db.execute(
        select(MetricDefinition).order_by(MetricDefinition.category, MetricDefinition.sort_order)
    )
    rows = list(res.scalars().all())
    by_key: dict[str, MetricDef] = {}
    by_cat: dict[str, list[MetricDef]] = {}
    for r in rows:
        m = _from_row(r)
        by_key[m.key] = m
        by_cat.setdefault(m.category, []).append(m)
    with _lock:
        _cache = by_key
        _by_category = by_cat


async def ensure_loaded(db: AsyncSession) -> None:
    if _cache is None:
        await _load(db)


async def refresh(db: AsyncSession) -> None:
    """Force a re-read from DB. Useful in tests."""
    await _load(db)


async def get_metric(db: AsyncSession, key: str) -> MetricDef | None:
    await ensure_loaded(db)
    return (_cache or {}).get(key)


async def list_all(db: AsyncSession) -> list[MetricDef]:
    await ensure_loaded(db)
    return list((_cache or {}).values())


async def list_by_category(db: AsyncSession) -> dict[str, list[MetricDef]]:
    await ensure_loaded(db)
    return dict(_by_category or {})
