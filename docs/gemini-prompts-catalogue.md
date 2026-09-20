# Gemini Prompts Catalogue

Working doc for iterating on every Gemini prompt in the codebase. One entry per prompt, sorted by domain. Each entry lists the exact file:line of the template string, what triggers it, its inputs, its expected JSON shape, the model tier (screening = Flash-Lite, analysis = user-configured deep-analysis model), and notes for improvement.

All prompts go through `app.ai.gemini_client.call_gemini_with_rotation()` (multi-credential auto-rotation, see `docs/superpowers/specs/2026-05-11-multi-credential-gemini-rotation-design.md`) unless otherwise noted. Prompts no longer end with the legacy "Return ONLY JSON, no markdown fences" phrasing — they import `STRICT_JSON_BOUNDARY` from `app/ai/prompt_helpers.py` instead (see "v3 changes" below).

## v3 changes — catalogue-driven hardening PR (2026-05-17)

This catalogue has been migrated from 17 live entries down to 15. Section numbers below are preserved for stable backlinks, but two entries are no longer live code:

- **#3 `COMPANY_EXTRACTION_PROMPT`** (Hindu BL extraction) — **DELETED**. Orphaned by commit `b6bfe4c` (News tab unified-aggregator refactor); the inbox classifier (#1) now handles HBL via the same noise-filtered path. See section 3 below for the deletion note.
- **#12 `SUMMARY_LINE_PROMPT`** (card summary line) — **DELETED**. Redundant after commit `9bf636c`; `PositionCard.tsx:458` reads `decision.reasoning` first and the LLM-generated summary line is no longer the load-bearing display string. See section 12.

Section-level systemic changes applied across **all surviving prompts**:

| Change | Source | Applied to |
|---|---|---|
| `STRICT_JSON_BOUNDARY` constant | `app/ai/prompt_helpers.py` | #1, #2, #4, #6, #7, #8, #11, #13, #14, #15, #16 |
| `INDIAN_MACRO_CONTEXT` constant | `app/ai/prompt_helpers.py` | #4, #6, #7, #8 |
| `DECIMAL_OUTPUT_RULE` constant | `app/ai/prompt_helpers.py` | #7, #8, #15, #16 |
| `{today_ist}` date anchor | call-site formatting | #2, #8, #11 |
| Dalal-Street sentiment anchors | inline prompt rewrite | #2 |
| CoT scratchpad before `entry_recommendation` | inline prompt rewrite | #7 (`entry_calculation_scratchpad`) |
| `strategies_diverge` boolean before `reasoning` | inline prompt rewrite | #7 |
| WATCHFUL → TRIM, `technical_scratchpad`, `RegFlag`, parametrised tax | inline prompt rewrite + `app/config.py` | #8 |
| Bellwether anchor names | inline prompt rewrite + `SECTOR_BELLWETHERS` map | #4 |
| `data_quality: rich\|thin` field | inline prompt rewrite + payload derivation | #6 |
| NSE-EQ series filter + stronger don't-pad clause | inline prompt rewrite | #13, #14 |
| Cost fail-safe ("return `{}` if you can't find 3+ values") | inline prompt rewrite | #15, #16 |
| Noise-filter rule (omit macro headlines, synthetic cache) | inline prompt + `classify_headlines` parser | #1 |

Downstream Python: `app/services/regulatory/asm_gsm.py` (new NSE ASM/GSM scraper) feeds `RegFlag` values per portfolio row in #8. `app/tasks/regulatory.py` + a new celery-beat entry (18:30 IST weekdays) refresh the surveillance cache daily.

Threshold re-tunings in `today.py:494` (chip visibility) and `eval_dispatcher.py:28` (`SENTIMENT_SWING_THRESHOLD`) are **deliberately deferred** to a Phase 2 PR ~7 days post-deploy, after observing the new score distribution.

---

## Index

| # | Prompt | File:lines | Domain | Tier | Grounding |
|---|---|---|---|---|---|
| 1 | `PROMPT_TEMPLATE` (inbox classifier) | `services/news/inbox_classifier.py:32-69` | News | screening | — |
| 2 | `SENTIMENT_PROMPT` | `services/news_sentiment.py:16-44` | News | screening | — |
| ~~3~~ | ~~`COMPANY_EXTRACTION_PROMPT`~~ | ~~`services/news_scraper.py`~~ | ~~News~~ | — | **DELETED v3** — folded into #1 |
| 4 | `SECTOR_SENTIMENT_PROMPT` | `services/sector_news.py` (with `SECTOR_BELLWETHERS`) | Market | screening | — |
| 5 | `PROMPT_TEMPLATE` (market pulse) | `services/market/market_pulse.py:33-64` | Market | screening | — |
| 6 | `PROMPT_TEMPLATE` (index drawer) | `services/market/indices_summary.py` | Market | screening | — |
| 7 | `INVESTMENT_DECISION_PROMPT` | `services/investment_decision.py` | Decisions | **analysis** | — |
| 8 | `SELL_STRATEGY_PROMPT` | `api/analysis.py` | Decisions | **analysis** | — |
| 9 | `_build_prompt()` (strategy fit) | `services/strategy_runner.py:208-243` | Decisions | screening | — |
| 10 | `PEER_SUMMARY_PROMPT` | `services/stock_card.py:41-45` | Stock card | screening | — |
| 11 | `QUALITATIVE_PROMPT` | `services/stock_card.py` (+ tools) | Stock card | screening | **Google Search Retrieval** |
| ~~12~~ | ~~`SUMMARY_LINE_PROMPT`~~ | ~~`services/stock_card.py`~~ | ~~Stock card~~ | — | **DELETED v3** — dashboard uses `decision.reasoning` |
| 13 | `PEER_PROMPT` | `services/peer_discovery.py` | Peers | screening | — |
| 14 | `RANK_PROMPT` | `services/peer_discovery.py` | Peers | screening | — |
| 15 | Inline fundamentals gap-fill v1 | `services/fundamentals_service.py` | Fundamentals | screening | `googleSearch` |
| 16 | Inline fundamentals gap-fill v2 | `services/metric_sources/gemini_source.py` | Fundamentals | screening | `googleSearch` |
| 17 | Inline thesis check | `api/watchlist.py:869-890` | Research | screening | — |

---

## News & sentiment

### 1. Inbox news classifier

- **File:** `backend/app/services/news/inbox_classifier.py:32-60`
- **Constant:** `PROMPT_TEMPLATE`
- **Triggered by:** Unified news inbox pipeline — runs over batches of fresh RSS headlines.
- **Inputs:** `{headlines}` — list of headlines prefixed with index numbers.
- **Output shape:** JSON array, one object per input headline, same order.
  ```json
  {
    "headline": "<exact original title>",
    "stocks": [{"symbol": "HDFCBANK", "name": "HDFC Bank"}],
    "sentiment": "tailwind" | "headwind" | "context",
    "confidence": "high" | "medium" | "low"
  }
  ```
