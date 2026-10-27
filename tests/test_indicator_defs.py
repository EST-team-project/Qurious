"""지표 정의 — RSI · 볼린저 · ATR 이 TradingView 정의 한 벌로 계산되는가 (TC-IN · `P01-②-1`).

목표 기능 ② 설계서 5.1 의 정의:
  RSI   상승 · 하락폭의 Wilder 평활(첫 n개 단순평균으로 시작 · α = 1/n) · 하락폭 0 → 100 · 상승폭 0 → 0
  볼린저 SMA ± k × 모집단 표준편차(나눗수 n)
  ATR   TR 의 Wilder 평활 · 첫 봉 TR = 고가 − 저가
  DMI   TradingView 내장 DMI 스크립트 식(±DM 은 큰 쪽만 · 동률이면 둘 다 0 · 첫 봉 TR 은 비움) · 상대 강도 = (종목 ÷ 기준선) 의 n봉 변화율
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


def _dmi_pine_loop(high, low, close, n=14, m=14):
    """TradingView 내장 DMI 스크립트를 봉 하나씩 옮긴 대조용 셈 — ta.rma 는 첫 n개 단순평균 뒤 α = 1/n, fixnan 은 앞 값."""
    def rma_step(prev, x, k, buf):
        if prev is None:
            if x is None:
                return None
            buf.append(x)
            return sum(buf) / k if len(buf) == k else None
        return prev if x is None else prev + (x - prev) / k

    out, st = [], {"tr": None, "p": None, "m": None, "a": None, "bt": [], "bp": [], "bm": [], "ba": [], "fp": None, "fm": None}
    for i in range(len(close)):
        if i == 0:
            up = dn = tr = None
        else:
            up, dn = high[i] - high[i - 1], -(low[i] - low[i - 1])
            tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        pdm = None if up is None else (up if up > dn and up > 0 else 0.0)
        mdm = None if dn is None else (dn if dn > up and dn > 0 else 0.0)
        st["tr"] = rma_step(st["tr"], tr, n, st["bt"])
        st["p"] = rma_step(st["p"], pdm, n, st["bp"])
        st["m"] = rma_step(st["m"], mdm, n, st["bm"])
        if st["tr"] is not None and st["p"] is not None:
            if st["tr"] != 0:
                st["fp"], st["fm"] = 100 * st["p"] / st["tr"], 100 * st["m"] / st["tr"]
        plus, minus = st["fp"], st["fm"]
        dx = None if plus is None else abs(plus - minus) / ((plus + minus) or 1.0)
        st["a"] = rma_step(st["a"], dx, m, st["ba"])
        out.append((plus, minus, None if st["a"] is None else 100 * st["a"]))
    return out


def test_dmi_matches_pine_script_bar_by_bar():
    df = preprocess(make_candles(300)).astype(float)
    plus, minus, adx = ta.dmi(df["high"], df["low"], df["close"], 14, 14)
    ref = _dmi_pine_loop(df["high"].tolist(), df["low"].tolist(), df["close"].tolist())
    for i, (p, m, a) in enumerate(ref):
        for got, want in ((plus.iloc[i], p), (minus.iloc[i], m), (adx.iloc[i], a)):
            assert (np.isnan(got) and want is None) or got == pytest.approx(want, rel=1e-12)
    assert plus.notna().to_numpy().argmax() == 14 and adx.notna().to_numpy().argmax() == 27   # 첫 봉 TR 이 비어 한 봉 늦게 시작


def test_dmi_tie_gives_zero_to_both_sides():
    # 고가 +1 · 저가 −1 이 매일 같으면(동률) ±DM 이 늘 0 → ±DI 0 · ADX 0 (0 나누기는 1 로)
    high, low = _s([10 + i for i in range(40)]), _s([8 - i for i in range(40)])
    plus, minus, adx = ta.dmi(high, low, (high + low) / 2, 14, 14)
    assert (plus.dropna() == 0).all() and (minus.dropna() == 0).all() and (adx.dropna() == 0).all()


def test_relative_strength_hand_computed():
    # 종목 100 → 110 → 121 · 기준선 100 → 100 → 110 → 비율 1 · 1.1 · 1.1 → 1봉 변화율 빈 값 · 10% · 0%
    idx = pd.to_datetime(["2026-08-27", "2026-08-28", "2026-08-31"])
    rs = ta.relative_strength(pd.Series([100, 110, 121], index=idx), pd.Series([100, 100, 110], index=idx), 1)
    assert np.isnan(rs.iloc[0]) and rs.iloc[1] == pytest.approx(0.10) and rs.iloc[2] == pytest.approx(0.0)


def test_relative_strength_leaves_missing_benchmark_day_empty():
    idx = pd.to_datetime(["2026-08-27", "2026-08-28", "2026-08-31"])
    bench = pd.Series([100, 110], index=idx[[0, 2]])          # 08-28 기준선 없음 — 앞 값으로 채우지 않는다
    rs = ta.relative_strength(pd.Series([100, 110, 121], index=idx), bench, 1)
    assert rs.iloc[1:].isna().all()


# 값이 처음 나오는 봉(0부터 센 자리 · 설계서 4.1 warm-up 표) — EMA · MACD 는 첫 봉부터 값이 있지만 시작값의 영향이 한동안 남는다
_WARMUP = {
    "sma20": (lambda d: ta.sma(d["close"], 20), 19),
    "sma60": (lambda d: ta.sma(d["close"], 60), 59),
    "ema20": (lambda d: ta.ema(d["close"], 20), 0),
    "macd": (lambda d: ta.macd(d["close"], 12, 26, 9)[0], 0),
    "macd_signal": (lambda d: ta.macd(d["close"], 12, 26, 9)[1], 0),
    "bb20": (lambda d: ta.bollinger(d["close"], 20, 2.0)[0], 19),
    "rsi14": (lambda d: ta.rsi(d["close"], 14), 14),
    "atr14": (lambda d: ta.atr(d["high"], d["low"], d["close"], 14), 13),
    "plus_di14": (lambda d: ta.dmi(d["high"], d["low"], d["close"], 14, 14)[0], 14),
    "adx14": (lambda d: ta.dmi(d["high"], d["low"], d["close"], 14, 14)[2], 27),
    "rs20": (lambda d: ta.relative_strength(d["close"], d["open"], 20), 20),
}


@pytest.mark.parametrize("name", sorted(_WARMUP))
def test_first_value_bar(name):
    df = preprocess(make_candles(120)).astype(float)
    fn, first = _WARMUP[name]
    s = fn(df)
    assert s.iloc[:first].isna().all() and s.iloc[first:].notna().all()


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


# 2026-10-26 TradingView KRX:005930 일봉 · 내장 「방향성 운동 지수」 14 · 14 에서 사람이 읽은 (ADX, +DI, −DI) — 화면은 소수 넷째 자리.
# 2024-10-17 은 고가 상승폭 = 저가 하락폭인 날이라, 동률이면 +DM 에 넣는 식(LEAN)이면 +DI 가 12.7079 로 갈린다.
TRADINGVIEW_DMI_005930 = {"2024-10-17": (47.1197, 12.2877, 34.8724), "2024-10-18": (47.1746, 11.7557, 33.3626),
                          "2026-08-03": (27.3250, 20.2175, 31.7230), "2026-08-06": (26.6565, 20.2312, 34.6019),
                          "2026-08-13": (23.5717, 25.9783, 27.4998), "2026-08-21": (18.4291, 32.6312, 24.8224),
                          "2026-08-31": (13.3685, 28.1758, 30.2554)}


@pytest.mark.skipif(not REAL_DB.is_file(), reason="수집 DB 가 없다(CI · 새 clone)")
def test_dmi_matches_tradingview_screen():
    data = read_daily_candles("005930.KS", period="max", today=date(2026, 8, 31), path=REAL_DB)
    assert data and data["candles"], "수집 DB 에 005930 일봉이 없다"
    kst = timezone(timedelta(hours=9))
    df = pd.DataFrame(data["candles"])
    df.index = [datetime.fromtimestamp(t, kst).date().isoformat() for t in df["time"]]
    plus, minus, adx = ta.dmi(df["high"], df["low"], df["close"], 14, 14)
    for day, shown in TRADINGVIEW_DMI_005930.items():
        assert (adx[day], plus[day], minus[day]) == pytest.approx(shown, abs=0.00005), day   # 화면 반올림의 절반


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
