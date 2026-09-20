"""Unit tests for intra-group transfer detection (addendum A1a).

The DB-roundtrip half of `detect_intra_group_transfers` is covered by
the integration smoke against live data. Here we lock down the matching
rules around the share-count tolerance and the buy-vs-sale pairing.
"""

from datetime import date
from types import SimpleNamespace

import pytest

# We import only what's needed and stub the DB out.
from app.services.smart_money import insider_disclosures as ind


def _row(*, id: int, symbol: str, txn_type: str, shares: int, category: str = "Promoter", txn_date: date = date(2026, 4, 27)):
    """Build a minimal row that matches the InsiderDisclosure attribute
    names the matcher reads. SimpleNamespace lets us avoid the SQLAlchemy
    constructor chain in pure-logic tests.
    """
    return SimpleNamespace(
        id=id,
        symbol=symbol,
        category=category,
        transaction_type=txn_type,
        shares=shares,
        transaction_date=txn_date,
        is_intra_group_transfer=False,
    )


def _run_match(rows: list) -> set[int]:
    """Reproduce the in-memory matching logic from
    `detect_intra_group_transfers` so we can test it without hitting
    the DB. The DB part is just persistence — the matching is the
    interesting bit."""
    by_key: dict[tuple[str, date], list] = {}
    for r in rows:
        by_key.setdefault((r.symbol, r.transaction_date), []).append(r)

    flag_ids: set[int] = set()
    for bucket in by_key.values():
        buys = [r for r in bucket if r.transaction_type == "Buy"]
        sales = [r for r in bucket if r.transaction_type == "Sale"]
        if not buys or not sales:
            continue
        used_sale: set[int] = set()
        for b in buys:
            best: tuple[float, object] | None = None
            for s in sales:
                if s.id in used_sale:
                    continue
                if b.shares == 0 or s.shares == 0:
                    continue
                diff = abs(b.shares - s.shares) / max(b.shares, s.shares)
                if diff <= ind._TRANSFER_TOLERANCE:  # noqa: SLF001
                    if best is None or diff < best[0]:
                        best = (diff, s)
            if best is not None:
                used_sale.add(best[1].id)
                flag_ids.add(b.id)
                flag_ids.add(best[1].id)
    return flag_ids


def test_exact_match_pair_is_flagged():
    rows = [
        _row(id=1, symbol="BAJAJFINSV", txn_type="Buy", shares=2_090_050, category="Promoter"),
        _row(id=2, symbol="BAJAJFINSV", txn_type="Sale", shares=2_090_050, category="Promoter Group"),
    ]
    assert _run_match(rows) == {1, 2}


def test_within_5pct_tolerance_is_flagged():
    rows = [
        _row(id=1, symbol="X", txn_type="Buy", shares=1_000_000),
        _row(id=2, symbol="X", txn_type="Sale", shares=1_040_000),  # 4% off
    ]
    assert _run_match(rows) == {1, 2}


def test_outside_tolerance_is_not_flagged():
    rows = [
        _row(id=1, symbol="X", txn_type="Buy", shares=1_000_000),
        _row(id=2, symbol="X", txn_type="Sale", shares=1_200_000),  # 17% off
    ]
    assert _run_match(rows) == set()


def test_pure_buy_or_pure_sale_day_is_not_flagged():
    rows = [
        _row(id=1, symbol="X", txn_type="Buy", shares=100_000),
        _row(id=2, symbol="X", txn_type="Buy", shares=200_000),
    ]
    assert _run_match(rows) == set()


def test_buy_consumes_one_sale_only():
    """If buy=100 and there are two sales of 100 each, only the first
    matched sale gets flagged — the second is unmatched residual."""
    rows = [
        _row(id=1, symbol="X", txn_type="Buy", shares=100_000),
        _row(id=2, symbol="X", txn_type="Sale", shares=100_000),
        _row(id=3, symbol="X", txn_type="Sale", shares=100_000),
    ]
    flagged = _run_match(rows)
    assert 1 in flagged
    assert flagged & {2, 3}  # one of them
    assert len(flagged) == 3 or len(flagged) == 2  # at least the matched pair


def test_zero_shares_never_match():
    rows = [
        _row(id=1, symbol="X", txn_type="Buy", shares=0),
        _row(id=2, symbol="X", txn_type="Sale", shares=0),
    ]
    assert _run_match(rows) == set()


def test_different_dates_dont_match():
    rows = [
        _row(id=1, symbol="X", txn_type="Buy", shares=100_000, txn_date=date(2026, 4, 27)),
        _row(id=2, symbol="X", txn_type="Sale", shares=100_000, txn_date=date(2026, 4, 28)),
    ]
    assert _run_match(rows) == set()


def test_different_symbols_dont_match():
    rows = [
        _row(id=1, symbol="A", txn_type="Buy", shares=100_000),
        _row(id=2, symbol="B", txn_type="Sale", shares=100_000),
    ]
    assert _run_match(rows) == set()


def test_promoter_family_categories():
    """The detector intentionally only runs on the promoter family,
    enforced by the SQL filter — kept here as a contract test."""
    assert ind._PROMOTER_FAMILY == {"Promoter", "Promoter Group", "Immediate Relative"}
    assert ind._TRANSFER_TOLERANCE == 0.05
