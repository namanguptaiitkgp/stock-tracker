# News sentiment

Two-stage pipeline: **scrape → classify**. Every weekday at **06:30 IST** (`morning-news-scan`) plus on-demand from the News page.

## Sources

| Source | Module | Notes |
|---|---|---|
| Google News RSS | `services/news_scraper.py` | Multi-query, 30-day window, supports custom queries, force-refresh |
| Hindu Business Line | `services/news_scraper.py` (HBL scraper) | HTML scrape of company page |
| User-pinned feeds | `services/news_scraper.py` | Optional, per-user |

All scrapers are best-effort — one failing source must not break the scan. Errors are logged and the pipeline continues with whatever succeeded.

## Classification

`services/news_sentiment.py` sends each article (headline + snippet, not full body) to Gemini Flash-Lite:

```
sentiment: positive | negative | neutral
impact:    low | medium | high
rationale: one sentence
relevance: 0–100 (how directly the article concerns this ticker)
```

Results land in `news_sentiments` (one row per article × symbol) and roll up into `daily_news_reports` (one row per user × symbol × date).

## UI surface

`/news` (frontend):
- Filters: all vs portfolio-holdings only, date range, sentiment, source.
- "View All Headlines" popup shows the raw feed for a stock, including neutrals.
- Per-article: sentiment badge, relevance, source, link, Gemini's one-line rationale.

The **Today** page uses daily roll-ups to adjust the AI decision (see `daily-analysis.md`).

## Caveats

- **RSS is stale-ish.** Google News RSS lags the web by several minutes; for breaking-news trading don't rely on this alone.
- **HTML scrapes break.** Hindu Business Line HTML can change. If counts fall to zero overnight, suspect selector drift. See `tests/services/test_hbl_scraper.py` (if present) or scrape manually to verify.
- **Relevance filtering.** We use Gemini's `relevance` score to drop false-positive matches (e.g., a "Reliance Industries" mention in an unrelated article). Threshold is tunable via settings.
- **Cost.** Flash-Lite is cheap per call, but morning scan can generate hundreds of articles across holdings. If costs climb, lower the article cap per symbol in settings before upgrading the model.
