import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from kiteconnect import KiteConnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_kite_for_user(user: User) -> KiteConnect:
    if not user.kite_api_key or not user.kite_api_secret:
        raise HTTPException(status_code=400, detail="Kite API key not configured. Go to Settings first.")
    kite = KiteConnect(api_key=user.kite_api_key)
    return kite


@router.get("/login")
async def login(user: User = Depends(get_current_user)) -> dict:
    kite = _get_kite_for_user(user)
    return {"login_url": kite.login_url()}


@router.get("/callback")
async def callback(
    request_token: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    kite = _get_kite_for_user(user)
    data = kite.generate_session(request_token, api_secret=user.kite_api_secret)

    user.kite_access_token = data["access_token"]
    user.kite_token_expiry = datetime.now(timezone.utc)
    await db.commit()

    return {"status": "success"}


@router.get("/status")
async def status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not user.kite_api_key:
        return {"authenticated": False, "has_keys": False}

    if not user.kite_access_token:
        return {"authenticated": False, "has_keys": True}

    # Actually verify the token works by calling Kite
    kite = KiteConnect(api_key=user.kite_api_key)
    kite.set_access_token(user.kite_access_token)
    try:
        await asyncio.to_thread(kite.profile)
        return {"authenticated": True, "has_keys": True}
    except Exception as e:
        logger.info(f"Kite token validation failed: {e}")
        # Token is invalid/expired — clear it from DB
        user.kite_access_token = None
        await db.commit()
        return {"authenticated": False, "has_keys": True, "reason": "Token expired or invalid"}
