"""Unit tests for the NSE corporate-announcements subject classifier."""

from app.services.smart_money.corporate_announcements import _classify_subject


def test_classify_buyback_subject():
    assert _classify_subject("Buy back of equity shares") == "BUYBACK"
    assert _classify_subject("Notice of buyback") == "BUYBACK"
    assert _classify_subject("BUYBACK OF SHARES") == "BUYBACK"


def test_classify_pledge_create_subject():
    assert _classify_subject("Encumbrance creation") == "PLEDGE_CREATED"
    assert _classify_subject("Creation of pledge") == "PLEDGE_CREATED"
    # Fallback "pledge" should match PLEDGE_CREATED when no other variant matches
    assert _classify_subject("Pledge") == "PLEDGE_CREATED"


def test_classify_pledge_release_subject():
    assert _classify_subject("Release of pledge") == "PLEDGE_RELEASED"
    assert _classify_subject("Encumbrance release") == "PLEDGE_RELEASED"
    assert _classify_subject("Revoke pledge") == "PLEDGE_RELEASED"


def test_classify_pledge_invoke_subject():
    assert _classify_subject("Pledge invoked by lender") == "PLEDGE_INVOKED"
    # "invoke" alone classifies as invoked
    assert _classify_subject("Invocation under SAST") == "PLEDGE_INVOKED"


def test_classify_preferential_allotment():
    assert _classify_subject("Preferential allotment of equity") == "PREFERENTIAL_ALLOTMENT"
    assert _classify_subject("Preferential issue") == "PREFERENTIAL_ALLOTMENT"


def test_classify_returns_none_for_unrelated():
    assert _classify_subject("Board meeting outcome") is None
    assert _classify_subject("Quarterly results FY26") is None
    assert _classify_subject("Dividend declaration") is None
    assert _classify_subject("") is None
    assert _classify_subject(None) is None


def test_classify_priority_invoke_beats_create():
    """Invoke wins when both keywords appear (the invocation is the news)."""
    # The order in _SUBJECT_RULES puts "invoke" before "pledge create"
    assert _classify_subject("Pledge invoked, creation reversed") == "PLEDGE_INVOKED"
