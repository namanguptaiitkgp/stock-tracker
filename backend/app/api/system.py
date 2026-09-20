"""System-wide observability endpoint.

`GET /api/system/cache-status` aggregates everything the Settings page's
"Refresh schedules & caching" section needs in one round-trip:
  - `ai_signals` — per-pipeline refresh policy + last-run timestamps
  - `data_caches` — TTL per cache + most recent fetched_at
  - `beat_jobs` — live beat schedule + next-fire ETAs
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.fetch_cache import FetchCache
from app.models.investment_decision import InvestmentDecision
from app.models.metric import MetricRun
from app.models.news_sentiment import NewsSentimentCache
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()

_TASK_TO_SOURCE: dict[str, str] = {
    "app.tasks.morning_pipeline.run_morning_pipeline": "morning_pipeline",
    "app.tasks.instruments.sync_instruments": "instrument_sync",
    "app.tasks.smart_money.amfi.sync_nav_and_schemes": "amfi_nav",
    "app.tasks.smart_money.deals.ingest_nse_daily": "nse_deals",
    "app.tasks.smart_money.bhavcopy.ingest_nse_daily": "nse_bhavcopy",
    "app.tasks.smart_money.rollup.compute": "smart_money_rollup",
    "app.tasks.smart_money.amfi_monthly.ingest": "amfi_mf",
    "app.tasks.smart_money.sebi.ingest_pms_quarterly": "sebi_pms",
    "app.tasks.smart_money.sebi.ingest_aif_quarterly": "sebi_aif",
    "app.tasks.smart_money.insider.ingest_nse_daily": "nse_insider",
    "app.tasks.smart_money.corporate_ann.ingest_nse_daily": "nse_corporate_announcements",
    "app.tasks.smart_money.deals.ingest_bse_daily": "bse_deals",
    "app.tasks.smart_money.fii_dii_stock.ingest_nse_daily": "fii_dii_stock",
    "app.tasks.smart_money.shareholding.ingest_bse_quarterly": "shareholding_pattern",
    "app.tasks.market.indices.refresh_quotes": "market_indices_quotes",
    "app.tasks.market.indices.refresh_summaries": "market_indices_summaries",
    "app.tasks.watchlist_snapshots.snapshot_watchlist_valuations": "watchlist_snapshot",
    "app.tasks.review_alerts.run_review_alerts_eval": "review_alerts",
    "app.tasks.review_alerts_intraday.run_intraday_eval": "review_alerts_intraday",
}


# Static metadata — TTLs match the values used in the live services.
_CACHE_DESCRIPTORS: list[dict[str, Any]] = [
    {"id": "kite_holdings", "name": "Kite holdings (per user)", "key_prefix": "kite_holdings:", "ttl_seconds": 7200},
    {"id": "kite_quote", "name": "Kite quotes", "key_prefix": "kite_quote:", "ttl_seconds": 60},
    {"id": "kite_historical", "name": "Kite historical bars", "key_prefix": "kite_historical:", "ttl_seconds": 3600},
    {"id": "rss_inbox", "name": "News inbox (Hindu BL + others)", "key_prefix": "rss:inbox_all", "ttl_seconds": 7200},
    {"id": "rss_hindu_bl", "name": "Hindu BL feed aggregator", "key_prefix": "rss:hindu_bl_all", "ttl_seconds": 7200},
    {"id": "rss_market", "name": "Market news (Moneycontrol + ET + Google)", "key_prefix": "rss:market_news", "ttl_seconds": 7200},
]


def _ist_describe(cron_str: str) -> str:
    """Tiny human-readable converter for the beat schedule strings the UI shows."""
    return cron_str  # placeholder; the frontend renders the full crontab


# celery.schedules.crontab stores each field as a populated set of ints
# (e.g. c.day_of_month = {1, 2, ..., 31} when unrestricted). The naive
# str() rendering leaked those sets straight into the UI. The helpers
# below collapse the sets back into proper cron syntax: full range → "*",
# contiguous range → "a-b", otherwise comma-separated.
_FIELD_RANGES = {
    "minute": range(0, 60),
    "hour": range(0, 24),
    "day_of_month": range(1, 32),
    "month_of_year": range(1, 13),
    "day_of_week": range(0, 7),
}


def _field_to_cron(field: str, val) -> str:
    full = set(_FIELD_RANGES[field])
    if val is None:
        return "*"
    if isinstance(val, (set, frozenset, list, tuple)):
        s = {int(v) for v in val}
    else:
        # crontab._expand returns sets but be defensive
        try:
            s = {int(val)}
        except (TypeError, ValueError):
            return str(val)
    if not s or s == full:
        return "*"
    if len(s) == 1:
        return str(next(iter(s)))
    ordered = sorted(s)
    # Detect contiguous range (a, a+1, ..., b).
    if ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"{ordered[0]}-{ordered[-1]}"
    return ",".join(str(v) for v in ordered)


def _cron_to_str(c) -> str:
    return " ".join(
        _field_to_cron(field, getattr(c, field, None))
        for field in ("minute", "hour", "day_of_month", "month_of_year", "day_of_week")
    )


_DOW_LABELS = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}


def _humanize_cron(c) -> str:
    """Compact human-readable form, e.g. "08:15 · Mon-Fri" or "every 5m · 09-15 · Mon-Fri".

    Best-effort — falls back to the raw cron string when the expression
    doesn't map cleanly to a friendly phrase.
    """
    try:
        minute = sorted(getattr(c, "minute", set()) or set())
        hour = sorted(getattr(c, "hour", set()) or set())
        dom = getattr(c, "day_of_month", None) or set()
        moy = getattr(c, "month_of_year", None) or set()
        dow = sorted(getattr(c, "day_of_week", set()) or set())

        dom_full = dom == set(_FIELD_RANGES["day_of_month"])
        moy_full = moy == set(_FIELD_RANGES["month_of_year"])

        # Time component: prefer HH:MM when both are single values; otherwise
        # describe each axis.
        if len(minute) == 1 and len(hour) == 1:
            time_part = f"{hour[0]:02d}:{minute[0]:02d}"
        elif len(minute) == 1 and len(hour) >= 2:
            time_part = f"{minute[0]:02d}m past {hour[0]:02d}-{hour[-1]:02d}"
        elif len(minute) >= 2 and len(hour) == 1:
            # every-N-minutes pattern inside one hour: rare; fall back
            time_part = f"{hour[0]:02d}:{minute[0]:02d}/{minute[-1]:02d}"
        elif minute == list(range(0, 60, max(1, minute[1] - minute[0] if len(minute) > 1 else 1))) and hour:
            step = minute[1] - minute[0] if len(minute) > 1 else 1
            hpart = f"{hour[0]:02d}-{hour[-1]:02d}" if len(hour) > 1 else f"{hour[0]:02d}"
            time_part = f"every {step}m · {hpart}"
        else:
            return _cron_to_str(c)

        # Day-of-week / day-of-month component.
        if dow and dow != list(_FIELD_RANGES["day_of_week"]):
            if dow == list(range(dow[0], dow[-1] + 1)):
                dow_part = f"{_DOW_LABELS[dow[0]]}-{_DOW_LABELS[dow[-1]]}"
            else:
                dow_part = ",".join(_DOW_LABELS[d] for d in dow)
        elif not dom_full:
            dom_sorted = sorted(int(v) for v in dom)
            if len(dom_sorted) == 1:
                dow_part = f"day {dom_sorted[0]}"
            elif dom_sorted == list(range(dom_sorted[0], dom_sorted[-1] + 1)):
                dow_part = f"day {dom_sorted[0]}-{dom_sorted[-1]}"
            else:
                dow_part = "day " + ",".join(str(v) for v in dom_sorted)
        else:
            dow_part = "daily"

        suffix = ""
        if not moy_full:
            moy_sorted = sorted(int(v) for v in moy)
            suffix = " · months " + ",".join(str(v) for v in moy_sorted)

        return f"{time_part} · {dow_part}{suffix}"
    except Exception:
        return _cron_to_str(c)


def _next_fire(cron_obj) -> str | None:
    """Use croniter (already a celery transitive dep) to compute next fire time."""
    try:
        from croniter import croniter
        cron_str = _cron_to_str(cron_obj)
        # croniter accepts standard 5-field strings; celery's crontab is the
        # same field set in the same order, so the string round-trips.
        it = croniter(cron_str, datetime.now(tz=ZoneInfo("Asia/Kolkata")))
        return it.get_next(datetime).isoformat()
    except Exception:
        return None


@router.get("/cache-status")
async def cache_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # ── AI signals ────────────────────────────────────────────────────
    # Latest news_sentiment timestamp (across all symbols).
    news_latest = (await db.execute(
        select(func.max(NewsSentimentCache.analyzed_at))
    )).scalar()
    # Latest InvestmentDecision the user has run.
    verdict_latest = (await db.execute(
        select(func.max(InvestmentDecision.created_at))
        .where(InvestmentDecision.user_id == user.id)
    )).scalar()
    # Latest metric_run for this user.
    metric_latest = (await db.execute(
        select(func.max(MetricRun.finished_at))
        .where(MetricRun.user_id == user.id, MetricRun.status.in_(("ok", "partial")))
    )).scalar()

    ai_signals = [
        {
            "id": "news_sentiment", "name": "News Sentiment",
            "refresh_policy": "manual",
            "ttl_seconds": 4 * 60 * 60,
            "last_run_at": news_latest.isoformat() if news_latest else None,
            "scope": "per_symbol",
        },
        {
            "id": "fundamental_analysis", "name": "Fundamental Analysis",
            "refresh_policy": "manual",
            "ttl_seconds": None,
            "last_run_at": metric_latest.isoformat() if metric_latest else None,
            "scope": "stock | watchlist | portfolio",
        },
        {
            "id": "investment_verdict", "name": "Investment Verdict",
            "refresh_policy": "manual",
            "ttl_seconds": None,
            "last_run_at": verdict_latest.isoformat() if verdict_latest else None,
            "stale_after_days": 7,
            "scope": "per_symbol",
        },
    ]

    # ── Data caches ───────────────────────────────────────────────────
    data_caches = []
    for d in _CACHE_DESCRIPTORS:
        latest = (await db.execute(
            select(func.max(FetchCache.fetched_at))
            .where(FetchCache.cache_key.like(f"{d['key_prefix']}%"))
        )).scalar()
        data_caches.append({
            "id": d["id"],
            "name": d["name"],
            "ttl_seconds": d["ttl_seconds"],
            "last_fetched_at": latest.isoformat() if latest else None,
        })

    # ── Last ingestion run per source ────────────────────────────────
    source_to_run: dict[str, Any] = {}
    try:
        from app.models.smart_money import IngestionRun

        max_ids_q = (
            select(func.max(IngestionRun.id))
            .group_by(IngestionRun.source)
        )
        max_ids = [row[0] for row in (await db.execute(max_ids_q)).all()]
        if max_ids:
            runs = (await db.execute(
                select(IngestionRun).where(IngestionRun.id.in_(max_ids))
            )).scalars().all()
            source_to_run = {r.source: r for r in runs}
    except Exception:
        logger.exception("cache-status: ingestion_runs query failed")

    # ── Beat jobs ─────────────────────────────────────────────────────
    beat_jobs: list[dict[str, Any]] = []
    try:
        from app.tasks.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule or {}
        for name, spec in schedule.items():
            cron_obj = spec.get("schedule")
            task = spec.get("task")
            source = _TASK_TO_SOURCE.get(task)
            run = source_to_run.get(source) if source else None
            last_run = None
            if run:
                last_run = {
                    "status": run.status,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "duration_ms": run.duration_ms,
                }
            beat_jobs.append({
                "id": name,
                "task": task,
                "schedule_str": _cron_to_str(cron_obj) if cron_obj else None,
                "schedule_human": _humanize_cron(cron_obj) if cron_obj else None,
                "next_run_at": _next_fire(cron_obj) if cron_obj else None,
                "last_run": last_run,
            })
    except Exception:
        logger.exception("cache-status: beat schedule introspection failed")

    # Disk / DB usage — best-effort, never fails the response.
    disk: dict = {}
    try:
        import shutil
        usage = shutil.disk_usage("/")
        disk["root_total_gb"] = round(usage.total / 1e9, 1)
        disk["root_used_gb"] = round(usage.used / 1e9, 1)
        disk["root_pct"] = round(usage.used / usage.total * 100, 1)
    except Exception:
        pass
    try:
        db_size = (await db.execute(
            text("SELECT pg_size_pretty(pg_database_size(current_database())), pg_database_size(current_database())")
        )).first()
        if db_size:
            disk["db_size_pretty"] = db_size[0]
            disk["db_size_bytes"] = int(db_size[1])
    except Exception:
        pass

    return {
        "ai_signals": ai_signals,
        "data_caches": data_caches,
        "beat_jobs": beat_jobs,
        "disk": disk,
        "as_of": datetime.now(tz=timezone.utc).isoformat(),
    }


@router.get("/activity")
async def system_activity(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Live + recent activity for the admin monitor. Aggregates:
    - active/queued Celery tasks (best-effort via inspect)
    - recent ingestion_runs (last 24h)
    - LLM call summary by purpose + by credential (last 24h)
    - Scrape summary by source (last 24h)
    """
    from app.models.smart_money import IngestionRun

    # ── Celery inspect (live tasks). May 500 if broker is down; swallow. ─
    active_tasks: list[dict] = []
    queued_tasks: list[dict] = []
    try:
        from app.tasks.celery_app import celery_app
        i = celery_app.control.inspect(timeout=1.0)
        active_raw = (i.active() or {}) if i else {}
        for _worker, tasks in active_raw.items():
            for t in tasks:
                active_tasks.append({
                    "name": t.get("name"),
                    "id": t.get("id"),
                    "args": t.get("args"),
                    "time_start": t.get("time_start"),
                })
        reserved_raw = (i.reserved() or {}) if i else {}
        for _worker, tasks in reserved_raw.items():
            for t in tasks:
                queued_tasks.append({"name": t.get("name"), "id": t.get("id")})
    except Exception as e:
        logger.debug("celery inspect failed: %s", e)

    # ── Recent ingestion_runs (last 24h) ────────────────────────────
    since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    recent_ingest: list[dict] = []
    try:
        rows = (await db.execute(
            select(IngestionRun)
            .where(IngestionRun.started_at > since)
            .order_by(desc(IngestionRun.started_at))
            .limit(50)
        )).scalars().all()
        for r in rows:
            recent_ingest.append({
                "source": r.source,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "duration_ms": r.duration_ms,
                "records_fetched": r.records_fetched,
                "records_inserted": r.records_inserted,
            })
    except Exception as e:
        logger.debug("ingestion_runs query failed: %s", e)

    # ── LLM summary (last 24h) ──────────────────────────────────────
    llm_summary: dict[str, Any] = {
        "by_purpose": {},
        "by_credential": {},
        "total_calls": 0,
        "total_cost_usd": 0.0,
        "fail_rate": 0.0,
    }
    try:
        from sqlalchemy import text as _t
        rows = (await db.execute(_t(
            "SELECT purpose, COUNT(*) AS cnt, COALESCE(SUM(cost_usd),0) AS cost, "
            "  COALESCE(AVG(latency_ms),0) AS avg_ms, "
            "  SUM(CASE WHEN success THEN 0 ELSE 1 END) AS fails "
            "FROM llm_calls WHERE ts > NOW() - INTERVAL '24 hours' "
            "GROUP BY purpose ORDER BY cnt DESC"
        ))).all()
        total_calls = 0
        total_cost = 0.0
        total_fails = 0
        for r in rows:
            purpose = r[0] or "unknown"
            cnt = int(r[1])
            cost = float(r[2] or 0)
            avg_ms = int(r[3] or 0)
            fails = int(r[4] or 0)
            llm_summary["by_purpose"][purpose] = {
                "count": cnt, "cost_usd": round(cost, 4),
                "avg_ms": avg_ms, "fail_count": fails,
            }
            total_calls += cnt
            total_cost += cost
            total_fails += fails
        llm_summary["total_calls"] = total_calls
        llm_summary["total_cost_usd"] = round(total_cost, 4)
        llm_summary["fail_rate"] = (
            round(total_fails / total_calls, 3) if total_calls else 0.0
        )

        cred_rows = (await db.execute(_t(
            "SELECT credential_id, COUNT(*) AS cnt, "
            "  SUM(CASE WHEN success THEN 0 ELSE 1 END) AS fails "
            "FROM llm_calls WHERE ts > NOW() - INTERVAL '24 hours' "
            "GROUP BY credential_id ORDER BY cnt DESC"
        ))).all()
        for r in cred_rows:
            cid = str(r[0]) if r[0] is not None else "null"
            cnt = int(r[1])
            fails = int(r[2] or 0)
            llm_summary["by_credential"][cid] = {
                "count": cnt,
                "fail_rate": round(fails / cnt, 3) if cnt else 0.0,
            }
    except Exception as e:
        logger.debug("llm_calls summary failed: %s", e)

    # ── Scrape summary (last 24h) ───────────────────────────────────
    scrape_summary: dict[str, Any] = {
        "by_source": {},
        "total_fetches": 0,
        "fail_rate": 0.0,
    }
    try:
        from sqlalchemy import text as _t
        rows = (await db.execute(_t(
            "SELECT source, COUNT(*) AS cnt, "
            "  COALESCE(AVG(latency_ms),0) AS avg_ms, "
            "  SUM(CASE WHEN success THEN 0 ELSE 1 END) AS fails "
            "FROM scrape_events WHERE ts > NOW() - INTERVAL '24 hours' "
            "GROUP BY source ORDER BY cnt DESC"
        ))).all()
        total_fetches = 0
        total_fails = 0
        for r in rows:
            source = r[0] or "unknown"
            cnt = int(r[1])
            avg_ms = int(r[2] or 0)
            fails = int(r[3] or 0)
            scrape_summary["by_source"][source] = {
                "count": cnt,
                "avg_ms": avg_ms,
                "fail_rate": round(fails / cnt, 3) if cnt else 0.0,
            }
            total_fetches += cnt
            total_fails += fails
        scrape_summary["total_fetches"] = total_fetches
        scrape_summary["fail_rate"] = (
            round(total_fails / total_fetches, 3) if total_fetches else 0.0
        )
    except Exception as e:
        logger.debug("scrape_events summary failed: %s", e)

    return {
        "active_celery": active_tasks,
        "queued_celery": queued_tasks,
        "recent_ingestion_runs": recent_ingest,
        "llm_summary_24h": llm_summary,
        "scrape_summary_24h": scrape_summary,
        "as_of": datetime.now(tz=timezone.utc).isoformat(),
    }


