# Daily analysis pipeline

Runs every weekday at **08:30 IST** (Celery beat entry: `daily-analysis`). Output feeds the **Today** page.

## Pipeline

```
watchlist symbols
      │
      ▼
┌──────────────────────────┐
│ 1. Gather inputs per     │    — latest OHLCV from TimescaleDB
│    symbol                │    — fundamentals (yfinance → Tickertape gap fill → Gemini fallback)
│                          │    — news sentiment for last 24–72h (news_sentiments table)
│                          │    — FII/DII net flow, MF activity deltas
│                          │    — smart-money snapshot via _format_smart_money()
│                          │      (conviction / flow / red-flag + signal_breakdown)
└──────────────┬───────────┘
               ▼
┌──────────────────────────┐
│ 2. Bulk screen           │    Provider: get_ai_provider(user, "screening")
│    (cheap, all symbols)  │    Always Gemini Flash-Lite regardless of the
│                          │    user's deep-analysis provider choice
│                          │    output: {score 0–100, thesis, flags}
└──────────────┬───────────┘
               ▼
       shortlist (score ≥ threshold, capped by user budget)
               ▼
┌──────────────────────────┐
│ 3. Deep analysis         │    Provider: get_ai_provider(user, "analysis")
│    (selective)           │    Default: Gemini Vertex (cheap); user can
│                          │    switch to Anthropic / OpenAI in Settings →
│                          │    AI Analysis. Prompt is provider-agnostic.
│                          │    output: {decision: BUY|HOLD|SELL|WATCH,
│                          │             confidence, rationale, risk_notes}
└──────────────┬───────────┘
               ▼
┌──────────────────────────┐
│ 4. Persist               │    investment_decisions + portfolio_analyses
└──────────────────────────┘
```

The deep-analysis prompt is **provider-agnostic** — plain Markdown, no provider-specific tool use or JSON-mode features — so switching providers is configuration-only.

## Budgets

- Screening: always Gemini Flash-Lite, bounded per call by `provider.estimate_cost()`.
- Deep analysis: capped per user by `settings_json.ai_max_daily_budget_usd` (default **$1/day**). The task calculates cost estimate per symbol and stops short once the cap would be breached. Legacy `opus_max_daily_budget_usd` is still read as a fallback for existing users; on next save it migrates to `ai_max_daily_budget_usd`.
- Env-level backstops: `AI_MAX_DAILY_BUDGET_USD` (current) and `OPUS_MAX_DAILY_BUDGET_USD` (legacy fallback).

## Manual triggers

The UI exposes manual runs so you don't have to wait for the cron:

| Action | Endpoint |
|---|---|
| Re-run daily analysis now | `POST /api/analysis/run-daily` |
| Re-analyze a single stock | `POST /api/analysis/run?symbol=RELIANCE` |
| Toggle schedule on/off | `PATCH /api/settings` with `{daily_analysis_enabled: bool}` |

## Data contracts

`investment_decisions` row (simplified):

| Column | Notes |
|---|---|
| `user_id` | FK → users |
| `symbol` | e.g. `RELIANCE` |
| `decision` | `BUY` \| `HOLD` \| `SELL` \| `WATCH` |
| `confidence` | 0–100 |
| `screener_score` | Gemini score |
| `rationale` | Opus long-form |
| `risk_notes` | Opus |
| `news_sentiment_snapshot` | JSON — aggregated sentiment at decision time |
| `inputs_hash` | dedupe re-runs on same inputs |
| `created_at` | |

## "Today" page consumption

The Today page (`frontend/src/app/(app)/today`) fetches `/api/today` which joins:
- Latest `investment_decisions` per watchlist symbol
- `daily_news_reports` for portfolio holdings (positive/negative headline count)
- Today's FII/DII net flow
- This month's MF activity for holdings
- Live positions + P&L

and renders a single morning brief with actionable cards. Actions now factor in fresh news sentiment, not just the AI decision — a BUY with fresh negative news drops to "review."
