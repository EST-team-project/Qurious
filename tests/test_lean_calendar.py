from datetime import date, datetime

import pandas as pd
from unittest.mock import patch

from app.services.lean_backtest import LeanBacktestService


def _algorithm_source(ticker):
    service = LeanBacktestService.__new__(LeanBacktestService)
    return service._algorithm_source(
        ticker=ticker,
        strategy="ma_cross",
        start=datetime(2024, 1, 2),
        end=datetime(2024, 3, 29),
        cash=1_000_000,
        short_window=20,
        long_window=60,
        dca_interval_days=20,
        breakout_window=20,
    )


def test_krx_custom_data_uses_krx_exchange_hours():
    source = _algorithm_source("005930.KS")

    assert (
        'MarketHoursDatabase.from_data_folder().get_entry(Market.KRX, "005930", '
        'SecurityType.INDEX).exchange_hours'
    ) in source
    assert (
        "self.add_data(YFPrice, \"YF\", custom_properties, "
        "market_hours, Resolution.DAILY)"
    ) in source

    # 종가 데이터는 입력 날짜의 시각에 배치하고 다음 날로 밀지 않습니다.
    assert (
        'item.time = datetime.strptime(d, "%Y-%m-%d").replace(hour=15, minute=29)'
    ) in source
    assert "item.end_time = item.time + timedelta(days=1)" not in source


def test_non_krx_custom_data_keeps_existing_subscription_path():
    source = _algorithm_source("AAPL")

    assert (
        'self.asset = self.add_data(YFPrice, "YF", Resolution.DAILY).symbol'
    ) in source
    assert "MarketHoursDatabase.get_entry(Market.KRX" not in source


def test_generated_krx_algorithm_is_valid_python():
    source = _algorithm_source("005930.KS")
    compile(source, "<generated_lean_algorithm>", "exec")


def test_equity_curve_uses_aligned_position_for_daily_return():
    dates = pd.date_range("2024-01-02", periods=3, freq="D")
    close = pd.Series([100.0, 90.0, 99.0], index=dates)
    position_after_close = pd.Series([0.0, 1.0, 1.0], index=dates)

    equity = LeanBacktestService._equity_from_position(
        close, position_after_close
    )

    expected = [1.0, 1.0, 1.1]
    assert all(abs(float(a) - b) < 1e-9 for a, b in zip(equity, expected))


def test_strategy_starts_flat_even_if_pre_window_signal_is_long():
    service = LeanBacktestService.__new__(LeanBacktestService)
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    close = pd.Series([101.0, 100.0, 90.0, 99.0], index=dates)
    preexisting_long_signal = pd.Series(1.0, index=dates)

    with patch.object(
        LeanBacktestService,
        "_position_ma_cross",
        return_value=preexisting_long_signal,
    ):
        equity = service._strategy_curve(
            "ma_cross",
            close,
            date(2024, 1, 2),
            date(2024, 1, 4),
            2, 3, 1, 2,
            ticker="AAPL",
            apply_costs=False,
        )

    expected = [1.0, 1.0, 1.1]
    assert all(abs(float(a) - b) < 1e-9 for a, b in zip(equity, expected))

def test_equity_from_position_delays_return_until_after_entry_close():
    dates = pd.date_range("2024-01-02", periods=3, freq="D")
    close = pd.Series([100.0, 90.0, 99.0], index=dates)
    # 이미 신호 지연이 적용된 보유 상태: 마지막 날만 보유
    position = pd.Series([0.0, 1.0, 1.0], index=dates)

    equity = LeanBacktestService._equity_from_position(close, position)
    expected = [1.0, 1.0, 1.1]

    assert all(
        abs(float(actual) - target) < 1e-9
        for actual, target in zip(equity.tolist(), expected)
    )

