# stock-tracker

Personal algorithmic trading platform for Indian markets, built on Zerodha Kite Connect with AI-assisted research and a three-stream **smart-money** signal subsystem (conviction / flow / red-flag) that scores both new candidates (discovery) and existing holdings.

> 📊 **[Interactive walkthrough — how the system works](docs/how-it-works.html)** (open in a browser, or serve via GitHub Pages)

Two-tier AI architecture: **Gemini 2.5 Flash-Lite** for the daily bulk screen (cheap, high-volume), and a **provider-agnostic deep-analysis layer** (`app/ai/registry.py`) that routes to whatever the user has configured — Gemini Vertex by default, with Anthropic and OpenAI provider classes scaffolded for future activation. Daily morning brief at 8:30 AM IST. Single-admin in default config — schema is ready for invite-only multi-user (see *Multi-user* below).

## Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python 3.12), SQLAlchemy 2.0 async, Alembic |
| Frontend | Next.js 16 (App Router, Turbopack), React 19, TypeScript, Tailwind v4 |
| Database | TimescaleDB (Postgres 16 + hypertables) |
| Cache / broker | Redis 7 |
| Jobs | Celery worker + beat, Flower (opt-in via `--profile monitoring`) |
| Broker | Zerodha Kite Connect |
| AI | Gemini 2.5 Flash-Lite (screening); pluggable deep-analysis provider via `app/ai/registry.py` (Gemini Vertex live; Anthropic + OpenAI scaffolded) |
| Observability | structlog JSON logs, slowapi rate limit, Prometheus `/metrics`, deep `/health` |
| Encryption | Fernet field-level encryption for Kite / Gemini / Anthropic / OpenAI creds at rest |
| Orchestration | Docker Compose (dev + separate prod compose; Celery containers run with `CELERY_NULL_POOL=1` to keep async DB sessions safe across event loops) |

## Quick start

Prereqs: Docker Desktop, a Zerodha Kite Connect app, a Gemini API key (or a Vertex service-account JSON at `backend/service_account.json`). Anthropic / OpenAI keys are optional — only needed if you switch the deep-analysis provider in Settings.

```bash
# 1. clone and enter
git clone https://github.com/namanguptaiitkgp/stock-tracker.git
cd algo-trader

# 2. env
cp .env.example .env
# edit .env — set APP_SECRET_KEY, FIELD_ENCRYPTION_KEY (see below),
# KITE_API_KEY/SECRET, GEMINI_API_KEY, ANTHROPIC_API_KEY

# Generate a Fernet key for at-rest credential encryption:
docker run --rm python:3.12-slim sh -c \
  'pip install -q cryptography && python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'

# 3. up
make dev                          # build + run everything attached
# or: make up && make logs        # detached + follow logs

# 4. migrate (first run only)
make migrate
```

In dev mode the frontend container runs `next dev` against the mounted `./frontend/src`, so saves hot-reload at http://localhost:3000 without a rebuild.

Services once up:

| URL | What |
|---|---|
| http://localhost:3000 | Frontend |
| http://localhost:8000 | Backend API (FastAPI) |
| http://localhost:8000/docs | OpenAPI / Swagger |
| http://localhost:8000/api/health | Deep health (DB + Redis + Celery) |
| http://localhost:8000/api/health/live | Cheap liveness probe |
| http://localhost:5555 | Flower — only with `--profile monitoring` |
| localhost:5432 | Postgres (user `algotrader`) |
| localhost:6379 | Redis |

Flower is gated behind a profile so a default `docker compose up` doesn't expose 5555. Bring it up explicitly:

```bash
docker compose --profile monitoring up -d flower
```

## First-time login

The default config is single-admin. On first boot `GET /api/user/setup-status` returns `{"is_setup": false}` — the frontend redirects to a **Register** screen. Pick a username and a password (≥6 chars). The first user is automatically promoted to `is_admin = true`.

