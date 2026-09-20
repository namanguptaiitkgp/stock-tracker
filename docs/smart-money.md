# Smart money

Ingests SEBI-mandated institutional disclosures + named-investor trades, converts them into per-stock **conviction / flow / red-flag** scores, feeds them into the deep-analysis prompt, the Today page, and a dedicated **Smart Money** page that surfaces both **discovery** (new candidates) and **holdings signals** (what to do with what you own).

## Current state (as of 2026-05-02 — PR 10 merged)

End-to-end pipeline live; the scoring system has moved from the original flat-composite model to a three-stream architecture (conviction / flow / red flags) with a coverage diagnostic and per-holding signals.

### Live + producing real signal

- **Three-stream scorer** (`services/smart_money/rollup.py`) — conviction, flow, red-flag scores per `(symbol, window_days, as_of)` plus `signal_breakdown JSONB` enumerating per-signal contributions. Composite is derived. Weight redistribution when a sub-signal's source data is absent. Window 30d is the default; the schema (`window_days` column) supports 90d / 365d / since-purchase additively when history accumulates.
- **Intra-group transfer detection** (`services/smart_money/insider_disclosures.py:detect_intra_group_transfers`) — flags matched same-date promoter-family Buy/Sale pairs (≤5% share-count tolerance). Conviction promoter-buying and red-flag promoter-selling both filter on `is_intra_group_transfer = FALSE` so transfers no longer double-count as both sides.
- **Action Summary** (`api/smart_money.py:action_summary` → `frontend/components/common/ActionSummaryCard.tsx`) — three cards on `/smart-money`: Accumulation (conviction ≥ 30, no severe red flags), Distribution (conviction ≤ -30), Avoid (red_flag ≤ -25). Headlines explain the binding signal per stock.
- **Holdings signal layer** (`services/smart_money/holdings_signal.py:compute_holding_signal`) — per-holding direction: `ADD / HOLD / TRIM / REVIEW / NO_SIGNAL`. Coverage gating is the first branch — when coverage_score < 50 we return NO_SIGNAL rather than guess. `/api/smart-money/holdings-signals` returns one row per Kite holding with confidence chip + driver bullets + coverage %. Surfaced in the "Your Holdings" section above Action Summary.
- **Coverage diagnostic** (`services/smart_money/coverage.py`) — per-symbol availability summary across 7 source tables, weighted score 0–100. Below 50 the SmartMoneyPanel renders a callout listing what's missing ("No insider disclosures in last 90 days" etc.) so users see *why* a panel is thin.
- **AMFI NAV + scheme registry** — ~14k schemes, refreshed daily.
- **NSE bulk/block deals** with named-shark flagging + 9-category party classification stored on each row (`bulk_block_deals.client_category`).
- **NSE bhavcopy + delivery %**.
- **NSE insider disclosures** (PIT Reg 7 / SAST) — endpoint moved to `/api/corporates-pit` (was `/api/corporates/insiderTrading` until 2025); parser keys off `acqName / secAcq / secVal / acqfromDt / intimDt / personCategory / acqMode`. `mode` filter accepts both "Market Purchase" and "Market Sale" (NSE labels on-exchange trades both ways).
- **NSE corporate announcements** (filtered by buyback / pledge / encumbrance / preferential allotment subjects) — feeds the buyback flow signal and the pledge-invocation red flag.
- **Net-position calculator** (`services/smart_money/net_position.py`) — 30-day rolling per-party netting with intermediary filter (`PROP_HFT` / `BROKER` dropped), share-count floor, square-off filter (drop when `|net| / gross < 5%`), and circular-pair detection (mirror-volume A buys ↔ B sells within 10%). `net_to_total_ratio` persisted on the row for the active-traders endpoint to filter directional vs noise.
- **Known-sharks** registry — schema columns `tier (1/2/3)`, `entity_type (individual / family_office / pms_aif / corporate)` ready; default seed of 30 names (~150-entry expansion deferred to a curated content PR).
- **Client overrides** (`client_overrides` table) — per-user category overrides applied first when scoring active traders; Settings → Holdings tab + `/smart-money/traders` page support edit.
- **Smart-money API** — `/pulse`, `/leaderboard?metric=composite|deals|delivery|conviction|flow|red_flags|shark_trades`, `/{symbol}`, `/coverage/{symbol}`, `/score-breakdown/{symbol}`, `/insider-activity[?...]`, `/insider-activity/{symbol}`, `/shareholding/{symbol}`, `/red-flags`, `/net-positions/{symbol}`, `/announcements`, `/fii-dii/{symbol}`, `/action-summary`, `/notable-insider`, `/net-traders`, `/holdings-signals`, `/runs`, `/runs/latest`, `/sharks`, `/shark/{name}`, `/top-clients`, `/by-fund/{scheme_code}`, `/by-manager/{id}`, plus the deal analyzer at `/analyzer/upload` and `/analyzer/sessions/...`.
- **Frontend:**
  - `/smart-money` page: "Your Holdings" section (per-stock signal table) → "Discovery" Action Summary three cards → expandable Insider Activity / Shark Trades / Net Positions / Red Flags / Data Freshness sections → Explore footer linking to sub-pages.
  - `/smart-money/insider`, `/smart-money/deals`, `/smart-money/traders` sub-pages — full filterable tables for research-mode use.
  - `/smart-money/shark/[name]` — trade timeline with window selector.
  - `/smart-money/analyzer` — ad-hoc CSV deal analyzer (Layer 1–6 pipeline, see below).
  - `SmartMoneyPanel.tsx` — Conviction / Flow / Red-Flag triple gauge + breakdown accordion + active-red-flag callout + insider timeline + named-shark deals + bulk/block history. Renders the **coverage callout** when score < 50.
  - Settings → **Holdings** tab — purchase-date + thesis editor (drives the holdings-signal "since you bought" logic in PR 11+).
  - Settings → AI Analysis → **Fundamental analysis rules** — hard/soft filter toggle per rule, "Load preset…" dropdown for the Indian-market screener.
