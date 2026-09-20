# Architecture

## Services

Compose brings up six containers:

| Service | Image / build | Port | Role |
|---|---|---|---|
| `timescaledb` | `timescale/timescaledb:latest-pg16` | 5432 | Primary store (Postgres with hypertables for OHLCV) |
| `redis` | `redis:7-alpine` | 6379 | Celery broker, API cache |
| `backend` | `docker/backend.Dockerfile` | 8000 | FastAPI app (uvicorn, `--reload`) |
| `celery-worker` | same image | — | Runs tasks on queues `default,analysis,data`. `CELERY_NULL_POOL=1` is set so the async DB engine uses `NullPool` — required because each task spins a fresh asyncio loop and asyncpg connections cached in the engine pool can't cross loop boundaries. |
| `celery-beat` | same image | — | Scheduler for recurring jobs. Same `CELERY_NULL_POOL=1` setting. |
| `frontend` | `docker/frontend.Dockerfile` | 3000 | Next.js 16 dev server (App Router, Turbopack, React 19) |
| `flower` | same backend image | 5555 | Celery UI |

All share a default bridge network; services reference each other by service name (`timescaledb`, `redis`).

## Request flow

```
Browser → Next.js (3000) → fetch → FastAPI (8000) → SQLAlchemy → Postgres
                                           │
                                           ├→ Kite Connect REST (market data, orders)
                                           ├→ Gemini / Anthropic APIs
                                           └→ Redis (cache / celery.apply_async)
```

Long-running or scheduled work goes via Celery:

```
FastAPI route → celery.send_task → Redis queue → celery-worker → DB write
celery-beat (cron) ───────────────→ Redis queue → celery-worker → DB write
```

## Backend layout

```
backend/app/
  main.py                FastAPI entrypoint, CORS, router mount
  config.py              pydantic-settings, pulls from env
  dependencies.py        auth helpers (JWT), password hashing, get_current_user
  db/session.py          async engine + session factory
  api/
    router.py            aggregates every domain router
    user_auth.py         register/login/me
    auth.py              Kite OAuth: /login, /callback
    settings_api.py      user profile + API keys + risk limits
    watchlist.py         CRUD on watchlists
    stock_search.py      resolve symbol / ISIN / name
    market_data.py       OHLCV endpoints
    portfolio.py         positions, holdings, P&L
    orders.py            place/modify/cancel orders (guarded by risk engine)
    strategies.py        list/run/backtest strategies
    analysis.py          trigger AI analysis; read past results
    investment.py        investment decisions feed
    notes.py             free-form per-stock notes
    today.py             consolidated morning brief for the "Today" page
  services/
    kite_service.py      Kite Connect wrapper
    stock_resolver.py    symbol / ISIN normalization
    nifty50.py           index constituent helpers
    fundamentals_service.py   yfinance primary
    tickertape_fetcher.py     backup + gap fill
    news_scraper.py      Google News RSS + custom queries
    news_sentiment.py    Gemini classification (positive / negative / neutral)
    fii_dii.py           NSE FII/DII daily activity
    mf_activity.py       mfdata.in monthly MF buy/sell
    instrument_sync.py   weekly Kite instrument-master sync
    strategy_runner.py   executes a strategy for a user
    default_strategies.py seeds is_default=True strategies
    investment_decision.py Routes deep-dive through app/ai/registry.get_ai_provider; stores decision
    smart_money/             Smart-money subsystem (rollup, conviction/flow/red_flag,
                             insider/deals/SHP/corporate-announcements ingestion,
                             coverage diagnostic, holdings_signal, net_position,
                             party_classifier analyzer)
  strategies/            concrete strategy classes
  engine/                trading / risk engine
  ai/                    Provider abstraction (`provider.py`, `registry.py`,
                         `providers/{gemini_vertex,anthropic,openai}.py`).
                         `gemini_client.py` is the internal SDK wrapper used by
                         the GeminiVertexProvider — call sites use the registry.
  models/                SQLAlchemy models (users, watchlists, strategies, ...
                         smart_money/{insider_disclosure, shareholding_pattern,
                         corporate_announcement, fii_dii_stock, net_position,
                         client_override, ...}, user_holdings_metadata)
  schemas/               pydantic request/response
  tasks/
    celery_app.py        beat schedule
    daily_analysis.py    screen + deep-dive
    morning_news.py      pre-market news scan
```

