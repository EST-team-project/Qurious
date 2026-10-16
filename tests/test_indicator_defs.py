"""지표 정의 — RSI · 볼린저 · ATR 이 TradingView 정의 한 벌로 계산되는가 (TC-IN · `P01-②-1`).

목표 기능 ② 설계서 5.1 의 정의:
  RSI   상승 · 하락폭의 Wilder 평활(첫 n개 단순평균으로 시작 · α = 1/n) · 하락폭 0 → 100 · 상승폭 0 → 0
  볼린저 SMA ± k × 모집단 표준편차(나눗수 n)
  ATR   TR 의 Wilder 평활 · 첫 봉 TR = 고가 − 저가
그리고 앱 안에서 이 지표가 나오는 길(화면 · 로보 스크리닝)이 모두 같은 값을 내는가 · 실제 종목에서 TradingView 화면 값과 같은가.
자동매매 종목 점수(`ml_symbol_score`)는 다른 파트의 파일이라 이 시험에 넣지 않았다(설계서 3.4).
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services import ta_utils as ta
from app.services.collector_db import read_daily_candles
from app.services.investment_research import indicators
from app.services.quant_pipeline import preprocess
from app.services.stock import _calc_bollinger, _calc_rsi
from tests.conftest import make_candles


def _s(values) -> pd.Series:
    return pd.Series(values, dtype=float)


# ── 손으로 셀 수 있는 수열 ───────────────────────────────────────────────

def test_rsi_hand_computed():
    # 변화 +1 · +1 · −1 · +2 (n = 3)
    # 셋째 변화에서: 상승 평균 (1+1+0)/3 = 2/3 · 하락 평균 1/3 → RS 2 → 66.67
    # 넷째 변화에서: 상승 (2/3·2 + 2)/3 = 10/9 · 하락 (1/3·2 + 0)/3 = 2/9 → RS 5 → 83.33
    r = ta.rsi(_s([1, 2, 3, 2, 4]), 3)
    assert r.iloc[:3].isna().all()
    assert r.iloc[3] == pytest.approx(100 - 100 / 3)
    assert r.iloc[4] == pytest.approx(100 - 100 / 6)


@pytest.mark.parametrize("closes, expected", [
    ([1, 2, 3, 4, 5, 6], 100.0),   # 오르기만 — 하락폭 0
    ([6, 5, 4, 3, 2, 1], 0.0),     # 내리기만 — 상승폭 0
    ([5, 5, 5, 5, 5, 5], 100.0),   # 평평 — 둘 다 0 이면 Pine 은 100 (하락폭 0 을 먼저 본다)
])
def test_rsi_edges(closes, expected):
    assert ta.rsi(_s(closes), 3).iloc[-1] == pytest.approx(expected)


def test_rsi_textbook_wilder_example():
    """Wilder 방식의 널리 쓰이는 예제(14일). 예제 표는 중간 평균을 반올림해 계산하므로 ±0.1 안에서 본다.
    단순평균 RSI 였다면 첫 값부터 크게 다르다."""
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
              46.28, 46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18,
              44.22, 44.57, 43.42, 42.66, 43.13]
    expected = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99,
                41.46, 41.87, 45.46, 37.30, 33.08, 37.77]
    got = ta.rsi(_s(closes), 14).dropna().to_numpy()
    assert len(got) == len(expected)
    assert np.abs(got - np.array(expected)).max() < 0.1


def test_rma_seed_is_simple_average():
    r = ta.rma(_s([2, 4, 6, 8]), 3)
    assert r.iloc[2] == pytest.approx(4.0)                    # (2+4+6)/3
    assert r.iloc[3] == pytest.approx((4.0 * 2 + 8) / 3)      # 이후 Wilder


def test_bollinger_uses_population_std():
    x = _s([10, 12, 11, 13, 15, 14, 16, 18, 17, 19])
    up, mid, lo = ta.bollinger(x, 5, 2.0)
    window = x.iloc[-5:].to_numpy()
    assert mid.iloc[-1] == pytest.approx(window.mean())
    assert up.iloc[-1] - mid.iloc[-1] == pytest.approx(2.0 * window.std(ddof=0))
    assert mid.iloc[-1] - lo.iloc[-1] == pytest.approx(2.0 * window.std(ddof=0))


def test_atr_hand_computed():
    # TR: 첫 봉 = 고 − 저 = 2 · 이후 max(고−저, |고−전종|, |저−전종|) = 3 · 2 · 4 (n = 3)
    high, low, close = _s([11, 13, 13, 16]), _s([9, 11, 11, 12]), _s([10, 12, 12, 15])
    a = ta.atr(high, low, close, 3)
    assert a.iloc[2] == pytest.approx((2 + 3 + 2) / 3)
    assert a.iloc[3] == pytest.approx(((7 / 3) * 2 + 4) / 3)


# ── TradingView 화면 값 (설계서 3.9 · 인수 기준 2) ────────────────────────────

# 2026-10-16 TradingView KRX:005930 일봉 · RSI 14 close(기본값)에서 사람이 읽은 값 — 화면은 소수 둘째 자리
TRADINGVIEW_RSI_005930 = {"2026-08-03": 44.25, "2026-08-06": 42.66, "2026-08-13": 53.39,
                          "2026-08-21": 56.06, "2026-08-31": 50.00}
# 시세는 저장소에 담지 않고(공개 저장소 · 계획서 7절 · 코딩표준 9절) 이 PC 의 수집 DB 를 읽는다
REAL_DB = Path(__file__).resolve().parents[1] / "data" / "collector" / "market.sqlite3"


@pytest.mark.skipif(not REAL_DB.is_file(), reason="수집 DB 가 없다(CI · 새 clone)")
def test_rsi_matches_tradingview_screen():
    """앱 일봉 다리로 읽은 종가(2026-08-31 까지 · 봉인 구간 밖)의 RSI 14 가 TradingView 화면 값과 반올림 안에서 같다."""
    data = read_daily_candles("005930.KS", period="max", today=date(2026, 8, 31), path=REAL_DB)
    assert data and data["candles"], "수집 DB 에 005930 일봉이 없다"
    kst = timezone(timedelta(hours=9))
    closes = pd.Series([c["close"] for c in data["candles"]],
                       index=[datetime.fromtimestamp(c["time"], kst).date().isoformat() for c in data["candles"]])
    rsi = ta.rsi(closes, 14)
    for day, shown in TRADINGVIEW_RSI_005930.items():
        assert rsi[day] == pytest.approx(shown, abs=0.005), day   # 화면 반올림의 절반


# ── 앱 안의 길이 모두 같은 값을 내는가 (갈래 0) ─────────────────────────────

def _closes(n=300, seed=7) -> pd.Series:
    return preprocess(make_candles(n, seed=seed))["close"].astype(float)


def test_screen_rsi_equals_ta_utils():
    c = _closes()
    screen = pd.Series(_calc_rsi(c.tolist()), index=c.index, dtype=float)
    pd.testing.assert_series_equal(screen, ta.rsi(c).round(2), check_names=False)


def test_screen_bollinger_equals_ta_utils():
    c = _closes()
    for got, want in zip(_calc_bollinger(c.tolist()), ta.bollinger(c)):
        pd.testing.assert_series_equal(pd.Series(got, index=c.index, dtype=float), want.round(2), check_names=False)


def test_robo_screening_rsi_equals_ta_utils():
    candles = make_candles(300, seed=11)
    df = indicators(candles)
    pd.testing.assert_series_equal(df["rsi"], ta.rsi(df["close"].astype(float)), check_names=False)


def test_rsi_has_no_method_switch():
    """정의를 고르는 인자를 다시 두지 않는다 — 두 정의가 갈라진 것이 이 문제의 시작이었다."""
    with pytest.raises(TypeError):
        ta.rsi(_closes(), 14, method="sma")
