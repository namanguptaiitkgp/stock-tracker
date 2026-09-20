from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery("algo_trader", broker=settings.CELERY_BROKER_URL)

celery_app.conf.update(
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=False,
    result_backend=settings.REDIS_URL,
    # Worker subscribes to `default,analysis,data` (see docker-compose
    # `--queues=...`). Celery's library default is the queue literally
    # named `celery`, which the worker doesn't consume. Aligning the
    # default to `default` makes tasks without an explicit `queue=` land
    # in a queue the worker actually reads — previously
    # watchlist_snapshots, review_alerts, and review_alerts_intraday
    # were silently piling up on the unconsumed `celery` queue.
    task_default_queue="default",
)

celery_app.conf.beat_schedule = {
    # Split daily run: pre-open news scan (08:15 IST) and post-close
    # full pipeline (16:00 IST). Noon mid-session run removed — Kite
    # data wasn't settled and fundamentals don't change intraday.
    "pre-open-news-scan": {
        "task": "app.tasks.morning_pipeline.run_news_scan",
        "schedule": crontab(hour=8, minute=15, day_of_week="1-5"),
    },
    "post-close-pipeline": {
        "task": "app.tasks.morning_pipeline.run_morning_pipeline",
        "schedule": crontab(hour=16, minute=0, day_of_week="1-5"),
    },
    # Refresh Kite instrument list weekly so newly listed/de-listed tickers
    # land in the local universe table.
    "instrument-sync": {
        "task": "app.tasks.instruments.sync_instruments",
        "schedule": crontab(hour=7, minute=0, day_of_week="1"),
    },
    # --- Smart-money workstreams ---
    "amfi-nav-and-schemes": {
        "task": "app.tasks.smart_money.amfi.sync_nav_and_schemes",
        "schedule": crontab(hour=18, minute=0),  # daily, after market hours
    },
    "nse-bulk-block-deals": {
        "task": "app.tasks.smart_money.deals.ingest_nse_daily",
        "schedule": crontab(hour=18, minute=30, day_of_week="1-5"),
    },
    "nse-bhavcopy": {
        "task": "app.tasks.smart_money.bhavcopy.ingest_nse_daily",
        "schedule": crontab(hour=18, minute=0, day_of_week="1-5"),
    },
    # NSE ASM (Additional Surveillance) + GSM (Graded Surveillance) lists.
    # 24h cache; this job force-refreshes after NSE publishes the
    # post-close list. Feeds RegFlag values into the Smart Exit prompt.
    "nse-asm-gsm-daily": {
        "task": "app.tasks.regulatory.refresh_surveillance_lists",
        "schedule": crontab(hour=18, minute=30, day_of_week="1-5"),
        "options": {"queue": "data"},
    },
    "smart-money-rollup": {
        "task": "app.tasks.smart_money.rollup.compute",
        "schedule": crontab(hour=19, minute=0, day_of_week="1-5"),
    },
    "amfi-monthly-mf-portfolios": {
        # Stub until the XLS parser is implemented; fires monthly on day 12.
        "task": "app.tasks.smart_money.amfi_monthly.ingest",
        "schedule": crontab(hour=10, minute=0, day_of_month="12"),
    },
    "sebi-pms-quarterly": {
        "task": "app.tasks.smart_money.sebi.ingest_pms_quarterly",
        "schedule": crontab(hour=10, minute=30, day_of_month="15", month_of_year="1,4,7,10"),
    },
    "sebi-aif-quarterly": {
        "task": "app.tasks.smart_money.sebi.ingest_aif_quarterly",
        "schedule": crontab(hour=11, minute=0, day_of_month="15", month_of_year="1,4,7,10"),
    },
    # PR-3 ingestion sources --------------------------------------------------
    # NSE insider disclosures (PIT Reg 7) — late-day filings, T+2 deadline.
    "nse-insider-disclosures": {
        "task": "app.tasks.smart_money.insider.ingest_nse_daily",
        "schedule": crontab(hour=17, minute=30, day_of_week="1-5"),
    },
    # NSE corporate announcements (buyback / pledge filings).
    "nse-corporate-announcements": {
        "task": "app.tasks.smart_money.corporate_ann.ingest_nse_daily",
        "schedule": crontab(hour=17, minute=0, day_of_week="1-5"),
    },
    # BSE bulk + block deals — staggered 15 min after NSE deals to avoid
    # piling up on the same celery worker minute.
    "bse-bulk-block-deals": {
        "task": "app.tasks.smart_money.deals.ingest_bse_daily",
        "schedule": crontab(hour=18, minute=45, day_of_week="1-5"),
    },
    # Per-stock FII/DII — placeholder task, see services/fii_dii.py docstring
    # for the upstream-data-gap caveat.
    "fii-dii-stock-daily": {
        "task": "app.tasks.smart_money.fii_dii_stock.ingest_nse_daily",
        "schedule": crontab(hour=18, minute=15, day_of_week="1-5"),
    },
    # Monthly shareholding pattern (NSE XBRL primary, BSE fallback).
    # Day 25 catches most quarterly filings (21-day deadline) plus
    # any mid-quarter updates.
    "shareholding-pattern-monthly": {
        "task": "app.tasks.smart_money.shareholding.ingest_bse_quarterly",
        "schedule": crontab(hour=10, minute=0, day_of_month="25"),
    },
    "market-indices-quotes": {
        "task": "app.tasks.market.indices.refresh_quotes",
        "schedule": crontab(minute="*/5", hour="9-15", day_of_week="1-5"),
    },
    "market-indices-summaries": {
        "task": "app.tasks.market.indices.refresh_summaries",
        "schedule": crontab(minute="10", hour="9-16", day_of_week="1-5"),
    },
    # Daily watchlist valuation snapshot — 16:30 IST, after market close
    "watchlist-valuation-snapshot": {
        "task": "app.tasks.watchlist_snapshots.snapshot_watchlist_valuations",
        "schedule": crontab(hour=16, minute=30, day_of_week="1-5"),
    },
    # 10 minutes after the snapshot above — gives the snapshot writer time
    # to commit before the evaluator reads. Fires watch-rule, valuation,
    # verdict, and sentiment review alerts for every user with a watchlist.
    "review-alerts-eval": {
        "task": "app.tasks.review_alerts.run_review_alerts_eval",
        "schedule": crontab(hour=16, minute=40, day_of_week="1-5"),
    },
    # Intraday: every 15 minutes during NSE hours. Evaluates only the fast
    # rule types (single_day_drop, price_below) on rules whose
    # check_frequency is set to 15min or hourly.
    "review-alerts-intraday": {
        "task": "app.tasks.review_alerts_intraday.run_intraday_eval",
        "schedule": crontab(minute="*/15", hour="9-15", day_of_week="1-5"),
    },
    # Event-driven re-evaluation: every 10 min during the market +
    # ingestion window. Polls ingestion_runs and queues
    # refresh_stock_analysis for affected holdings/watchlist symbols.
    "event-dispatcher": {
        "task": "app.tasks.event_dispatcher.run_event_dispatcher",
        "schedule": crontab(minute="*/10", hour="9-19", day_of_week="1-5"),
    },
    # Daily DB prune at 03:00 IST — caps row growth on fetch_cache,
    # ingestion_runs, news_sentiment_cache, llm_calls, scrape_events.
    "db-prune-daily": {
        "task": "app.tasks.db_prune.run_db_prune",
        "schedule": crontab(hour=3, minute=0),
    },
    # Weekly peer-backfill sweep — Sunday 17:00 IST. Reuses existing
    # run_peer_backfill task; idempotent for symbols that already have
    # peers (Phase G2).
    "peer-backfill-weekly": {
        "task": "app.tasks.peer_backfill_task.run_peer_backfill",
        "schedule": crontab(hour=17, minute=0, day_of_week="0"),
    },
    # Weekly stock-card refresh for watchlist symbols — Saturday 08:00
    # IST (markets closed Sat+Sun). Plugs the gap where the daily
    # morning_pipeline Step 4 only refreshes portfolio holdings, leaving
    # ResearchingCard's 3-section grid reading stale stock_analyses
    # data. Idempotent via `last_completed_date == today` skip. Cost
    # estimate ~$0.03/week. See task module docstring.
    "watchlist-card-weekly": {
        "task": "app.tasks.watchlist_card_refresh.refresh_all_watchlist_cards",
        "schedule": crontab(hour=8, minute=0, day_of_week="6"),
    },
}