- **Celery beat schedule** (queue=`data` for ingest, `analysis` for rollup):
  - 18:00 daily — `amfi.sync_nav_and_schemes`
  - 17:00 M–F — `corporate_ann.ingest_nse_daily`
  - 17:30 M–F — `insider.ingest_nse_daily`
  - 18:00 M–F — `bhavcopy.ingest_nse_daily`
  - 18:15 M–F — `fii_dii_stock.ingest_nse_daily` (placeholder; upstream pending — see *Known limitations*)
  - 18:30 M–F — `deals.ingest_nse_daily`
  - 18:45 M–F — `deals.ingest_bse_daily` (currently empty payload — endpoint shape pending)
  - 19:00 M–F — `rollup.compute`
  - 10:00 day-12 monthly — `amfi_monthly.ingest` (parser stubbed; downloads-only mode pending)
  - 10:00 day-20 Jan/Apr/Jul/Oct — `shareholding.ingest_bse_quarterly`
  - 10:30/11:00 day-15 Jan/Apr/Jul/Oct — `sebi.ingest_pms_quarterly` / `ingest_aif_quarterly` (PDF parser stubbed)

### Scaffolded / data-thin (waiting on accumulation or upstream)

- `services/smart_money/amfi_mf.py` — AMFI XLS parser (`parse_amc_xls` raises `NotImplementedError`). The plan in `smart-money-mf-monitoring.md` proposes building URL-discovery + raw-XLS download first so samples accumulate over monthly runs, then writing the parser. mfdata.in scrape is live but in-memory only — persistence to a new `mf_activity_monthly` table is also planned in that doc.
- `services/smart_money/sebi_pdf_parser.py` + `sebi_pms.py` + `sebi_aif.py` — pdfplumber + Gemini Flash-Lite fallback; needs real SEBI sample PDFs.
- BSE bulk/block deals — task scheduled, returns empty (BSE endpoint shape needs another iteration).
- Stock-level FII/DII (`fii_dii_stock_daily`) — NSE doesn't actually publish per-stock FII/DII; task is a no-op until a derived source (e.g. Δ from quarterly shareholding pattern × shares × avg price) or a paid feed is wired.
- Trajectory classifier (strengthening / weakening) — needs ≥12 weeks of 30d composite history. Will populate naturally as the rollup runs.
- 90d / 365d window compute — schema-only today (`window_days` column ready); turn on once `smart_money_signals` has ≥60 days of history.