- **Caching:** Per-headline DB cache keyed by SHA1(title) → `fetch_cache` with `classify:` prefix.
- **Why it's interesting:** Largest volume call. Includes explicit company-name whitelists for banking + IT to anchor the model on canonical NSE symbols. `context` means "macro/sector with no specific company" and must have empty `stocks`.
- **Exact prompt:**
  ```text
  You are a financial news analyst. For each headline below, identify:
  1. Which NSE/BSE-listed Indian companies are mentioned (use exact NSE trading symbol).
  2. The directional sentiment for those companies:
     - "tailwind" — clearly positive (earnings beat, big order, regulatory tailwind, upgrades)
     - "headwind" — clearly negative (earnings miss, downgrades, fines, deferred orders, lawsuits)
     - "context" — macro/sector/policy news with no clear company-specific directional impact (e.g. RBI policy review, inflation print, govt policy under review). ALSO use "context" if no specific listed company is mentioned.

  Output ONLY a JSON array, no prose, no markdown fences. One object per input headline, in the same order:

  [
    {
      "headline": "<exact original title>",
      "stocks": [{"symbol": "HDFCBANK", "name": "HDFC Bank"}],
      "sentiment": "tailwind" | "headwind" | "context",
      "confidence": "high" | "medium" | "low"
    }
  ]

  Rules:
  - Use the NSE trading symbol (RELIANCE, TCS, HDFCBANK, INFY, etc.) — NOT BSE codes.
  - For banking: HDFCBANK, ICICIBANK, SBIN, KOTAKBANK, AXISBANK, INDUSINDBK, BANDHANBNK, IDFCFIRSTB, etc.
  - For IT: TCS, INFY, WIPRO, HCLTECH, TECHM, LTIM, PERSISTENT, MPHASIS, COFORGE.
  - A headline can mention multiple companies — include all.
  - If headline mentions a parent company (e.g. "Flipkart") of a non-listed entity OR an unlisted competitor, return the affected LISTED Indian counterpart if obvious (e.g. ZOMATO/RELIANCE for Q-commerce headlines), else empty stocks.
  - "context" headlines (no specific company) MUST have empty stocks: [].

  Headlines (one per line, prefixed with index):
  {headlines}
  ```
- **Improvement ideas:**
  - The two long whitelist lines (banking + IT) are hardcoded — moving them to a config makes adding sectors easier.
  - "Context" headlines explicitly require `stocks: []`; consider also requiring `confidence: high` for those (otherwise model invents low-confidence picks).

### 2. Per-stock news sentiment

- **File:** `backend/app/services/news_sentiment.py:16-41`
- **Constant:** `SENTIMENT_PROMPT`
- **Triggered by:** `morning_pipeline` step 2 (per-symbol news classification) — runs over Google News headlines for each portfolio/watchlist symbol.
- **Inputs:** `{symbol}`, `{company_name}`, `{headlines}`.
- **Output shape:**
  ```json
  {
    "sentiment": "bullish" | "bearish" | "neutral",
    "score": -100..100,
    "summary": "2-3 sentences",
    "key_themes": ["..."],
    "headlines": [{"title": "...", "sentiment": "...", "impact": "high|medium|low"}]
  }
  ```
- **Caching:** Result feeds `NewsSentimentCache` table.
- **Exact prompt:**
  ```text
  Analyze the sentiment of these news headlines about the Indian stock {symbol} ({company_name}).

  Headlines (most recent first):
  {headlines}

  Return ONLY a JSON object:
  {
    "sentiment": "bullish" | "bearish" | "neutral",
    "score": <integer from -100 (very bearish) to +100 (very bullish)>,
    "summary": "<2-3 sentence summary of overall news sentiment and what's driving it>",
    "key_themes": ["theme1", "theme2", "theme3"],
    "headlines": [
      {
        "title": "<exact headline>",
        "sentiment": "bullish" | "bearish" | "neutral",
        "impact": "high" | "medium" | "low"
      }
    ]
  }

  Rules:
  - Score 0 means perfectly neutral. Positive = bullish. Negative = bearish.
  - Consider Indian market context (RBI policy, FII flows, sector trends).
  - Rate each headline's impact (high = earnings/results/major news, low = routine).
  - If headlines are mixed, reflect that in a moderate score.
  ```
- **Improvement ideas:**
  - No relevance filter — a headline mentioning the stock incidentally gets the same weight as one about its results. Add a `relevance: 0-100` per headline so the rollup can drop noise.
  - Score range -100..+100 not anchored — model tends to cluster around ±60. Add explicit anchors ("-90 = company-specific fraud/bankruptcy, +90 = beat + raised guidance").

### 3. Hindu Business Line company extraction — **DELETED (v3)**

