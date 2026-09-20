import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

# Celery's prefork worker spins up a fresh asyncio event loop per task
# (each task wraps its work in `asyncio.run(...)`). Asyncpg connection
# objects are bound to the loop they were created on, so any pooled
# connection that survives a task into the next loop trips
#   RuntimeError: got Future ... attached to a different loop
#   asyncpg.InterfaceError: another operation is in progress
# NullPool fixes this by closing every connection at session-exit, so
# nothing crosses a loop boundary. FastAPI runs in a single long-lived
# loop where the standard pool is correct (and avoids per-request TCP +
# auth round-trips), so the celery containers opt in via env var.
# See: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-multiple-asyncio-event-loops
_CELERY_NULL_POOL = os.getenv("CELERY_NULL_POOL", "").lower() in {"1", "true", "yes"}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    poolclass=NullPool if _CELERY_NULL_POOL else None,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
