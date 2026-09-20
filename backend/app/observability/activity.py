"""Logging helpers for LLM calls and external scrapes.

Callers wrap their Gemini/Anthropic call in `ai_purpose("sentiment")` etc.
so we can categorise the LLM spend. If no context is set the call is
logged with purpose="unknown" — still useful for total-cost tracking.

Scrape logging hooks into the unified data_cache path: every fetch
records (source, url, status, latency, success).
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)


@dataclass
class _AiCtx:
    purpose: str = "unknown"
    symbol: str | None = None
    user_id: int | None = None


_ai_ctx: contextvars.ContextVar[_AiCtx] = contextvars.ContextVar(
    "ai_ctx", default=_AiCtx()
)


@asynccontextmanager
async def ai_purpose(purpose: str, *, symbol: str | None = None, user_id: int | None = None):
    """Sets the purpose/symbol/user_id for any LLM calls inside the block.
    Nested usage stacks correctly (innermost wins)."""
    prev = _ai_ctx.get()
    token = _ai_ctx.set(_AiCtx(
        purpose=purpose,
        symbol=symbol if symbol is not None else prev.symbol,
        user_id=user_id if user_id is not None else prev.user_id,
    ))
    try:
        yield
    finally:
        _ai_ctx.reset(token)


def current_ai_ctx() -> _AiCtx:
    return _ai_ctx.get()


# Lazy module-level engine for synchronous-ish fire-and-forget logging.
_engine = None
_SM = None


def _get_session_maker():
    global _engine, _SM
    if _SM is None:
        from app.config import get_settings
        settings = get_settings()
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=0)
        _SM = async_sessionmaker(_engine, expire_on_commit=False)
    return _SM


async def log_llm_call(
    *,
    provider: str,
    model: str | None,
    purpose: str | None = None,
    symbol: str | None = None,
    user_id: int | None = None,
    credential_id: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
    latency_ms: int | None = None,
    success: bool = True,
    error_class: str | None = None,
) -> None:
    """Best-effort: never raises. If the table doesn't exist yet, swallows
    silently."""
    ctx = _ai_ctx.get()
    try:
        from app.models.llm_call import LlmCall
        SM = _get_session_maker()
        async with SM() as db:
            row = LlmCall(
                provider=provider,
                model=model,
                purpose=purpose or ctx.purpose,
                symbol=symbol or ctx.symbol,
                user_id=user_id or ctx.user_id,
                credential_id=credential_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                success=success,
                error_class=error_class,
            )
            db.add(row)
            await db.commit()
    except Exception as e:
        logger.debug("log_llm_call swallow: %s", e)


async def log_scrape_event(
    *,
    source: str,
    url: str | None = None,
    symbol: str | None = None,
    status: int | None = None,
    latency_ms: int | None = None,
    bytes_: int | None = None,
    success: bool = True,
    error_class: str | None = None,
) -> None:
    """Best-effort: never raises."""
    try:
        from app.models.scrape_event import ScrapeEvent
        SM = _get_session_maker()
        async with SM() as db:
            row = ScrapeEvent(
                source=source,
                url=url,
                symbol=symbol,
                status=status,
                latency_ms=latency_ms,
                bytes=bytes_,
                success=success,
                error_class=error_class,
            )
            db.add(row)
            await db.commit()
    except Exception as e:
        logger.debug("log_scrape_event swallow: %s", e)