### Known limitations / data-quality reality

- The `mf_consensus` conviction sub-signal currently shows `note: "no data"` for every symbol — the rollup reads `mf_holdings_monthly` which is empty until the AMFI parser ships.
- `shareholding_patterns` is empty until the first day-20 quarterly run produces data.
- `bhavcopy_daily` history is shallow (~10–15 trading days) due to the 10-day Celery outage that was fixed by the NullPool patch (May 1). Delivery z-score requires 10+ baseline trading days; will normalize as the daily ingest accumulates.
- Holdings signals correctly return `NO_SIGNAL` for stocks not in our equity universe (sovereign gold bonds, etc.) — this is intentional, not a bug.
- The 30-name `known_sharks` seed produces few "named shark" matches; expansion to ~150 entries is a curated-content PR (deferred).
- Composite leans heavily on `deals_score` + `delivery_score` + `red_flag_score` today; weights auto-normalize across available sub-signals.

## Deal Analyzer (ad-hoc CSV upload)

`/smart-money/analyzer` — upload one or more bulk / block / SEBI-insider CSVs over any window and get Signal Grades per stock. Backend: `app/services/smart_money/analyzer/`.

**Design principles (applied verbatim from spec):**
1. Reject more than accept. Default to NEUTRAL unless evidence is strong.
2. Structural quality > statistical quantity — Rs 5 Cr of IRB promoter buying > Rs 500 Cr of prop-desk churn.
3. One dominant signal type per stock. Don't combine promoter-accumulation with VC-exit scores — they mean different things.
4. Every rule has a failure mode, documented in the code.

**Six layers:**
- **Layer 1 — Data hygiene:** drop rows missing Party / Side / Symbol; normalize party names (strip "Revised", HUF, titles, whitespace); classify into exactly one of 9 categories (`QUALITY_MF_FPI, VC_PE, PROMOTER, INSIDER_OTHER, PROP_HFT, OTHER_FUND, BROKER, CORP_OTHER, INDIVIDUAL`) via curated dictionary + CSV-category override.
- **Layer 2 — NOISE gate (applied first per stock):** N1 prop share ≥60% · N2 gross <Rs 1 Cr · N3 single party + single day.
- **Layer 3 — Priority-ordered signal detection:** VC/PE exit block → Strong-buy promoter → Strong-buy consensus → Moderate buy → Strong-sell promoter → Strong-sell quality → Weak buy/sell → Neutral. Each gate has explicit B1..B8 / C1..C4 / M1..M3 / S1..S4 / Q1..Q4 checks; failing any gate falls through to the next priority.
- **Layer 4 — Tier:** Sizeable (net ≥Rs 5 Cr OR holdings change ≥0.25%) vs Symbolic.
- **Layer 5 — Confidence modifiers:** +Corroboration, +Persistence (≥5 days), -Conflict (opposing promoter vs quality), -Structural (single-txn holdings >5%), -Recency (no activity in last 5 days).
- **Layer 6 — Output:** Stock · Signal · Tier · Confidence · Net Cr · Days · Primary Evidence · Modifiers; plus separate NOISE and NEUTRAL audit lists for transparency.

**Key files:**
- `party_classifier.py` — 9-category keyword dictionary + normalizer. Used by both the analyzer AND the daily ingestion (`bulk_block_deals.client_category` is set at insert time so the active-traders endpoint can filter PROP_HFT / BROKER without re-running the classifier per query). Grow over time: edit `QUALITY_MF_FPI_KEYS`, `VC_PE_KEYS`, `PROP_HFT_KEYS`, or add to `OVERRIDES` / `PROMOTER_OVERRIDES` / `INSIDER_OTHER_OVERRIDES`. PR 6 added the addendum's broker/prop patterns (`securities research`, `puma securities`, `qe securities`, `irage broking`, `jainam broking`, `silverleaf capital`, `arihant capital market`).
- `csv_parser.py` — flexible column synonym matching; auto-detects bulk/block/insider; reads NSE CSV export format and SEBI PIT Reg 7 disclosures.
- `engine.py` — Layers 2-6, priority-ordered signal detection.

