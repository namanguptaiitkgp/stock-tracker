"""Signal engine — Layers 2-6 of the analyzer spec.

Given a list of normalized DealRows for a window, bucket by stock, apply
NOISE gates, run priority-ordered signal detection, assign tier, attach
confidence modifiers, return a full AnalyzerReport.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Iterable

from app.services.smart_money.analyzer.models import (
    SIGNAL_TO_DIRECTION,
    SIG_MODERATE_BUY,
    SIG_NEUTRAL,
    SIG_NOISE,
    SIG_STRONG_BUY_CONSENSUS,
    SIG_STRONG_BUY_PROMOTER,
    SIG_STRONG_SELL_PROMOTER,
    SIG_STRONG_SELL_QUALITY,
    SIG_VC_EXIT,
    SIG_WEAK_BUY,
    SIG_WEAK_SELL,
    AnalyzerReport,
    DealRow,
    StockSignal,
)
from app.services.smart_money.analyzer.party_classifier import (
    PROMOTER,
    PROP_HFT,
    QUALITY_MF_FPI,
    VC_PE,
    INSIDER_OTHER,
)

logger = logging.getLogger(__name__)


CR = 1_00_00_000  # 1 crore = 10^7 rupees


def _to_cr(v: float) -> float:
    return round(v / CR, 2)


def _net(rows: list[DealRow]) -> float:
    """Net (buy - sell) INR across the supplied rows."""
    return sum(r.value_inr if r.side == "BUY" else -r.value_inr for r in rows)


def _gross(rows: list[DealRow]) -> float:
    return sum(r.value_inr for r in rows)


def _distinct_days(rows: list[DealRow]) -> int:
    return len({r.trade_date for r in rows})


def _by_category(rows: list[DealRow], categories: set[str], side: str | None = None) -> list[DealRow]:
    return [
        r for r in rows
        if r.category in categories and (side is None or r.side == side)
    ]


def _by_side(rows: list[DealRow], side: str) -> list[DealRow]:
    return [r for r in rows if r.side == side]


def _distinct_parties(rows: list[DealRow]) -> set[str]:
    return {r.party_norm for r in rows}


def _distinct_parties_netting(rows: list[DealRow], direction: str) -> set[str]:
    """Parties whose NET flow across the window is in `direction` (BUY / SELL)."""
    per_party: dict[str, float] = defaultdict(float)
    for r in rows:
        per_party[r.party_norm] += r.value_inr if r.side == "BUY" else -r.value_inr
    if direction == "BUY":
        return {p for p, v in per_party.items() if v > 0}
    return {p for p, v in per_party.items() if v < 0}


# -------------------- Layer 2 — NOISE gates --------------------

def _noise_gate(rows: list[DealRow]) -> tuple[bool, str]:
    """Return (is_noise, reason) for a stock's rows."""
    if not rows:
        return True, "empty"

    gross = _gross(rows)

    # N2: <₹1 Cr total
    if gross < 1 * CR:
        return True, f"N2: gross {_to_cr(gross):.2f} Cr < 1 Cr"

    # N1: Prop/HFT ≥ 60% of gross
    prop_gross = _gross([r for r in rows if r.category == PROP_HFT])
    prop_share = (prop_gross / gross) if gross else 0.0
    if prop_share >= 0.60:
        return True, f"N1: prop share {prop_share*100:.0f}% ≥ 60%"

    # N3: single party + single day
    days = _distinct_days(rows)
    parties = _distinct_parties(rows)
    if len(parties) == 1 and days == 1:
        return True, "N3: single party, single day"

    return False, ""


# -------------------- Layer 3 — Signal priorities --------------------