# Ensure smart-money tasks are imported so celery registers them.
from app.tasks.smart_money import amfi as _sm_amfi  # noqa: E402, F401
from app.tasks.smart_money import amfi_monthly as _sm_amfi_monthly  # noqa: E402, F401
from app.tasks.smart_money import deals as _sm_deals  # noqa: E402, F401
from app.tasks.smart_money import bhavcopy as _sm_bhavcopy  # noqa: E402, F401
from app.tasks.smart_money import rollup as _sm_rollup  # noqa: E402, F401
from app.tasks.smart_money import sebi as _sm_sebi  # noqa: E402, F401
from app.tasks.smart_money import insider as _sm_insider  # noqa: E402, F401
from app.tasks.smart_money import corporate_ann as _sm_corp_ann  # noqa: E402, F401
from app.tasks.smart_money import fii_dii_stock as _sm_fii_dii  # noqa: E402, F401
from app.tasks.smart_money import shareholding as _sm_shp  # noqa: E402, F401
from app.tasks.market import indices as _mkt_indices  # noqa: E402, F401
from app.tasks import watchlist_snapshots as _wl_snapshots  # noqa: E402, F401
from app.tasks import instruments as _instruments  # noqa: E402, F401
from app.tasks import review_alerts as _review_alerts_task  # noqa: E402, F401
from app.tasks import review_alerts_intraday as _review_alerts_intraday  # noqa: E402, F401
from app.tasks import morning_pipeline as _morning_pipeline  # noqa: E402, F401
from app.tasks import peer_backfill_task as _peer_backfill  # noqa: E402, F401
from app.tasks import peer_warmup_task as _peer_warmup  # noqa: E402, F401
from app.tasks import news_onboarding as _news_onboarding  # noqa: E402, F401
from app.tasks import event_dispatcher as _event_dispatcher  # noqa: E402, F401
from app.tasks import db_prune as _db_prune  # noqa: E402, F401
from app.tasks import regulatory as _regulatory  # noqa: E402, F401
from app.tasks import metric_snapshot_task as _metric_snapshot  # noqa: E402, F401
from app.tasks import watchlist_card_refresh as _wl_card_refresh  # noqa: E402, F401