**API:** `POST /api/smart-money/analyzer/upload` — multipart form, field `files`, up to 10 MB each. Returns signals + neutral/noise audits. Not persisted; re-upload to re-analyze.

## Tables

### Core (PR 2 — `c7a3b8e1d5f9`)

| Table | Purpose |
|---|---|
| `smart_money_signals` | One row per `(symbol, window_days, as_of)`. Carries conviction / flow / red_flag scores + composite + `signal_breakdown JSONB`. |
| `insider_disclosures` | NSE PIT Reg 7 filings; `is_intra_group_transfer` flag drives the conviction / red-flag exclusion. |
| `shareholding_patterns` | Quarterly per-symbol shareholding (promoter / FII / DII / pledge %) with QoQ deltas. |
| `corporate_announcements` | Filtered NSE filings — buyback / pledge / encumbrance / preferential allotment. |
| `fii_dii_stock_daily` | Per-stock FII/DII flows (currently empty — upstream pending). |
| `net_positions_30d` | Rollup-materialized per-party netting. `is_circular_suspect`, `net_to_total_ratio`, `is_known_shark` columns. |
| `bulk_block_deals` | NSE/BSE deals; `client_category` populated at ingest by `party_classifier`. |
| `bhavcopy_daily` | Per-stock daily OHLCV + delivery %. |
| `mf_schemes` | AMFI scheme registry (~14k rows). |
| `mf_holdings_monthly` | AMFI per-scheme stock holdings (parser stubbed, table empty). |
| `pms_managers`, `pms_strategy_holdings_quarterly`, `aif_funds`, `aif_holdings_quarterly` | SEBI PMS/AIF (PDF parser stubbed, tables empty). |
| `known_sharks` | Tracked HNIs; `tier`, `entity_type` columns added in PR 6. |
| `client_overrides` | Per-user category override for the active-traders classifier (PR 8). |
| `ingestion_runs` | Audit row per task invocation. Status = success / partial / failed; counts + meta JSONB + validation_warnings. |
| `today_brief_cache` | Memoised morning-brief payload. |

### Holdings + window-aware (PR 10 — `a2c8d4f7b1e9`)

| Table | Purpose |
|---|---|
| `user_holdings_metadata` | Per-user (`user_id` FK CASCADE) `(symbol, first_purchase_date, initial_thesis, thesis_tags, target_holding_period_months)`. Drives holdings-signal "since you bought" comparisons (full drift analysis lands once history accumulates). |
| `smart_money_signals.window_days` | New column, default 30. Unique key re-keyed to `(symbol, window_days, as_of)` so 90d / 365d / since-purchase windows can coexist. |

## Run logging (every task)

Every ingestion task wraps its work in:

```python
async with ingestion_run(source="amfi_nav", task_name="app.tasks.smart_money.amfi.sync_nav_and_schemes") as ctx:
    result = await sync_nav()
    ctx.fetched = result["fetched"]
    ctx.inserted = result["inserted"]
    ctx.updated = result["updated"]
    ctx.skipped = result["skipped"]
    ctx.meta["bytes"] = result["bytes"]
```

Output in `ingestion_runs`:
- `status`: `running` → `success` / `partial` / `failed`
- `started_at`, `finished_at`, `duration_ms`
- counts + `error_class` / `error_message` on failure
- `meta` JSONB for source-specific breadcrumbs (URL, byte size, fallback count, validation_warnings, ...)

**Use `ctx.mark_partial("...")`** when some items failed but others succeeded — useful for multi-PDF batches, low-row sanity warnings, etc.

**Validation layer** (PR 2 — `services/smart_money/validation.py`): each ingestion task calls `validate_run(source, run_date, row_count)` before finalize. Returns warnings for low-volume (`<30%` of 30-day average), high-volume (`>3×`), and zero-rows-on-trading-day. Warnings populate `meta.validation_warnings` and mark the run `partial`.