def _eval_vc_exit(rows: list[DealRow]) -> tuple[bool, str]:
    """Priority 1 — VC/PE exit block.

    Gate: VC_PE on sell side AND ≥1 QUALITY_MF_FPI on buy side, same day,
    same price (±1%).
    """
    vc_sells = _by_category(rows, {VC_PE}, side="SELL")
    if not vc_sells:
        return False, ""
    qmf_buys = _by_category(rows, {QUALITY_MF_FPI}, side="BUY")
    if not qmf_buys:
        return False, ""

    for vs in vc_sells:
        for qb in qmf_buys:
            if qb.trade_date != vs.trade_date:
                continue
            if vs.price > 0 and abs(qb.price - vs.price) / vs.price <= 0.01:
                return True, (
                    f"VC/PE {vs.party_raw} sold ≈{_to_cr(vs.value_inr):.1f} Cr to "
                    f"{qb.party_raw} on {vs.trade_date} @ Rs {vs.price:.2f} "
                    f"(buyer @ Rs {qb.price:.2f})"
                )
    return False, ""


def _eval_strong_buy_promoter(rows: list[DealRow]) -> tuple[bool, str, list[str]]:
    """Priority 2 — STRONG BUY — Clean Promoter Accumulation."""
    promoter = [r for r in rows if r.category == PROMOTER]
    if not promoter:
        return False, "", []

    pbuy = _by_side(promoter, "BUY")
    psell = _by_side(promoter, "SELL")
    buy_val = _gross(pbuy)
    sell_val = _gross(psell)
    net = buy_val - sell_val

    # B1
    if not (sell_val == 0 or buy_val >= 3 * sell_val):
        return False, f"B1 fail: buy {_to_cr(buy_val)} < 3× sell {_to_cr(sell_val)}", []
    # B2
    if net < 0.5 * CR:
        return False, f"B2 fail: net {_to_cr(net)} < 0.5 Cr", []
    # B3 — ≥3 distinct buying days
    days = _distinct_days(pbuy)
    if days < 3:
        return False, f"B3 fail: promoter buying across {days} days (<3)", []
    # B4 — no same-day promoter buy+sell (inter-se)
    for d in {r.trade_date for r in pbuy}:
        if any(s.trade_date == d for s in psell):
            return False, f"B4 fail: inter-se promoter trade on {d}", []
    # B5 — holdings change via buying ≤ 5% per transaction
    for r in pbuy:
        if r.holdings_change_pct is not None and r.holdings_change_pct > 5.0:
            return False, f"B5 fail: holdings change {r.holdings_change_pct}% on {r.trade_date}", []
    # B6 — no VC/PE exit in same stock during window
    if any(r.category == VC_PE and r.side == "SELL" for r in rows):
        return False, "B6 fail: VC/PE exit present in window", []
    # B7 — no quality MF/FPI net selling
    qmf_net_sellers = _distinct_parties_netting(
        _by_category(rows, {QUALITY_MF_FPI}), "SELL"
    )
    if qmf_net_sellers:
        return False, f"B7 fail: {len(qmf_net_sellers)} quality MF/FPI net-selling", []
    # B8 already covered by N1 in Layer 2

    buyer_names = sorted({r.party_raw for r in pbuy})[:3]
    evidence = (
        f"Promoter net buy {_to_cr(net):.2f} Cr across {days} days; buyers: "
        f"{', '.join(buyer_names)}"
    )
    return True, evidence, []


def _eval_strong_buy_consensus(rows: list[DealRow]) -> tuple[bool, str, list[str]]:
    """Priority 3 — STRONG BUY — Institutional Consensus."""
    qmf = _by_category(rows, {QUALITY_MF_FPI})
    if not qmf:
        return False, "", []
    qmf_buys = _by_side(qmf, "BUY")

    buy_parties = _distinct_parties(qmf_buys)
    # C1
    if len(buy_parties) < 2:
        return False, f"C1 fail: only {len(buy_parties)} quality buyer(s)", []
    # C2
    buy_days = _distinct_days(qmf_buys)
    if buy_days < 2:
        return False, f"C2 fail: buying across {buy_days} day(s)", []
    # C3 — net quality flow on buy side > 10 Cr
    net_qmf = _net(qmf)
    if net_qmf < 10 * CR:
        return False, f"C3 fail: net quality {_to_cr(net_qmf)} < 10 Cr", []
    # C4 — zero quality names net-selling
    qmf_net_sellers = _distinct_parties_netting(qmf, "SELL")
    if qmf_net_sellers:
        return False, f"C4 fail: {len(qmf_net_sellers)} quality net-selling", []

    names = sorted(buy_parties)[:3]
    evidence = (
        f"{len(buy_parties)} quality MF/FPI names bought across {buy_days} days "
        f"(net {_to_cr(net_qmf):.1f} Cr): {', '.join(names)}"
    )
    return True, evidence, []


