"""Compute per-stock smart-money signals.

For every symbol observed in any source table over the relevant lookback
windows we:

1. Compute the **legacy** sub-scores (`deals_score`, `delivery_score`,
   weighted `composite`) — unchanged from before, kept so the current
   UI/Opus prompt don't regress while PRs 4 and 5 are in flight.

2. Compute and persist `net_positions_30d` rows for the symbol via
   `services.smart_money.net_position.compute_net_positions`. This
   replaces the rollup-only "raw deal list" with a per-party netted view
   and is the input for shark-accumulation + circular-suspect detection.

3. Compute the **revamped** scores per spec §7:
       - conviction_score (-100..+100)
       - flow_score       (-100..+100)
       - red_flag_score   (-100..0)
   Each sub-signal degrades gracefully: when the source table is empty
   (e.g. `insider_disclosures` before PR 3 ships) its weight is
   redistributed across available signals and it lands in
   `signal_breakdown.signals_absent`.

4. Upsert one `smart_money_signals` row per (symbol, as_of) carrying
   both the legacy and the new fields.

The Celery beat schedule is unchanged (`19:00 IST M-F`).
"""

from __future__ import annotations

import logging
import math
import statistics
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.smart_money import (
    BhavcopyDaily,
    BulkBlockDeal,
    CorporateAnnouncement,
    FiiDiiStockDaily,
    InsiderDisclosure,
    KnownShark,
    MfHoldingMonthly,
    NetPosition30d,
    ShareholdingPattern,
    SmartMoneySignal,
)
from app.services.smart_money.analyzer import party_classifier as pc
from app.services.smart_money.net_position import NetPosition, compute_net_positions

logger = logging.getLogger(__name__)


# ---- Legacy weights (preserved for backwards compat) -----------------------
DEFAULT_WEIGHTS = {
    "mf": 0.25,
    "pms": 0.15,
    "aif": 0.10,
    "deals": 0.35,
    "delivery": 0.15,
}


# ---- Spec §7 weights -------------------------------------------------------
CONVICTION_WEIGHTS = {
    "promoter_buying": 0.30,
    "shark_accumulation": 0.25,
    "mf_consensus": 0.25,
    "shareholding_delta": 0.20,
}
FLOW_WEIGHTS = {
    "delivery": 0.35,
    "fii_dii_stock": 0.30,
    "block_bulk_net": 0.20,
    "buyback_active": 0.15,
}
# Tier-weight multiplier for shark accumulation
TIER_WEIGHTS = {1: 1.0, 2: 0.7, 3: 0.5}

# Red-flag penalties
RED_FLAG_PENALTIES = {
    "circular_trading": -30,
    "pump_pattern": -40,
    "promoter_selling": -25,
    "high_pledge": -20,           # plus -10 per 10pp above 40
    "pledge_invocation": -40,
}


# ---- Helpers ----------------------------------------------------------------


