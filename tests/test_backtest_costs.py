"""백테스트 비용(수수료·슬리피지)·손절·익절 반영 검증."""
import pandas as pd
import pytest

from app.services.quant_pipeline import apply_stops, backtest, backtest_custom_indicator, feature_engineer, preprocess
from app.services.investment_research import backtest_strategy
from tests.conftest import make_candles


def _df():
    return feature_engineer(preprocess(make_candles(260)))


def test_costs_reduce_return_by_turnover():
    df = _df()
    sig = pd.Series(0, index=df.index); sig.iloc[10:30] = 1   # 1회 진입 + 1회 청산 = 회전 2회
    free = backtest(df, sig)
    paid = backtest(df, sig, commission_bps=10, slippage_bps=5)
    assert paid["trade_count"] == 2
    assert paid["cost_pct"] == pytest.approx(2 * 0.15, abs=1e-6)          # 15bp × 2
    assert paid["total_return_pct"] < free["total_return_pct"]
    assert paid["gross_return_pct"] == free["total_return_pct"]


def test_stop_loss_exits_and_blocks_until_reentry():
    idx = pd.date_range("2026-01-01", periods=8, freq="D")
    close = pd.Series([100, 100, 90, 95, 99, 100, 101, 102], index=idx, dtype=float)
    held = pd.Series([0, 1, 1, 1, 1, 1, 1, 1], index=idx, dtype=float)  # 2일차부터 계속 보유 신호
    out, n_sl, n_tp = apply_stops(close, held, stop_loss_pct=5)
    # 진입가 100(전일 종가) → 3일차 종가 90 ≤ 95 → 손절, 이후 신호가 계속 1이라 재진입 없음
    assert n_sl == 1 and n_tp == 0
    assert out.tolist() == [0, 1, 1, 0, 0, 0, 0, 0]


def test_take_profit_then_reentry_on_fresh_signal():
    idx = pd.date_range("2026-01-01", periods=8, freq="D")
    close = pd.Series([100, 100, 112, 113, 114, 110, 111, 112], index=idx, dtype=float)
    held = pd.Series([0, 1, 1, 1, 0, 0, 1, 1], index=idx, dtype=float)
    out, n_sl, n_tp = apply_stops(close, held, take_profit_pct=10)
    assert n_tp == 1
    assert out.tolist() == [0, 1, 1, 0, 0, 0, 1, 1]  # 익절 후 신호 0→1 재진입 허용


def test_no_stops_is_identity():
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    held = pd.Series([0, 1, 1, 0, 1], index=idx, dtype=float)
    out, a, b = apply_stops(pd.Series(range(5), index=idx, dtype=float), held)
    assert out.equals(held) and (a, b) == (0, 0)


def test_backtest_strategy_accepts_costs_and_stops():
    r = backtest_strategy(make_candles(400), strategy="ma", cost_bps=10, slippage_bps=5, stop_loss_pct=5, take_profit_pct=20)
    assert "error" not in r
    for k in ("gross_return_pct", "cost_pct", "stop_loss_exits", "take_profit_exits"):
        assert k in r
    assert r["total_return_pct"] <= r["gross_return_pct"] + 1e-9


def test_optimize_portfolio_expected_return_is_shrunk():
    """기대수익률은 실현수익(±30% 클립)과 장기 7%의 절반씩 → 종목별 -11.5%~18.5% 범위를 벗어날 수 없다."""
    from app.services.investment_research import optimize_portfolio
    data = [{"symbol": "A", "candles": make_candles(400, seed=1, start=100)},
            {"symbol": "B", "candles": make_candles(400, seed=2, start=200)},
            {"symbol": "C", "candles": make_candles(400, seed=3, start=50)}]
    r = optimize_portfolio(data, "aggressive")
    assert -11.5 - 1e-6 <= r["expected_return_pct"] <= 18.5 + 1e-6
    assert "expected_return_raw_pct" in r and abs(sum(r["weights"].values()) - 100) < 0.5


def test_backtest_stop_gap_and_realized_rr():
    """B2 — 갭 하락 · 실현 손익비 · 기대값."""
    idx = pd.date_range("2026-01-01", periods=12, freq="D")
    close = pd.Series([100, 100, 95, 95, 100, 100, 104, 104, 104, 104, 104, 104], index=idx, dtype=float)
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1000}, index=idx)
    signals = pd.Series([0, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 0], index=idx, dtype=float)

    r = backtest(df, signals, stop_loss_pct=2, take_profit_pct=4)
    assert r["stop_loss_exits"] >= 1
    assert r["stop_gap_count"] >= 1                 # 95 ≤ 98 → 갭
    assert r["stop_avg_actual_pct"] is not None
    assert r["stop_avg_actual_pct"] < r["stop_avg_planned_pct"]   # 실제가 더 나쁨
    assert r["realized_rr"] is not None
    assert r["expectancy"] is not None