After logging in, open **Settings** to:
1. Paste your Kite API key + secret → click **Connect Kite** to complete the OAuth handshake.
2. Paste your Gemini key (or drop a Vertex service-account JSON in the backend); add Anthropic / OpenAI keys later if you want to switch the deep-analysis provider.
3. Tune risk limits (position size, daily loss, drawdown, order cap, kill switch).
4. Record purchase date + thesis for each Kite holding under **Settings → Holdings** — this drives the per-holding smart-money signal.
5. Optionally load the **Indian Market Screener** preset under **Settings → AI Analysis → Fundamental analysis rules** to apply the 8 hard-filter / 12 soft-filter universe definition from `indian_stock_screener_criteria.md`.

All credentials are stored Fernet-encrypted in `users` (column type `EncryptedStr`, transparent on read/write). The session idle timeout is 15 minutes.

## Multi-user (invite-only)

Schema for closed-beta multi-user is in place:

- `users.is_admin` Boolean — gates admin endpoints
- `invite_codes` table — `code`, `created_by_user_id`, `redeemed_by_user_id`, `expires_at`

The admin invite REST surface (`POST/GET/DELETE /api/admin/invites`) and the registration `invite_code` field are not wired yet. To unlock multi-user, build those endpoints, then drop the `count > 0` block in `api/user_auth.py:register` and require `invite_code` in the register body.

## Production deploy

A separate compose file ships the production-grade backend / frontend / worker / beat stack:

```bash
cp .env.example .env  # set production values; see "Required prod env" below
docker compose -f docker-compose.prod.yml up -d --build
```

Prod differences:
- Backend uses `docker/backend.prod.Dockerfile` (multi-worker uvicorn, non-root user, no reload, `--proxy-headers`, no server header).
- Frontend uses `docker/frontend.prod.Dockerfile` (multi-stage build, `npm start`).
- `restart: always` on every long-running service.
- Healthchecks on the backend hit `/api/health/live`.
- No source-code volume mounts — image is the source of truth.
- Flower is opt-in via `--profile monitoring` and requires `--basic_auth` (set `FLOWER_BASIC_AUTH=user:pass`).

### Required prod env

The backend will refuse to start with `APP_ENV=production` unless these are set to non-default values (validated in `app/config.py:validate_production_settings()`):

- `APP_SECRET_KEY` — JWT signing key, NOT `change-me`.
- `FIELD_ENCRYPTION_KEY` — Fernet key (generate via the snippet in *Quick start*).
- `KITE_REDIRECT_URL` — public origin, NOT localhost.
- `CORS_ORIGINS` — comma-separated explicit origins, no `*`.

Optional prod env:
- `METRICS_ALLOW_TOKEN` — set to enable `/metrics`. Requests must send `X-Metrics-Token: <value>`.
- `SENTRY_DSN` — Sentry DSN slot; SDK init is left for the consumer.
- `RATE_LIMIT_DEFAULT` (default `300/minute`), `RATE_LIMIT_AUTH` (default `10/minute`).
- `BACKEND_WORKERS` (default `4`), `WORKER_CONCURRENCY` (default `4`).

## Observability

- **Logs**: every line is JSON via `structlog`. `RequestContextMiddleware` tags each log with `request_id`, `user_id` (when authenticated), `path`, `status`, `latency_ms`. The `X-Request-ID` response header is echoed to clients for cross-system tracing.
- **Health**: `/api/health` deep-checks DB ping, Redis ping, Celery worker ping; returns 503 if any fail. `/api/health/live` is a cheap process-up probe.
- **Rate limit**: `slowapi` Limiter; default per-user/IP, tighter `10/min` on `/api/user/login` and `/api/user/register`. Returns 429 with `{detail, request_id}`.
- **Metrics**: Prometheus exposition at `/metrics`, gated by `METRICS_ALLOW_TOKEN` header.
- **Errors**: global `@app.exception_handler(Exception)` catches anything unhandled, logs the traceback structured, and returns `{"detail": "internal_error", "request_id": ...}`.

