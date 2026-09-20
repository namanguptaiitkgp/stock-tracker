import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai_credential import AiCredential

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


class AllCredentialsExhaustedError(RuntimeError):
    pass


class NoCredentialsConfiguredError(RuntimeError):
    pass


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)


def _ist_date_key() -> str:
    return datetime.now(tz=IST).strftime("%Y-%m-%d")


def _exhaustion_key(credential_id: int) -> str:
    return f"gemini:exhausted:{credential_id}:{_ist_date_key()}"


def is_exhausted(credential_id: int) -> bool:
    try:
        return bool(_redis_client().exists(_exhaustion_key(credential_id)))
    except Exception:
        return False


def mark_exhausted(credential_id: int) -> None:
    try:
        r = _redis_client()
        key = _exhaustion_key(credential_id)
        r.set(key, "1", ex=86400)
        logger.warning("Credential %d marked exhausted for %s", credential_id, _ist_date_key())
    except Exception as e:
        logger.error("Failed to mark credential %d exhausted: %s", credential_id, e)


async def get_active_credentials(user_id: int, db: AsyncSession) -> list[AiCredential]:
    result = await db.execute(
        select(AiCredential)
        .where(AiCredential.user_id == user_id, AiCredential.is_active == True)
        .order_by(AiCredential.priority.asc(), AiCredential.id.asc())
    )
    return list(result.scalars().all())


async def get_credential(user_id: int, db: AsyncSession) -> AiCredential:
    creds = await get_active_credentials(user_id, db)
    if not creds:
        raise NoCredentialsConfiguredError(
            "No AI credentials configured. Add one in Settings → Connections → AI Infra."
        )

    for cred in creds:
        if not is_exhausted(cred.id):
            return cred

    raise AllCredentialsExhaustedError(
        "All Gemini credentials exhausted for today. Add more credentials or try again tomorrow."
    )


async def get_next_credential(user_id: int, db: AsyncSession, after_id: int) -> AiCredential:
    creds = await get_active_credentials(user_id, db)
    past_current = False
    for cred in creds:
        if cred.id == after_id:
            past_current = True
            continue
        if past_current and not is_exhausted(cred.id):
            return cred

    raise AllCredentialsExhaustedError(
        "All Gemini credentials exhausted for today. Add more credentials or try again tomorrow."
    )
