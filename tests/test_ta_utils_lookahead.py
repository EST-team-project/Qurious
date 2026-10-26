"""지표 함수의 미래 데이터 참조(look-ahead) 방지 검증.

t 시점 지표값은 t 이후 데이터가 추가·변경돼도 달라지면 안 된다(causal).
"""
import numpy as np
import pandas as pd
import pytest

from app.services import ta_utils as ta
from app.services.quant_pipeline import feature_engineer, preprocess, FEATURE_COLS, backtest
from tests.conftest import make_candles


def _close(n=300):
    return preprocess(make_candles(n))["close"].astype(float)


@pytest.mark.parametrize("fn", [
    lambda c: ta.sma(c, 20),
    lambda c: ta.rsi(c, 14),
    lambda c: ta.macd(c, 12, 26, 9)[0],
    lambda c: ta.bollinger(c, 20, 2.0)[0],
    lambda c: ta.bollinger(c, 20, 2.0)[2],
    lambda c: ta.bollinger(c, 20, 2.0)[1],
    lambda c: ta.ema(c, 20),
    lambda c: ta.macd(c, 12, 26, 9)[1],
    lambda c: ta.macd(c, 12, 26, 9)[2],
    lambda c: ta.rma(c, 14),
])
def test_indicators_are_causal(fn):
    c = _close(300)
    full = fn(c)
    truncated = fn(c.iloc[:250])
    # 앞 250개 구간의 값은 뒤 50개 데이터 존재 여부와 무관해야 한다
    pd.testing.assert_series_equal(full.iloc[:250].dropna(), truncated.dropna(), check_names=False)


_STREAM = {
    "sma20": lambda d: ta.sma(d["close"], 20),
    "ema20": lambda d: ta.ema(d["close"], 20),
    "rma14": lambda d: ta.rma(d["close"], 14),
    "rsi14": lambda d: ta.rsi(d["close"], 14),
    "macd": lambda d: ta.macd(d["close"], 12, 26, 9)[0],
    "macd_signal": lambda d: ta.macd(d["close"], 12, 26, 9)[1],
    "macd_hist": lambda d: ta.macd(d["close"], 12, 26, 9)[2],
    "bb_upper": lambda d: ta.bollinger(d["close"], 20, 2.0)[0],
    "bb_mid": lambda d: ta.bollinger(d["close"], 20, 2.0)[1],
    "bb_lower": lambda d: ta.bollinger(d["close"], 20, 2.0)[2],
    "atr14": lambda d: ta.atr(d["high"], d["low"], d["close"], 14),
    "plus_di14": lambda d: ta.dmi(d["high"], d["low"], d["close"], 14, 14)[0],
    "minus_di14": lambda d: ta.dmi(d["high"], d["low"], d["close"], 14, 14)[1],
    "adx14": lambda d: ta.dmi(d["high"], d["low"], d["close"], 14, 14)[2],
    "rs20": lambda d: ta.relative_strength(d["close"], d["high"].rolling(3).mean(), 20),
}


@pytest.mark.parametrize("name", sorted(_STREAM))
def test_one_new_bar_matches_full_recompute(name):
    df = preprocess(make_candles(300))[["high", "low", "close"]].astype(float)
    fn = _STREAM[name]
    full = fn(df)
    prev = fn(df.iloc[:240])
    for k in range(241, len(df) + 1):
        cur = fn(df.iloc[:k])
        pd.testing.assert_series_equal(cur.iloc[:-1], prev, check_names=False, rtol=1e-12, atol=0)
        assert cur.iloc[-1] == pytest.approx(full.iloc[k - 1], rel=1e-12, abs=0)
        prev = cur


@pytest.mark.parametrize("name", sorted(_STREAM))
def test_missing_bar_keeps_past_and_recovers(name):
    df = preprocess(make_candles(300))[["high", "low", "close"]].astype(float)
    gap = df.copy()
    gap.iloc[150] = np.nan
    fn = _STREAM[name]
    full, holed = fn(df), fn(gap)
    pd.testing.assert_series_equal(holed.iloc[:150], full.iloc[:150], check_names=False)
    assert holed.iloc[200:].notna().all()


def test_atr_is_causal():
    df = preprocess(make_candles(300))
    h, l, c = (df[k].astype(float) for k in ("high", "low", "close"))
    full = ta.atr(h, l, c, 14)
    truncated = ta.atr(h.iloc[:250], l.iloc[:250], c.iloc[:250], 14)
    pd.testing.assert_series_equal(full.iloc[:250].dropna(), truncated.dropna(), check_names=False)


def test_rsi_value_unchanged_when_later_bars_change():
    """뒤 봉을 크게 바꿔도(30% 급등) 그 앞 RSI 는 그대로다 — Wilder 평활은 앞 값만 이어받는다."""
    c = _close(300)
    tampered = c.copy()
    tampered.iloc[-1] *= 1.30
    pd.testing.assert_series_equal(ta.rsi(c).iloc[:-1], ta.rsi(tampered).iloc[:-1])


def test_rsi_bounds():
    rsi = ta.rsi(_close(), 14).dropna()
    assert ((rsi >= 0) & (rsi <= 100)).all()


def test_feature_engineering_is_causal():
    """피처(타깃 제외)는 마지막 봉을 바꿔도 이전 행이 변하지 않아야 한다."""
    candles = make_candles(320)
    a = feature_engineer(preprocess(candles))
    tampered = [dict(x) for x in candles]
    tampered[-1]["close"] *= 1.30  # 마지막 봉 종가 +30%
    b = feature_engineer(preprocess(tampered))
    common = a.index.intersection(b.index)[:-6]  # 타깃(5일 후) 영향 구간 제외
    pd.testing.assert_frame_equal(a.loc[common, FEATURE_COLS], b.loc[common, FEATURE_COLS])


def test_backtest_applies_signal_next_day():
    """백테스트는 t일 신호를 t+1일 수익률에 적용해야 한다 (shift(1))."""
    df = feature_engineer(preprocess(make_candles(200)))
    sig = pd.Series(0, index=df.index)
    sig.iloc[10] = 1  # 10일째 하루만 매수 신호
    bt = backtest(df, sig)
    ret = df["close"].pct_change()
    expected = float(ret.iloc[11]) * 100  # 다음 날 수익률만 반영
    assert bt["total_return_pct"] == pytest.approx(expected, abs=0.006)  # 결과는 소수 2자리 반올림


def test_sharpe_and_mdd_helpers():
    r = pd.Series([0.01, -0.02, 0.015, 0.0, -0.01])
    cum = (1 + r).cumprod()
    assert ta.max_drawdown(cum) <= 0
    assert np.isfinite(ta.sharpe_ratio(r))
