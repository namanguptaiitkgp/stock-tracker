from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.credential_rotation import get_credential, NoCredentialsConfiguredError
from app.ai.provider import AIProvider, AIProviderConfigError
from app.ai.providers.gemini_vertex import GeminiVertexProvider
from app.models.user import User

Purpose = Literal["analysis", "screening"]


async def get_ai_provider(user: User, db: AsyncSession, purpose: Purpose = "analysis") -> AIProvider:
    try:
        credential = await get_credential(user.id, db)
    except NoCredentialsConfiguredError as e:
        raise AIProviderConfigError(str(e)) from e

    return GeminiVertexProvider(credential=credential)
