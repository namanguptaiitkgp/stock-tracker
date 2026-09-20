"""Tests for the net-position calculator's pure logic.

`compute_net_positions` itself is async + DB-dependent; we exercise the
synchronous `_flag_circular_pairs` helper directly with synthetic
`NetPosition` lists. Integration coverage of the DB query path lands
with the ingestion-task tests in PR 3.
"""

from app.services.smart_money.net_position import (
    NetPosition,
    _flag_circular_pairs,
)


def _pos(name: str, net: int, **kw) -> NetPosition:
    return NetPosition(
        party_name_norm=name,
        party_category=kw.get("category", "INDIVIDUAL"),
        net_shares=net,
        net_value_inr=kw.get("value", float(net) * 100.0),
        distinct_buy_days=kw.get("buy_days", 1),
        distinct_sell_days=kw.get("sell_days", 1),
        is_known_shark=kw.get("is_known_shark", False),
        is_circular_suspect=False,
    )


def test_circular_detects_matched_pair():
    a = _pos("party_a", +100_000)
    b = _pos("party_b", -100_000)
    _flag_circular_pairs([a, b])
    assert a.is_circular_suspect is True
    assert b.is_circular_suspect is True


def test_circular_detects_pair_within_tolerance():
    a = _pos("party_a", +100_000)
    b = _pos("party_b", -106_000)  # 6% off — within 10% tol
    _flag_circular_pairs([a, b])
    assert a.is_circular_suspect is True
    assert b.is_circular_suspect is True


def test_circular_skips_pair_outside_tolerance():
    a = _pos("party_a", +100_000)
    b = _pos("party_b", -150_000)  # 50% off
    _flag_circular_pairs([a, b])
    assert a.is_circular_suspect is False
    assert b.is_circular_suspect is False


def test_circular_skips_when_only_buyers():
    a = _pos("party_a", +100_000)
    b = _pos("party_b", +90_000)
    _flag_circular_pairs([a, b])
    assert a.is_circular_suspect is False
    assert b.is_circular_suspect is False


def test_circular_skips_when_only_sellers():
    a = _pos("party_a", -100_000)
    b = _pos("party_b", -110_000)
    _flag_circular_pairs([a, b])
    assert a.is_circular_suspect is False
    assert b.is_circular_suspect is False


def test_circular_handles_empty_list():
    _flag_circular_pairs([])  # must not raise


def test_circular_flags_one_buyer_against_multiple_sellers():
    a = _pos("buyer", +200_000)
    s1 = _pos("seller_1", -50_000)   # too small, won't match
    s2 = _pos("seller_2", -195_000)  # ~3% off, matches
    _flag_circular_pairs([a, s1, s2])
    assert a.is_circular_suspect is True
    assert s2.is_circular_suspect is True
    assert s1.is_circular_suspect is False


def test_netposition_dataclass_fields():
    p = NetPosition(
        party_name_norm="x",
        party_category="QUALITY_MF_FPI",
        net_shares=1000,
        net_value_inr=100_000.0,
        distinct_buy_days=2,
        distinct_sell_days=0,
        is_known_shark=True,
        is_circular_suspect=False,
    )
    assert p.party_name_norm == "x"
    assert p.is_known_shark is True
    assert p.net_shares == 1000
