"""Unit tests for the NSE insider-disclosure JSON parser.

Live HTTP coverage is exercised by the celery task in dev. These tests
lock down the field-mapping logic so vendor renames don't silently
produce bogus rows in the DB.
"""

from datetime import date

from app.services.smart_money.insider_disclosures import (
    _normalize_category,
    _normalize_txn_type,
    _row_from_api,
)

# Real shape from /api/corporates-pit (2026-05-01)
SAMPLE = {
    "symbol": "HCLTECH",
    "company": "HCL Technologies Ltd.",
    "anex": "7(2)",
    "acqName": "Vama Sundari Investments (Delhi) Private Limited",
    "date": "28-Apr-2026",
    "tdpTransactionType": "Buy",
    "secAcq": "183673",
    "secVal": "220277165",
    "personCategory": "Promoter",
    "befAcqSharesPer": "44.42",
    "afterAcqSharesPer": "44.49",
    "acqfromDt": "28-Apr-2026",
    "acqtoDt": "28-Apr-2026",
    "intimDt": "29-Apr-2026",
    "acqMode": "Market Purchase",
}


def test_row_from_api_maps_promoter_buy_correctly():
    row = _row_from_api(SAMPLE)
    assert row is not None
    assert row["symbol"] == "HCLTECH"
    assert row["category"] == "Promoter"
    assert row["transaction_type"] == "Buy"
    assert row["shares"] == 183673
    assert row["value_inr"] == 220277165.0
    assert row["mode"] == "Market Purchase"
    assert row["transaction_date"] == date(2026, 4, 28)
    assert row["intimation_date"] == date(2026, 4, 29)
    assert row["pre_holding_pct"] == 44.42
    assert row["afterAcqSharesPer" if False else "post_holding_pct"] == 44.49


def test_row_from_api_returns_none_for_missing_symbol():
    item = {**SAMPLE, "symbol": ""}
    assert _row_from_api(item) is None


def test_row_from_api_returns_none_for_zero_shares():
    item = {**SAMPLE, "secAcq": "0", "buyQuantity": "0", "sellquantity": "0"}
    assert _row_from_api(item) is None


def test_row_from_api_falls_back_to_buyQuantity_when_secAcq_missing():
    item = {**SAMPLE, "secAcq": "0", "buyQuantity": "5000", "sellquantity": "0"}
    row = _row_from_api(item)
    assert row is not None
    assert row["shares"] == 5000


def test_row_from_api_uses_txn_date_as_intim_fallback():
    item = {**SAMPLE, "intimDt": ""}
    row = _row_from_api(item)
    assert row is not None
    assert row["intimation_date"] == row["transaction_date"]


def test_normalize_category_handles_variants():
    assert _normalize_category("Promoter") == "Promoter"
    assert _normalize_category("Promoter Group") == "Promoter Group"
    assert _normalize_category("Designated Person") == "Designated Person"
    assert _normalize_category("kmp / dp&sap") == "Designated Person"
    assert _normalize_category("director (independent)") == "Director"
    assert _normalize_category("immediate relative") == "Immediate Relative"
    assert _normalize_category("") is None


def test_normalize_txn_type_handles_variants():
    assert _normalize_txn_type("Buy") == "Buy"
    assert _normalize_txn_type("Acquisition") == "Buy"
    assert _normalize_txn_type("Sale") == "Sale"
    assert _normalize_txn_type("disposal") == "Sale"
    assert _normalize_txn_type("Pledge Creation") == "Pledge"
    assert _normalize_txn_type("Release of Pledge") == "Revoke"
    assert _normalize_txn_type("Invocation") == "Invoke"
    assert _normalize_txn_type("") is None
