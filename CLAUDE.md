# CLAUDE.md

Guidance for Claude Code sessions working in this repo. Read before editing.

## What this is

Personal algo-trading platform for Indian equities. Zerodha Kite Connect for market data + execution, **Gemini Vertex** for both bulk screening and deep analysis (the AI provider is configurable per-user via the abstraction in `app/ai/`). Default config is single-admin (one user per deployment); the schema is set up for invite-only multi-user (see *Multi-user mode* below) but the admin invite endpoints aren't wired yet — don't assume multi-tenancy until they are.

## Ground rules

- **Default is single-admin; multi-user is schema-only.** `users.is_admin` and `invite_codes` exist, but registration still rejects the second user (`api/user_auth.py:register`). Don't write code that assumes multi-tenancy works end-to-end yet.
- **Never commit secrets.** `.env`, `*credentials*.json`, design-handoff dirs (`payments */`), and the `ceat-detail-mockup.html` are gitignored. Before any `git add -A`, double-check new files. Never inline API keys as defaults or fallbacks in code.
- **Sensitive cred columns are Fernet-encrypted.** `User.kite_api_key`, `kite_api_secret`, `kite_access_token`, `gemini_api_key`, `anthropic_api_key` all use the `EncryptedStr` SQLAlchemy type from `app/security/crypto.py`. Reads/writes are transparent — do NOT hand-encrypt or hand-decrypt at call sites. The dev key is auto-derived from `APP_SECRET_KEY`; in production `FIELD_ENCRYPTION_KEY` is required and the app fails fast at boot if missing.
- **Money code is load-bearing.** Anything touching `app/engine/`, `app/api/orders.py`, or risk limits needs extra care. Don't bypass risk checks "temporarily." Don't remove the kill switch. Don't place live orders from a test path.
- **Budget matters.** LLM spend is the biggest variable cost. Default screener is Gemini Flash-Lite; deep analysis runs on the user's configured provider (Gemini Vertex by default). Don't silently upgrade models in bulk paths.
- **AI provider is an abstraction.** Deep-analysis call sites import from `app/ai/registry.py:get_ai_provider(user, purpose)`, NOT a vendor SDK directly. The user's configured provider lives in `users.settings_json["ai_analysis_provider"]` (defaults to `gemini_vertex`). Adding a new provider = new class in `app/ai/providers/` + a `PROVIDER_REGISTRY` entry — call sites don't change. `app/ai/gemini_client.py` is now an internal implementation detail; new code uses the registry.
- **IST everywhere.** Celery timezone is `Asia/Kolkata`, market hours are 09:15–15:30 IST. Prefer `datetime.now(tz=ZoneInfo("Asia/Kolkata"))` over naive `datetime.now()`.

## Architecture at a glance

```
Kite Connect  ──┐                              ┌── Frontend (Next.js :3000)
                │                              │
News sources ──┼── Backend FastAPI :8000 ──────┤── OpenAPI at /docs
                │        │                     │
AI provider  ──┘         │── TimescaleDB :5432 │── Flower :5555 (monitoring profile only)
(via app/ai/             │
 registry.py)            └── Celery worker + beat (Redis broker :6379)
                              CELERY_NULL_POOL=1 — see app/db/session.py
```

- **Backend entry:** `backend/app/main.py` — initializes structlog, slowapi rate limiter, request middleware, global exception handler, optional Prometheus `/metrics`, and CORS, then mounts `app/api/router.py`.
- **Auth:** `/api/user/*` (local username+password, JWT bearer, rate-limited 10/min) and `/api/auth/*` (Kite OAuth handshake, stores Kite access token on the user row, encrypted).
- **Health:** `/api/health/live` (cheap) + `/api/health` (deep DB/Redis/Celery).
- **Jobs:** `backend/app/tasks/celery_app.py` holds the beat schedule. Tasks live as siblings.
- **Strategies:** `backend/app/strategies/` — each strategy is a class; defaults are registered via `app/services/default_strategies.py` with `is_default=True, user_id=NULL`.

## Conventions

