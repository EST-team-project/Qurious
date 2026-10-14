"""P01-④-2 — 의견 변환 진리표 (TC-OP)."""
from app.services.opinion import BUY, SELL, HOLD, SKIP, CONFIDENCE_MIN, decide


def test_buy_when_not_held_and_buy_signal_with_conf():
    assert decide("매수", CONFIDENCE_MIN, held=False) == (BUY, "buy_new")
    assert decide("매수", 1.0, held=False) == (BUY, "buy_new")


def test_skip_when_low_conf():
    assert decide("매수", CONFIDENCE_MIN - 0.01, held=False) == (SKIP, "skip_low_conf")


def test_sell_when_held_and_sell_signal_with_conf():
    assert decide("매도", CONFIDENCE_MIN, held=True) == (SELL, "sell_held")


def test_hold_when_held_and_low_conf_sell():
    assert decide("매도", CONFIDENCE_MIN - 0.01, held=True) == (HOLD, "hold_low_conf")


def test_hold_when_held_any_signal():
    assert decide("매수", 0.9, held=True) == (HOLD, "hold_held")
    assert decide("관망", 0.5, held=True) == (HOLD, "hold_held")


def test_skip_when_not_held_and_sell_or_neutral():
    assert decide("매도", 0.9, held=False) == (SKIP, "skip_neutral")
    assert decide("관망", 0.5, held=False) == (SKIP, "skip_neutral")


def test_risk_gate_forces_sell_when_held():
    assert decide("매수", 0.9, held=True, risk_gate=True) == (SELL, "sell_risk_gate")
    assert decide("관망", 0.5, held=True, risk_gate=True) == (SELL, "sell_risk_gate")


def test_risk_gate_no_effect_when_not_held():
    assert decide("매수", 0.9, held=False, risk_gate=True) == (BUY, "buy_new")
    assert decide("관망", 0.5, held=False, risk_gate=True) == (SKIP, "skip_neutral")