> Removed in catalogue v3. The unified inbox classifier (#1) already covers HBL via `inbox_aggregator._fetch_hindu_bl` → `classify_headlines`, and the parallel `extract_companies()` function had zero callers. The deletion was confirmed via grep before removal — see plan §C1 for the audit trail.

- **Was:** `backend/app/services/news_scraper.py:24-45` (`COMPANY_EXTRACTION_PROMPT`)
- **Replacement:** Prompt #1 with its new noise-filter rule (omit macro headlines from response array entirely; synthetic-cache the omissions so re-runs are free).

### 4. Sector sentiment

- **File:** `backend/app/services/sector_news.py` — `SECTOR_SENTIMENT_PROMPT`.
- **Tier:** screening.
- **Triggered by:** `morning_pipeline` step 2.5 — runs once per unique sector in the portfolio + watchlist (sector-deduped). Result cached in `SectorAnalysis` table and shared across all stocks in that sector. Also re-runnable on demand via `POST /api/today/sectors/{sector}/refresh`.
- **Inputs:** `{today_ist}`, `{sector}`, `{top_stocks_in_sector}` (top-3 bellwethers from `SECTOR_BELLWETHERS`), `{headlines}` (top 20 from `fetch_google_news(sector_name, days=7)`, pre-sorted by recency).
- **Output shape:**
  ```json
  {
    "sentiment": "bullish" | "bearish" | "neutral",
    "score": -100..100,
    "confidence": "HIGH" | "MEDIUM" | "LOW",
    "macro_drivers": [{"factor": "...", "tilt": "+|-|0", "rationale": "1 sentence"}],
    "key_themes": ["t1", "t2", "t3"],
    "summary": "Exactly 5 sentences",
    "what_to_watch": ["...", "..."]
  }
  ```
  Persisted into `sector_analyses` v3 (migration `d2f8a4b6c1e7`): `score`, `confidence`, `summary`, `macro_drivers`, `what_to_watch`, `top_headlines` (the 8 headlines that fed the prompt) — all alongside the legacy `mood` / `signals` columns so the dashboard's per-holding sector-mood chip doesn't regress.
- **Exact prompt:**
  ```text
  SYSTEM: You are a macro-sector analyst for Dalal Street on {today_ist}.
  INPUT: Nifty Sector: {sector}. Bellwether stocks: {top_stocks_in_sector}. Headlines: {headlines}.
  TASK: Determine the prevailing 7-day sentiment for this sectoral index.
  RULES:
  1. [BELLWETHER FOCUS] Prioritize news affecting {top_stocks_in_sector}, as their market cap dictates the index direction.
  2. [MACRO & DIVERGENCE] Consider Indian macroeconomic factors (RBI MPC, FII/DII flows, capex, PLI schemes, INR/USD). IMPORTANT: When fundamentals are strong but stock reactions are weak (e.g., "good earnings but stock falls"), tilt the score negative — it indicates the market priced in higher expectations.
  3. [STRICT ANCHORS] Score from -100 to +100 based on these exact anchors:
     * +80 to +100: Massive structural tailwinds (e.g., major PLI scheme, massive FII inflow).
     * +30 to +60: Positive earnings cycle for bellwethers, steady macro tailwinds.
     * -10 to +10: Routine noise, mixed signals.
     * -30 to -60: Cyclical downturns, bellwether earnings misses, margin pressures.
     * -80 to -100: Structural headwinds (e.g., severe regulatory crackdown, windfall taxes, demand collapse).
  4. [CONFIDENCE SCORING] Set confidence to "HIGH" if there are >=5 high-impact headlines on bellwether stocks. Set to "LOW" if there are <3 sector-specific headlines. Otherwise, "MEDIUM".
  5. [TRACEABILITY] Every item in `key_themes` MUST be directly traceable to at least one provided headline.
  6. [SUMMARY FORMAT] The summary must be exactly 5 sentences. You must open with the single most important driver.

  OUTPUT FORMAT:
  Start your response with "{" and end with "}". Do not output markdown fences.
  { ...output shape above... }
  ```
- **Improvement ideas (v3 follow-ups):**
  - Macro drivers panel at the top of Market Brief — aggregate `macro_drivers` across all displayed sectors, dedupe by `factor`, render the top 3-4 above the sector list.
  - Sparklines on the sectors list — once sectoral indices (NIFTY IT, NIFTY BANK) are wired via Kite, replace the score-bar column with real price-history sparks.
  - Threshold for `confidence: HIGH` is currently a fixed `>=5 high-impact headlines`. After 2-3 weeks of production data, re-tune based on the actual confidence distribution.

---

## Market pulse & indices

### 5. Market pulse one-liner

- **File:** `backend/app/services/market/market_pulse.py:33-64`
- **Constant:** `PROMPT_TEMPLATE`
- **Triggered by:** `/api/market/pulse` endpoint (and morning pipeline).
- **Inputs:** `{direction}`, `{magnitude}`, `{label}`, `{score}`, `{breadth_up}/{breadth_total}`, `{vix_summary}`, `{movers}` (top 6 index movers by abs change), `{headlines}` (top 30).
- **Output shape:**
  ```json
  {
    "one_liner": "10-15 words",
    "summary": "2-3 sentences connecting moves to drivers",
    "drivers": [{"label": "...", "weight": "high|medium|low", "sentiment": "+|-|n"}],
    "top_headlines": [{"title": "...", "source": "...", "impact": "..."}]
  }
  ```
  > Note: `url` field was removed from the schema in commit `144ea26` — Gemini was copying the literal placeholder string. URLs are now post-processed via `_enrich_top_headlines_with_urls` (matches title back to raw scraper output).
- **Caching:** 30 minutes.
- **Exact prompt:**
  ```text
  You are a market analyst. The Indian stock market direction snapshot:

  Direction: {direction} ({magnitude}) — {label}
  Weighted score: {score:+.2f}%
  Breadth: {breadth_up}/{breadth_total} indices up
  India VIX: {vix_summary}

  Top index movers (positive change_pct = up):
  {movers}

  Recent market headlines (most recent first):
  {headlines}

  Return ONLY a JSON object with this structure — no prose, no markdown fences:
  {
    "one_liner": "one sentence (10-15 words) capturing why the market is {direction} today",
    "summary": "2-3 sentence narrative connecting the index moves to the news drivers",
    "drivers": [
      {"label": "short phrase naming the driver", "weight": "high" | "medium" | "low", "sentiment": "positive" | "negative" | "neutral"}
    ],
    "top_headlines": [
      {"title": "<exact title from headlines above>", "source": "<source name>", "impact": "high" | "medium" | "low"}
    ]
  }

  Rules:
  - `drivers` must have 3-5 items ordered by weight descending. Each must be traceable to at least one headline above.
  - `top_headlines` must have 3-5 items selected from the most impactful headlines above (use exact titles).
  - If headlines are too sparse, set `summary` to acknowledge that and keep drivers minimal.
  - Use India-specific context: FII/DII flows, RBI, budget, crude, INR, banking, IT exports, etc.
  - Be specific. Avoid generic phrases like "mixed sentiment" — say WHAT and WHY.
  ```
- **Improvement ideas:**
  - `drivers must be traceable to at least one headline` is the strongest anti-hallucination clause we have. Consider replicating in other prompts.
  - Headlines limit (30) is high — Flash-Lite handles it but cost adds up. Could trim to 15 most impactful by source.

### 6. Index "why is it moving?" drawer

- **File:** `backend/app/services/market/indices_summary.py:30-56`
- **Constant:** `PROMPT_TEMPLATE`
- **Triggered by:** Click on an index chip in the sticky strip → `GET /api/market/indices/{slug}/summary`.
- **Inputs:** `{display_name}`, `{ltp}`, `{change_pct}`, `{dir_hint}`, `{headlines}`.
- **Output shape:**
  ```json
  {
    "direction": "UP|DOWN|FLAT",
    "magnitude": "SHARP|MILD|FLAT",
    "one_liner": "...",
    "drivers": [{"label": "...", "weight": "..."}],
    "what_to_watch": "..."
  }
  ```
- **Caching:** 1 hour per index.
- **Exact prompt:**
  ```text
  You are a market analyst. Given recent headlines about {display_name}, explain briefly why this index is moving today.

  Today's quote (for context):
  - Last price: {ltp}
  - Change: {change_pct}%
  - Direction: {dir_hint}

  Headlines (most recent first):
  {headlines}

  Return ONLY a JSON object with this structure — no prose, no markdown fences:
  {
    "direction": "UP" | "DOWN" | "FLAT",
    "magnitude": "SHARP" | "MILD" | "FLAT",
    "one_liner": "one sentence that a trader can read in 3 seconds",
    "drivers": [
      {"label": "short phrase naming the driver", "weight": "high" | "medium" | "low"}
    ],
    "what_to_watch": "one sentence on the key near-term trigger"
  }

  Rules:
  - `drivers` must have 2–4 items ordered by weight descending.
  - Every driver label must be traceable to at least one headline above.
  - If headlines are sparse or unclear, say so in `one_liner` and keep `magnitude`: "FLAT".
  - Use India-specific context (FII/DII, RBI, budget, crude, INR, Nifty sector leaders, etc.) where relevant.
  ```
- **Improvement ideas:**
  - Sparse-headlines path: spec says "if sparse, say so + magnitude FLAT" but model often still confabulates. Could add an explicit `data_quality: "thin"` field.

---

## Investment decisions (deep-analysis tier)

### 7. The big investment decision prompt

- **File:** `backend/app/services/investment_decision.py:26-96`
- **Constant:** `INVESTMENT_DECISION_PROMPT`
- **Triggered by:** Manual "Run analysis" on any stock, and the post-close pipeline at 16:00 IST for portfolio holdings (gated by `eval_dispatcher.should_reevaluate`). Routes to the user's configured deep-analysis provider via `get_ai_provider(user, "analysis")` — default Gemini Vertex Flash, can be switched to Anthropic/OpenAI without prompt changes.
- **Inputs:** `{strategy_breakdown}`, `{fundamentals_data}`, `{peer_comparison_context}`, `{technicals_data}`, `{market_context}`, `{smart_money_context}`, `{news_sentiment_context}`.
- **Output shape:**
  ```json
  {
    "verdict": "INVEST|WAIT|AVOID",
    "confidence": 0-100,
    "reasoning": "3-4 sentences",
    "strategy_consensus": {"summary": "...", "best_fit_strategy": "...", "worst_fit_strategy": "..."},
    "valuation_view": "1-2 sentences",
    "technical_view": "1-2 sentences",
    "market_sentiment": {"nifty_trend": "...", "sector_outlook": "...", "sentiment_summary": "..."},
    "entry_recommendation": {"entry_price_low": 0, "entry_price_high": 0, "stop_loss": 0, "target_price": 0, "time_horizon": "..."},
    "key_risks": ["r1", "r2", "r3"],
    "action_items": ["a1", "a2", "a3"]
  }
  ```
- **Why it's the load-bearing prompt:** This is the prompt the rest of the system was built around. Every other prompt either feeds it or post-processes it.
- **Hard constraint:** `entry_recommendation` must have real numbers even for WAIT and AVOID — never zeros. The model frequently violates this; downstream code currently doesn't validate.
- **Exact prompt:**
  ```text
  You are a world-class equity research analyst specializing in the Indian stock market (NSE/BSE).

  A user is asking: "Should I invest in {symbol}?"

  Your job is to synthesize fundamental data, technical data, and multiple investment strategy evaluations into a clear, actionable verdict.

  ## Strategy Evaluations
  Each strategy below has been independently evaluated against this stock's fundamentals.
  A "PASSED" strategy means the stock meets all that strategy's filter criteria.

  {strategy_breakdown}

  ## Fundamentals Data
  {fundamentals_data}

  ## Peer Comparison
  {peer_comparison_context}

  ## Technical Data
  {technicals_data}

  ## Market Context
  {market_context}

  ## Smart-Money Snapshot
  {smart_money_context}

  ## News Sentiment
  {news_sentiment_context}

  ## Instructions
  - Weigh all strategies, fundamentals, and technicals together.
  - Be honest and direct. If the stock is overvalued or risky, say so.
  - When citing valuation as cheap, fair, or stretched, **ground it in the Peer Comparison block above** — cite the peer median and the stock's spread to it (e.g., "PE 74× vs peer median 28× — 2.6× the comparable set"). Absolute thresholds without peer context are weaker. If peer data is unavailable, fall back to your judgment but note the limitation.
  - Consider the Indian market context (FII/DII flows, sector rotation, budget season, etc.).
  - Incorporate the smart-money snapshot: treat named-shark trades and composite signal as corroboration (or contradiction) of fundamentals + technicals. When smart-money disagrees sharply with fundamentals, call out the divergence.
  - Treat the news sentiment as a near-term overlay on the fundamental/technical picture. High-impact recent headlines (earnings, regulatory action, M&A, guidance changes) should shift the verdict or confidence; routine coverage should not. If news disagrees with fundamentals or smart-money, call out the divergence in the reasoning. If the news snapshot is stale or unavailable, note it as a confidence limitation.
  - If data is missing, note that it limits your confidence.
  - ALWAYS populate entry_recommendation with meaningful price levels, even for WAIT or AVOID verdicts:
    - For INVEST: recommended entry zone, target, and stop loss.
    - For WAIT: the price level at which the stock becomes attractive (entry_price_low/high), a downside stop loss, and the upside target if conditions improve. Set time_horizon to reflect when to re-evaluate.
    - For AVOID: a contrarian entry level if the thesis were to reverse, a tight stop loss, and a conservative target. Set time_horizon accordingly.
    - Never return zeros — use the stock's current price, support/resistance levels, and fundamentals to derive real numbers.

  Return ONLY a JSON object with this exact structure:
  {
    "verdict": "INVEST" | "WAIT" | "AVOID",
    "confidence": 0-100,
    "reasoning": "3-4 sentences explaining the verdict",
    "strategy_consensus": {
      "summary": "How strategies collectively view this stock",
      "best_fit_strategy": "Name of strategy that fits best (or null)",
      "worst_fit_strategy": "Name of strategy that fits worst (or null)"
    },
    "valuation_view": "1-2 sentences on valuation (PE, PB, fair value)",
    "technical_view": "1-2 sentences on technicals (trend, momentum, support/resistance)",
    "market_sentiment": {
      "nifty_trend": "Bullish/Bearish/Neutral with context",
      "sector_outlook": "Sector-specific outlook",
      "sentiment_summary": "1-2 sentences overall market sentiment"
    },
    "entry_recommendation": {
      "entry_price_low": 0,
      "entry_price_high": 0,
      "stop_loss": 0,
      "target_price": 0,
      "time_horizon": "e.g. 6-12 months"
    },
    "key_risks": ["risk1", "risk2", "risk3"],
    "action_items": ["action1", "action2", "action3"]
  }
  ```
- **Improvement ideas:**
  - The "ALWAYS populate entry_recommendation" instruction is ignored ~10% of runs (verify via `investment_decisions.entry_price_low = 0` count). Either enforce via Pydantic validator + retry, or split entry_recommendation into separate prompts per verdict.
  - Smart-money + news context guidance is dense ("call out divergence", "stale news = confidence limitation") — model often skips these signals. Could move to a separate "constraints" section at the end.
  - No explicit handling for missing fundamentals — when `{fundamentals_data}` is "--" the model still produces a confident verdict. Add: "If >50% of fundamentals are missing, verdict must be WAIT with reasoning: 'insufficient data'."
  - No `traceability` clause despite this being the highest-stakes prompt — the strongest such clause in the codebase (`market_pulse`, `watchlist:869`, `SELL_STRATEGY_PROMPT`) is *"each claim must be traceable to the data block above"*. Worth adding here.

### 8. Smart Exit System (portfolio-level)

- **File:** `backend/app/api/analysis.py:26-115`
- **Constant:** `SELL_STRATEGY_PROMPT`
- **Triggered by:** `POST /api/analysis/sell-strategy` — manual trigger from dashboard.
- **Inputs:** `{portfolio_data}` (one line per holding with LTP/Avg/PnL%/MAs/52WH/returns/RS30d/PE/PB/RevGr/EPSGr/ROE/DE/Sector), `{market_context}`.
- **Output shape:**
  ```json
  {
    "portfolio_summary": {
      "overall_health": "STRONG|MODERATE|WEAK",
      "sell_count": 0, "hold_count": 0, "watchful_count": 0,
      "key_portfolio_risks": [...],
      "sector_concentration_warning": "...",
      "tax_optimization_note": "..."
    },
    "stocks": [{"symbol": "...", "signal": "HOLD|SELL|WATCHFUL", "confidence": 0-100,
                 "current_price": 0, "target_exit_price": 0, "stop_loss": 0,
                 "pnl_pct": 0, "key_triggers": [...], "tax_impact": "STCG|LTCG",
                 "reasoning": "..."}],
    "top_actions": ["...", "...", "..."]
  }
  ```
- **Best instruction template in the codebase:** The "Ground every technical claim in the numbers above" + data-schema section is the strongest anti-hallucination guard. Worth replicating in prompt #7.
- **Exact prompt:**
  ```text
  You are a world-class equity research analyst specializing in the Indian stock market (NSE/BSE).

  ## Your Strategy Framework: "Indian Market Smart Exit System"
  This is a composite strategy combining the best elements from proven global frameworks, adapted for Indian market characteristics:

  1. **Peter Lynch's Fair Value Exit** — Sell when PEG ratio > 2 or stock overshoots intrinsic value by 30%+
  2. **William O'Neil's CAN SLIM Exit** — Sell if stock drops 7-8% below purchase price (strict stop-loss)
  3. **Trend Following Exit** — Sell when price closes below 50-DMA for 3+ consecutive days
  4. **Trailing Stop Exit** — Dynamic trailing stop at 15-20% from 52-week high
  5. **Relative Strength Exit** — Sell if stock underperforms Nifty 50 for 3+ months

  ## Indian Market Adjustments:
  - Higher volatility in mid/small caps → wider stops (20-25% for small caps)
  - Tax: STCG (20%) for holdings < 1 year, LTCG (12.5%) for > 1 year with Rs 1.25L exemption
  - Quarterly results cycle and Budget season (Feb) create unique volatility
  - FII/DII flow patterns affect large caps differently than small caps
  - Rupee depreciation impact on IT/export vs import-dependent stocks
  - Indian promoter pledge patterns as red flag signals

  ## For each stock in the portfolio below, analyze:
  1. **Signal**: HOLD, SELL, or WATCHFUL (consider partial exit)
  2. **Confidence**: 0-100
  3. **Key Triggers**: Specific conditions that would trigger a sell
  4. **Tax Consideration**: STCG vs LTCG impact
  5. **Target Exit Price**: If SELL, at what price; if HOLD, at what price to sell
  6. **Stop Loss**: Where to place a stop loss
  7. **Reasoning**: 2-3 sentences combining technical + fundamental view

  ## Data schema (per stock line)
  Each stock line below contains the actual computed values you must reason from.
  Do NOT infer price history or trend beyond what is explicitly shown.

  - `LTP` current last traded price; `Avg` your average buy price; `P&L%` unrealized P&L
  - `50DMA`, `200DMA` simple moving averages from daily closes (last ~12 months of data)
  - `52WH`, `52WL` 52-week high / low; `FromHigh` = (LTP - 52WH)/52WH, shows how far below high
  - `30d`, `90d` price returns over last 30 / 90 calendar days (positive = up, negative = down)
  - `RS30d` relative strength vs Nifty-50 over last 30 days (stock return − Nifty return, in %pp)
  - `PE` trailing P/E; `PB` price/book; `RevGr` revenue growth YoY; `EPSGr` earnings growth YoY
  - `ROE` return on equity; `DE` debt-to-equity; `Sector` GICS/Zerodha sector
  - Fields shown as `--` mean data is not available; do not guess the missing value.

  ## Portfolio Data:
  {portfolio_data}

  ## Market context:
  {market_context}

  ## IMPORTANT:
  - Ground every technical claim in the numbers above. If you claim "downtrend",
    it must follow from LTP being below 50DMA / 200DMA, negative 30d/90d returns,
    OR negative RS30d. Do not fabricate trend narratives.
  - If 30d return is strongly positive while 90d is negative, the stock has
    likely bottomed and is recovering — factor this into the recommendation.
  - Be honest. If a stock should be sold, say so clearly.
  - Consider opportunity cost — money in a loser could be in a winner.
  - Analyze current sector rotation in Indian markets.
  - Factor in current market conditions (Nifty trend, global cues).

  Return ONLY a JSON object:
  {
    "portfolio_summary": {
      "overall_health": "STRONG" | "MODERATE" | "WEAK",
      "total_stocks_analyzed": 0,
      "sell_count": 0,
      "hold_count": 0,
      "watchful_count": 0,
      "key_portfolio_risks": ["risk1", "risk2"],
      "sector_concentration_warning": "warning or null",
      "tax_optimization_note": "note about STCG/LTCG optimization"
    },
    "stocks": [
      {
        "symbol": "SYMBOL",
        "signal": "HOLD",
        "confidence": 75,
        "current_price": 0,
        "target_exit_price": 0,
        "stop_loss": 0,
        "pnl_pct": 0,
        "key_triggers": ["trigger1", "trigger2"],
        "tax_impact": "STCG or LTCG",
        "reasoning": "2-3 sentences"
      }
    ],
    "top_actions": [
      "most urgent action 1",
      "most urgent action 2",
      "most urgent action 3"
    ]
  }
  ```
- **Improvement ideas:**
  - Tax slabs are hardcoded ("STCG 20%, LTCG 12.5% with ₹1.25L exemption") — pull from a config so a Union Budget rate change is a one-line fix.
  - The 5 framework names (Lynch / O'Neil / trend / trailing stop / RS) are explanatory, not actionable. Could be trimmed if context becomes a bottleneck.

### 9. Strategy-fit ranking

- **File:** `backend/app/services/strategy_runner.py:208-243`
- **Function:** `_build_prompt()` (inline f-string, not a constant).
- **Triggered by:** "Run strategy on stocks" UI action.
- **Inputs:** Strategy name + type + description + filters (JSON) + signal rules, plus per-candidate scored summary (CMP/PE/PB/DE/RevGr/EPSGr).
- **Output shape:**
  ```json
  {
    "top_picks": ["S1", "S2", "S3"],
    "strategy_fit_summary": "...",
    "stocks": [{"symbol": "...", "signal": "STRONG_BUY|BUY|HOLD|AVOID", "reasoning": "..."}]
  }
  ```
- **Exact prompt:** (inline f-string — `summary_lines` is built one line per candidate stock from `_check_filters` output)
  ```text
  You are evaluating stocks against the "{strategy.name}" strategy.

  Strategy type: {strategy.strategy_type}
  Description: {strategy.description}
  Filters: {json.dumps(filters)}
  Signal rules: {rules}

  ## Candidate stocks (pre-filtered with scores):
  - {symbol}: score={score}, pass={passed}, CMP={cmp}, PE={pe}, PB={pb}, D/E={de}, RevGr={rev_gr}, EPSGr={eps_gr}
  - ... (one line per candidate, up to 15)

  For each stock, give:
  - signal: STRONG_BUY, BUY, HOLD, or AVOID
  - reasoning: 1-2 sentences explaining why this stock fits (or doesn't fit) the strategy

  Return ONLY a JSON object:
  {
    "top_picks": ["SYMBOL1", "SYMBOL2", "SYMBOL3"],
    "strategy_fit_summary": "overall verdict on how well this target set suits the strategy",
    "stocks": [
      {"symbol": "SYM", "signal": "BUY", "reasoning": "..."}
    ]
  }
  ```
- **Improvement ideas:**
  - No grounding clause — the model can pick a stock that failed its own filters. Add: "Don't recommend STRONG_BUY for any stock with `pass=false`."
  - Cap at 15 candidates per call — sufficient context but loses comparative depth. Consider chunked calls with a final aggregator.

---

## Stock card (Today page sections)

### 10. Peer comparison summary

- **File:** `backend/app/services/stock_card.py:41-45`
- **Constant:** `PEER_SUMMARY_PROMPT`
- **Triggered by:** `evaluate_peers()` during morning pipeline step 2.7 (per-stock card refresh).
- **Inputs:** `{symbol}`, `{peers}` (list of peer symbols), `{breakdown}` (JSON of per-metric stock vs peer-median).
- **Output:** Plain text, 2 sentences. No JSON.
- **Exact prompt:** (note the trailing `\` in the source — collapses leading whitespace from the next line)
  ```text
  Summarize this peer comparison for {symbol} vs peers {peers} in 2 sentences.
  Metric comparison: {breakdown}
  Focus on where the stock meaningfully leads or lags. Be specific with numbers. No hedging.
  ```
- **Improvement ideas:**
  - "No hedging" instruction good, but model still defaults to "while the stock leads in X, it lags in Y" structure. Consider: "Lead with the most important number. Avoid 'while' constructions."
  - Token waste — `{breakdown}` is JSON in the prompt; could be condensed to "ROE 28% vs 18%, PE 22 vs 31, …" pipe-separated.

### 11. Qualitative analysis with Google Search Grounding ⭐

- **File:** `backend/app/services/stock_card.py:47-60` (prompt) + `:62-71` (tools)
- **Constant:** `QUALITATIVE_PROMPT` + `QUALITATIVE_TOOLS`.
- **Triggered by:** `evaluate_news_outlook()` during morning pipeline step 2.7.
- **Special:** Uses `googleSearchRetrieval` with `mode: MODE_DYNAMIC, dynamicThreshold: 0.3` — Gemini fetches live Google Search + Google Finance data. This is the only stock-level prompt with live web access.
- **Inputs:** `{company_name}`, `{symbol}` — that's it. Model pulls everything else from Search.
- **Output shape:**
  ```json
  {
    "company_overview": "1 sentence",
    "overall_sentiment": "Bullish|Bearish|Neutral",
    "bull_case": ["bullet 1", "bullet 2"],
    "bear_case": ["bullet 1", "bullet 2"],
    "earnings_highlights": "2 sentences"
  }
  ```
- **Cost:** Higher than plain Flash-Lite — grounding adds ~100 input tokens + the search itself. ~$0.003/call. ~$0.06/day for 20 holdings.
- **Exact prompt:** (one long sentence — line-continuation backslashes collapse line breaks in the source)
  ```text
  Using your access to live Google Search and Google Finance, perform a qualitative analysis of {company_name} (NSE: {symbol}) based on information from the past 30 days. Return the response strictly as a JSON object without any markdown formatting. Use the following keys: 'company_overview' (a 1-sentence business summary), 'overall_sentiment' (classify as Bullish, Bearish, or Neutral), 'bull_case' (an array of 2 bullet points detailing current growth drivers or positive catalysts), 'bear_case' (an array of 2 bullet points detailing current risks or headwinds), and 'earnings_highlights' (a 2-sentence summary of management commentary from the most recent earnings or latest major corporate announcement).
  ```
- **Grounding tools config:**
  ```python
  QUALITATIVE_TOOLS = [
      {
          "googleSearchRetrieval": {
              "dynamicRetrievalConfig": {
                  "mode": "MODE_DYNAMIC",
                  "dynamicThreshold": 0.3,
              }
          }
      }
  ]
  ```
- **Improvement ideas:**
  - "Past 30 days" is the only temporal anchor — too loose. Could include the current date (`{today_ist}`) so model knows what "past 30 days" actually means.
  - Search threshold 0.3 is low (more aggressive search). Consider raising to 0.5 for stocks where we already have rich cached news — grounding becomes duplicative.
  - Always exactly 2 bullets per side — sometimes there are 4 bull-case items worth surfacing. Make it "2-4 bullets" with a quality bar.

### 12. Card summary line — **DELETED (v3)**

> Removed in catalogue v3. After commit `9bf636c`, `PositionCard.tsx:458` renders `h.reasoning || h.summary_line || headline` — `decision.reasoning` from the deep-analysis prompt always wins for rendered cards, and the fallback chain falls through to the computed `headline` for stocks without a deep-analysis row. The dedicated `SUMMARY_LINE_PROMPT` call was an entire Gemini round-trip per stock per analysis run producing data that's redundant with what `reasoning` already says. See plan §C2 for the audit trail.

- **Was:** `backend/app/services/stock_card.py:73-80` (`SUMMARY_LINE_PROMPT`, `generate_summary_line()`)
- **Replacement:** `decision.reasoning` from #7 (`INVESTMENT_DECISION_PROMPT`) drives the rendered card text. `refresh_stock_analysis` now passes `summary_line=None` and the existing column stays NULL for new rows.

---

## Peer discovery

### 13. Cold-start peer discovery

- **File:** `backend/app/services/peer_discovery.py:27-68`
- **Constant:** `PEER_PROMPT`
- **Triggered by:** First time we need peers for a stock — no cached `peer_sets` row. Now also fired from the `warm_peers_for_symbol` Celery task (commit `c299211`) on watchlist add, Kite portfolio sync, news opportunity surfacing, and lazy on first `/api/market-data/peers/{symbol}` fetch.
- **Inputs:** `{symbol}`, `{name}`, `{sector}`, `{industry}`, `{market_cap_display}`, `{cap_category}`.
- **Output shape:**
  ```json
  {
    "peers": [{"symbol": "NSE_SYMBOL", "rationale": "one line"}],
    "notes": "caveats or null"
  }
  ```
- **Strong instruction:** Explicit handling for near-monopolies (IRCTC/CDSL/IEX), conglomerate subsidiaries, PSU vs private. This is the most carefully-tuned prompt for handling Indian-market edge cases.
- **Exact prompt:**
  ```text
  You are an Indian equity market analyst. Identify 6–8 true peer companies for
  {symbol} ({name}).

  Company profile:
  - Sector: {sector}
  - Industry: {industry}
  - Market cap: ₹{market_cap_display} ({cap_category})

  Definition of a "true peer":
  1. SAME SUB-INDUSTRY — not adjacent. A private bank's peer is another private
     bank, not an NBFC, insurance company, or payments fintech. A tyre maker's
     peer is another tyre maker, not an auto-ancillary broadly.
  2. COMPARABLE SCALE — prefer within ~3× market cap, but for niche industries
     with few listed players (e.g. tyres, exchanges, defence), include ALL
     industry participants regardless of cap difference.
  3. SIMILAR BUSINESS MODEL — same revenue mix (B2B vs B2C, product vs platform,
     domestic vs export). A domestic pharma formulator is not a peer to a
     CRAMS/CDMO export house.
  4. DIRECT COMPETITOR or close substitute in the same value chain position
     (not supplier/customer).
  5. LISTED ON NSE.

  Special cases:
  - If the company is a near-monopoly (e.g. IRCTC, CDSL, IEX), say so and
    suggest the closest functional comparables even if imperfect. Label them
    as "closest comparable (not a direct peer)."
  - If the company is a conglomerate subsidiary, compare the subsidiary's
    primary business, not the parent.
  - PSU vs private distinction matters for valuation — include both if relevant
    but note the distinction.

  Return ONLY valid JSON:
  {
    "peers": [
      {"symbol": "NSE_SYMBOL", "rationale": "one line explaining why this is a peer"}
    ],
    "notes": "any caveats about peer selection for this stock (optional, can be null)"
  }

  Use NSE trading symbols (e.g. HDFCBANK, RELIANCE, TCS). Return 6–8 peers,
  ordered by relevance (closest peer first).
  ```
- **Improvement ideas:**
  - Cap category buckets (Large 50K+, Mid 10K+, Small <10K Cr) are different from the dashboard's SEBI buckets (20K/5K — see `redundancy-audit.md §2a`). Unifying these is on the cleanup list.
  - "Listed on NSE" is the only filter — model occasionally returns BSE-only or unlisted comparables that fail verification. Add: "Each suggested symbol must be actively traded on NSE in the EQ series."

### 14. Peer ranking from verified list

- **File:** `backend/app/services/peer_discovery.py:71-103`
- **Constant:** `RANK_PROMPT`
- **Triggered by:** Second pass after `PEER_PROMPT` candidates are verified against the NSE symbol list.
- **Inputs:** `{symbol}`, `{name}`, `{sector}`, `{industry}`, `{market_cap_display}`, `{cap_category}`, `{candidates_block}` (verified NSE symbols only).
- **Output:** Same shape as PEER_PROMPT.
- **Note:** The sub-industry strictness is explicit and great ("If {symbol} is a tyre manufacturer, pick ONLY other tyre manufacturers, NOT generic auto parts").
- **Exact prompt:**
  ```text
  You are an Indian equity market analyst. I need you to pick the 6–8 best peer
  companies for {symbol} ({name}) from the VERIFIED list below.

  Target company:
  - Sector: {sector}
  - Industry: {industry}
  - Market cap: ₹{market_cap_display} ({cap_category})

  VERIFIED CANDIDATES (all real NSE-listed companies):
  {candidates_block}

  IMPORTANT: Pick ONLY companies in the SAME specific sub-industry as {symbol}.
  For example:
  - If {symbol} is a tyre manufacturer, pick ONLY other tyre manufacturers,
    NOT generic auto parts companies like brake/glass/electronics makers.
  - If {symbol} is a jewellery retailer, pick ONLY other jewellery retailers,
    NOT generic luxury goods companies.

  The industry classification "{industry}" may be broad — use your knowledge
  of each company's actual business to pick true peers.

  Pick the best peers, ranked by relevance (closest peer first). Aim for
  6–8, but if there are fewer true sub-industry peers, return only those —
  do NOT pad the list with companies from adjacent industries.

  Return ONLY valid JSON:
  {
    "peers": [
      {"symbol": "NSE_SYMBOL", "rationale": "one line explaining why this is a peer"}
    ],
    "notes": "any caveats (optional, can be null)"
  }
  ```
- **Improvement ideas:**
  - "Do NOT pad the list" instruction is well-phrased but the model still pads. Consider adding: "It is better to return 3 true peers than 8 with 5 adjacent-industry filler."

---

## Fundamentals gap-fill (with Google Search grounding)

### 15. Gap-fill v1 (stock_fundamentals path)

- **File:** `backend/app/services/fundamentals_service.py:274-280` (inline prompt; helper `_fill_gaps_with_gemini` starts at :248)
- **Triggered by:** Final fallback in `get_fundamentals()` after Screener → yfinance → NSE ownership all leave fields null.
- **Inputs:** `{symbol}`, `{null_fields}` (subset of `field_labels`).
- **Grounding:** `tools=[{"googleSearch": {}}]`.
- **Output:** Flat JSON with only the requested keys; null if uncertain; decimals for percentages (15% → 0.15).
- **Field labels passed in the `Needed:` dict** (defined at `:252-267`):
  - `debt_to_equity`: "Debt to Equity ratio (number, e.g. 0.5)"
  - `roe`: "Return on Equity (decimal, e.g. 0.15 for 15%)"
  - `revenue_growth_1y`: "Revenue Growth 1 Year (decimal, e.g. 0.12 for 12%)"
  - `eps_growth_1y`: "EPS Growth 1 Year (decimal, e.g. 0.10 for 10%)"
  - `net_profit_margin`: "Net Profit Margin (decimal, e.g. 0.08 for 8%)"
  - `forward_pe`: "Forward P/E ratio (number, e.g. 20.5)"
  - `promoter_holding`: "Promoter Holding percentage (number, e.g. 47.2 for 47.2%)"
  - `pe_ratio`: "Trailing P/E ratio (number, e.g. 22.5)"
  - `pb_ratio`: "Price to Book ratio (number, e.g. 3.2)"
  - `dividend_yield`: "Dividend Yield (decimal, e.g. 0.012 for 1.2%)"
  - `market_cap`: "Market Capitalization in Crores (number, e.g. 1500000)"
  - `earnings_growth_forward`: "Forward Earnings Growth (decimal, e.g. 0.15 for 15%)"
  - `high_52w`: "52-Week High price in Rupees (number, e.g. 3217.0)"
  - `low_52w`: "52-Week Low price in Rupees (number, e.g. 2220.0)"
- **Exact prompt:** (inline f-string)
  ```text
  For the Indian stock {symbol} listed on NSE, provide these financial metrics.
  Return ONLY a JSON object with these exact keys. Use null for any value you are not confident about.
  All percentage values should be decimals (e.g., 15% = 0.15). Debt/Equity and P/E are plain numbers.

  Needed: {json.dumps({f: field_labels.get(f, f) for f in null_fields if f in field_labels})}

  Return JSON only, no explanation.
  ```
- **Improvement ideas:**
  - Identical-shape sibling at #16. Both paths should call a single helper.
  - No upper bound on retries — if the model returns null for everything, we still spend the Search Grounding cost. Add: "If you cannot find 3+ values from authoritative sources, return `{}` and we'll skip."

### 16. Gap-fill v2 (metric_snapshots path)

- **File:** `backend/app/services/metric_sources/gemini_source.py:89-95` (inline)
- **Triggered by:** Final source in `metric_engine._gather_one()` chain.
- **Differences from #15:**
  - Reads `_FIELD_LABELS` from the metric_engine config, not `field_labels` from fundamentals_service.
  - Logs filled metrics on success.
- **Exact prompt:** (inline f-string — slightly tighter wording than v1)
  ```text
  For the Indian stock {symbol} listed on NSE, provide these financial metrics.
  Return ONLY a JSON object with these exact keys. Use null for any value you are not confident about.
  All percentage values should be decimals (e.g., 15% = 0.15).

  Needed: {json.dumps(needed)}

  Return JSON only, no explanation.
  ```
- **Improvement ideas:**
  - Will become redundant once `redundancy-audit.md §R7` (fundamentals unification) lands. Until then, keep them in sync.

---

## Watchlist research

### 17. Thesis-check + peer dynamics

- **File:** `backend/app/api/watchlist.py:869-890` (inline f-string)
- **Triggered by:** `POST /api/watchlist/{id}/items/{item_id}/research` — user-initiated research on a specific watchlist item.
- **Inputs:** `{item.symbol}`, `{item.name}`, `{item.reason}` (the user's stated thesis), `{blocks}` (headline blocks for the symbol + named peers).
- **Output shape:**
  ```json
  {
    "thesis_check": "1-2 sentences: does recent news support or challenge the thesis?",
    "tailwinds": ["bullet 1", "..."],
    "headwinds": ["bullet 1", "..."],
    "peer_dynamics": ["bullet — how peers are doing", "..."],
    "watch_items": ["specific catalyst over next 4-8 weeks", "..."],
    "summary": "2-3 sentence executive summary"
  }
  ```
- **Side effect:** Writes a `WatchlistJournalEntry` with the summary.
- **Exact prompt:** (inline f-string — `{blocks}` is built one section per symbol, with `### SYM` headers and headline lines like `- [{pub_date}] {title} ({source})`)
  ```text
  You are an equity research analyst. The user is researching {item.symbol} ({item.name or ''}).
  {f"Their thesis: {item.reason}" if item.reason else ""}

  Below are recent headlines for {item.symbol} and its named peers. Synthesize a comprehensive analysis.

  {blocks}

  Return a JSON object only — no prose, no fences:
  {
    "thesis_check": "1-2 sentences: does the recent news support or challenge the user's thesis?",
    "tailwinds": ["bullet 1", "bullet 2", "..."],
    "headwinds": ["bullet 1", "..."],
    "peer_dynamics": ["bullet — how peers are doing relative to {item.symbol}", "..."],
    "watch_items": ["specific catalyst/event/data to watch over the next 4-8 weeks", "..."],
    "summary": "2-3 sentence executive summary"
  }

  Rules:
  - Use 3-5 bullets per array, max 8.
  - Each bullet must be traceable to at least one headline above.
  - Be specific — name the catalyst or risk.
  ```
- **Improvement ideas:**
  - Best traceability clause in the codebase: "Each bullet must be traceable to at least one headline above." Replicate in #2 and #7.
  - 3-5 bullets per array, max 8 — sometimes too loose. Consider strict 3-5 with a tie-breaker rule ("if tied, prefer most recent headline").

---

## Cross-cutting improvement themes

### A. Hallucination control — uneven across prompts

The best traceability clauses live in:
- `market_pulse.PROMPT_TEMPLATE` — "Every driver label must be traceable to at least one headline above"
- `watchlist.py:869` — "Each bullet must be traceable to at least one headline above"
- `analysis.py.SELL_STRATEGY_PROMPT` — "Ground every technical claim in the numbers above"

These should be replicated in `investment_decision.INVESTMENT_DECISION_PROMPT` (currently has no traceability clause despite being the highest-stakes prompt).

### B. Confidence anchoring

`SENTIMENT_PROMPT`, `INVESTMENT_DECISION_PROMPT`, and the strategy-fit prompts all return 0-100 confidence but provide no scale anchors. The model clusters around 60-80 for everything. Adding two anchors per scale ("90 = X, 30 = Y") would spread the distribution.

### C. JSON-only enforcement

Every prompt says "JSON only, no markdown fences" — and yet 6 fence-strippers exist in the codebase (`redundancy-audit.md §3a`). Consolidating to one utility is the cleanup task; tightening the prompt instruction itself is the prompt-engineering task. Worth trying: "Start your response with `{` and end with `}`. Do not output anything else."

### D. Date awareness

No prompt currently includes the current IST date. For prompts with temporal logic (`QUALITATIVE_PROMPT`'s "past 30 days", `SENTIMENT_PROMPT`'s headline freshness), pass `{today_ist}` so the model knows the anchor.

### E. Missing-data handling

`INVESTMENT_DECISION_PROMPT` says "If data is missing, note that it limits your confidence" — but never enforces a degraded verdict. Consider: "If >50% of fundamentals/technicals are missing, verdict must be WAIT and confidence ≤30."

### F. Token-efficiency wins

- `PEER_SUMMARY_PROMPT` passes the metric breakdown as JSON (~120 tokens) when a pipe-separated string would do (~40 tokens).
- `INVESTMENT_DECISION_PROMPT` has full section headers (`## Fundamentals Data`, `## Technical Data`, etc.) for context that the model uses positionally anyway. Tightening to `FUND:`, `TECH:` saves ~30 tokens per call × thousands of calls/day.

### G. Provider portability

All prompts are written for Gemini but routed through `app.ai.registry.get_ai_provider()` which can dispatch to Anthropic or OpenAI. None of them use Gemini-specific features (function calling, JSON mode) — that's good. But:
- `QUALITATIVE_PROMPT` uses Gemini Search Grounding (`googleSearchRetrieval`). When switching providers, this needs a substitute (Anthropic web_search tool, OpenAI tool calling). Currently the fallback is unhandled.
- Fundamentals gap-fills #15 + #16 same issue.

---

## How to iterate

1. **Pick a prompt** from the index.
2. **Read the live template** at the file:line citation (don't edit blind — the table here may go stale).
3. **Write a test case** in `backend/tests/` against the prompt with a known-input/known-output pair.
4. **Edit in place.** All prompts are module-level constants or inline f-strings — no DB seeding.
5. **Verify with `make test`** + a manual run through the morning pipeline (`POST /api/today/refresh`).

For high-stakes prompts (#7, #8, #11), capture a baseline of 20 runs before and after the change. The `ai_usage_log` table records every call with prompt-purpose tag — query it for before/after comparison.