### Backend
- Python 3.12, type hints everywhere. Pydantic v2 schemas in `app/schemas/`, SQLAlchemy 2.0 async models in `app/models/`.
- DB sessions come from `get_db` (`app/db/session.py`) — FastAPI `Depends`, one session per request.
- New tables get an Alembic migration: `make migrate-create msg="add X"`. Never hand-edit an applied migration. Use `CREATE INDEX IF NOT EXISTS` and similar idempotent DDL where possible so re-running on a partially-migrated DB is safe.
- Every protected route uses `Depends(get_current_user)` from `app/dependencies.py`.
- Services (`app/services/`) are the right home for integrations (Kite, news, fundamentals, LLMs). Routes should stay thin.
- **All Kite reads must go through `app/services/portfolio_cache.py`** (`get_holdings`, `get_quote`, `get_historical_data`). It wraps `kite.holdings/quote/historical_data` with the unified `fetch_cache` so concurrent dashboard widgets share one fan-out. Don't re-introduce direct `kite.holdings()` call sites in route handlers.
- **All external HTTP scrapes should route through `app/services/data_cache.py`** (`cache_get_or_fetch`). Existing in-process caches (`tickertape_fetcher._slug_cache`, `mf_activity._name_cache`, `google_finance._cache`) are bounded `OrderedDict` LRUs — keep new caches bounded too.
- **Logging:** use `app.observability.logging.get_logger(__name__)` (structlog) for new code. Stdlib `logging.getLogger` still works and is routed through the same JSON pipeline. Don't `print`.
- **Rate limiting:** import `limiter` from `app.observability.ratelimit` and decorate sensitive routes (`@limiter.limit("10/minute")`). The default per-IP/per-user limit is applied automatically by `SlowAPIMiddleware`.

### Frontend
- Next.js 16 (App Router, Turbopack), React 19, Tailwind v4. **This is NOT the Next.js you may be familiar with** — see `frontend/AGENTS.md`. Read the relevant guide in `node_modules/next/dist/docs/` before writing non-trivial Next-specific code.
- Authed pages live under `src/app/(app)/`; unauthed under top-level routes like `login`, `auth`, `analysis`.
- Server components by default; use `"use client"` only when you need hooks/state.
- API calls go through `src/lib/api.ts` (attaches the JWT from localStorage and points at `NEXT_PUBLIC_API_URL`).
- **All formatters live in `src/lib/format.ts`** — `fmtN`, `fmtINR`, `pctStr`, `fmtCr`, `fmtVol`, `fmtDateShort`, `fmtRelative`. Don't define inline copies in components; import from `@/lib/format`.
- **The morning brief is fetched via `src/lib/today-brief.ts`** (`getTodayBrief`, `refreshTodayBrief`) — it dedups concurrent fetches between the dashboard page and `ModeSidebar`. Don't call `/api/today/brief` directly.
- The session idle timeout is 15 minutes (`AppShell.tsx:IDLE_TIMEOUT_MS`).
- Heavy reusable primitives live in `src/components/ui/`:
  - `ErrorState.tsx` — error UI primitive
  - `MobileBanner.tsx` — slim full-width banner; `mobileOnly` (default true) hides at `≥md`. Used for Reconnect-Kite-style persistent alerts.
  - `AvatarMenu.tsx` — circular user-menu dropdown for the mobile header (the header collapses `username + Reconnect Kite + logout` into this at `<md`).
  - `ResponsiveTable.tsx` — `<table>` at `≥md`, stacked card list at `<md` from one column/row spec.
  - `FreshnessChip.tsx` — single chip pattern for `live / snapshot / ai` data; auto-flips to amber "stale" past kind-specific thresholds (live > 5 min, snapshot > 14 d, ai > 48 h). Use this on every block of data with mixed provenance so an analyst can tell "live 09:07" from "snapshot 3 May" from "AI 15 May".
  - `NarrativeStaleChip.tsx` — extracted from `PositionCard`. Render alongside any AI-generated paragraph that quotes numbers, when those numbers are likely older than the structured cards next to them. See "Cross-tab data divergence" below.
- **Mobile primitives use 720 px as the breakpoint** (matches `PortfolioHero.tsx:257`). When converting a desktop grid/table to a mobile layout, prefer `@media (max-width: 720px)` inside `<style jsx>` over Tailwind responsive prefixes — the codebase mixes inline styles + Tailwind heavily and the `<style jsx>` pattern keeps the rule colocated with the JSX it targets.
- **Body scroll lock for modals.** Use `useBodyScrollLock(open)` from `src/lib/modal-utils.ts` when mounting a modal/sheet. It increments a module-level counter (so nested modals coexist) and dispatches a `modal:state-change` CustomEvent that `FinanceWidget` already subscribes to (the floating $ FAB hides while any modal is open). For backdrop dismiss, prefer `useTapNotDrag(onClose)` over plain `onClick={onClose}` so touch-drag-to-scroll doesn't fire close.
- **Paid LLM call sites need `confirm()` on tap.** `runAnalysis` in `StockDetailPanel.tsx`, `evaluate` in `InvestmentDecision.tsx`, and any future POST to `/api/stocks/{symbol}/analyze` / `/api/investment/evaluate` must `confirm(...)` before firing — these calls go through `app/ai/registry.py:get_ai_provider()` which is real cost. The first explicit "Should I Invest?" tap is allowed without confirm (the tap itself is the intent signal); re-evaluations need the prompt.
- **Replay queue on `openStockDetail`.** `src/lib/stock-detail.ts` buffers up to 8 requests if the call fires before `AppShell` has registered its subscriber (route-transition timing). Don't reintroduce the no-op-when-no-listener variant.

