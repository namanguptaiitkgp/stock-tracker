"""30-day net position calculator + circular-trading detector.

For each (symbol, party) pair seen in `bulk_block_deals` over a rolling
window, compute net shares / net value / activity-day counts, drop noise
(intermediaries, negligible positions, near-square-offs), and flag
circular-trading suspect pairs (mirror-volume A buys ↔ B sells within
10%).

The output is a list of `NetPosition` dataclasses which the smart-money
rollup (a) persists into `net_positions_30d` and (b) reads back to
compute the named-shark conviction signal and the block/bulk flow
signal.

Per spec §5: this module does NOT have its own Celery beat entry — the
rollup invokes it directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.smart_money import BulkBlockDeal, KnownShark
from app.services.smart_money.analyzer import party_classifier as pc

# Categories that get dropped before scoring — they're intermediaries,
# not principals putting their own conviction behind a position.
_DROP_CATEGORIES = {pc.PROP_HFT, pc.BROKER}

# Minimum gross share count below which we treat the position as noise.
# Free-float-relative threshold (0.01%) lives in the rollup where free
# float is fetched per symbol; this is the absolute floor.
_ABSOLUTE_GROSS_FLOOR = 1_000

# Square-off filter: if |net| / gross is within this fraction of zero,
# treat as square-off and drop. e.g. 0.05 means "drop parties whose net
# is within 5% of their gross."
_SQUARE_OFF_TOL = 0.05

# Circular-pair detection: A and B flagged when |A_buy - B_sell| / max(...)
# is below this fraction.
_CIRCULAR_PAIR_TOL = 0.10


@dataclass
class NetPosition:
    party_name_norm: str
    party_category: str
    net_shares: int
    net_value_inr: float
    distinct_buy_days: int
    distinct_sell_days: int
    is_known_shark: bool = False
    is_circular_suspect: bool = False
    # |net| / gross. ~1.0 = clean directional bet; ~0.05 = squaring off.
    # Set in `compute_net_positions`. Persisted on `net_positions_30d`
    # for the /net-traders endpoint's ratio filter.
    net_to_total_ratio: float = 0.0


def _to_int(v) -> int:
    if v is None:
        return 0
    if isinstance(v, Decimal):
        return int(v)
    return int(v)


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


async def _load_known_shark_norms(session: AsyncSession) -> set[str]:
    """Return the set of normalized canonical names for active known sharks
    so callers can flag rows. Aliases are NOT applied here — `_norm_client`
    is the matching key for raw client names, but for the purposes of the
    net-position rollup we already store `client_name_norm` on the deal
    row, so we just look up that normalized form against the canonical
    name set."""
    q = await session.execute(
        select(KnownShark.canonical_name).where(KnownShark.active.is_(True))
    )
    return {row[0] for row in q.all()}


async def compute_net_positions(
    session: AsyncSession,
    symbol: str,
    as_of: date,
    *,
    window_days: int = 30,
    free_float_shares: int | None = None,
) -> list[NetPosition]:
    """Compute net positions per party for `symbol` over the trailing
    `window_days` ending on `as_of`.

    `free_float_shares` is optional — if provided, the noise filter
    drops parties whose |net_shares| < 0.01% of free float. Without it,
    we fall back to `_ABSOLUTE_GROSS_FLOOR`.
    """
    since = as_of - timedelta(days=window_days)

    # Aggregate per party
    rows = await session.execute(
        select(
            BulkBlockDeal.client_name_norm,
            BulkBlockDeal.client_name_raw,
            BulkBlockDeal.side,
            func.sum(BulkBlockDeal.quantity).label("qty"),
            func.sum(BulkBlockDeal.trade_value_inr).label("val"),
            func.count(distinct(BulkBlockDeal.trade_date)).label("days"),
        )
        .where(
            BulkBlockDeal.symbol == symbol,
            BulkBlockDeal.trade_date >= since,
            BulkBlockDeal.trade_date <= as_of,
        )
        .group_by(
            BulkBlockDeal.client_name_norm,
            BulkBlockDeal.client_name_raw,
            BulkBlockDeal.side,
        )
    )

    # Bucket by party
    by_party: dict[str, dict] = {}
    for norm, raw, side, qty, val, days in rows.all():
        slot = by_party.setdefault(
            norm,
            {
                "raw": raw,
                "buy_qty": 0,
                "sell_qty": 0,
                "buy_val": 0.0,
                "sell_val": 0.0,
                "buy_days": 0,
                "sell_days": 0,
            },
        )
        if side == "BUY":
            slot["buy_qty"] += _to_int(qty)
            slot["buy_val"] += _to_float(val)
            slot["buy_days"] += int(days or 0)
        elif side == "SELL":
            slot["sell_qty"] += _to_int(qty)
            slot["sell_val"] += _to_float(val)
            slot["sell_days"] += int(days or 0)

    if not by_party:
        return []

    shark_set = await _load_known_shark_norms(session)
    abs_floor = max(
        _ABSOLUTE_GROSS_FLOOR,
        int((free_float_shares or 0) * 0.0001),
    )

    positions: list[NetPosition] = []
    for norm, slot in by_party.items():
        gross = slot["buy_qty"] + slot["sell_qty"]
        net = slot["buy_qty"] - slot["sell_qty"]

        if gross < abs_floor:
            continue

        # Square-off filter
        if gross > 0 and abs(net) / gross < _SQUARE_OFF_TOL:
            continue

        # Category from name
        classification = pc.classify(slot["raw"])
        if classification.category in _DROP_CATEGORIES:
            continue

        ratio = (abs(net) / gross) if gross > 0 else 0.0
        positions.append(
            NetPosition(
                party_name_norm=norm,
                party_category=classification.category,
                net_shares=int(net),
                net_value_inr=float(slot["buy_val"] - slot["sell_val"]),
                distinct_buy_days=slot["buy_days"],
                distinct_sell_days=slot["sell_days"],
                is_known_shark=norm in shark_set,
                is_circular_suspect=False,  # set below
                net_to_total_ratio=round(ratio, 4),
            )
        )

    _flag_circular_pairs(positions)
    return positions


def _flag_circular_pairs(positions: list[NetPosition]) -> None:
    """Pairwise scan: if A is net buyer and B is net seller and their
    magnitudes match within `_CIRCULAR_PAIR_TOL`, flag both.

    Self-circulars (same party as net buyer AND net seller across
    different days with net~0) are already eliminated by the square-off
    filter upstream — anything that survives there has a meaningful
    one-sided position.
    """
    buyers = [p for p in positions if p.net_shares > 0]
    sellers = [p for p in positions if p.net_shares < 0]
    for b in buyers:
        b_mag = b.net_shares
        for s in sellers:
            s_mag = -s.net_shares  # positive
            if max(b_mag, s_mag) == 0:
                continue
            diff = abs(b_mag - s_mag) / max(b_mag, s_mag)
            if diff <= _CIRCULAR_PAIR_TOL:
                b.is_circular_suspect = True
                s.is_circular_suspect = True
