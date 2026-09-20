import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models.base import Base
from app.models import user, stock, watchlist, analysis, fundamentals, strategy, strategy_run, note, investment_decision, news_sentiment, daily_news_report  # noqa: F401
from app.models import fetch_cache as _fetch_cache_model  # noqa: F401
from app.models import review_alert as _review_alert_model  # noqa: F401
from app.models import invite_code as _invite_code_model  # noqa: F401
from app.models import metric as _metric_models  # noqa: F401
from app.models import fundamental_rule as _fundamental_rule_models  # noqa: F401
from app.models.smart_money import (  # noqa: F401
    AifFund,
    AifHoldingQuarterly,
    AnalyzerSession,
    AnalyzerSessionFile,
    BhavcopyDaily,
    BulkBlockDeal,
    IngestionRun,
    KnownShark,
    MfHoldingMonthly,
    MfScheme,
    PmsManager,
    PmsStrategyHoldingQuarterly,
    SmartMoneySignal,
    TodayBriefCache,
)
from app.models.market import IndexNewsSummary, IndexQuoteCache, MarketPulse  # noqa: F401
from app.models import paper_trading as _paper_trading_models  # noqa: F401
from app.models import ai_credential as _ai_credential_model  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

db_url = os.environ.get("DATABASE_SYNC_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
