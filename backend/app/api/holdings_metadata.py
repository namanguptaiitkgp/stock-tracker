"""Holdings metadata — purchase date + thesis per held stock.

The Settings editor seeds its row list from `portfolio_cache.get_holdings()`
so even un-tagged holdings show up. The user records purchase date +
optional thesis text + tags via PUT; the holdings-signal layer reads
these to compute "since you bought" comparisons and to surface the
original thesis when smart money state contradicts it.

Per-user FK CASCADE per CLAUDE.md.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.user_holdings_metadata import UserHoldingsMetadata
from app.services.screener_presets import CANONICAL_SECTORS

router = APIRouter()


class HoldingsMetadataBody(BaseModel):
    # All fields optional — users can record any subset. Passing null for
    # any field clears it; omitting a field leaves the existing value.
    first_purchase_date: date | None = None
    initial_thesis: str | None = None
    thesis_tags: list[str] | None = None
    target_holding_period_months: int | None = Field(default=None, ge=0, le=600)
    sector_override: str | None = None


class SectorOverrideBody(BaseModel):
    """Lightweight body for the dedicated sector-override endpoint. Pass null
    to clear. Value must be one of the 11 canonical sectors."""
    sector: str | None = None


def _serialize(row: UserHoldingsMetadata) -> dict:
    return {
        "symbol": row.symbol,
        "first_purchase_date": row.first_purchase_date.isoformat() if row.first_purchase_date else None,
        "initial_thesis": row.initial_thesis,
        "thesis_tags": row.thesis_tags or [],
        "target_holding_period_months": row.target_holding_period_months,
        "sector_override": row.sector_override,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
async def list_metadata(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Return all holdings-metadata rows the user has recorded.

    The frontend joins this list with the live Kite holdings (via
    `portfolio_cache.get_holdings()`) so un-tagged holdings appear in
    the editor too — we deliberately don't merge here because the
    Kite call requires the user's live access token.
    """
    q = await db.execute(
        select(UserHoldingsMetadata)
        .where(UserHoldingsMetadata.user_id == user.id)
        .order_by(UserHoldingsMetadata.symbol)
    )
    return {"rows": [_serialize(r) for r in q.scalars().all()]}


def _validate_sector_override(s: str | None) -> str | None:
    """Sector override must be one of the 11 canonical sectors (or null to
    clear). The UI dropdown enforces this; the server enforces it again so
    direct API callers can't bypass the contract."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    if s not in CANONICAL_SECTORS:
        raise HTTPException(
            400,
            f"sector_override must be one of {CANONICAL_SECTORS!r}, got {s!r}",
        )
    return s


@router.put("/{symbol}")
async def upsert_metadata(
    symbol: str,
    body: HoldingsMetadataBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Insert or update the metadata row for one symbol. All fields optional."""
    sym = symbol.upper().strip()
    if not sym:
        raise HTTPException(400, "Symbol is required")

    sector_override = _validate_sector_override(body.sector_override)

    existing_q = await db.execute(
        select(UserHoldingsMetadata).where(
            UserHoldingsMetadata.user_id == user.id,
            UserHoldingsMetadata.symbol == sym,
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing is not None:
        existing.first_purchase_date = body.first_purchase_date
        existing.initial_thesis = body.initial_thesis
        existing.thesis_tags = body.thesis_tags
        existing.target_holding_period_months = body.target_holding_period_months
        existing.sector_override = sector_override
    else:
        db.add(UserHoldingsMetadata(
            user_id=user.id,
            symbol=sym,
            first_purchase_date=body.first_purchase_date,
            initial_thesis=body.initial_thesis,
            thesis_tags=body.thesis_tags,
            target_holding_period_months=body.target_holding_period_months,
            sector_override=sector_override,
        ))
    await db.commit()
    return {"status": "ok", "symbol": sym}


@router.put("/{symbol}/sector-override")
async def set_sector_override(
    symbol: str,
    body: SectorOverrideBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Lightweight endpoint to set/clear the sector_override on a holding
    without touching the other metadata fields.

    Pass `{"sector": null}` to clear. Pass `{"sector": "Energy"}` (or any
    other canonical sector name) to set. Creates the metadata row if it
    doesn't exist."""
    sym = symbol.upper().strip()
    if not sym:
        raise HTTPException(400, "Symbol is required")

    sector_override = _validate_sector_override(body.sector)

    existing_q = await db.execute(
        select(UserHoldingsMetadata).where(
            UserHoldingsMetadata.user_id == user.id,
            UserHoldingsMetadata.symbol == sym,
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing is not None:
        existing.sector_override = sector_override
    else:
        db.add(UserHoldingsMetadata(
            user_id=user.id,
            symbol=sym,
            sector_override=sector_override,
        ))
    await db.commit()
    return {"status": "ok", "symbol": sym, "sector_override": sector_override}


@router.delete("/{symbol}")
async def delete_metadata(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    sym = symbol.upper().strip()
    existing_q = await db.execute(
        select(UserHoldingsMetadata).where(
            UserHoldingsMetadata.user_id == user.id,
            UserHoldingsMetadata.symbol == sym,
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing is None:
        raise HTTPException(404, "Metadata not found for symbol")
    await db.delete(existing)
    await db.commit()
    return {"status": "deleted", "symbol": sym}
