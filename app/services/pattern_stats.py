"""패턴 통계 — 과거 모든 날의 패턴과 그 뒤 5거래일 수익률 (목표 기능 ② 설계서 5.2 · `P01-②-2`).

이 파일이 답하는 질문: **"이 패턴이 나온 날 뒤 5거래일 동안 값은 어떻게 움직였나."**

탐지 정의는 화면 탐지기(`patterns.detect_candle_patterns` · `detect_breakouts`)와 같다. 화면 탐지기는
마지막 몇 봉만 보므로, 여기서는 같은 식을 모든 날에 한 번에 계산한다 — 날 t 의 탐지는 t 까지의 봉만 쓴다.
두 쪽이 날마다 같은지는 시험(TC-PS)이 대조한다.

사건 연구 규칙(설계서 <표 9>)
  사건   종목이 날 t 종가로 패턴을 냄 · 거래가 없던 날(거래량 0)은 사건이 아니다
  결과   t → t+5 종가 누적 수익률(`forward_ret_5d`) · 같은 날짜 사이 코스피 수익률을 뺀 초과수익
  겹침   같은 종목 · 같은 패턴이 앞 사건 뒤 5거래일 안에 다시 나면 뺀다(수익 구간이 겹치지 않게)
  기간   봉인 구간(2026-09-01 ~) 밖에서만 — t+5 가 봉인 구간에 닿는 사건은 뺀다
  기준선 같은 종목의 사건 후보가 될 수 있던 모든 날의 5일 수익률 평균
  비용   넣지 않는다 — 가격 움직임의 통계이지 전략 성과가 아니다
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services import ta_utils as ta
from app.services.patterns import PATTERN_META

HORIZON = 5
#: 봉인 구간의 가장 이른 시작 가능일(설계서 3.2 · D7) — 이 날부터의 시세는 읽지도 쓰지도 않는다
SEAL_START = "2026-09-01"
#: 화면 탐지기(`pattern_summary` · `detect_breakouts`)의 최소 봉 수 — 이보다 앞선 날은 사건 후보가 아니다
MIN_BARS = 65
#: 52주 신고가는 1년 치 봉이 다 있을 때만 센다
YEAR_BARS = 252

#: 통계에 넣는 패턴 — 설계서 5.2.1. 나머지 탐지는 화면 표시용이다
BREAKOUT_META = {
    "golden_cross": ("골든크로스 (MA20 > MA60)", "bullish"),
    "dead_cross": ("데드크로스 (MA20 < MA60)", "bearish"),
    "high_52w": ("52주 신고가", "bullish"),
    "support_break": ("지지선 하향 이탈", "bearish"),
    "resistance_break": ("저항선 상향 돌파", "bullish"),
}
CANDLE_KEYS = ("hammer", "bullish_engulfing", "bearish_engulfing", "doji", "morning_star", "three_black_crows")
STAT_PATTERNS = ("golden_cross", "dead_cross", "high_52w", *CANDLE_KEYS, "support_break", "resistance_break")


def pattern_label(key: str) -> tuple[str, str]:
    """(이름, 방향)."""
    if key in BREAKOUT_META:
        return BREAKOUT_META[key]
    name, direction, _desc = PATTERN_META[key]
    return name, direction


# ── 탐지 — 모든 날 ────────────────────────────────────────────────────────

def candle_hits(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """날마다 캔들 패턴이 났는가 — `detect_candle_patterns` 의 식을 모든 봉에 한 번에."""
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    rng = np.maximum(h - l, 1e-9)
    body = np.abs(c - o)
    body_pct = body / rng
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    bull, bear = c > o, c < o
    close = df["close"].astype(float)
    avg = (df["close"].astype(float) - df["open"].astype(float)).abs().rolling(20).mean().to_numpy()
    ab = np.where(np.isnan(avg), body, avg)
    trend = close.pct_change(5).shift(1).to_numpy()
    up = np.where(np.isnan(trend), 0.0, trend)

    def prev(a: np.ndarray, k: int) -> np.ndarray:
        out = np.zeros_like(a)
        out[k:] = a[:-k]
        return out

    p1o, p1c, p1b = prev(o, 1), prev(c, 1), prev(body, 1)
    p1bull, p1bear = prev(bull, 1), prev(bear, 1)
    p2o, p2c, p2b, p2bp = prev(o, 2), prev(c, 2), prev(body, 2), prev(body_pct, 2)
    p2bull, p2bear = prev(bull, 2), prev(bear, 2)
    p1bp = prev(body_pct, 1)

    small = body_pct <= 0.35
    hammer_shape = small & (lower >= 2 * body) & (upper <= body)
    hits = {
        "doji": body_pct <= 0.1,
        "hammer": hammer_shape & ~(up > 0.03),
        "bullish_engulfing": bull & p1bear & (c >= p1o) & (o <= p1c) & (body > p1b),
        "bearish_engulfing": bear & p1bull & (o >= p1c) & (c <= p1o) & (body > p1b),
        "morning_star": p2bear & (p2b > ab) & (p1b < ab * 0.5) & bull & (body > ab) & (c > (p2o + p2c) / 2),
        "three_black_crows": bear & p1bear & p2bear & (c < p1c) & (p1c < p2c)
                             & (np.minimum(np.minimum(body_pct, p1bp), p2bp) > 0.5),
    }
    # 화면 탐지기는 봉이 25개 이상일 때만 본다 — 날 t 에 봉 t + 1 개
    for k in hits:
        hits[k] = hits[k].copy()
        hits[k][:24] = False
    return hits


def _sr_breaks(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int = 5, lookback: int = 120,
               tolerance_pct: float = 1.0, max_levels: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """날마다 지지 이탈 · 저항 돌파가 났는가 — `support_resistance` + `detect_breakouts` 의 레벨 판정.

    날 t 의 레벨은 t 까지 마지막 `lookback` 봉의 피벗으로 만든다. 피벗 j 는 j ± window 봉의 최고 · 최저라
    j + window ≤ t 인 것만 쓴다 — 미래 봉을 보지 않는다.
    """
    n = len(close)
    up = np.zeros(n, dtype=bool)
    dn = np.zeros(n, dtype=bool)
    w = 2 * window + 1
    hi_max = pd.Series(high).rolling(w, center=True).max().to_numpy()
    lo_min = pd.Series(low).rolling(w, center=True).min().to_numpy()
    ph = np.flatnonzero(high == hi_max)
    pl = np.flatnonzero(low == lo_min)
    for t in range(MIN_BARS - 1, n):
        last, prv = close[t], close[t - 1]
        if last == prv:
            continue                                   # 값이 그대로면 어떤 레벨도 넘지 않는다
        s = max(0, t - lookback + 1)
        a, b = s + window, t - window                  # 피벗 자리 [a, b]
        hs = ph[np.searchsorted(ph, a):np.searchsorted(ph, b, side="right")]
        ls = pl[np.searchsorted(pl, a):np.searchsorted(pl, b, side="right")]
        # 화면 탐지기와 같은 차례 — 자리마다 고점 다음 저점, 그 뒤 (가격, 종류)로 정렬
        pivots = sorted([(float(high[j]), "high") for j in hs] + [(float(low[j]), "low") for j in ls])
        clusters: list[list] = []                      # [평균, 가격들]
        for price, _kind in pivots:
            for cl in clusters:
                if abs(price - cl[0]) / cl[0] * 100 <= tolerance_pct:
                    cl[1].append(price)
                    cl[0] = float(np.mean(cl[1]))
                    break
            else:
                clusters.append([price, [price]])
        levels = sorted(((-len(cl[1]), abs(round((cl[0] / last - 1) * 100, 2)), round(cl[0], 2)) for cl in clusters),
                        key=lambda x: (x[0], x[1]))[:max_levels]
        for _t, _d, p in levels:
            if prv <= p < last:
                up[t] = True
            if prv >= p > last:
                dn[t] = True
    return dn, up


def breakout_hits(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """날마다 크로스 · 52주 신고가 · 지지 이탈 · 저항 돌파가 났는가 — `detect_breakouts` 의 식."""
    close = df["close"].astype(float)
    ma20, ma60 = ta.sma(close, 20), ta.sma(close, 60)
    c = close.to_numpy()
    dn, up = _sr_breaks(df["high"].to_numpy(dtype=float), df["low"].to_numpy(dtype=float), c)
    hi52 = close.rolling(YEAR_BARS).max().to_numpy()   # 1년 치가 다 있을 때만 값이 있다
    return {
        "golden_cross": ((ma20 > ma60) & (ma20.shift(1) <= ma60.shift(1))).to_numpy(),
        "dead_cross": ((ma20 < ma60) & (ma20.shift(1) >= ma60.shift(1))).to_numpy(),
        "high_52w": np.where(np.isnan(hi52), False, c >= hi52),
        "support_break": dn,
        "resistance_break": up,
    }


def detect_events(df: pd.DataFrame) -> pd.DataFrame:
    """통계 대상 패턴의 사건 후보 — 칸 `pos`(봉 자리) · `key`. 거래 없던 날 · 최소 봉 수 전은 뺀다."""
    hits = {**candle_hits(df), **breakout_hits(df)}
    ok = df["volume"].to_numpy(dtype=float) > 0
    ok[:MIN_BARS - 1] = False
    rows = [(int(p), k) for k in STAT_PATTERNS for p in np.flatnonzero(hits[k] & ok)]
    return pd.DataFrame(rows, columns=["pos", "key"]).sort_values(["key", "pos"], ignore_index=True)


def thin(pos: np.ndarray, gap: int = HORIZON) -> np.ndarray:
    """앞 사건 뒤 `gap` 거래일 안에 다시 난 사건을 뺀 표식 — 남긴 사건부터 센다."""
    keep = np.zeros(len(pos), dtype=bool)
    last = -10**9
    for i, p in enumerate(pos):
        if p - last > gap:
            keep[i] = True
            last = p
    return keep


# ── 사건 연구 ─────────────────────────────────────────────────────────────

def _day(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def event_study(df: pd.DataFrame, benchmark: pd.Series | None = None, end: str | None = None,
                horizon: int = HORIZON) -> tuple[pd.DataFrame, dict]:
    """한 종목의 사건 표와 기준선.

    df        `preprocess` 를 거친 일봉(날짜 색인)
    benchmark 코스피 종가(날짜 색인) — 없으면 초과수익은 비운다
    end       결과 기간의 끝날(포함). 봉인 구간에 닿으면 그 전날로 줄인다
    돌려주는 것: (사건 표 — date · key · forward_ret_5d · excess_ret_5d, 기준선 {"baseline" · "baseline_up" · "baseline_days"})
    """
    limit = (pd.Timestamp(SEAL_START) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    end = min(end, limit) if end else limit
    days = np.array([_day(t) for t in df.index])
    close = df["close"].to_numpy(dtype=float)
    n = len(close)
    fwd = np.full(n, np.nan)
    if n > horizon:
        fwd[:-horizon] = close[horizon:] / close[:-horizon] - 1
    exit_day = np.array([days[i + horizon] if i + horizon < n else "9999-12-31" for i in range(n)])
    usable = ~np.isnan(fwd) & (exit_day <= end)        # t+5 가 끝날(봉인 구간 전) 안에 있다

    candidate = usable & (df["volume"].to_numpy(dtype=float) > 0)
    candidate[:MIN_BARS - 1] = False
    base = {"baseline": float(np.mean(fwd[candidate])) if candidate.any() else None,
            "baseline_up": float(np.mean(fwd[candidate] > 0)) if candidate.any() else None,
            "baseline_days": int(candidate.sum())}

    ev = detect_events(df)
    keep = np.zeros(len(ev), dtype=bool)
    for _key, g in ev.groupby("key", sort=False):
        keep[g.index] = thin(g["pos"].to_numpy())
    ev = ev[keep]
    ev = ev[usable[ev["pos"].to_numpy(dtype=int)]]
    pos = ev["pos"].to_numpy(dtype=int)
    out = pd.DataFrame({"date": days[pos], "key": ev["key"].to_numpy(), "forward_ret_5d": fwd[pos]})
    if benchmark is not None and len(out):
        b = benchmark.copy()
        b.index = [_day(t) for t in b.index]
        b0 = b.reindex(days[pos]).to_numpy(dtype=float)
        b1 = b.reindex(exit_day[pos]).to_numpy(dtype=float)
        out["excess_ret_5d"] = out["forward_ret_5d"] - (b1 / b0 - 1)
    else:
        out["excess_ret_5d"] = np.nan
    return out, base


def summarize(events: pd.DataFrame) -> list[dict]:
    """패턴별 집계 — 칸 `symbol` · `key` · `forward_ret_5d` · `excess_ret_5d` · `baseline` 이 있는 사건 표."""
    out = []
    for key in STAT_PATTERNS:
        g = events[events["key"] == key]
        name, direction = pattern_label(key)
        row = {"key": key, "name": name, "direction": direction, "events": int(len(g)),
               "symbols": int(g["symbol"].nunique()) if len(g) else 0}
        if len(g):
            r = g["forward_ret_5d"]
            x = g["excess_ret_5d"].dropna()
            row.update({
                "mean_ret_5d": float(r.mean()), "median_ret_5d": float(r.median()), "up_ratio": float((r > 0).mean()),
                "mean_excess_5d": float(x.mean()) if len(x) else None,
                "median_excess_5d": float(x.median()) if len(x) else None,
                "mean_vs_baseline": float((r - g["baseline"]).mean()),
                "first": str(g["date"].min()), "last": str(g["date"].max()),
            })
        out.append(row)
    return out