def _eval_moderate_buy(rows: list[DealRow]) -> tuple[bool, str, list[str]]:
    """Priority 4 — MODERATE BUY — Single-name quality accumulation."""
    qmf = _by_category(rows, {QUALITY_MF_FPI})
    if not qmf:
        return False, "", []
    # M1 + M2: any single quality party buying across ≥2 days with net > 5 Cr
    by_party: dict[str, list[DealRow]] = defaultdict(list)
    for r in qmf:
        by_party[r.party_norm].append(r)

    for party, prows in by_party.items():
        buys = _by_side(prows, "BUY")
        days = _distinct_days(buys)
        net = _net(prows)
        if days >= 2 and net > 5 * CR:
            # M3 — no conflicting quality seller (net)
            conflict = _distinct_parties_netting(
                [r for r in qmf if r.party_norm != party], "SELL"
            )
            if conflict:
                continue
            display = prows[0].party_raw
            evidence = (
                f"{display} accumulated Rs {_to_cr(net):.2f} Cr across {days} days"
            )
            return True, evidence, []
    return False, "", []


def _eval_strong_sell_promoter(rows: list[DealRow]) -> tuple[bool, str, list[str]]:
    """Priority 5 — STRONG SELL — Promoter Distribution."""
    promoter = [r for r in rows if r.category == PROMOTER]
    if not promoter:
        return False, "", []

    pbuy = _by_side(promoter, "BUY")
    psell = _by_side(promoter, "SELL")
    buy_val = _gross(pbuy)
    sell_val = _gross(psell)
    net = buy_val - sell_val

    # S1
    if not (buy_val == 0 or sell_val >= 3 * buy_val):
        return False, f"S1 fail: sell {_to_cr(sell_val)} < 3× buy {_to_cr(buy_val)}", []
    # S2
    if -net < 0.5 * CR:
        return False, f"S2 fail: net {_to_cr(net)} too small", []
    # S3
    sell_days = _distinct_days(psell)
    if sell_days < 3:
        return False, f"S3 fail: {sell_days} selling days (<3)", []
    # S4 — not a single-day placement (ensured by S3 really, but explicit)
    if sell_days < 2:
        return False, "S4 fail: single-day placement", []

    seller_names = sorted({r.party_raw for r in psell})[:3]
    evidence = (
        f"Promoter net sell {_to_cr(-net):.2f} Cr across {sell_days} days; "
        f"sellers: {', '.join(seller_names)}"
    )
    return True, evidence, []


def _eval_strong_sell_quality(rows: list[DealRow]) -> tuple[bool, str, list[str]]:
    """Priority 6 — STRONG SELL — Quality Distribution."""
    qmf = _by_category(rows, {QUALITY_MF_FPI})
    if not qmf:
        return False, "", []
    qmf_sells = _by_side(qmf, "SELL")
    sell_parties = _distinct_parties(qmf_sells)
    # Q1
    if len(sell_parties) < 2:
        return False, f"Q1 fail: {len(sell_parties)} quality seller(s)", []
    # Q2
    sell_days = _distinct_days(qmf_sells)
    if sell_days < 2:
        return False, f"Q2 fail: selling across {sell_days} day(s)", []
    # Q3
    net_qmf = _net(qmf)
    if -net_qmf < 10 * CR:
        return False, f"Q3 fail: net quality {_to_cr(net_qmf)} not < -10 Cr", []
    # Q4
    qmf_net_buyers = _distinct_parties_netting(qmf, "BUY")
    if qmf_net_buyers:
        return False, f"Q4 fail: {len(qmf_net_buyers)} quality net-buying", []

    names = sorted(sell_parties)[:3]
    evidence = (
        f"{len(sell_parties)} quality MF/FPI names sold across {sell_days} days "
        f"(net {_to_cr(net_qmf):.1f} Cr): {', '.join(names)}"
    )
    return True, evidence, []


