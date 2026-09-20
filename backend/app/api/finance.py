"""Floating Finance widget backend — thin wrapper around google_finance."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user
from app.models.user import User
from app.services.google_finance import lookup

router = APIRouter()


@router.get("/quote")
async def quote(
    q: str = Query(..., min_length=1, max_length=40),
    exchange: str = Query(default="NSE", max_length=8),
    user: User = Depends(get_current_user),
) -> dict:
    """Return Google Finance quote for a symbol. `q` may be either plain
    ticker ("RELIANCE") or with exchange ("TCS:NSE")."""
    return await lookup(q, default_exchange=exchange.upper())