## Common commands

```bash
make dev             # build + up, attached
make up / make down  # detached start / stop
make logs            # tail all
make logs-backend    # tail backend only
make logs-celery     # tail worker + beat
make migrate         # alembic upgrade head
make migrate-create msg="your message"
make seed            # seed instrument master
make test            # pytest
make clean           # down -v (wipes volumes!)
```

## Repo layout

```
backend/                  FastAPI app
  app/
    api/                  route modules (one per domain) + health.py
    services/             Kite, news, fundamentals, smart-money, etc.
      portfolio_cache.py    cached holdings/quotes/historical (per-user)
      data_cache.py         unified DB-backed fetch cache (2h TTL)
      news/                 unified inbox news pipeline
    tasks/                Celery tasks (daily_analysis, morning_news, ...)
    strategies/           strategy implementations
    engine/               trading/risk engine
    models/               SQLAlchemy models (incl. invite_code, review_alert)
    ai/                   provider abstraction (provider.py, registry.py,
                          providers/{gemini_vertex,anthropic,openai}.py;
                          gemini_client.py is the internal SDK wrapper)
    security/             field-level Fernet encryption (EncryptedStr)
    observability/        structlog config + ratelimit Limiter
  alembic/                migrations
frontend/                 Next.js 16 (App Router)
  src/app/(app)/          authed shell: dashboard, watchlist, awaiting-correction,
                          smart-money (+ insider/deals/traders sub-pages,
                          analyzer), fno, strategies, orders, settings (+ tabs:
                          connections, appearance, trading-risk, ai-analysis,
                          holdings, data-caching, background-jobs, about), ...
  src/components/
    common/               feature components (NewsInbox, MarketPulse, ...)
    layout/               AppShell, ModeSidebar
    ui/                   shared primitives (ErrorState)
  src/lib/                api, format, today-brief, ...
docker/                   dev + prod Dockerfiles for backend & frontend
docker-compose.yml        dev compose
docker-compose.prod.yml   prod compose (multi-worker, restart:always)
scripts/                  SQL + utility scripts
docs/                     deeper docs — see docs/README.md
```

## Scheduled jobs (Celery beat, IST)

| Time | Task |
|---|---|
| 06:30 M–F | `morning_news.run_morning_news_scan_task` — news scrape + sentiment |
| 07:00 Mon | `instruments.sync_instruments_task` — Kite instrument master refresh |
| 08:30 M–F | `daily_analysis.run_daily_analysis` — Gemini screen → user's configured deep-analysis provider |
| 16:30 M–F | `watchlist_snapshots.snapshot_watchlist_valuations` — daily P/E·P/B·52w snapshot |
| every 5 min, 9–15 M–F | `market.indices.refresh_quotes` — index quotes |
| 17:00 M–F | `smart_money.corporate_ann.ingest_nse_daily` — buybacks / pledges |
| 17:30 M–F | `smart_money.insider.ingest_nse_daily` — PIT Reg 7 disclosures |
| 18:00 daily | `smart_money.amfi.sync_nav_and_schemes` |
| 18:00 M–F | `smart_money.bhavcopy.ingest_nse_daily` |
| 18:15 M–F | `smart_money.fii_dii_stock.ingest_nse_daily` — placeholder, upstream pending |
| 18:30 M–F | `smart_money.deals.ingest_nse_daily` — bulk + block deals (NSE) |
| 18:45 M–F | `smart_money.deals.ingest_bse_daily` — BSE bulk + block (endpoint pending) |
| 19:00 M–F | `smart_money.rollup.compute` — three-stream conviction / flow / red-flag |
| 12th of month | `smart_money.amfi_monthly.ingest` — MF portfolios (parser stubbed) |
| 20th of Jan/Apr/Jul/Oct | `smart_money.shareholding.ingest_bse_quarterly` |
| 15th of Jan/Apr/Jul/Oct | SEBI PMS + AIF quarterly ingest (PDF parser stubbed) |