def _eval_weak(rows: list[DealRow]) -> tuple[str | None, str, list[str]]:
    """Priority 7 — WEAK BUY/SELL fallback.

    Any other stock with net flow > 5 Cr AND prop share < 40%.
    """
    gross = _gross(rows)
    prop_share = _gross([r for r in rows if r.category == PROP_HFT]) / gross if gross else 0
    if prop_share >= 0.40:
        return None, f"weak: prop share {prop_share*100:.0f}% too high", []
    net = _net(rows)
    if net > 5 * CR:
        return SIG_WEAK_BUY, f"Fallback weak BUY: net +Rs {_to_cr(net):.2f} Cr, prop {prop_share*100:.0f}%", []
    if net < -5 * CR:
        return SIG_WEAK_SELL, f"Fallback weak SELL: net Rs {_to_cr(net):.2f} Cr, prop {prop_share*100:.0f}%", []
    return None, "weak: net flow within ±5 Cr", []


# -------------------- Layer 4 — Tier --------------------

def _tier_for(signal: str, rows: list[DealRow]) -> str | None:
    """Tier 1 (Sizeable): net ≥ ₹5 Cr OR holdings change ≥ 0.25%
       Tier 2 (Symbolic): clean pattern, small size"""
    if signal in {SIG_NOISE, SIG_NEUTRAL}:
        return None

    # For sell signals, use absolute value
    net = abs(_net(rows))
    if net >= 5 * CR:
        return "Sizeable"
    if any((r.holdings_change_pct or 0) >= 0.25 for r in rows):
        return "Sizeable"
    return "Symbolic"


# -------------------- Layer 5 — Modifiers --------------------

def _modifiers_for(signal: str, rows: list[DealRow], window_end: date | None) -> list[str]:
    mods: list[str] = []

    has_promoter_buy = any(r.category == PROMOTER and r.side == "BUY" for r in rows)
    has_qmf_buy = any(r.category == QUALITY_MF_FPI and r.side == "BUY" for r in rows)
    has_promoter_sell = any(r.category == PROMOTER and r.side == "SELL" for r in rows)
    has_qmf_sell = any(r.category == QUALITY_MF_FPI and r.side == "SELL" for r in rows)

    if signal in {SIG_STRONG_BUY_PROMOTER} and has_qmf_buy:
        mods.append("+Corroboration (quality MF/FPI also buying)")
    if signal in {SIG_STRONG_BUY_CONSENSUS} and has_promoter_buy:
        mods.append("+Corroboration (promoter also buying)")
    if signal in {SIG_STRONG_SELL_PROMOTER} and has_qmf_sell:
        mods.append("+Corroboration (quality MF/FPI also selling)")
    if signal in {SIG_STRONG_SELL_QUALITY} and has_promoter_sell:
        mods.append("+Corroboration (promoter also selling)")

    # +Persistence
    if _distinct_days(rows) >= 5:
        mods.append("+Persistence (≥5 active days)")

    # -Conflict
    promoter_buy = any(r.category == PROMOTER and r.side == "BUY" for r in rows)
    qmf_sell = any(r.category == QUALITY_MF_FPI and r.side == "SELL" for r in rows)
    promoter_sell = any(r.category == PROMOTER and r.side == "SELL" for r in rows)
    qmf_buy = any(r.category == QUALITY_MF_FPI and r.side == "BUY" for r in rows)

    if (promoter_buy and qmf_sell) or (promoter_sell and qmf_buy):
        mods.append("-Conflict (opposing promoter vs quality signals)")

    # -Structural
    if any((r.holdings_change_pct or 0) > 5 for r in rows):
        mods.append("-Structural (single-txn holdings change >5% — verify filing)")

    # -Recency: no activity in last 5 trading days of window
    if window_end:
        last_date = max(r.trade_date for r in rows)
        if (window_end - last_date) > timedelta(days=5):
            mods.append("-Recency (stale — no activity in last 5 days)")

    return mods