### Data model touchpoints
All per-user tables FK to `users.id` with `ON DELETE CASCADE`: `watchlists`, `strategies`, `strategy_runs`, `investment_decisions`, `portfolio_analyses`, `stock_notes`, `daily_news_reports`, `review_alerts`, `invite_codes (created_by)`, `client_overrides`, `user_holdings_metadata`. When adding new per-user data, follow the same pattern.

## Local dev loop

```bash
make dev            # attached
make migrate        # after adding a migration
make logs-backend   # watch backend
docker exec -it algo-trader-timescaledb-1 psql -U algotrader -d algotrader
```

Code reloads:
- Backend: uvicorn `--reload` is on; the `./backend` volume is mounted into the container.
- Frontend: `docker/frontend.Dockerfile` runs `next dev --hostname 0.0.0.0` against the mounted `./frontend/src`. Saves hot-reload at http://localhost:3000 — no rebuild needed. (The legacy version of this Dockerfile baked a prod build at image-build time and ignored the volume mount; if a session sees `next start` running, the image is stale and needs `docker compose up -d --build frontend`.)

When changing Python deps or Dockerfile: `make build && make up` (or just `docker compose up -d --build backend celery-worker celery-beat`).

For prod-mode local testing: `docker compose -f docker-compose.prod.yml up --build`.

## Testing

`make test` runs pytest inside the backend container. Add tests alongside new services under `backend/tests/`. Integration tests should hit the real Postgres/Redis via Docker, not mocks.

## Git workflow

- Main branch is `main`. `origin` is `github.com/namanguptaiitkgp/stock-tracker` (private).
- A **post-commit hook** (installed under `.git/hooks/post-commit`, source in `scripts/git-hooks/post-commit`) auto-pushes the current branch to `origin` after each commit. Suppress by setting `NO_AUTO_PUSH=1 git commit ...`.
- To reinstall the hook on a fresh clone: `make install-hooks`.
- Commit messages: short imperative subject, details in body when the "why" isn't obvious from the diff.

## Things that have bitten us