Timezone is `Asia/Kolkata` (`CELERY_TIMEZONE`). The worker + beat containers run with `CELERY_NULL_POOL=1` so async DB sessions stay safe across the per-task event loops Celery's prefork model spins up — without it the smart-money rollup hits "Future attached to a different loop" errors and dark-fails.

## Caching strategy

The platform deduplicates external fetches at three levels:

1. **`fetch_cache` (DB-resident, 2h default TTL)** — survives restarts. RSS feeds, Tickertape pages, Hindu BL aggregator, Moneycontrol/ET market news, NSE option chain, holdings/quotes/historical via `portfolio_cache.py`. Key prefix is the source name (`rss:`, `kite_holdings:`, …) so per-source invalidation is one call.
2. **In-process LRU caches** — bounded `OrderedDict` (`_slug_cache` in `tickertape_fetcher.py`, `_name_cache` in `mf_activity.py`, `_cache` in `google_finance.py`). Caps protect against unbounded growth on long-running processes.
3. **Per-request memoization** in the frontend — `lib/today-brief.ts` dedups concurrent `/api/today/brief` calls between the dashboard page and `ModeSidebar`.

## Database migrations

Recent migrations (newest first):

- `a2c8d4f7b1e9_window_days_holdings_metadata` — `smart_money_signals.window_days` column with re-keyed unique index (multi-window architecture); `user_holdings_metadata` per-user table for purchase date + thesis.
- `e9f5a2b8d4c1_add_client_overrides` — per-user category overrides for the active-traders classifier.
- `f1c8b2e7d9a3_screener_hard_filter_and_metrics` — `fundamental_rules.is_hard_filter` + 7 new metric definitions (operating_cash_flow, free_cash_flow, cash_flow_margin, roce, earning_power, ret_1d, pe_premium_vs_sector).
- `d8f4c5b9a2e3_smart_money_data_quality_fixes` — `insider_disclosures.is_intra_group_transfer`, `bulk_block_deals.client_category`, `net_positions_30d.net_to_total_ratio`.
- `c7a3b8e1d5f9_smart_money_revamp_conviction_flow_redflags` — 5 new tables (insider_disclosures, shareholding_patterns, corporate_announcements, fii_dii_stock_daily, net_positions_30d), conviction/flow/red_flag/signal_breakdown columns on smart_money_signals, tier/entity_type on known_sharks.
- `b9e1f4d3c2a5_backfill_metric_snapshots` — fundamentals metric backfill.
- `a8c4d2e0a3f1_fundamental_analysis_schema` — fundamental rule sets + metric definitions.
- `e7c2a91d4f3b_phase5_admin_invites_alerts_index` — multi-user schema (invite_codes, is_admin).
- `d4f1a8b6c0e2_encrypt_kite_creds_and_dedup_indexes` — Fernet at-rest credential encryption.

All recent migrations are idempotent (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).

## Documentation

See [`docs/`](docs/README.md) for deeper notes:
- Architecture overview
- Authentication & Kite OAuth
- Daily analysis pipeline
- News sentiment (Google News + Hindu Business Line + Gemini)
- FII/DII and Mutual Fund activity
- Smart-money subsystem
- Risk engine
- Auto-push / GitHub workflow

## Costs

Target ≈ **Rs 1,000–1,200 / month**: Kite Connect (Rs 500), Gemini Vertex / Flash-Lite (negligible — both screening and the default deep-analysis path). Per-user spend is capped by `settings_json.ai_max_daily_budget_usd` (legacy `opus_max_daily_budget_usd` still read as a fallback for existing users; default $1/day). Switching the deep-analysis provider to Anthropic / OpenAI in Settings increases that cost — keys are user-supplied.

## License

Private / personal project. Not for distribution.
