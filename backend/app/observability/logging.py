"""structlog-based JSON logging and request middleware.

Configures `structlog` to emit one JSON line per log call, routes Python's
stdlib logger output through the same pipeline, and exposes
`RequestContextMiddleware` which tags every request log with
`request_id`, `user_id`, `path`, `status`, and `latency_ms`.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Per-request context — picked up by structlog processors so any log line
# emitted during the request automatically carries these fields.
_request_id: ContextVar[str | None] = ContextVar("_request_id", default=None)
_user_id: ContextVar[int | None] = ContextVar("_user_id", default=None)


def _add_context(_logger: Any, _name: str, event_dict: dict) -> dict:
    rid = _request_id.get()
    uid = _user_id.get()
    if rid is not None:
        event_dict.setdefault("request_id", rid)
    if uid is not None:
        event_dict.setdefault("user_id", uid)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """One-time logging setup. Idempotent."""
    if getattr(configure_logging, "_done", False):
        return

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors = [
        timestamper,
        structlog.stdlib.add_log_level,
        _add_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level, logging.INFO)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging through structlog's JSON renderer too.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Reduce noise from chatty libraries.
    for noisy in ("uvicorn.access", "kiteconnect", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    configure_logging._done = True  # type: ignore[attr-defined]


def get_logger(name: str | None = None):
    return structlog.get_logger(name) if name else structlog.get_logger()


def set_user_id(user_id: int | None) -> None:
    """Bind the authenticated user id for the rest of this request."""
    _user_id.set(user_id)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request_id, log access lines, and surface latency."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token_rid = _request_id.set(rid)
        token_uid = _user_id.set(None)
        log = get_logger("request")
        started = time.monotonic()
        status = 500
        try:
            response: Response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=status,
                latency_ms=elapsed_ms,
                client=request.client.host if request.client else None,
            )
            _request_id.reset(token_rid)
            _user_id.reset(token_uid)


def current_request_id() -> str | None:
    return _request_id.get()
