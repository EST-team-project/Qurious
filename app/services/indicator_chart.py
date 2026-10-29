"""U7 지표 차트 — 기본 인디케이터 전략 화면(W7 `indicator-strategy`)의 가격 차트에 그릴 값(#392 · 설계서 4.6).

지표는 모두 정의 한 벌(`ta_utils` · TradingView 정의)로 일봉 전체에서 계산한 뒤 고른 기간만 돌려준다 — 기간 앞쪽 봉도
창이 찬 값이 나온다. 새로 짓지 않는다:
- 이동평균 5 · 20 · 60 · 볼린저(20 · 2σ · 모집단) · RSI(14) · MACD(12 · 26 · 9) · DMI(ADX · +DI · −DI · 14 · 14)
- 상대 강도 = 「종목 ÷ 기준선」 의 20 · 60 · 120봉 변화율(#197 3). 기준선은 시장 지수부터(코스피 · 코스닥) — 기준선을 모르는
  시장은 비우고 까닭을 적는다(국내만으로 굳히지 않는다).
- 매수 · 매도 표식 = 카드 판 2 조건(`ma_cross` · 단기 > 장기 상태)이 바뀐 봉. 판단은 그 봉 종가까지의 값이다 — 체결은 카드의
  `entry_mode` 를 따른다(차트는 판단 봉만 찍는다).
"""
from __future__ import annotations

import math

import pandas as pd

from app.services import ta_utils

#: 기호 끝 → 기준선(시장 지수). 여기 없는 시장은 상대 강도를 비운다.
BENCHMARKS = {".KS": ("^KS11", "코스피"), ".KQ": ("^KQ11", "코스닥")}
RS_PERIODS = (20, 60, 120)
#: 기간 → 돌려줄 봉 수(거래일). 지표 계산에는 받은 일봉 전체를 쓴다.
PERIOD_BARS = {"3mo": 63, "6mo": 126, "1y": 252, "2y": 504}
#: 계산용으로 더 받을 기간 — 가장 긴 창(상대 강도 120 · 이동평균 120)이 기간 첫 봉부터 값을 내게.
FETCH_PERIOD = {"3mo": "1y", "6mo": "1y", "1y": "2y", "2y": "5y"}


def benchmark_for(symbol: str) -> tuple[str, str] | None:
    for suffix, bench in BENCHMARKS.items():
        if symbol.upper().endswith(suffix):
            return bench
    return None


def _frame(candles: list[dict]) -> pd.DataFrame:
    rows = [c for c in candles if c.get("close") is not None]
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    return df.astype({"open": float, "high": float, "low": float, "close": float}).set_index("time")


def _list(s: pd.Series, digits: int = 4) -> list[float | None]:
    return [None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), digits) for v in s.tolist()]


def ma_cross_markers(close: pd.Series, short: int, long: int) -> list[dict]:
    """카드 조건(단기 이동평균 > 장기 이동평균 상태)이 바뀐 봉 — 참이 되면 buy, 거짓이 되면 sell. 두 평균이 다 나온 뒤부터."""
    s, l = ta_utils.sma(close, short), ta_utils.sma(close, long)
    ready = s.notna() & l.notna()
    state = (s > l).where(ready)
    out, prev = [], None
    for t, v in state.items():
        if pd.isna(v):
            continue
        v = bool(v)
        if prev is not None and v != prev:
            out.append({"time": int(t), "side": "buy" if v else "sell"})
        prev = v
    return out


def build(candles: list[dict], period: str, short: int, long: int,
          bench_candles: list[dict] | None = None, bench: tuple[str, str] | None = None) -> dict:
    """일봉 전체 → 고른 기간의 봉 · 지표 시계열 · 표식. 봉이 모자라면 `error`."""
    df = _frame(candles)
    if len(df) < 20:
        return {"error": "데이터 부족"}
    close = df["close"]
    upper, mid, lower = ta_utils.bollinger(close, 20, 2.0)
    macd, signal, hist = ta_utils.macd(close)
    plus_di, minus_di, adx = ta_utils.dmi(df["high"], df["low"], close)
    series = {
        "ma5": ta_utils.sma(close, 5), "ma20": ta_utils.sma(close, 20), "ma60": ta_utils.sma(close, 60),
        "bb_upper": upper, "bb_mid": mid, "bb_lower": lower, "rsi": ta_utils.rsi(close, 14),
        "macd": macd, "macd_signal": signal, "macd_hist": hist, "adx": adx, "plus_di": plus_di, "minus_di": minus_di,
    }
    rs_note = None
    if bench is None:
        rs_note = "이 시장은 기준선(시장 지수)을 정하지 않아 상대 강도를 비웁니다."
    elif not bench_candles:
        rs_note = f"기준선 {bench[1]}({bench[0]}) 일봉을 받지 못해 상대 강도를 비웁니다."
    else:
        b = _frame(bench_candles)["close"]
        for n in RS_PERIODS:
            series[f"rs{n}"] = ta_utils.relative_strength(close, b, n) * 100   # 화면은 % 로 읽는다
    keep = PERIOD_BARS.get(period, len(df))
    df_k = df.tail(keep)
    first = df_k.index[0]
    markers = [m for m in ma_cross_markers(close, short, long) if m["time"] >= first]
    return {
        "bars": [{"time": int(t), "open": r.open, "high": r.high, "low": r.low, "close": r.close} for t, r in df_k.iterrows()],
        "series": {k: _list(v.reindex(df_k.index), 2 if k.startswith(("ma", "bb")) else 4) for k, v in series.items()},
        "markers": markers,
        "card_condition": {"indicator": "ma_cross", "short_window": short, "long_window": long, "condition": "short_above_long"},
        "benchmark": {"symbol": bench[0], "name": bench[1]} if bench else None,
        "rs_note": rs_note,
    }