# -------------------- Orchestration --------------------

def _build_signal(
    stock: str,
    rows: list[DealRow],
    window_end: date | None,
) -> StockSignal:
    gross = _gross(rows)
    net = _net(rows)
    prop_share = _gross([r for r in rows if r.category == PROP_HFT]) / gross if gross else 0.0

    is_noise, noise_reason = _noise_gate(rows)
    if is_noise:
        return StockSignal(
            stock=stock,
            signal=SIG_NOISE,
            direction=SIGNAL_TO_DIRECTION[SIG_NOISE],
            tier=None,
            confidence="Noise — no signal",
            net_cr=_to_cr(net),
            days=_distinct_days(rows),
            primary_evidence=noise_reason,
            modifiers=[],
            gross_value_inr=gross,
            prop_share=round(prop_share, 3),
            top_parties=_top_parties(rows),
            reason_notes=[noise_reason],
        )

    reasons: list[str] = []

    ok, ev = _eval_vc_exit(rows)
    if ok:
        return _finish(stock, rows, SIG_VC_EXIT, ev, window_end, reasons)

    ok, ev, _ = _eval_strong_buy_promoter(rows)
    reasons.append(ev if not ok else "promoter buy: matched")
    if ok:
        return _finish(stock, rows, SIG_STRONG_BUY_PROMOTER, ev, window_end, reasons)

    ok, ev, _ = _eval_strong_buy_consensus(rows)
    reasons.append(ev if not ok else "consensus buy: matched")
    if ok:
        return _finish(stock, rows, SIG_STRONG_BUY_CONSENSUS, ev, window_end, reasons)

    ok, ev, _ = _eval_moderate_buy(rows)
    if ok:
        return _finish(stock, rows, SIG_MODERATE_BUY, ev, window_end, reasons)

    ok, ev, _ = _eval_strong_sell_promoter(rows)
    reasons.append(ev if not ok else "promoter sell: matched")
    if ok:
        return _finish(stock, rows, SIG_STRONG_SELL_PROMOTER, ev, window_end, reasons)

    ok, ev, _ = _eval_strong_sell_quality(rows)
    reasons.append(ev if not ok else "quality sell: matched")
    if ok:
        return _finish(stock, rows, SIG_STRONG_SELL_QUALITY, ev, window_end, reasons)

    weak, ev, _ = _eval_weak(rows)
    if weak:
        return _finish(stock, rows, weak, ev, window_end, reasons)

    # Priority 8 — NEUTRAL
    return StockSignal(
        stock=stock,
        signal=SIG_NEUTRAL,
        direction=SIGNAL_TO_DIRECTION[SIG_NEUTRAL],
        tier=None,
        confidence="Neutral — no strong pattern",
        net_cr=_to_cr(net),
        days=_distinct_days(rows),
        primary_evidence="No signal qualifies — mixed/low-conviction flow",
        modifiers=[],
        gross_value_inr=gross,
        prop_share=round(prop_share, 3),
        top_parties=_top_parties(rows),
        reason_notes=reasons,
    )


