"""Validation layer unit tests — schema mismatches + trading-day calendar."""

from datetime import date

import pytest

from app.services.smart_money.validation import (
    SCHEMA_REGISTRY,
    SchemaValidationError,
    is_trading_day,
    validate_columns,
)


def test_schema_registry_lists_known_sources():
    assert "nse_bhavcopy" in SCHEMA_REGISTRY
    assert "nse_deals" in SCHEMA_REGISTRY
    assert "nse_insider" in SCHEMA_REGISTRY
    assert "shareholding_pattern" in SCHEMA_REGISTRY
    assert "nse_corporate_announcements" in SCHEMA_REGISTRY
    assert "fii_dii_stock" in SCHEMA_REGISTRY


def test_validate_columns_passes_when_all_expected_present():
    cols = list(SCHEMA_REGISTRY["nse_deals"]) + ["Some Extra Column"]
    # Should not raise — extras are allowed (only missing keys are fatal).
    validate_columns("nse_deals", cols)


def test_validate_columns_raises_on_missing_keys():
    cols = ["Date", "Symbol"]  # most keys missing
    with pytest.raises(SchemaValidationError) as exc:
        validate_columns("nse_deals", cols)
    msg = str(exc.value)
    assert "nse_deals" in msg
    assert "Client Name" in msg or "Quantity Traded" in msg


def test_validate_columns_message_lists_unexpected_extras():
    cols = list(SCHEMA_REGISTRY["nse_deals"]) + ["UnexpectedJunk1", "UnexpectedJunk2"]
    # All expected present — should not raise even with extras
    validate_columns("nse_deals", cols)


def test_validate_columns_unknown_source_is_noop():
    # Sources not registered should not raise — supports new dev sources.
    validate_columns("not_a_known_source", ["whatever"])


def test_validate_columns_strips_whitespace():
    cols = [c + " " for c in SCHEMA_REGISTRY["nse_deals"]]
    validate_columns("nse_deals", cols)  # must not raise


def test_is_trading_day_skips_weekends():
    # 2026-05-02 is a Saturday
    assert is_trading_day(date(2026, 5, 2)) is False
    # 2026-05-03 is a Sunday
    assert is_trading_day(date(2026, 5, 3)) is False


def test_is_trading_day_skips_known_holidays():
    # Republic Day 2026 — Mon 26-Jan
    assert is_trading_day(date(2026, 1, 26)) is False
    # Independence Day 2026 — Sat 15-Aug (also a weekend, double-no)
    assert is_trading_day(date(2026, 8, 15)) is False


def test_is_trading_day_accepts_weekday_non_holiday():
    # 2026-05-04 is a Monday and not in the holiday list
    assert is_trading_day(date(2026, 5, 4)) is True


def test_is_trading_day_accepts_treats_unknown_year_as_trading_day():
    # 2027 has no entries in the static holiday list yet — until we wire in
    # a live calendar, every weekday is "trading" so genuine zero-row issues
    # still surface as warnings.
    assert is_trading_day(date(2027, 5, 4)) is True  # Tuesday
