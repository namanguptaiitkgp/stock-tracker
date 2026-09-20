# Indices strip + "why is it moving?" summary

Sticky row of index chips in the AppShell header; click any chip to see
a Gemini-generated summary of drivers drawn from the last 24 hours of
Google News.

## Tracked indices (left to right, Sensex first)

| # | Slug | Display | Source |
|---|---|---|---|
| 1 | `sensex` | BSE Sensex | Kite `BSE:SENSEX` |
| 2 | `nifty50` | Nifty 50 | Kite `NSE:NIFTY 50` |
| 3 | `banknifty` | Nifty Bank | Kite `NSE:NIFTY BANK` |
| 4 | `gift_nifty` | Gift Nifty | Scrape (moneycontrol) — best-effort |
| 5 | `india_vix` | India VIX | Kite `NSE:INDIA VIX` |
| 6 | `nifty_it` | Nifty IT | Kite `NSE:NIFTY IT` |
| 7 | `nifty_midcap100` | Nifty Midcap 100 | Kite `NSE:NIFTY MIDCAP 100` |
| 8 | `nifty_smlcap100` | Nifty Smallcap 100 | Kite `NSE:NIFTY SMLCAP 100` |
| 9 | `nifty_fmcg` | Nifty FMCG | Kite `NSE:NIFTY FMCG` |
| 10 | `nifty_auto` | Nifty Auto | Kite `NSE:NIFTY AUTO` |
| 11 | `nifty_pharma` | Nifty Pharma | Kite `NSE:NIFTY PHARMA` |
| 12 | `nifty_energy` | Nifty Energy | Kite `NSE:NIFTY ENERGY` |

Registry is hardcoded in `backend/app/services/market/indices_registry.py`.

## Data flow

```
Kite quote batch ──┐
                   ├──► indices_quotes.fetch_and_cache_quotes() ──► index_quote_cache
Moneycontrol scrape┘
    (Gift Nifty, graceful-degrade to last known or "—")

Google News RSS ──► indices_summary.refresh_summary_for() ──► Gemini ──► index_news_summary
```

## Cache TTLs

- **Quotes** — 5 min. `GET /api/market/indices` serves cached rows; refreshes if any row older than TTL.
- **Summaries** — 1 hour. `GET /api/market/indices/{slug}/summary` serves cached; force with `POST /.../refresh`.

## Celery beat

```
market-indices-quotes        */5 9-15 * * 1-5   (queue: data)
market-indices-summaries     10 9-16 * * 1-5    (queue: analysis)
```

Both tasks wrap in the shared `ingestion_run(...)` context manager so
runs show up under `ingestion_runs` for the data-freshness strip.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/market/indices` | Bulk quote list |
| POST | `/api/market/indices/refresh` | Force a quote recompute |
| GET | `/api/market/indices/{slug}/summary` | Gemini summary (cache-served) |
| POST | `/api/market/indices/{slug}/summary/refresh` | Force Gemini recompute |

## Gemini output shape

```json
{
  "direction": "UP" | "DOWN" | "FLAT",
  "magnitude": "SHARP" | "MILD" | "FLAT",
  "one_liner": "Sensex fell 1.2% on FII selling + weak global cues.",
  "drivers": [
    { "label": "FII net sell Rs 3,200 Cr", "weight": "high" },
    { "label": "US tech selloff overnight", "weight": "medium" }
  ],
  "what_to_watch": "Tomorrow's CPI print; reaction at 24300 support."
}
```

## Frontend

- `src/components/common/IndicesStrip.tsx` — horizontal-scroll chips, polled every 60 s, mounted in `AppShell.tsx`.
- `src/components/common/IndexSummaryDrawer.tsx` — right-side drawer; direction arrow, one-liner, drivers list, what-to-watch, top headlines, refresh.
- Chips color-coded green (>+0.02%) / red (<-0.02%) / grey. Unavailable indices (Gift Nifty scrape failure) render greyed with "—".

## Gift Nifty caveat

NSE IX / GIFT City is **not** in the Kite instrument universe. We scrape moneycontrol's public page. Regex-based extraction means a layout change can break parsing; when it does, the row retains its previous value with `status="stale"` or falls to `status="unavailable"` with `error_message` filled. The strip continues rendering — never blocks on Gift Nifty alone.

## Related UI additions in the same commit

- **Mask mode** (portfolio privacy) — new toggle button in header; independent from the existing "Privacy Curtain" full-screen overlay. When on, all portfolio totals, quantities, invested/current/P&L values render as `••••` while prices/LTP/action grades/signals stay visible. State persists in localStorage and broadcasts via `window` event so all views update instantly. See `frontend/src/lib/privacy-mode.ts`.
- **Day % change** — added to each holding-action card on the Today page next to the P&L% (P&L% shows change since purchase; day% shows today's move).