**Schema validation** (`validate_columns(source, parsed_columns)`) — raises `SchemaValidationError` when CSV/JSON columns drift from the registry. Stops "successful runs writing wrong data."

**Staleness cadence** (`SOURCE_CADENCE_HOURS` in `run_logger.py`): 1.5× the cadence gets flagged `stale` in the UI freshness strip. Sources covered: `amfi_nav`, `amfi_mf`, `sebi_pms`, `sebi_aif`, `nse_deals`, `bse_deals`, `nse_bhavcopy`, `bse_bhavcopy`, `nse_insider`, `nse_corporate_announcements`, `fii_dii_stock`, `shareholding_pattern`, `smart_money_rollup`.

## Composite scoring (per spec §7)

Per `(symbol, window_days, as_of)` the rollup writes:

- **conviction_score** (-100..+100) — promoter buying (0.30) + tracked-shark accumulation (0.25, tier-weighted) + MF consensus (0.25) + shareholding Δ (0.20). Weight redistributed across available sub-signals.
- **flow_score** (-100..+100) — delivery z-score (0.35) + stock-level FII/DII (0.30) + institutional block/bulk net (0.20) + buyback active (0.15 binary).
- **red_flag_score** (-100..0) — circular trading (-30), pump pattern (-40), promoter selling (-25), high pledge (-20 plus -10 per 10pp above 40, capped -50), pledge invocation (-40). Sum clamped to -100.
- **composite** = `conviction + flow * 0.4 + red_flag`, clamped to ±100.
- **signal_breakdown JSONB** — per-signal `{raw, normalized, source_rows, note?}` plus `signals_available` / `signals_absent` lists. Used by the SmartMoneyPanel breakdown accordion and the `/score-breakdown/{symbol}` endpoint.

Default weights are tunable via `users.settings_json["smart_money_weights"]` (per-window keyed map: `{"30": {...}, "90": {...}}`).

## Holdings signal (PR 10)

Per-holding direction surfaced in the "Your Holdings" section on `/smart-money`:

```python
if coverage_score < 50:
    return "NO_SIGNAL", confidence="LOW"

if red_flag_score <= -30:
    return "REVIEW", confidence by coverage, headline = worst red-flag label

if conviction_score >= +40 and red_flag_score > -20:
    return "ADD", confidence by coverage + magnitude

if conviction_score <= -30:
    return "TRIM", confidence by coverage

return "HOLD"
```

The order matters: coverage gating first (so thin-data holdings never get a wrong direction), red-flag override second (a single bad flag overrides a positive conviction), then conviction direction, then HOLD as the default. Trajectory ("strengthening / weakening") would refine ADD-with-HIGH-confidence; v1 omits it because we don't yet have ≥30 days of signal history per symbol.

## Coverage diagnostic

`services/smart_money/coverage.py:compute_coverage(symbol, db)` → 0–100 score weighted by source importance:

- bhavcopy 0.30, signal 0.30, deals 0.15, insider 0.15
- shareholding 0.05, mf_holdings 0.05
- corporate_announcements 0.00 (rare events; absence carries no information)

Below 50 the SmartMoneyPanel renders a callout block listing what's missing in plain language. This is the user's "highlight when smart money isn't producing a signal" requirement: a holding without data is visible information, not silent absence.

## Testing live data

```bash
# inside the backend container
docker exec algo-trader-backend-1 python3 -c "
import asyncio
from app.services.smart_money.amfi_nav import sync_nav
from app.services.smart_money.deals import sync_nse_deals
from app.services.smart_money.bhavcopy import sync_bhavcopy
from app.services.smart_money.insider_disclosures import sync_nse_insider
print(asyncio.run(sync_nav()))
print(asyncio.run(sync_nse_deals()))
print(asyncio.run(sync_bhavcopy()))
print(asyncio.run(sync_nse_insider()))
"
```

Inspect what landed:

```sql
SELECT source, status, records_fetched, records_inserted, duration_ms, started_at
FROM ingestion_runs ORDER BY started_at DESC LIMIT 20;

SELECT count(*) FROM mf_schemes;        -- ~14000+
SELECT count(*) FROM bhavcopy_daily;
SELECT count(*) FROM insider_disclosures;
SELECT count(*) FILTER (WHERE conviction_score IS NOT NULL) AS with_conv,
       count(*) FILTER (WHERE flow_score IS NOT NULL) AS with_flow,
       count(*) FILTER (WHERE red_flag_score < 0) AS with_red_flags,
       count(*) FROM smart_money_signals WHERE as_of = (SELECT MAX(as_of) FROM smart_money_signals);
SELECT symbol, conviction_score, red_flag_score
FROM smart_money_signals
WHERE as_of = (SELECT MAX(as_of) FROM smart_money_signals)
  AND red_flag_score IS NOT NULL AND red_flag_score < 0
ORDER BY red_flag_score ASC LIMIT 10;
```

## Triggering a task manually

```bash
# via celery call (worker + redis must be up)
docker exec algo-trader-backend-1 celery -A app.tasks.celery_app call \
  app.tasks.smart_money.amfi.sync_nav_and_schemes

# or direct service call from a shell
docker exec algo-trader-backend-1 python3 -c "
import asyncio
from app.services.smart_money.amfi_nav import sync_nav
print(asyncio.run(sync_nav()))
"
```

## Gotchas

- **Celery + async DB.** The celery-worker and celery-beat containers MUST set `CELERY_NULL_POOL=1` (already wired in both compose files). Each celery task wraps work in `asyncio.run(...)` which spins a fresh event loop; without `NullPool`, asyncpg connections cached in the engine pool from a prior task's loop trip `RuntimeError: got Future attached to a different loop` and `InterfaceError: another operation is in progress`. FastAPI runs in a single long-lived loop so the standard pool stays for it. See `app/db/session.py` for the env-detection.
- **NSE archives hostname** requires a preflight `GET https://www.nseindia.com` to seed cookies. The services handle this automatically (`services/smart_money/deals.py` lines ~155–173 is the canonical pattern; `insider_disclosures.py` and `corporate_announcements.py` reuse it).
- **NSE insider endpoint** moved from `/api/corporates/insiderTrading` to `/api/corporates-pit` some time in 2025. The legacy URL 404s. Current code targets the new path.
- **NSE `acqMode` ambiguity** — for a Promoter Buy, `acqMode` may be either "Market Purchase" OR "Market Sale" depending on which side initiated the trade; both are genuine on-exchange transactions. Conviction promoter-buying filter accepts both. Off-market / ESOP / inter-se transfers are still excluded.
- **Bhavcopy URL template** is `sec_bhavdata_full_DDMMYYYY.csv` (lowercase, compact date). `sync_bhavcopy()` walks back 5 days if today's 404s — handles weekends/holidays cleanly.
- **Client-name normalization** drops `LLP / Ltd / Limited / Pvt` and collapses whitespace — so `ASHISH KACHOLIA` and `Ashish Kacholia` match. Aliases in `known_sharks` are the source of truth for shark linkage. The same `_norm_client()` in `deals.py` is the matching key everywhere — don't introduce a parallel normalizer.
- **Bulk deals CSV** has only today's trades. For history we'd need a different endpoint; backfilling isn't part of this phase.
- **AMFI NAV file** mixes header lines (fund house, scheme type) with data lines. The parser tracks fund_house + scheme_type as rolling context.
- **Intra-group transfers** must be excluded from BOTH conviction promoter-buying AND red-flag promoter-selling. The detector tags both sides of a matched pair (within 5% share-count tolerance, same symbol/date, both within the promoter family). Historical context: BAJAJFINSV, PKTEA, DEEPAKFERT, MIDWESTLTD all double-counted before PR 6 fixed this.
- **Holdings signals + the equity universe.** Sovereign gold bonds, ETFs, and other non-equity holdings correctly land in `NO_SIGNAL` (coverage_score = 0). That's intentional — they're not in the smart-money source universe — and the user-facing label is explicit.