- **Port 3000 collisions.** Another Next.js dev server on the same Mac can hold 3000. Check with `lsof -nP -iTCP:3000 -sTCP:LISTEN` before assuming Docker is broken.
- **Stale frontend image.** If the dashboard doesn't reflect file edits, the frontend container may be running `next start` against a baked build (the original Dockerfile did this). Rebuild: `docker compose up -d --build frontend`. The current Dockerfile uses `next dev` against the mounted source.
- **News-rail sticky positioning.** The dashboard's news inbox uses `position: fixed` (anchored with a `right: max(8px, calc((100vw - 1400px) / 2 + 8px))` so it lines up with the centered grid cell). Earlier `position: sticky` attempts failed because the AppShell flex column had `overflow: hidden` + `<main>` had `overflow-auto`, creating two competing scroll roots. Page scroll now lives on `<body>`; if you re-introduce a scroll container above `<main>`, the sticky header/nav will stop pinning.
- **Kite token expiry.** Kite access tokens expire daily around 6 AM IST. Relogin is manual through Settings → Connect Kite. (The old `tasks/health.check_token_health` task is gone — it pointed at a file that didn't exist; warn UI is purely client-side now.)
- **LLM cost blowup.** Always route bulk LLM work through screening (Gemini Flash-Lite). Before introducing a new deep-analysis call, confirm it's bounded by `settings_json.ai_max_daily_budget_usd` (renamed from the legacy `opus_max_daily_budget_usd` which is still read as a fallback). The `get_ai_provider()` factory is the only path that should produce billable model calls — never instantiate a provider class directly.
- **Celery + async DB.** The worker and beat containers MUST run with `CELERY_NULL_POOL=1` (set in both compose files). Each celery task wraps work in `asyncio.run(...)` which spins a fresh event loop; without `NullPool`, asyncpg connections cached in the engine pool from a prior task's loop trip `RuntimeError: got Future attached to a different loop` and `InterfaceError: another operation in progress`. FastAPI runs on a single long-lived loop so the standard pool stays for it. See `app/db/session.py` for the env-detection. This bug previously dark-broke the smart-money rollup for 10 days.
- **News scrapers are fragile.** Hindu BL, Tickertape, mfdata.in are all HTML scrapes — assume they can break on any site redesign. Wrap in try/except and log; don't let one source take down the morning scan. The unified entry points are `services/news_scraper.fetch_all_feeds` (Hindu BL) and `services/market/market_news_aggregator.fetch_market_news` (Moneycontrol+ET+Google). Both are wrapped with `data_cache.cache_get_or_fetch` (2h TTL).
- **Encrypted columns must round-trip.** If a migration alters a credential column, run `EncryptedStr.encrypt()` on the data path so already-Fernet-encoded values pass through unchanged (the `is_token()` check makes this idempotent). Plaintext values get encrypted; ciphertext stays as-is.
- **Smart-money intra-group transfers.** Same-date promoter-family Buy/Sale pairs (within 5% share-count tolerance) are flagged `is_intra_group_transfer = TRUE` by `services/smart_money/insider_disclosures.py:detect_intra_group_transfers` and excluded from BOTH conviction promoter-buying AND red-flag promoter-selling scoring. Without this filter, a transfer between Bajaj group entities (BAJAJFINSV) would score as conviction +99 AND red-flag -25 simultaneously — both spurious. New scoring code that reads `insider_disclosures` MUST add the `is_intra_group_transfer = FALSE` filter.
- **NSE `acqMode` is not the trade direction.** For an insider Buy, `acqMode` may be either `"Market Purchase"` OR `"Market Sale"` — both are genuine on-exchange trades. The conviction scorer accepts both. Off-market / ESOP / inter-se transfers are excluded explicitly.
- **FastAPI route ordering for `/{symbol}` catch-alls.** Smart-money routes that look like `/insider-activity`, `/red-flags`, `/coverage/{symbol}` etc. MUST be registered BEFORE `/{symbol}` in `app/api/smart_money.py`, otherwise FastAPI matches them as `symbol="insider-activity"`. The file is structured to put specific paths first; new specific routes go above the catch-all.
- **Cross-tab data divergence (AI narrative vs structured cards).** The structured cards on the Stock Detail Panel (Valuation gauge, Smart Money cards, rule engine) read fresh from `StockFundamentals`. The AI narrative paragraphs (`investment_decision.result_json.valuation_view`, `result_json.news_sentiment_context`, `result_json.reasoning`) were generated against an older snapshot and bake values directly into prose — so ETERNAL can show `P/E 629×` on the Valuation gauge and `P/E 648× vs peer median 7×` in the AVOID rationale on the same panel. The frontend fix (visibility layer) is shipped: `today.py` emits `narrative_stale` + `narrative_fund_lag_hours` per holding when `fund.fetched_at - decision.created_at > 24h`, and `FreshnessChip` + `NarrativeStaleChip` surface divergence to the user. **The proper fix (pipeline reconciliation) is not yet shipped** — either snapshot fundamentals at narrative generation time and pin both rendering paths to the same snapshot, OR template-render the numbers from live data instead of letting the LLM emit them inline. Filed as a backend follow-up.
- **Sovereign Gold Bonds in equity smart-money endpoints.** `portfolio_cache.get_holdings()` returns raw Kite holdings including bonds. `app/api/smart_money.py:holdings_signals` filters them via `_is_non_equity()` (SGB* prefix and `-GB` suffix patterns) and surfaces them separately under `non_equity` in the response. Any new equity-only smart-money endpoint that iterates holdings MUST apply the same filter — otherwise bonds get scored against insider/institutional signals that don't apply.
- **P/B `2.0 below 2.0` rounding-edge false positives.** `app/services/fundamental_analysis.py:_evaluate_rule` has `_BOUNDARY_TOLERANCE = 0.01` — any actual value within 0.01 of the threshold passes regardless of comparator (`gte`/`lte`/`gt`/`lt`/`between` all get the tolerance). Without it, a stock with `pb=1.997` displaying as `"2.0"` would trigger a `< 2.0` failure that looks wrong to the analyst. Don't lower the tolerance below 0.01 — that's calibrated to the 1-dp display precision used app-wide.
- **HHI is reported at sector AND position level.** `/api/portfolio/concentration` returns both `herfindahl_sectors` (intuitive — what the analyst expects when reading "concentration") and `herfindahl_positions` (the strict per-stock definition). Frontend defaults to sector. The legacy `herfindahl` key still ships and aliases position-level for back-compat.

## Smart-money subsystem

Lives under `app/models/smart_money/`, `app/services/smart_money/`, `app/tasks/smart_money/`. Everything ingesting a third-party disclosure goes here. Key conventions:

- **Audit every run.** Wrap ingestion logic in `async with ingestion_run(source=...) as ctx:` from `services/smart_money/run_logger.py`. Populate `ctx.fetched/inserted/updated/skipped` and `ctx.meta` for breadcrumbs. Use `ctx.mark_partial("...")` when part of a batch failed.
- **Validate every run.** Call `validate_run(source, run_date, row_count)` from `services/smart_money/validation.py` before finalising. Returns warnings for low-volume / high-volume / zero-on-trading-day; populate `ctx.meta["validation_warnings"]` and call `ctx.mark_partial(...)` when warnings fire.
- **Sources use stable short names** — match the key in `SOURCE_CADENCE_HOURS` (`run_logger.py`) exactly. Current set: `amfi_nav`, `amfi_mf`, `sebi_pms`, `sebi_aif`, `nse_deals`, `bse_deals`, `nse_bhavcopy`, `bse_bhavcopy`, `nse_insider`, `nse_corporate_announcements`, `fii_dii_stock`, `shareholding_pattern`, `smart_money_rollup`.
- **Client-name normalization** (`deals.py:_norm_client`) is the matching key for named-shark linkage AND for client_overrides AND for net-position aggregation. Don't introduce a parallel normalizer. `known_sharks.aliases` is the source of truth for canonicalization.
- **Party classification at ingest, not query.** `bulk_block_deals.client_category` is populated by `services/smart_money/analyzer/party_classifier.py:classify()` at insert time so the active-traders endpoint can filter PROP_HFT / BROKER without re-classifying per query. New deals readers should expect this column to be NULL for legacy rows (a one-off `reclassify_existing_deals()` backfill is available).
- **Three-stream scoring (PR 2 onwards).** The rollup writes `conviction_score / flow_score / red_flag_score / signal_breakdown` per `(symbol, window_days, as_of)`. Composite is derived. Default `window_days = 30`; the schema is keyed `(symbol, window_days, as_of)` so 90d / 365d / since-purchase rows can coexist additively. Per-window weights live in `WEIGHTS_BY_WINDOW` (eventually `users.settings_json["smart_money_weights"]` per-window keyed). Don't reintroduce flat-composite logic.
- **Coverage gating for holdings.** `services/smart_money/coverage.py:compute_coverage()` returns 0–100 weighted by source importance. The holdings-signal layer (`holdings_signal.py:compute_holding_signal`) returns `NO_SIGNAL` when score < 50 rather than producing a misleading direction from sparse data. New per-stock signal output should follow the same convention.
- **Celery queue** for smart-money data ingest is `data`. Rollups + PDF parsers use `analysis` (longer-running).

Full design: `docs/smart-money.md` (also lists what's live vs. pending and known data-quality limits).

## Multi-user mode (schema-ready, not wired)

Schema additions in migration `e7c2a91d4f3b`:
- `users.is_admin` Boolean, default false. Oldest user is backfilled to true on upgrade.
- `invite_codes` table — `code`, `created_by_user_id`, `redeemed_by_user_id`, `redeemed_at`, `expires_at`.

To unlock invite-only multi-user, build:
1. `app/api/admin_invites.py` — `POST/GET/DELETE /api/admin/invites`, gated by `Depends(get_current_user)` + `is_admin` check.
2. Add `invite_code: str` to the `RegisterRequest` body in `api/user_auth.py:register` and replace the `count > 0` rejection with an atomic invite-code redemption (mark redeemed in the same transaction as user create).
3. Frontend: admin-only `/admin/invites` page (generate / copy / revoke), and an `invite_code` field on the register form.

## Production deployment

Use `docker-compose.prod.yml` (multi-worker uvicorn, non-root user, `restart: always`, healthchecks). Required env beyond dev:
- `APP_SECRET_KEY` (non-default), `FIELD_ENCRYPTION_KEY`, non-localhost `KITE_REDIRECT_URL`, explicit `CORS_ORIGINS`.
- Optional: `METRICS_ALLOW_TOKEN` (enables `/metrics`), `RATE_LIMIT_DEFAULT`, `RATE_LIMIT_AUTH`, `BACKEND_WORKERS`, `WORKER_CONCURRENCY`, `FLOWER_BASIC_AUTH`.
- `app/config.py:validate_production_settings()` is invoked at startup and raises if any of the required values are missing/insecure when `APP_ENV=production`.

## When modifying agents' behavior

If a change belongs to "how Claude should work in this repo going forward" (conventions, invariants, gotchas), update this file. If it's about a specific feature, put it in `docs/`.