def _finish(
    stock: str,
    rows: list[DealRow],
    signal: str,
    evidence: str,
    window_end: date | None,
    reason_notes: list[str],
) -> StockSignal:
    tier = _tier_for(signal, rows)
    mods = _modifiers_for(signal, rows, window_end)

    # Confidence label
    if any("+Corroboration" in m for m in mods) and any("+Persistence" in m for m in mods):
        conf = "High confidence"
    elif any("+Corroboration" in m for m in mods):
        conf = "High confidence"
    elif any("+Persistence" in m for m in mods):
        conf = "High confidence"
    elif any("-Conflict" in m for m in mods):
        conf = "Mixed — investigate"
    elif any("-Structural" in m for m in mods):
        conf = "Structural — verify filing"
    elif any("-Recency" in m for m in mods):
        conf = "Stale"
    else:
        conf = "Standard"

    gross = _gross(rows)
    prop_share = _gross([r for r in rows if r.category == PROP_HFT]) / gross if gross else 0.0

    return StockSignal(
        stock=stock,
        signal=signal,
        direction=SIGNAL_TO_DIRECTION[signal],
        tier=tier,
        confidence=conf,
        net_cr=_to_cr(_net(rows)),
        days=_distinct_days(rows),
        primary_evidence=evidence,
        modifiers=mods,
        gross_value_inr=gross,
        prop_share=round(prop_share, 3),
        top_parties=_top_parties(rows),
        reason_notes=reason_notes,
    )


def _top_parties(rows: list[DealRow], k: int = 5) -> list[dict]:
    per_party: dict[str, dict] = {}
    for r in rows:
        slot = per_party.setdefault(r.party_norm, {
            "party": r.party_raw,
            "category": r.category,
            "buy_inr": 0.0,
            "sell_inr": 0.0,
            "trades": 0,
        })
        slot["trades"] += 1
        if r.side == "BUY":
            slot["buy_inr"] += r.value_inr
        else:
            slot["sell_inr"] += r.value_inr

    ordered = sorted(per_party.values(), key=lambda x: x["buy_inr"] + x["sell_inr"], reverse=True)
    for e in ordered:
        e["net_cr"] = round((e["buy_inr"] - e["sell_inr"]) / CR, 2)
        e["gross_cr"] = round((e["buy_inr"] + e["sell_inr"]) / CR, 2)
        # keep compact
        del e["buy_inr"]
        del e["sell_inr"]
    return ordered[:k]


def analyze_deals(rows: Iterable[DealRow]) -> AnalyzerReport:
    rows_list = list(rows)
    if not rows_list:
        return AnalyzerReport(
            window_start=None, window_end=None,
            total_rows=0, dropped_rows=0, stocks_seen=0,
            signals=[], neutral=[], noise=[], files=[], warnings=[],
        )

    window_start = min(r.trade_date for r in rows_list)
    window_end = max(r.trade_date for r in rows_list)

    by_stock: dict[str, list[DealRow]] = defaultdict(list)
    for r in rows_list:
        by_stock[r.symbol].append(r)

    signals: list[StockSignal] = []
    neutral: list[StockSignal] = []
    noise: list[StockSignal] = []

    for stock, srows in sorted(by_stock.items()):
        sig = _build_signal(stock, srows, window_end)
        if sig.signal == SIG_NOISE:
            noise.append(sig)
        elif sig.signal == SIG_NEUTRAL:
            neutral.append(sig)
        else:
            signals.append(sig)

    # Rank: BUY priority first within same direction, then by |net|
    priority_order = {
        "STRONG_BUY_PROMOTER_ACCUMULATION": 0,
        "STRONG_BUY_INSTITUTIONAL_CONSENSUS": 1,
        "MODERATE_BUY_SINGLE_NAME_QUALITY": 2,
        "WEAK_BUY": 3,
        "VC_PE_EXIT_BLOCK": 4,
        "STRONG_SELL_PROMOTER_DISTRIBUTION": 5,
        "STRONG_SELL_QUALITY_DISTRIBUTION": 6,
        "WEAK_SELL": 7,
    }
    signals.sort(key=lambda s: (priority_order.get(s.signal, 99), -abs(s.net_cr)))
    neutral.sort(key=lambda s: -abs(s.net_cr))
    noise.sort(key=lambda s: -s.gross_value_inr)

    return AnalyzerReport(
        window_start=window_start,
        window_end=window_end,
        total_rows=len(rows_list),
        dropped_rows=0,
        stocks_seen=len(by_stock),
        signals=signals,
        neutral=neutral,
        noise=noise,
        files=[],
        warnings=[],
    )
