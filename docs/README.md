# Docs

Deeper notes on individual subsystems. The top-level `README.md` has the quick-start; this directory is for "how does X actually work."

| Doc | Topic |
|---|---|
| [architecture.md](architecture.md) | Service boundaries, data flow, key modules |
| [authentication.md](authentication.md) | Local admin auth + Kite OAuth handshake |
| [daily-analysis.md](daily-analysis.md) | 8:30 AM IST pipeline — Gemini Flash-Lite screen → user's configured deep-analysis provider via `app/ai/registry.py` |
| [news-sentiment.md](news-sentiment.md) | Google News + Hindu Business Line + Gemini classification |
| [market-signals.md](market-signals.md) | FII/DII activity (NSE) and Mutual Fund activity (mfdata.in) |
| [risk-engine.md](risk-engine.md) | Risk limits, kill switch, per-user settings |
| [auto-push.md](auto-push.md) | The post-commit auto-push hook |
| [smart-money.md](smart-money.md) | Three-stream signal subsystem (conviction / flow / red-flag), insider + corporate-announcement + shareholding-pattern ingestion, holdings signals, coverage diagnostic, Action Summary |
| [indices.md](indices.md) | Live indices strip + Gemini "why is it moving?" summary |