def _to_float(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _clamp(v: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _round2(v: float | None) -> float | None:
    if v is None:
        return None
    return round(v, 2)


# ---- Symbol discovery -------------------------------------------------------


async def _symbols_of_interest(session: AsyncSession, as_of: date) -> set[str]:
    """Union of symbols that appear in any signal source over their relevant
    lookback windows. Keeps the rollup scoped to live names."""
    syms: set[str] = set()

    deals_since = as_of - timedelta(days=60)
    q = await session.execute(
        select(BulkBlockDeal.symbol)
        .where(BulkBlockDeal.trade_date >= deals_since)
        .distinct()
    )
    syms.update(row[0] for row in q.all())

    bhav_since = as_of - timedelta(days=90)
    q = await session.execute(
        select(BhavcopyDaily.symbol)
        .where(BhavcopyDaily.trade_date >= bhav_since)
        .distinct()
    )
    syms.update(row[0] for row in q.all())

    return syms


# ---- Legacy sub-scores (unchanged) ------------------------------------------


async def _compute_deals_score(
    session: AsyncSession, symbol: str, as_of: date
) -> tuple[float | None, list[dict]]:
    """30-day net bulk/block value normalized by avg daily turnover, mapped
    to ±100 via tanh. Plus the top-5 named-shark deals for display."""
    since = as_of - timedelta(days=30)

    q = await session.execute(
        select(
            BulkBlockDeal.side,
            func.sum(BulkBlockDeal.trade_value_inr).label("sum_v"),
        )
        .where(
            BulkBlockDeal.symbol == symbol,
            BulkBlockDeal.trade_date >= since,
        )
        .group_by(BulkBlockDeal.side)
    )
    sums = {side: _to_float(v) or 0.0 for side, v in q.all()}
    buy = sums.get("BUY", 0.0)
    sell = sums.get("SELL", 0.0)
    net = buy - sell

    t = await session.execute(
        select(func.avg(BhavcopyDaily.turnover_inr))
        .where(
            BhavcopyDaily.symbol == symbol,
            BhavcopyDaily.trade_date >= since,
            BhavcopyDaily.turnover_inr.is_not(None),
        )
    )
    avg_turnover = _to_float(t.scalar_one_or_none()) or 0.0

    if avg_turnover <= 0 or net == 0:
        score: float | None = 0.0 if (buy + sell) == 0 else None
    else:
        normalized = net / (avg_turnover * 3.0)
        score = _clamp(100.0 * math.tanh(normalized))

    ev = await session.execute(
        select(BulkBlockDeal)
        .where(
            BulkBlockDeal.symbol == symbol,
            BulkBlockDeal.trade_date >= since,
            BulkBlockDeal.is_known_shark.is_(True),
        )
        .order_by(BulkBlockDeal.trade_value_inr.desc())
        .limit(5)
    )
    named = [
        {
            "name": d.client_name_raw,
            "side": d.side,
            "quantity": int(d.quantity) if d.quantity is not None else 0,
            "price": _to_float(d.avg_price),
            "value_inr": _to_float(d.trade_value_inr),
            "date": d.trade_date.isoformat(),
            "exchange": d.exchange,
            "deal_type": d.deal_type,
        }
        for d in ev.scalars().all()
    ]

    return (score, named)


async def _compute_delivery_zscore(
    session: AsyncSession, symbol: str, as_of: date
) -> tuple[float | None, dict | None]:
    """5-day avg delivery % vs 90-day baseline as a z-score, mapped to ±100.

    Returns (score, breakdown_dict) so the flow scorer can reuse the raw
    figures in `signal_breakdown`.
    """
    since = as_of - timedelta(days=90)
    recent_cutoff = as_of - timedelta(days=5)

    q = await session.execute(
        select(BhavcopyDaily.trade_date, BhavcopyDaily.delivery_pct)
        .where(
            BhavcopyDaily.symbol == symbol,
            BhavcopyDaily.trade_date >= since,
            BhavcopyDaily.delivery_pct.is_not(None),
        )
    )
    rows = [(d, _to_float(p)) for d, p in q.all()]
    if len(rows) < 10:
        return None, None

    recent = [p for d, p in rows if d > recent_cutoff and p is not None]
    baseline = [p for d, p in rows if d <= recent_cutoff and p is not None]
    if not recent or len(baseline) < 10:
        return None, None

    recent_avg = statistics.mean(recent)
    base_mean = statistics.mean(baseline)
    try:
        base_stdev = statistics.stdev(baseline)
    except statistics.StatisticsError:
        return None, None
    if base_stdev == 0:
        return None, None

    z = (recent_avg - base_mean) / base_stdev
    z_clipped = max(-3.0, min(3.0, z))
    score = _clamp(z_clipped * (100.0 / 3.0))
    breakdown = {
        "recent_avg": round(recent_avg, 2),
        "baseline_avg": round(base_mean, 2),
        "z_score": round(z, 2),
    }
    return score, breakdown


# ---- net_positions_30d population ------------------------------------------


async def _persist_net_positions(
    session: AsyncSession,
    symbol: str,
    as_of: date,
    positions: list[NetPosition],
) -> None:
    """Upsert one row per surviving party. Idempotent on
    (symbol, as_of, party_name_norm)."""
    if not positions:
        return
    for p in positions:
        stmt = pg_insert(NetPosition30d).values(
            symbol=symbol,
            as_of=as_of,
            party_name_norm=p.party_name_norm,
            party_category=p.party_category,
            net_shares=p.net_shares,
            net_value_inr=p.net_value_inr,
            distinct_buy_days=p.distinct_buy_days,
            distinct_sell_days=p.distinct_sell_days,
            is_known_shark=p.is_known_shark,
            is_circular_suspect=p.is_circular_suspect,
            net_to_total_ratio=p.net_to_total_ratio,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "as_of", "party_name_norm"],
            set_={
                "party_category": stmt.excluded.party_category,
                "net_shares": stmt.excluded.net_shares,
                "net_value_inr": stmt.excluded.net_value_inr,
                "distinct_buy_days": stmt.excluded.distinct_buy_days,
                "distinct_sell_days": stmt.excluded.distinct_sell_days,
                "is_known_shark": stmt.excluded.is_known_shark,
                "is_circular_suspect": stmt.excluded.is_circular_suspect,
                "net_to_total_ratio": stmt.excluded.net_to_total_ratio,
            },
        )
        await session.execute(stmt)


# ---- New scorers (spec §7) -------------------------------------------------


async def _shark_tier_lookup(session: AsyncSession) -> dict[str, int]:
    """canonical_name → tier (1/2/3). Used by shark_accumulation."""
    q = await session.execute(
        select(KnownShark.canonical_name, KnownShark.tier).where(KnownShark.active.is_(True))
    )
    return {name: int(tier) for name, tier in q.all()}


async def _compute_conviction(
    session: AsyncSession,
    symbol: str,
    as_of: date,
    positions: list[NetPosition],
    tier_lookup: dict[str, int],
) -> tuple[float | None, dict]:
    """Conviction = weighted sum of: promoter buying, shark accumulation,
    MF consensus, shareholding-Δ. Weight redistributed when a sub-signal
    has no source data."""
    breakdown: dict[str, dict] = {}
    available: list[tuple[str, float]] = []  # (key, normalized_value)

    # --- Promoter open-market buying (from insider_disclosures) ---
    # Excludes rows tagged `is_intra_group_transfer` (addendum A1a).
    # `mode` filter accepts both "Market Purchase" and "Market Sale" —
    # NSE uses `acqMode` to describe the transaction route, not the side,
    # so a promoter Buy can have mode "Market Sale" when shares were
    # received via an on-exchange sale order from another party. Either
    # term means "open-market trade" for our purposes; we exclude ESOPs,
    # off-market transfers, and inter-se transfers explicitly.
    since_90d = as_of - timedelta(days=90)
    q = await session.execute(
        select(
            func.sum(InsiderDisclosure.shares).label("sum_shares"),
            func.count().label("n"),
        )
        .where(
            InsiderDisclosure.symbol == symbol,
            InsiderDisclosure.transaction_date >= since_90d,
            InsiderDisclosure.category.in_(("Promoter", "Promoter Group")),
            InsiderDisclosure.transaction_type == "Buy",
            InsiderDisclosure.mode.in_(("Market Purchase", "Market Sale")),
            InsiderDisclosure.is_intra_group_transfer.is_(False),
        )
    )
    row = q.first()
    if row and row.n and row.n > 0:
        # Normalize: large promoter buys are rare; use a soft-cap mapping.
        # 100k shares ≈ moderate, 1M+ ≈ strong. Map via tanh to ±100.
        shares = int(row.sum_shares or 0)
        normalized = _clamp(100.0 * math.tanh(shares / 500_000.0))
        available.append(("promoter_buying", normalized))
        breakdown["promoter_buying"] = {
            "raw": shares,
            "normalized": round(normalized, 2),
            "source_rows": int(row.n),
        }
    else:
        breakdown["promoter_buying"] = {"raw": None, "normalized": 0.0, "note": "no data"}

    # --- Named-shark accumulation (from net_positions_30d + tier) ---
    sharks_in_play = [p for p in positions if p.is_known_shark and p.net_shares > 0]
    if sharks_in_play:
        weighted_sum = 0.0
        for p in sharks_in_play:
            tier = tier_lookup.get(p.party_name_norm, 1)
            weighted_sum += p.net_shares * TIER_WEIGHTS.get(tier, 1.0)
        # Map via tanh — 250k shares-equivalent is a strong tier-1 signal
        normalized = _clamp(100.0 * math.tanh(weighted_sum / 250_000.0))
        available.append(("shark_accumulation", normalized))
        breakdown["shark_accumulation"] = {
            "raw": int(weighted_sum),
            "normalized": round(normalized, 2),
            "source_rows": len(sharks_in_play),
        }
    else:
        breakdown["shark_accumulation"] = {"raw": None, "normalized": 0.0, "note": "no shark activity"}

    # --- MF consensus (from mf_holdings_monthly) ---
    since_3mo = as_of - timedelta(days=92)
    q = await session.execute(
        select(MfHoldingMonthly.scheme_id, MfHoldingMonthly.change_type)
        .where(
            MfHoldingMonthly.symbol == symbol,
            MfHoldingMonthly.report_month >= since_3mo,
        )
    )
    rows = q.all()
    if rows:
        increased = sum(1 for _, ct in rows if ct in {"increase", "new"})
        decreased = sum(1 for _, ct in rows if ct in {"decrease", "exit"})
        net_houses = increased - decreased
        # (count - 1) × 20 capped to ±100, per spec
        if net_houses != 0:
            normalized = _clamp((net_houses - (1 if net_houses > 0 else -1)) * 20)
            normalized = _clamp(normalized + (20 if net_houses > 0 else -20))
        else:
            normalized = 0.0
        available.append(("mf_consensus", normalized))
        breakdown["mf_consensus"] = {
            "raw": net_houses,
            "normalized": round(normalized, 2),
            "increased": increased,
            "decreased": decreased,
        }
    else:
        breakdown["mf_consensus"] = {"raw": None, "normalized": 0.0, "note": "no data"}

    # --- Shareholding pattern delta (from shareholding_patterns) ---
    q = await session.execute(
        select(ShareholdingPattern)
        .where(ShareholdingPattern.symbol == symbol)
        .order_by(ShareholdingPattern.quarter_end_date.desc())
        .limit(1)
    )
    shp = q.scalar_one_or_none()
    if shp and shp.promoter_delta is not None:
        promoter_delta = _to_float(shp.promoter_delta) or 0.0
        normalized = _clamp(promoter_delta * 10.0)
        available.append(("shareholding_delta", normalized))
        breakdown["shareholding_delta"] = {
            "raw": promoter_delta,
            "normalized": round(normalized, 2),
            "quarter": shp.quarter,
        }
    else:
        breakdown["shareholding_delta"] = {"raw": None, "normalized": 0.0, "note": "no data"}

    # --- Aggregate with weight redistribution ---
    if not available:
        return None, breakdown
    total_weight = sum(CONVICTION_WEIGHTS[k] for k, _ in available)
    if total_weight == 0:
        return None, breakdown
    weighted = sum(CONVICTION_WEIGHTS[k] * v for k, v in available) / total_weight
    return _clamp(weighted), breakdown


async def _compute_flow(
    session: AsyncSession,
    symbol: str,
    as_of: date,
    positions: list[NetPosition],
    delivery_score: float | None,
    delivery_breakdown: dict | None,
) -> tuple[float | None, dict]:
    """Flow = delivery z-score, stock-level FII/DII, block/bulk net by
    institutional categories, buyback-active boost. Weight redistributed."""
    breakdown: dict[str, dict] = {}
    available: list[tuple[str, float]] = []

    # Delivery (already computed)
    if delivery_score is not None:
        available.append(("delivery", delivery_score))
        breakdown["delivery"] = {
            **(delivery_breakdown or {}),
            "normalized": round(delivery_score, 2),
        }
    else:
        breakdown["delivery"] = {"raw": None, "normalized": 0.0, "note": "no data"}

    # Stock-level FII/DII 5d net (from fii_dii_stock_daily)
    since_5d = as_of - timedelta(days=7)  # 5 trading days ≈ 7 calendar
    q = await session.execute(
        select(
            func.sum(FiiDiiStockDaily.fii_net_value).label("fii_net"),
            func.sum(FiiDiiStockDaily.dii_net_value).label("dii_net"),
            func.count().label("n"),
        )
        .where(
            FiiDiiStockDaily.symbol == symbol,
            FiiDiiStockDaily.trade_date >= since_5d,
        )
    )
    fii_row = q.first()
    if fii_row and fii_row.n and fii_row.n > 0:
        fii_net = _to_float(fii_row.fii_net) or 0.0
        dii_net = _to_float(fii_row.dii_net) or 0.0
        net_cr = fii_net + dii_net
        # 50 Cr 5-day net is a strong signal; tanh map.
        normalized = _clamp(100.0 * math.tanh(net_cr / 50.0))
        available.append(("fii_dii_stock", normalized))
        breakdown["fii_dii_stock"] = {
            "fii_net_cr": round(fii_net, 2),
            "dii_net_cr": round(dii_net, 2),
            "normalized": round(normalized, 2),
        }
    else:
        breakdown["fii_dii_stock"] = {"raw": None, "normalized": 0.0, "note": "no data"}

    # Block/bulk net by institutional categories (from net_positions_30d)
    inst_categories = {pc.QUALITY_MF_FPI, pc.OTHER_FUND}
    inst_positions = [p for p in positions if p.party_category in inst_categories]
    if inst_positions:
        net_shares = sum(p.net_shares for p in inst_positions)
        normalized = _clamp(100.0 * math.tanh(net_shares / 500_000.0))
        available.append(("block_bulk_net", normalized))
        breakdown["block_bulk_net"] = {
            "raw": net_shares,
            "normalized": round(normalized, 2),
            "party_count": len(inst_positions),
        }
    else:
        breakdown["block_bulk_net"] = {"raw": None, "normalized": 0.0, "note": "no data"}

    # Buyback active (from corporate_announcements)
    since_90d = as_of - timedelta(days=90)
    q = await session.execute(
        select(func.count())
        .select_from(CorporateAnnouncement)
        .where(
            CorporateAnnouncement.symbol == symbol,
            CorporateAnnouncement.announcement_type == "BUYBACK",
            CorporateAnnouncement.announcement_date >= since_90d,
        )
    )
    n_buyback = int(q.scalar_one() or 0)
    if n_buyback > 0:
        # Binary boost +30
        available.append(("buyback_active", 30.0))
        breakdown["buyback_active"] = {"raw": n_buyback, "normalized": 30.0}
    else:
        breakdown["buyback_active"] = {"raw": 0, "normalized": 0.0, "note": "no buyback in 90d"}

    if not available:
        return None, breakdown
    total_weight = sum(FLOW_WEIGHTS[k] for k, _ in available)
    if total_weight == 0:
        return None, breakdown
    weighted = sum(FLOW_WEIGHTS[k] * v for k, v in available) / total_weight
    return _clamp(weighted), breakdown


async def _compute_red_flags(
    session: AsyncSession,
    symbol: str,
    as_of: date,
    positions: list[NetPosition],
) -> tuple[float, dict]:
    """Sum of triggered penalties, clamped to -100. Breakdown lists the
    specific flags that fired (so the UI can surface them prominently)."""
    triggered: list[str] = []
    detail: dict[str, dict] = {}
    total = 0.0

    # Circular trading
    if any(p.is_circular_suspect for p in positions):
        suspects = [p.party_name_norm for p in positions if p.is_circular_suspect]
        triggered.append("circular_trading")
        detail["circular_trading"] = {
            "penalty": RED_FLAG_PENALTIES["circular_trading"],
            "suspects": suspects[:5],
        }
        total += RED_FLAG_PENALTIES["circular_trading"]

    # Pump pattern: price up >15% in 20 days AND delivery z-score negative.
    # Approximation: pull bhavcopy 20 trading days back, compute pct change,
    # combine with the (already computed) delivery z-score.
    since_30d = as_of - timedelta(days=30)
    q = await session.execute(
        select(BhavcopyDaily.trade_date, BhavcopyDaily.close_price, BhavcopyDaily.delivery_pct)
        .where(
            BhavcopyDaily.symbol == symbol,
            BhavcopyDaily.trade_date >= since_30d,
            BhavcopyDaily.close_price.is_not(None),
        )
        .order_by(BhavcopyDaily.trade_date)
    )
    bhavs = q.all()
    if len(bhavs) >= 15:
        first_close = _to_float(bhavs[0][1])
        last_close = _to_float(bhavs[-1][1])
        if first_close and first_close > 0 and last_close:
            pct_change = (last_close - first_close) / first_close
            recent_dlv = [_to_float(p) for _, _, p in bhavs[-5:] if p is not None]
            baseline_dlv = [_to_float(p) for _, _, p in bhavs[:-5] if p is not None]
            if pct_change > 0.15 and recent_dlv and baseline_dlv:
                if statistics.mean(recent_dlv) < statistics.mean(baseline_dlv):
                    triggered.append("pump_pattern")
                    detail["pump_pattern"] = {
                        "penalty": RED_FLAG_PENALTIES["pump_pattern"],
                        "pct_change_20d": round(pct_change * 100, 2),
                    }
                    total += RED_FLAG_PENALTIES["pump_pattern"]

    # Promoter selling — same intra-group transfer exclusion as the
    # conviction promoter-buying signal.
    since_90d = as_of - timedelta(days=90)
    q = await session.execute(
        select(func.sum(InsiderDisclosure.shares))
        .where(
            InsiderDisclosure.symbol == symbol,
            InsiderDisclosure.transaction_date >= since_90d,
            InsiderDisclosure.category.in_(("Promoter", "Promoter Group")),
            InsiderDisclosure.transaction_type == "Sale",
            InsiderDisclosure.is_intra_group_transfer.is_(False),
        )
    )
    sold = q.scalar_one_or_none()
    if sold and int(sold) > 0:
        triggered.append("promoter_selling")
        detail["promoter_selling"] = {
            "penalty": RED_FLAG_PENALTIES["promoter_selling"],
            "shares_sold": int(sold),
        }
        total += RED_FLAG_PENALTIES["promoter_selling"]

    # High pledge
    q = await session.execute(
        select(ShareholdingPattern.promoter_pledge_pct, ShareholdingPattern.quarter)
        .where(ShareholdingPattern.symbol == symbol)
        .order_by(ShareholdingPattern.quarter_end_date.desc())
        .limit(1)
    )
    shp = q.first()
    if shp and shp.promoter_pledge_pct is not None:
        pledge_pct = _to_float(shp.promoter_pledge_pct) or 0.0
        if pledge_pct > 40:
            base = RED_FLAG_PENALTIES["high_pledge"]
            extra = -10 * math.floor((pledge_pct - 40) / 10)
            penalty = max(-50.0, base + extra)
            triggered.append("high_pledge")
            detail["high_pledge"] = {
                "penalty": penalty,
                "pledge_pct": pledge_pct,
                "quarter": shp.quarter,
            }
            total += penalty

    # Pledge invocation
    q = await session.execute(
        select(func.count())
        .select_from(CorporateAnnouncement)
        .where(
            CorporateAnnouncement.symbol == symbol,
            CorporateAnnouncement.announcement_type == "PLEDGE_INVOKED",
            CorporateAnnouncement.announcement_date >= since_90d,
        )
    )
    n_invoked = int(q.scalar_one() or 0)
    if n_invoked > 0:
        triggered.append("pledge_invocation")
        detail["pledge_invocation"] = {
            "penalty": RED_FLAG_PENALTIES["pledge_invocation"],
            "events": n_invoked,
        }
        total += RED_FLAG_PENALTIES["pledge_invocation"]

    return _clamp(total, lo=-100.0, hi=0.0), {"triggered": triggered, "detail": detail}


# ---- Orchestration ---------------------------------------------------------


async def _compute_for_symbol(
    session: AsyncSession,
    symbol: str,
    as_of: date,
    weights: dict[str, float],
    tier_lookup: dict[str, int],
) -> dict:
    # Legacy
    deals_score, named_sharks = await _compute_deals_score(session, symbol, as_of)
    delivery_score, delivery_breakdown = await _compute_delivery_zscore(session, symbol, as_of)

    legacy_components: list[tuple[float, float]] = []
    for key, score in [("mf", None), ("pms", None), ("aif", None), ("deals", deals_score), ("delivery", delivery_score)]:
        if score is None:
            continue
        legacy_components.append((weights.get(key, 0.0), score))
    if legacy_components:
        total_weight = sum(w for w, _ in legacy_components) or 1.0
        legacy_composite: float | None = _clamp(
            sum(w * s for w, s in legacy_components) / total_weight
        )
    else:
        legacy_composite = None

    # New scorers — populate net_positions_30d first, then read them back
    # via the in-memory list so we don't pay an extra round-trip.
    positions = await compute_net_positions(session, symbol, as_of)
    await _persist_net_positions(session, symbol, as_of, positions)

    conviction_score, conv_breakdown = await _compute_conviction(
        session, symbol, as_of, positions, tier_lookup
    )
    flow_score, flow_breakdown = await _compute_flow(
        session, symbol, as_of, positions, delivery_score, delivery_breakdown
    )
    red_flag_score, rf_breakdown = await _compute_red_flags(
        session, symbol, as_of, positions
    )

    # Assemble signal_breakdown
    available: list[str] = []
    absent: list[str] = []
    for key, sub in conv_breakdown.items():
        if sub.get("raw") is not None:
            available.append(f"conviction.{key}")
        else:
            absent.append(f"conviction.{key}")
    for key, sub in flow_breakdown.items():
        if sub.get("raw") is not None or sub.get("normalized", 0) != 0:
            available.append(f"flow.{key}")
        else:
            absent.append(f"flow.{key}")

    signal_breakdown = {
        "conviction": conv_breakdown,
        "flow": flow_breakdown,
        "red_flags": rf_breakdown,
        "signals_available": available,
        "signals_absent": absent,
        "scores": {
            "conviction": _round2(conviction_score),
            "flow": _round2(flow_score),
            "red_flag": _round2(red_flag_score),
        },
    }

    return {
        "symbol": symbol,
        "as_of": as_of,
        # Legacy fields (preserved)
        "mf_score": None,
        "pms_score": None,
        "aif_score": None,
        "deals_score": _round2(deals_score),
        "delivery_score": _round2(delivery_score),
        "composite": _round2(legacy_composite),
        # New fields
        "conviction_score": _round2(conviction_score),
        "flow_score": _round2(flow_score),
        "red_flag_score": _round2(red_flag_score),
        "signal_breakdown": signal_breakdown,
        "top_adders": None,
        "top_reducers": None,
        "named_sharks": named_sharks or None,
        "meta": {
            "weights_used": weights,
            "generated_at": datetime.utcnow().isoformat(),
            "net_positions_count": len(positions),
        },
    }


async def compute_rollup(
    as_of: date | None = None,
    weights: dict[str, float] | None = None,
    symbols: Iterable[str] | None = None,
) -> dict:
    """Entrypoint for the rollup celery task. Returns counts for run_logger."""
    as_of = as_of or datetime.now().date()
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}

    fetched = 0
    inserted = 0
    updated = 0
    skipped = 0

    # Discover symbols + load tier lookup in one short-lived session.
    async with async_session() as session:
        sym_set = set(symbols) if symbols else await _symbols_of_interest(session, as_of)
        fetched = len(sym_set)
        tier_lookup = await _shark_tier_lookup(session)

    # Per-symbol session so a single bad row doesn't poison the rest of
    # the rollup. With NullPool active in celery this is cheap — the
    # outer loop runs at ~5s for 3000+ symbols on dev.
    for sym in sorted(sym_set):
        try:
            async with async_session() as session:
                row = await _compute_for_symbol(session, sym, as_of, weights, tier_lookup)

                # Skip rule: nothing meaningful to write
                if (
                    row["composite"] is None
                    and row["conviction_score"] is None
                    and row["flow_score"] is None
                    and (row["red_flag_score"] or 0) == 0
                    and not row["named_sharks"]
                ):
                    skipped += 1
                    continue

                stmt = pg_insert(SmartMoneySignal).values(**row)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_sm_signals_symbol_window_date",
                    set_={
                        "mf_score": stmt.excluded.mf_score,
                        "pms_score": stmt.excluded.pms_score,
                        "aif_score": stmt.excluded.aif_score,
                        "deals_score": stmt.excluded.deals_score,
                        "delivery_score": stmt.excluded.delivery_score,
                        "composite": stmt.excluded.composite,
                        "conviction_score": stmt.excluded.conviction_score,
                        "flow_score": stmt.excluded.flow_score,
                        "red_flag_score": stmt.excluded.red_flag_score,
                        "signal_breakdown": stmt.excluded.signal_breakdown,
                        "top_adders": stmt.excluded.top_adders,
                        "top_reducers": stmt.excluded.top_reducers,
                        "named_sharks": stmt.excluded.named_sharks,
                        "meta": stmt.excluded.meta,
                    },
                )
                await session.execute(stmt)
                await session.commit()
                inserted += 1
        except Exception as e:
            logger.warning("rollup failed for %s: %s", sym, e)
            skipped += 1
            continue

    return {
        "as_of": as_of.isoformat(),
        "fetched": fetched,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
    }
