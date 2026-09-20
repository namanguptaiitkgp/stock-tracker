# Market signals: FII/DII and Mutual Fund activity

Two supplementary data feeds that show up alongside AI decisions on the **Today** page.

## FII / DII activity

Foreign Institutional Investor / Domestic Institutional Investor net flows, from the public NSE daily report.

- **Source:** NSE (public CSV/JSON endpoint fetched via `services/fii_dii.py`).
- **Frequency:** Daily, pulled during the morning tasks window.
- **Stored:** one row per date with `fii_buy`, `fii_sell`, `fii_net`, `dii_buy`, `dii_sell`, `dii_net` (all in INR crore).
- **Surfaced:**
  - Today page header strip — yesterday's net flow + 5-day trend.
  - News page sidebar — when opened, correlates sentiment with flow direction.

The net flow is a market-wide signal (not per-stock). It's a sanity check rather than a trigger: a BUY decision into a day where FIIs dumped Rs 5000 crore of equities deserves a second look.

## Mutual Fund activity

Monthly buy/sell disclosures aggregated from [mfdata.in](https://mfdata.in).

- **Source:** `services/mf_activity.py` — scrapes the public monthly data page.
- **Frequency:** Monthly (MF disclosures are monthly). Re-pulled weekly to catch late revisions.
- **Stored:** per stock × month — which funds bought, which sold, net units, net value.
- **Surfaced:**
  - Per-stock panel on the Watchlist page: "3 funds bought, 1 sold this month."
  - Today page action card augmentation: if the Opus decision is BUY and MFs are net sellers, the card flags it for review.

## Why these are separate from news sentiment

News sentiment is about narrative and near-term reaction. FII/DII and MF activity are about positioning and conviction by large players. They answer different questions — both flow into the AI's deep-dive context so Opus can weigh narrative against positioning.

## Gotchas

- **mfdata.in is a scrape.** Expect occasional empty pulls; data is monthly anyway, so a one-day miss is harmless. Log and skip.
- **NSE endpoint changes.** NSE periodically shuffles its report URLs. Keep the user-agent rotation and retry/backoff in `fii_dii.py` current.
- **Weekends / holidays.** Both feeds skip on non-trading days. The Today page should show "no update" rather than zero-filling.
