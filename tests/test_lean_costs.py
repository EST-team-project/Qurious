from datetime import date

import pandas as pd
import pytest

from app.services.lean_backtest import service


def _close():
    index = pd.date_range("2024-01-02", periods=8, freq="B")
    return pd.Series(
        [100, 101, 99, 103, 102, 105, 104, 108],
        index=index,
        dtype=float,
        name="close",
    )


def _curve(ticker, apply_costs):
    close = _close()
    return service._strategy_curve(
        "buy_hold",
        close,
        date(2024, 1, 2),
        date(2024, 1, 11),
        5, 20, 21, 20,
        ticker=ticker,
        apply_costs=apply_costs,
    )


def test_krx_reference_curve_includes_entry_costs():
    gross = _curve("005930.KS", apply_costs=False)
    net = _curve("005930.KS", apply_costs=True)

    assert gross.iloc[0] == pytest.approx(1.0)
    assert net.iloc[0] < 1.0
    assert net.iloc[-1] < gross.iloc[-1]


def test_non_krx_ticker_does_not_receive_krx_costs():
    gross = _curve("SPY", apply_costs=False)
    net = _curve("SPY", apply_costs=True)

    pd.testing.assert_series_equal(net, gross)