def test_apply_stops_return_exits():
    """B2 — return_exits=True 시 exits 리스트 반환."""
    idx = pd.date_range("2026-01-01", periods=8, freq="D")
    close = pd.Series([100, 100, 90, 95, 99, 100, 101, 102], index=idx, dtype=float)
    held = pd.Series([0, 1, 1, 1, 1, 1, 1, 1], index=idx, dtype=float)
    out, exits = apply_stops(close, held, stop_loss_pct=5, return_exits=True)
    assert len(exits) == 1
    assert exits[0]["type"] == "stop"
    assert exits[0]["planned_pct"] == -5.0
    assert exits[0]["actual_pct"] == pytest.approx(-10.0, abs=1e-3)   # 90/100 - 1 = -10%


def test_backtest_entry_mode_open_captures_day_only():
    """B3 — entry_mode='open'은 진입일 시가→종가만 반영."""
    idx = pd.date_range("2026-01-01", periods=8, freq="D")
    # 시가·종가 다르게
    open_ = pd.Series([100, 100, 110, 111, 112, 113, 114, 115], index=idx, dtype=float)
    close = pd.Series([100, 100, 121, 111, 112, 113, 114, 115], index=idx, dtype=float)
    df = pd.DataFrame({"open": open_, "high": close, "low": open_, "close": close, "volume": 1000}, index=idx)
    signals = pd.Series([0, 1, 1, 0, 0, 0, 0, 0], index=idx, dtype=float)

    # 종가 진입 (기본): 진입일 종가→다음 종가 = close[2]/close[1] = 121/100
    r_close = backtest(df, signals, entry_mode="close", exit_mode="close")
    # 시가 진입: 진입일 시가→종가 = close[2]/open[2] = 121/110
    r_open = backtest(df, signals, entry_mode="open", exit_mode="close")

    assert r_close["total_return_pct"] > r_open["total_return_pct"]   # 종가 진입이 이 날은 더 유리
    assert r_close["entry_mode"] == "close"
    assert r_open["entry_mode"] == "open"


def test_backtest_exit_mode_open_captures_gap():
    """B3 — exit_mode='open'은 청산일 시가로 나가므로 갭만 반영."""
    idx = pd.date_range("2026-01-01", periods=6, freq="D")
    close = pd.Series([100, 100, 110, 120, 120, 120], index=idx, dtype=float)
    open_ = pd.Series([100, 100, 110, 120, 115, 120], index=idx, dtype=float)
    df = pd.DataFrame({"open": open_, "high": close, "low": open_, "close": close, "volume": 1000}, index=idx)
    signals = pd.Series([0, 1, 1, 0, 0, 0], index=idx, dtype=float)

    r_close = backtest(df, signals, exit_mode="close")
    r_open = backtest(df, signals, exit_mode="open")
    assert r_close["exit_mode"] == "close"
    assert r_open["exit_mode"] == "open"
    # open 청산은 4일차 시가(115)로 나감 → 종가(120) 청산보다 손해
    assert r_open["total_return_pct"] < r_close["total_return_pct"]


def test_backtest_invalid_mode_raises():
    idx = pd.date_range("2026-01-01", periods=4, freq="D")
    close = pd.Series([100, 101, 102, 103], index=idx, dtype=float)
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1000}, index=idx)
    sig = pd.Series([0, 1, 1, 0], index=idx, dtype=float)
    with pytest.raises(ValueError):
        backtest(df, sig, entry_mode="intrabar")


def test_backtest_custom_indicator_passes_entry_mode():
    """B3 — backtest_custom_indicator 가 entry_mode 를 받아 backtest 에 전달."""
    r = backtest_custom_indicator(make_candles(300), base="rsi_ma", entry_mode="open", exit_mode="open")
    assert r["costs"]["entry_mode"] == "open"
    assert r["costs"]["exit_mode"] == "open"


def test_backtest_strategy_accepts_entry_mode():
    """B3 — backtest_strategy 도 entry_mode · exit_mode 를 받는다."""
    r = backtest_strategy(make_candles(400), strategy="ma",
                          entry_mode="open", exit_mode="open")
    assert "error" not in r
    assert r["entry_mode"] == "open"
    assert r["exit_mode"] == "open"


def test_backtest_strategy_rejects_bad_mode():
    r = backtest_strategy(make_candles(400), strategy="ma", entry_mode="intrabar")
    assert "error" in r
    assert "close | open" in r["error"]