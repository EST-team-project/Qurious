from datetime import date
from types import SimpleNamespace

from app.services.paper_kis_reconciliation import (
    _action_side,
    _adverse_bps,
    _decision_date,
)


def test_action_side_handles_journal_and_kis_actions():
    assert _action_side("강력 매수") == "BUY"
    assert _action_side("매수") == "BUY"
    assert _action_side("강력 매도") == "SELL"
    assert _action_side("매도") == "SELL"
    assert _action_side("관망") is None
    assert _action_side("HOLD") is None


def test_adverse_bps_buy_positive_means_worse_price():
    assert _adverse_bps("BUY", 100, 101) == 100.0
    assert _adverse_bps("BUY", 100, 99) == -100.0


def test_adverse_bps_sell_positive_means_worse_price():
    assert _adverse_bps("SELL", 100, 99) == 101.0101
    assert _adverse_bps("SELL", 100, 101) == -99.0099


def test_adverse_bps_rejects_invalid_values():
    assert _adverse_bps("BUY", 0, 100) is None
    assert _adverse_bps("HOLD", 100, 100) is None
    assert _adverse_bps("BUY", float("nan"), 100) is None


def test_decision_date_uses_bar_end_at_not_intent_created_date():
    result = {
        "price_basis": {
            "decision": {"bar_end_at": "2026-11-05T15:30:00+09:00"}
        }
    }
    assert _decision_date(result) == date(2026, 11, 5)


def test_decision_date_rejects_missing_or_naive_timestamp():
    assert _decision_date({}) is None
    assert _decision_date({"price_basis": {"decision": {"bar_end_at": "2026-11-05T15:30:00"}}}) is None
