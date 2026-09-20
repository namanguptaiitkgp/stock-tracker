import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.router import router as api_router
from app.config import (
    cors_origins_list,
    get_settings,
    is_production,
    validate_production_settings,
)
from app.observability.logging import (
    RequestContextMiddleware,
    configure_logging,
    current_request_id,
    get_logger,
)
from app.observability.ratelimit import limiter

# --- Logging --------------------------------------------------------------- #
configure_logging(level="INFO")
logger = get_logger(__name__)
_stdlib_logger = logging.getLogger(__name__)
_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    errors = validate_production_settings()
    if errors:
        msg = "Refusing to start in production: " + " ".join(errors)
        _stdlib_logger.error(msg)
        raise RuntimeError(msg)
    logger.info("startup", production=is_production())
    yield
    logger.info("shutdown")


app = FastAPI(title="Algo-Trader", lifespan=lifespan)
app.state.limiter = limiter


# --- Middleware (outermost first) ----------------------------------------- #
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestContextMiddleware)


# --- Rate-limit handler --------------------------------------------------- #
@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": "Too many requests. Slow down.",
            "request_id": current_request_id(),
        },
    )


# --- Global exception handler --------------------------------------------- #
@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all so a 500 never leaks a stack trace to the client.
    The full traceback is logged structured under `request_id` for triage."""
    logger.exception("unhandled_exception", path=request.url.path, exc_type=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "internal_error",
            "request_id": current_request_id(),
        },
    )


# --- Prometheus /metrics --------------------------------------------------- #
if _settings.METRICS_ALLOW_TOKEN:
    from prometheus_fastapi_instrumentator import Instrumentator

    @app.middleware("http")
    async def _gate_metrics(request: Request, call_next):
        if request.url.path == "/metrics":
            token = request.headers.get("x-metrics-token", "")
            if token != _settings.METRICS_ALLOW_TOKEN:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "metrics access denied"},
                )
        return await call_next(request)

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/metrics", "/api/health.*"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    logger.info("metrics_enabled", endpoint="/metrics")


# --- Routers --------------------------------------------------------------- #
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root() -> dict:
    return {"status": "ok", "app": "algo-trader"}