@router.get("/data-sources")
async def data_sources(
    user: User = Depends(get_current_user),
) -> dict:
    """Static inventory of all scraping / data-ingestion services and the
    fundamentals fallback chain. Used by the Settings → Data & Caching tab."""
    return {
        "scraping_services": _SCRAPING_SERVICES,
        "fundamentals_fallback": _FUNDAMENTALS_FALLBACK,
    }


_SCRAPING_SERVICES: list[dict[str, Any]] = [
    # ── Market data ──────────────────────────────────────────────────
    {
        "id": "kite_holdings",
        "name": "Kite Holdings",
        "category": "Market Data",
        "source": "Zerodha Kite Connect API",
        "url": "kite.zerodha.com",
        "writes_to": "portfolio_cache (FetchCache)",
        "ttl": "2 hours",
        "schedule": "On demand (dashboard refresh)",
        "status": "active",
    },
    {
        "id": "kite_quotes",
        "name": "Kite Quotes",
        "category": "Market Data",
        "source": "Zerodha Kite Connect API",
        "url": "kite.zerodha.com",
        "writes_to": "portfolio_cache (FetchCache)",
        "ttl": "60 seconds",
        "schedule": "On demand (stock detail / watchlist)",
        "status": "active",
    },
    {
        "id": "kite_historical",
        "name": "Kite Historical Bars",
        "category": "Market Data",
        "source": "Zerodha Kite Connect API",
        "url": "kite.zerodha.com",
        "writes_to": "portfolio_cache (FetchCache)",
        "ttl": "1h intraday / 24h daily",
        "schedule": "On demand",
        "status": "active",
    },
    {
        "id": "market_indices",
        "name": "Market Indices",
        "category": "Market Data",
        "source": "Kite batch quote + Moneycontrol (Gift Nifty fallback)",
        "url": "kite.zerodha.com / moneycontrol.com",
        "writes_to": "index_quote_cache",
        "ttl": "~5 min",
        "schedule": "Mon–Fri 09:00–15:00, every 5 min",
        "status": "active",
    },
    # ── Fundamentals ─────────────────────────────────────────────────
    {
        "id": "screener_in",
        "name": "Screener.in",
        "category": "Fundamentals",
        "source": "Screener.in company page scrape",
        "url": "screener.in",
        "writes_to": "stock_fundamentals + metric_snapshots",
        "ttl": "24 hours",
        "schedule": "On demand / daily analysis",
        "status": "active",
    },
    {
        "id": "yfinance",
        "name": "yfinance (Yahoo Finance)",
        "category": "Fundamentals",
        "source": "Yahoo Finance API via yfinance library",
        "url": "finance.yahoo.com",
        "writes_to": "stock_fundamentals + metric_snapshots",
        "ttl": "24 hours (FRESHNESS_HOURS)",
        "schedule": "On demand / daily analysis",
        "status": "active",
    },
    {
        "id": "google_finance",
        "name": "Google Finance",
        "category": "Fundamentals",
        "source": "Google Finance page scrape",
        "url": "google.com/finance",
        "writes_to": "In-memory LRU (4096 keys, 60s TTL)",
        "ttl": "60 seconds",
        "schedule": "On demand (stock detail popup)",
        "status": "active",
    },
    {
        "id": "kite_returns",
        "name": "Kite Historical Returns",
        "category": "Fundamentals",
        "source": "Kite Connect historical candles",
        "url": "kite.zerodha.com",
        "writes_to": "metric_snapshots",
        "ttl": "Per refresh cycle",
        "schedule": "On demand / daily analysis",
        "status": "active",
    },
    {
        "id": "nse_ownership",
        "name": "NSE Shareholding (XBRL)",
        "category": "Fundamentals",
        "source": "NSE quarterly XBRL filings (DB read)",
        "url": "nseindia.com",
        "writes_to": "metric_snapshots",
        "ttl": "Quarterly",
        "schedule": "On demand / daily analysis",
        "status": "active",
    },
    {
        "id": "gemini_ai",
        "name": "Gemini AI Gap-Fill",
        "category": "Fundamentals",
        "source": "Gemini + Google Search grounding",
        "url": "Vertex AI / Generative Language API",
        "writes_to": "stock_fundamentals + metric_snapshots",
        "ttl": "Per refresh cycle",
        "schedule": "On demand (last resort gap-fill)",
        "status": "active",
    },
    # ── News ─────────────────────────────────────────────────────────
    {
        "id": "hindu_bl",
        "name": "Hindu Business Line",
        "category": "News",
        "source": "RSS feeds (7 feeds: Markets, Stock Markets, Companies, Portfolio, Fundamentals, Economy, Banking)",
        "url": "thehindubusinessline.com",
        "writes_to": "daily_news_reports (via morning pipeline)",
        "ttl": "2 hours",
        "schedule": "Mon–Fri 11:00 IST (morning pipeline step 1)",
        "status": "active",
    },
    {
        "id": "moneycontrol_rss",
        "name": "Moneycontrol",
        "category": "News",
        "source": "RSS feeds (Markets, Top News, Buzzing Stocks)",
        "url": "moneycontrol.com",
        "writes_to": "news_inbox",
        "ttl": "2 hours",
        "schedule": "On demand / market pulse",
        "status": "active",
    },
    {
        "id": "et_rss",
        "name": "Economic Times",
        "category": "News",
        "source": "RSS feeds (ET Markets, ET Stocks)",
        "url": "economictimes.indiatimes.com",
        "writes_to": "news_inbox",
        "ttl": "2 hours",
        "schedule": "On demand / market pulse",
        "status": "active",
    },
    {
        "id": "mint_rss",
        "name": "Mint",
        "category": "News",
        "source": "RSS feeds (Markets, Companies)",
        "url": "livemint.com",
        "writes_to": "news_inbox",
        "ttl": "2 hours",
        "schedule": "On demand / market pulse",
        "status": "active",
    },
    {
        "id": "reuters_rss",
        "name": "Reuters India",
        "category": "News",
        "source": "RSS feeds (Business, Markets)",
        "url": "reuters.com",
        "writes_to": "news_inbox",
        "ttl": "2 hours",
        "schedule": "On demand / market pulse",
        "status": "active",
    },
    {
        "id": "pib_rss",
        "name": "Press Information Bureau",
        "category": "News",
        "source": "RSS feed (Government press releases)",
        "url": "pib.gov.in",
        "writes_to": "news_inbox",
        "ttl": "2 hours",
        "schedule": "On demand / market pulse",
        "status": "active",
    },
    {
        "id": "google_news",
        "name": "Google News RSS",
        "category": "News",
        "source": "Google News RSS search (per-symbol + market-wide)",
        "url": "news.google.com",
        "writes_to": "news_sentiment_cache",
        "ttl": "2 hours",
        "schedule": "On demand (per-symbol sentiment)",
        "status": "active",
    },
    {
        "id": "bse_filings",
        "name": "BSE Filings",
        "category": "News",
        "source": "BSE India API (corporate filings)",
        "url": "api.bseindia.com",
        "writes_to": "news_inbox",
        "ttl": "2 hours",
        "schedule": "On demand",
        "status": "active",
    },
    # ── Smart Money ──────────────────────────────────────────────────
    {
        "id": "nse_insider",
        "name": "NSE Insider Disclosures",
        "category": "Smart Money",
        "source": "NSE PIT Regulation 7 / SAST filings",
        "url": "nseindia.com/api/corporates-pit",
        "writes_to": "insider_disclosures",
        "ttl": "—",
        "schedule": "Mon–Fri 17:30 IST",
        "status": "active",
    },
    {
        "id": "nse_bulk_block",
        "name": "NSE Bulk & Block Deals",
        "category": "Smart Money",
        "source": "NSE daily CSV archives",
        "url": "nsearchives.nseindia.com",
        "writes_to": "bulk_block_deals",
        "ttl": "—",
        "schedule": "Mon–Fri 18:30 IST",
        "status": "active",
    },
    {
        "id": "bse_deals",
        "name": "BSE Bulk & Block Deals",
        "category": "Smart Money",
        "source": "BSE India API",
        "url": "api.bseindia.com",
        "writes_to": "bulk_block_deals",
        "ttl": "—",
        "schedule": "Mon–Fri 18:45 IST",
        "status": "active",
    },
    {
        "id": "nse_corporate_ann",
        "name": "Corporate Announcements",
        "category": "Smart Money",
        "source": "NSE corporate announcements API (buyback, pledge)",
        "url": "nseindia.com/api/corporate-announcements",
        "writes_to": "corporate_announcements",
        "ttl": "—",
        "schedule": "Mon–Fri 17:00 IST",
        "status": "active",
    },
    {
        "id": "nse_bhavcopy",
        "name": "NSE Bhavcopy",
        "category": "Smart Money",
        "source": "NSE daily bhavcopy CSV (OHLC + delivery %)",
        "url": "nsearchives.nseindia.com",
        "writes_to": "bhavcopy_daily",
        "ttl": "—",
        "schedule": "Mon–Fri 18:00 IST",
        "status": "active",
    },
    {
        "id": "shareholding_pattern",
        "name": "Shareholding Pattern",
        "category": "Smart Money",
        "source": "NSE XBRL filings (BSE API fallback)",
        "url": "nseindia.com + api.bseindia.com",
        "writes_to": "shareholding_patterns",
        "ttl": "—",
        "schedule": "25th of month 10:00 IST",
        "status": "active",
    },
    {
        "id": "fii_dii",
        "name": "FII/DII Daily Flows",
        "category": "Smart Money",
        "source": "NSE FII/DII trade data (market-wide aggregate)",
        "url": "nseindia.com/api/fiidiiTradeReact",
        "writes_to": "fii_dii_daily",
        "ttl": "—",
        "schedule": "Mon–Fri 18:15 IST",
        "status": "active",
    },
    {
        "id": "amfi_nav",
        "name": "AMFI NAV & Schemes",
        "category": "Smart Money",
        "source": "AMFI India NAV text file (pipe-delimited)",
        "url": "amfiindia.com/spages/NAVAll.txt",
        "writes_to": "mf_schemes",
        "ttl": "—",
        "schedule": "Daily 18:00 IST",
        "status": "active",
    },
    {
        "id": "amfi_mf_monthly",
        "name": "AMFI MF Monthly Portfolios",
        "category": "Smart Money",
        "source": "AMC monthly portfolio XLS files",
        "url": "amfiindia.com",
        "writes_to": "mf_holding_monthly",
        "ttl": "—",
        "schedule": "12th of month 10:00 IST",
        "status": "stub",
    },
    {
        "id": "sebi_pms",
        "name": "SEBI PMS Quarterly",
        "category": "Smart Money",
        "source": "SEBI PMS quarterly disclosure PDFs",
        "url": "sebi.gov.in",
        "writes_to": "—",
        "ttl": "—",
        "schedule": "15th Jan/Apr/Jul/Oct 10:30 IST",
        "status": "stub",
    },
    {
        "id": "sebi_aif",
        "name": "SEBI AIF Quarterly",
        "category": "Smart Money",
        "source": "SEBI AIF quarterly disclosure PDFs",
        "url": "sebi.gov.in",
        "writes_to": "—",
        "ttl": "—",
        "schedule": "15th Jan/Apr/Jul/Oct 11:00 IST",
        "status": "stub",
    },
    # ── Scoring ──────────────────────────────────────────────────────
    {
        "id": "smart_money_rollup",
        "name": "Smart Money Rollup",
        "category": "Scoring",
        "source": "Internal aggregation (conviction + flow + red-flag)",
        "url": "—",
        "writes_to": "smart_money_signals",
        "ttl": "—",
        "schedule": "Mon–Fri 19:00 IST",
        "status": "active",
    },
    {
        "id": "market_pulse",
        "name": "Market Pulse",
        "category": "Scoring",
        "source": "Indices + news + Gemini analysis",
        "url": "—",
        "writes_to": "market_pulse",
        "ttl": "30 min",
        "schedule": "On demand",
        "status": "active",
    },
]


