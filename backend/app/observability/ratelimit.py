"""Single shared `Limiter` instance — kept here (not in main.py) so route
modules can decorate handlers without circular-importing the FastAPI app."""

from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request
from slowapi.util import get_remote_address

from app.config import get_settings


def _key_func(request: Request) -> str:
    """Authenticated user => stable per-token bucket; else fall back to IP.
    Hashing the first 64 chars of the bearer token keeps the key short
    without decoding the JWT."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return f"tok:{hash(auth[:64])}"
    return get_remote_address(request)


limiter = Limiter(
    key_func=_key_func,
    default_limits=[get_settings().RATE_LIMIT_DEFAULT],
)


def auth_limit():
    """Lazy decorator factory — re-reads RATE_LIMIT_AUTH so test overrides
    take effect without re-importing this module."""
    return limiter.limit(get_settings().RATE_LIMIT_AUTH)
