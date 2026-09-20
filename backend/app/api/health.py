"""Deep-check health endpoint for Docker / uptime monitoring.

`GET /health` returns 200 with `{db, redis, celery: ok|fail}` when all three
dependencies respond, 503 if any check fails. Intended for liveness probes
and external uptime monitors. The lightweight `GET /health/live` returns
200 immediately without touching dependencies — use it for k8s liveness
probes that should NOT depend on DB.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config import get_settings
from app.db.session import async_session

logger = logging.getLogger(__name__)
router = APIRouter()


async def _check_db(timeout: float = 2.0) -> tuple[bool, str | None]:
    try:
        async with async_session() as s:
            await asyncio.wait_for(s.execute(text("SELECT 1")), timeout=timeout)
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


def _check_redis(timeout: float = 2.0) -> tuple[bool, str | None]:
    try:
        import redis  # local import — only needed in this path

        client = redis.Redis.from_url(get_settings().REDIS_URL, socket_timeout=timeout)
        client.ping()
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


def _check_celery(timeout: float = 2.0) -> tuple[bool, str | None]:
    try:
        from app.tasks.celery_app import celery_app

        # ping returns a list of {worker_name: pong}. Empty list = no workers.
        replies = celery_app.control.ping(timeout=timeout)
        if not replies:
            return False, "no workers responded"
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


@router.get("/live")
async def live() -> dict:
    """Cheap probe — just confirms the process is up."""
    return {"status": "ok"}


@router.get("")
@router.get("/")
async def health(response: Response) -> dict:
    db_ok, db_err = await _check_db()
    redis_ok, redis_err = await asyncio.to_thread(_check_redis)
    celery_ok, celery_err = await asyncio.to_thread(_check_celery)
    all_ok = db_ok and redis_ok and celery_ok
    if not all_ok:
        response.status_code = 503
    return {
        "status": "ok" if all_ok else "degraded",
        "db": {"ok": db_ok, "error": db_err},
        "redis": {"ok": redis_ok, "error": redis_err},
        "celery": {"ok": celery_ok, "error": celery_err},
    }
