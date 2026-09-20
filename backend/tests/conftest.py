import pytest


@pytest.fixture
def app_settings():
    from app.config import Settings

    return Settings(
        DATABASE_URL="postgresql+asyncpg://localhost:5432/algo_trader_test",
        REDIS_URL="redis://localhost:6379/15",
        CELERY_BROKER_URL="redis://localhost:6379/14",
        KITE_API_KEY="test_key",
        KITE_API_SECRET="test_secret",
    )
