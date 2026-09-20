"""backfill metric_snapshots from existing StockFundamentals rows

Revision ID: b9e1f4d3c2a5
Revises: a8c4d2e0a3f1
Create Date: 2026-05-01 14:30:00.000000

Reads every StockFundamentals row and writes one MetricSnapshot per
symbol so the Fundamental Analysis evaluator has data on day one.
Uses a single synthetic backfill MetricRun that's not tied to a user
(target_user_id is the oldest user). Idempotent — re-running is a
no-op because the run row carries a fixed `target_symbol="__backfill__"`
sentinel and we skip if it already exists.
"""
from typing import Sequence, Union
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision: str = "b9e1f4d3c2a5"
down_revision: Union[str, None] = "a8c4d2e0a3f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# StockFundamentals column → metric_definitions key
COLUMN_TO_METRIC: dict[str, str] = {
    "pe_ratio": "pe_ratio",
    "forward_pe": "forward_pe",
    "pb_ratio": "pb_ratio",
    "revenue_growth_1y": "revenue_growth_1y",
    "eps_growth_1y": "eps_growth_1y",
    "earnings_growth_forward": "earnings_growth_forward",
    "net_profit_margin": "net_profit_margin",
    "debt_to_equity": "debt_to_equity",
    "dividend_yield": "dividend_yield",
    "roe": "roe",
    "promoter_holding": "promoter_holding",
    "market_cap": "market_cap",  # already in ₹ Cr in StockFundamentals
}


def upgrade() -> None:
    conn = op.get_bind()

    # Skip if already backfilled.
    existing = conn.execute(sa.text(
        "SELECT id FROM metric_runs WHERE target_symbol = '__backfill__' AND scope = 'portfolio' LIMIT 1"
    )).fetchone()
    if existing:
        return

    # Pick the oldest user as the run's owner (every user gets the
    # backfilled snapshots — they're symbol-keyed, not user-keyed).
    user_row = conn.execute(sa.text(
        "SELECT id FROM users ORDER BY created_at ASC, id ASC LIMIT 1"
    )).fetchone()
    if not user_row:
        # No users yet — nothing to do. The backfill will run lazily on
        # next refresh once a user exists, since this migration is
        # idempotent.
        return
    user_id = user_row.id

    # Read all StockFundamentals rows.
    cols = ", ".join(["symbol", "exchange", "fetched_at"] + list(COLUMN_TO_METRIC.keys()))
    rows = conn.execute(sa.text(f"SELECT {cols} FROM stock_fundamentals")).fetchall()
    if not rows:
        return

    now = datetime.now(timezone.utc)

    # Create the synthetic backfill run.
    run_res = conn.execute(sa.text("""
        INSERT INTO metric_runs (user_id, scope, target_symbol, started_at, finished_at, status, stocks_total, stocks_ok, stocks_failed)
        VALUES (:uid, 'portfolio', '__backfill__', :now, :now, 'ok', :total, :ok, 0)
        RETURNING id
    """), {"uid": user_id, "now": now, "total": len(rows), "ok": len(rows)})
    run_id = run_res.scalar()

    # Build snapshot rows — one wide-JSONB row per symbol.
    snapshot_payloads: list[dict] = []
    for r in rows:
        values: dict[str, float] = {}
        sources: dict[str, str] = {}
        for col, key in COLUMN_TO_METRIC.items():
            v = getattr(r, col, None)
            if v is None:
                continue
            try:
                values[key] = float(v)
                sources[key] = "backfill"
            except (TypeError, ValueError):
                continue
        if not values:
            continue
        snapshot_payloads.append({
            "run_id": run_id,
            "symbol": (r.symbol or "").upper(),
            "exchange": r.exchange or "NSE",
            "fetched_at": r.fetched_at or now,
            "values_json": values,
            "sources_json": sources,
        })

    if snapshot_payloads:
        # Bulk insert via raw SQL — JSONB columns need a cast.
        for p in snapshot_payloads:
            conn.execute(sa.text("""
                INSERT INTO metric_snapshots
                  (run_id, symbol, exchange, fetched_at, values_json, sources_json)
                VALUES
                  (:run_id, :symbol, :exchange, :fetched_at,
                   CAST(:values AS JSONB), CAST(:sources AS JSONB))
            """), {
                "run_id": p["run_id"],
                "symbol": p["symbol"],
                "exchange": p["exchange"],
                "fetched_at": p["fetched_at"],
                "values": __import__("json").dumps(p["values_json"]),
                "sources": __import__("json").dumps(p["sources_json"]),
            })


def downgrade() -> None:
    conn = op.get_bind()
    # Delete the backfill run + its CASCADE'd snapshots.
    conn.execute(sa.text("DELETE FROM metric_runs WHERE target_symbol = '__backfill__' AND scope = 'portfolio'"))
