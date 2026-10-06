"""공통 기술적 지표 · 성과지표 계산 유틸.

앱 안의 RSI · 볼린저 · ATR 은 모두 이 모듈 하나로 계산한다 — 같은 이름의 지표가 파일마다
다른 식으로 갈라지지 않게 한다(목표 기능 ② 설계서 5.1 · RTM `P01-②-1`).
정의는 TradingView Pine v5 의 식을 그대로 옮긴 판 `DEFINITION` 이다.

  RSI(n)       상승 · 하락폭을 `rma`(첫 n개 단순평균으로 시작 · α = 1/n)로 평활 ·
               하락폭 0 → 100 · 상승폭 0 → 0 (Pine `ta.rsi`)
  볼린저(n, k)  SMA(n) ± k × 모집단 표준편차(나눗수 n · Pine `ta.stdev`)
  ATR(n)       TR 을 `rma` 로 평활(Pine `ta.atr`) · 첫 봉의 TR 은 고가 − 저가

예전에는 RSI 가 단순평균(기본) · 시작값이 첫 값인 Wilder 두 갈래였고, 볼린저는 n − 1,
ATR 은 단순평균이었다 — 실제 종목 2,653개에서 RSI 30 아래 날 수가 2.6배 갈렸다(설계서 3.3).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 지표 정의 판. 정의를 바꾸면 판을 올린다 — 신호 기록(T2)이 판으로 옛 기록과 새 기록을 가른다.
DEFINITION = "tv-2026"


def rma(x: pd.Series, period: int) -> pd.Series:
    """Wilder 평활(Pine `ta.rma`). 첫 값 = 처음 n개 유효값의 단순평균, 이후 α = 1/n.

    t 시점 값은 t 까지의 값으로만 정해진다. 중간의 빈 값은 건너뛰고(상태 유지) 그 자리는 빈 값으로 둔다.
    """
    x = x.astype(float)
    out = pd.Series(np.nan, index=x.index)
    valid = np.flatnonzero(x.notna().to_numpy())
    if len(valid) < period:
        return out
    seed_pos = valid[period - 1]
    s = x.iloc[seed_pos:].copy()
    s.iloc[0] = x.iloc[valid[:period]].mean()
    smoothed = s.ewm(alpha=1 / period, adjust=False, ignore_na=True).mean()
    out.iloc[seed_pos:] = smoothed.where(s.notna()).to_numpy()
    return out


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """상대강도지수(Pine `ta.rsi`)."""
    delta = close.astype(float).diff()
    gain = rma(delta.clip(lower=0), period)
    loss = rma(-delta.clip(upper=0), period)
    with np.errstate(divide="ignore", invalid="ignore"):
        value = 100 - 100 / (1 + gain / loss)
    value = value.where(gain != 0, 0.0).where(loss != 0, 100.0)
    return value.where(gain.notna())


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(period).mean()


def ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """반환: (MACD선, 시그널선, 히스토그램)."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """반환: (상단밴드, 중심선, 하단밴드). 표준편차는 모집단(나눗수 n)."""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return mid + std_mult * std, mid, mid - std_mult * std


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """평균 진폭(Pine `ta.atr`) — TR 의 Wilder 평활."""
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return rma(tr, period)


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def max_drawdown(cum_returns: pd.Series) -> float:
    """누적 수익 배수 시계열(1.0 시작)을 받아 최대낙폭을 음수 비율로 반환."""
    roll_max = cum_returns.cummax()
    drawdown = (cum_returns - roll_max) / roll_max.replace(0, np.nan)
    return float(drawdown.min())