_FUNDAMENTALS_FALLBACK: list[dict[str, Any]] = [
    {
        "order": 1,
        "source": "screener_in",
        "label": "Screener.in",
        "description": "Primary source for Indian stock fundamentals. Extracts 22 metrics from financial statements, ratios, cash flow, and shareholding sections.",
        "fields": ["pe_ratio", "roe", "roce", "debt_to_equity", "revenue_growth_1y", "eps_growth_1y",
                   "net_profit_margin", "ebitda_margin", "dividend_yield", "market_cap",
                   "promoter_holding", "fii_holding", "dii_holding", "operating_cash_flow",
                   "free_cash_flow", "cash_flow_margin", "return_on_assets", "eps_growth_5y",
                   "promoter_holding_change_3m", "fii_holding_change_3m", "shareholding_history"],
        "reliability": "high",
        "notes": "Consolidated page first, standalone fallback. Cached 24h. Handles bank P&L format (Revenue vs Sales).",
    },
    {
        "order": 2,
        "source": "yfinance",
        "label": "Yahoo Finance (yfinance)",
        "description": "Fills gaps Screener misses: forward P/E, P/B, EV/EBITDA, P/S, earnings yield, current/quick ratio, interest coverage.",
        "fields": ["forward_pe", "pb_ratio", "ev_ebitda", "ps_ratio", "earning_power",
                   "earnings_growth_forward", "ebitda_margin", "return_on_assets",
                   "current_ratio", "quick_ratio", "interest_coverage"],
        "reliability": "medium",
        "notes": "Known issues with Indian stocks: dividend_yield can be 100x wrong, OCF can be negative when positive. Only fills fields still null after Screener.",
    },
    {
        "order": 3,
        "source": "google_finance",
        "label": "Google Finance",
        "description": "Public page scrape for price-related metrics: 52-week range, P/E, EPS, market cap. Cross-validates Screener data.",
        "fields": ["pe_ratio", "high_52w", "low_52w", "eps", "market_cap",
                   "dividend_yield", "last_price", "pct_from_52w_high"],
        "reliability": "medium",
        "notes": "60s in-memory LRU cache. 15-17 fields per stock. Also provides live price for pct_from_52w_high computation.",
    },
    {
        "order": 4,
        "source": "kite_returns",
        "label": "Kite Historical Returns",
        "description": "Trading metrics from Kite historical price candles.",
        "fields": ["ret_1m", "ret_1y", "pct_from_52w_high"],
        "reliability": "high",
        "notes": "Requires active Kite connection. Falls back gracefully if token expired.",
    },
    {
        "order": 5,
        "source": "nse_ownership",
        "label": "NSE Shareholding Pattern (XBRL)",
        "description": "Authoritative quarterly filing data. Provides MF holding and pledge % that Screener doesn't split out.",
        "fields": ["promoter_holding", "fii_holding", "dii_holding", "mf_holding",
                   "pledged_promoter_holding", "promoter_holding_change_3m",
                   "fii_holding_change_3m", "shareholding_history"],
        "reliability": "high",
        "notes": "Only 134 symbols covered by XBRL scraper. For uncovered stocks, Screener provides ownership data.",
    },
    {
        "order": 6,
        "source": "gemini_ai",
        "label": "Gemini AI (web-search grounded)",
        "description": "Last resort for metrics still null. Uses Google Search grounding to look up current data from the web.",
        "fields": ["return_on_assets", "eps_growth_5y", "free_cash_flow",
                   "interest_coverage", "current_ratio", "quick_ratio"],
        "reliability": "low",
        "notes": "Only targets metrics fillable by web search. Capped at 1 call per symbol per refresh. Uses credential rotation.",
    },
    {
        "order": 7,
        "source": "manual_overrides",
        "label": "Manual Overrides",
        "description": "User-configured values via the pencil icon. Always take priority over all other sources.",
        "fields": ["any metric"],
        "reliability": "user-defined",
        "notes": "Set via metric_engine manual_source. Overrides persist until removed.",
    },
]