## Frontend layout

```
frontend/src/app/
  layout.tsx             root layout + providers
  page.tsx               marketing/redirect
  login/                 login + register (first-time setup)
  auth/                  Kite OAuth callback handler
  analysis/              public-ish analysis UI
  (app)/                 authed shell (all require JWT)
    layout.tsx           sidebar + top-nav
    dashboard/           legacy landing (superseded by "Today")
    today/               morning brief — news, FII/DII, MF activity, portfolio, decisions
    watchlist/           watchlists + per-stock detail panel
    news/                news feed + sentiment drill-down
    strategies/          list, run, backtest
    orders/              order book, placement
    backtest/            backtest UI
    settings/            API keys, risk limits, kill switch
```

## Key data flows

### Daily analysis (08:30 IST)
1. Beat fires `run_daily_analysis`.
2. Worker pulls every active watchlist.
3. Gemini Flash-Lite screens each symbol (price action + fundamentals + latest news + smart-money snapshot) and assigns an interest score.
4. Top-N cross a configurable threshold → the user's configured deep-analysis provider (Gemini Vertex by default; Anthropic / OpenAI if switched in Settings) runs a deep dive via `app/ai/registry.py:get_ai_provider`.
5. The deep-analysis prompt is provider-agnostic — plain Markdown, no provider-specific tool use or JSON modes — so swapping providers is configuration-only.
6. Results stored in `investment_decisions` + `portfolio_analyses`.
7. Frontend "Today" page reads the latest batch and merges with smart-money signals via `decide_action_v2` (BUY/HOLD/SELL/WATCH × conviction × red-flag matrix).

### Smart-money rollup (19:00 IST M-F)
1. Beat fires `smart_money.rollup.compute`.
2. Worker iterates the universe (~3000 NSE symbols) per-symbol session under `NullPool`.
3. For each symbol the rollup:
   - Computes `net_positions_30d` rows from `bulk_block_deals` with the noise + circular-pair filter.
   - Reads `insider_disclosures` (filtering `is_intra_group_transfer = FALSE`), `shareholding_patterns`, `mf_holdings_monthly`, `corporate_announcements`, `bhavcopy_daily`, `fii_dii_stock_daily`.
   - Produces `conviction_score / flow_score / red_flag_score` and the `signal_breakdown JSONB` enumerating per-signal contributions.
   - Upserts one row per `(symbol, window_days=30, as_of)` into `smart_money_signals`.
4. `_format_smart_money()` reads the row when building the deep-analysis prompt; the Action Summary, Holdings Signal, and SmartMoneyPanel surfaces all read it for display.

### Morning news (06:30 IST)
1. Scrape Google News + Hindu Business Line for each portfolio holding.
2. Gemini classifies articles (positive / negative / neutral, with one-sentence rationale).
3. Output stored in `news_sentiments` and aggregated per stock into `daily_news_reports`.
4. "Today" actions on each stock weight AI-generated decisions against fresh sentiment.

### Order placement
1. Frontend calls `POST /api/orders/place`.
2. Backend runs risk checks (position size %, exposure %, daily loss, daily order count, per-order value, kill switch).
3. If allowed, Kite client sends the order; response persisted.
4. Failure modes (rate limit, token expiry, margin) are surfaced to the user verbatim.

## Configuration

All config is env-driven via `config.py` (`pydantic-settings`). The `.env` file is loaded by docker-compose into backend/worker/beat/flower. See `.env.example` for the full list.

Per-user overrides live in `users.settings_json` (risk limits, AI provider + model choices, `ai_max_daily_budget_usd`, smart-money weights). These take precedence over env defaults at request time. Legacy keys (`opus_max_daily_budget_usd`, flat `gemini_model`) are read as fallbacks; new writes use the current keys (`ai_max_daily_budget_usd`, per-window `smart_money_weights`).
