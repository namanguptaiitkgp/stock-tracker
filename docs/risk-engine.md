# Risk engine

Every order goes through the risk engine before it hits Kite. No exceptions, no "temporary bypass" paths.

## Limits

All limits live on `users.settings_json`, with env-level defaults in `.env.example`:

| Key | Env default | Meaning |
|---|---|---|
| `risk_max_position_size_pct` | 10 | Max % of portfolio in a single stock |
| `risk_max_total_exposure_pct` | 80 | Max % of portfolio in equities (keep cash buffer) |
| `risk_max_daily_loss_inr` | 5000 | Realized + unrealized loss; halts new buys once crossed |
| `risk_max_drawdown_pct` | 5 | Drawdown from rolling peak; halts new buys |
| `risk_max_orders_per_day` | 20 | Rate cap across all users (single-admin) |
| `risk_max_order_value_inr` | 100000 | Per-order notional cap |
| `risk_kill_switch` | false | When true, all order placement is refused |

## Evaluation order

For a new order:

1. **Kill switch.** If true, refuse immediately.
2. **Daily order count.** Sum of today's orders including this one vs `risk_max_orders_per_day`.
3. **Per-order value.** `qty × ltp` vs `risk_max_order_value_inr`.
4. **Daily loss.** Aggregate today's P&L; refuse new buys if loss exceeds `risk_max_daily_loss_inr`.
5. **Drawdown.** Current equity vs rolling peak; refuse new buys if drawdown exceeds `risk_max_drawdown_pct`.
6. **Position sizing.** Projected position after fill vs `risk_max_position_size_pct`.
7. **Total exposure.** Projected total equity exposure vs `risk_max_total_exposure_pct`.

Sells that reduce exposure are allowed even when some limits are breached (kill-switch still blocks them).

## Surfacing

- Settings page has sliders and hard-number inputs for each limit plus the kill switch.
- Today page header shows a compact "risk status" chip: green / amber / red with the binding constraint.
- Failed orders return a 400 with `{reason: "risk_max_position_size_pct", current: 14, limit: 10}` so the UI can explain exactly what blocked the trade.

## Kill switch

- Flipping it on is idempotent and reversible; no cleanup required.
- Auto-trip conditions (planned, not all implemented): `risk_max_daily_loss_inr` breached twice in a week, three consecutive risk rejections in under a minute, Kite auth failure during market hours.
- Manual trip is the safe default. Review what happened before turning it off.

## Testing new limits

Before deploying a tweak, exercise `engine` with a test portfolio:

```bash
docker compose exec backend pytest -v tests/engine/test_risk.py
```

Do not test risk changes by placing real orders.
