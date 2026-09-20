from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "change-me"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/algo_trader"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    KITE_API_KEY: str = ""
    KITE_API_SECRET: str = ""
    KITE_REDIRECT_URL: str = "http://localhost:8000/api/auth/callback"

    GEMINI_API_KEY: str = ""

    ANTHROPIC_API_KEY: str = ""
    OPUS_MODEL: str = "claude-opus-4-6"
    OPUS_MAX_DAILY_BUDGET_USD: float = 1.0

    CELERY_TIMEZONE: str = "Asia/Kolkata"

    RISK_MAX_POSITION_SIZE_PCT: float = 10
    RISK_MAX_TOTAL_EXPOSURE_PCT: float = 80
    RISK_MAX_DAILY_LOSS_INR: float = 5000
    RISK_MAX_DRAWDOWN_PCT: float = 5
    RISK_MAX_ORDERS_PER_DAY: int = 20
    RISK_MAX_ORDER_VALUE_INR: float = 100000
    RISK_KILL_SWITCH: bool = False

    # Field-level encryption (Fernet) for sensitive user creds at rest.
    # Required in non-dev. Generate via:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    FIELD_ENCRYPTION_KEY: str = ""

    # Comma-separated list of allowed origins for CORS. Defaults to localhost
    # in dev; required in production.
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Token required to call /metrics. If empty, /metrics is disabled.
    METRICS_ALLOW_TOKEN: str = ""

    # Sentry DSN — optional, set to enable error reporting.
    SENTRY_DSN: str = ""

    # Rate limiting (requests per window). Use slowapi notation.
    RATE_LIMIT_DEFAULT: str = "300/minute"
    RATE_LIMIT_AUTH: str = "10/minute"

    # Indian capital gains tax framework — used as parameters into the
    # Smart Exit System prompt (`SELL_STRATEGY_PROMPT`). Stored as ints
    # representing whole-percent rates because the prompt renders them
    # as "{stcg_rate}%". Update here when the budget changes the regime,
    # not at the call site.
    INDIA_STCG_RATE: int = 20
    INDIA_LTCG_RATE: int = 12  # 12.5% rounded — prompt uses whole int for legibility
    INDIA_LTCG_EXEMPTION_INR: int = 125_000  # ₹1.25L annual long-term exemption


@lru_cache
def get_settings() -> Settings:
    return Settings()


def is_production(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return (s.APP_ENV or "development").lower() in {"production", "prod"}


def validate_production_settings() -> list[str]:
    """Return a list of error strings if any required-in-prod settings are missing/insecure.

    Called from app startup; raises RuntimeError when running in production with violations.
    Safe to call in dev (returns empty list).
    """
    s = get_settings()
    errors: list[str] = []
    if not is_production(s):
        return errors

    if s.APP_SECRET_KEY in {"", "change-me"}:
        errors.append("APP_SECRET_KEY must be set to a strong random value in production.")
    if not s.FIELD_ENCRYPTION_KEY:
        errors.append("FIELD_ENCRYPTION_KEY must be set in production.")
    if "localhost" in (s.KITE_REDIRECT_URL or "") or "127.0.0.1" in (s.KITE_REDIRECT_URL or ""):
        errors.append(
            "KITE_REDIRECT_URL must point to your public domain in production "
            f"(currently: {s.KITE_REDIRECT_URL!r})."
        )
    if not s.CORS_ORIGINS or any(
        origin.strip() in {"", "*"} for origin in s.CORS_ORIGINS.split(",")
    ):
        errors.append(
            "CORS_ORIGINS must be set to an explicit comma-separated list of origins in production."
        )

    return errors


def cors_origins_list() -> list[str]:
    raw = get_settings().CORS_ORIGINS or ""
    return [o.strip() for o in raw.split(",") if o.strip()]
