"""패턴 통계 — 과거 모든 날 탐지 · 5거래일 뒤 수익률 · 겹침 · 봉인 구간 (TC-PS · `P01-②-2`).

목표 기능 ② 설계서 5.2 <표 9>. 모든 날 탐지(`pattern_stats`)가 화면 탐지기(`patterns`)와 날마다 같은지,
날 t 의 사건과 수익률이 t 뒤 봉을 쓰지 않는지(수익률은 t+5 까지만), 봉인 구간이 빠지는지를 본다.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import pattern_stats as ps
from app.services import patterns as pt


def _random_df(n: int, seed: int) -> pd.DataFrame:
    """시가 · 꼬리가 제멋대로인 일봉 — 캔들 패턴 · 지지/저항 돌파가 고루 나오게 진동을 섞는다."""
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.002, 0.02, n)) * (1 + 0.08 * np.sin(np.arange(n) / 9))
    open_ = close * (1 + rng.normal(0, 0.015, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.01, n)))
    vol = rng.integers(1_000, 5_000, n).astype(float)
    idx = pd.bdate_range("2021-01-04", periods=n)
    return pd.DataFrame({"open": open_.round(2), "high": high.round(2), "low": low.round(2),
                         "close": close.round(2), "volume": vol}, index=idx)


def _screen_keys(df: pd.DataFrame, t: int) -> set[str]:
    """화면 탐지기가 날 t(그날까지의 봉만 줌)의 마지막 봉에서 낸 통계 대상 패턴."""
    d = df.iloc[:t + 1]
    keys = {p["key"] for p in pt.detect_candle_patterns(d, lookback=1) if p["bars_ago"] == 0}
    for e in pt.detect_breakouts(d):
        if e["key"] in ("golden_cross", "dead_cross") and not e["detail"].startswith("0봉"):
            continue                                    # 화면은 5봉 안의 크로스를 보인다 — 사건은 그날 난 것만
        keys.add(e["key"])
    if t < ps.YEAR_BARS - 1:
        keys.discard("high_52w")                        # 통계는 1년 치가 다 있을 때만 센다
    return keys & set(ps.STAT_PATTERNS)


def test_all_days_detection_equals_screen_detector():
    df = _random_df(300, seed=3)
    hits = {**ps.candle_hits(df), **ps.breakout_hits(df)}
    seen = set()
    for t in range(ps.MIN_BARS - 1, len(df)):
        mine = {k for k in ps.STAT_PATTERNS if hits[k][t]}
        assert mine == _screen_keys(df, t), df.index[t]
        seen |= mine
    # 대조가 빈 집합끼리의 일치가 되지 않게 — 대상 패턴이 모두 한 번 이상 나오는 수열이다
    assert seen == set(ps.STAT_PATTERNS)


def test_detection_does_not_use_later_bars():
    df = _random_df(260, seed=3)
    t = 180
    changed = df.copy()
    changed.iloc[t + 1:, :4] = changed.iloc[t + 1:, :4] * 3     # t 뒤 봉을 크게 바꾼다
    a, b = ps.detect_events(df), ps.detect_events(changed)
    assert a[a["pos"] <= t].reset_index(drop=True).equals(b[b["pos"] <= t].reset_index(drop=True))


def _doji_df(n: int, start: str = "2021-01-04") -> pd.DataFrame:
    """날마다 도지(시가 = 종가 · 꼬리 ±1) · 종가 100, 101, 102 …"""
    c = 100.0 + np.arange(n)
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000.0}, index=idx)


def test_forward_return_and_excess_hand_computed():
    df = _doji_df(100)
    bench = pd.Series(1000 * 1.01 ** np.arange(100), index=df.index)
    ev, base = ps.event_study(df, bench)
    doji = ev[ev["key"] == "doji"].reset_index(drop=True)
    # 첫 후보 = 봉 65개째(자리 64) · 겹침 규칙으로 6거래일마다 · t+5 가 있는 마지막 자리는 94
    pos = list(range(64, 95, 6))
    assert list(doji["date"]) == [df.index[p].strftime("%Y-%m-%d") for p in pos]
    expect = [(105 + p) / (100 + p) - 1 for p in pos]
    assert doji["forward_ret_5d"].tolist() == pytest.approx(expect)
    assert doji["excess_ret_5d"].tolist() == pytest.approx([e - (1.01 ** 5 - 1) for e in expect])
    # 기준선 = 후보가 될 수 있던 모든 날(64 ~ 94)의 5일 수익률 평균
    assert base["baseline_days"] == 31
    assert base["baseline"] == pytest.approx(np.mean([(105 + p) / (100 + p) - 1 for p in range(64, 95)]))
    assert base["baseline_up"] == 1.0


def test_thin_keeps_first_and_counts_from_kept():
    keep = ps.thin(np.array([10, 12, 15, 16, 21, 22, 30]))
    assert keep.tolist() == [True, False, False, True, False, True, True]


def test_sealed_period_is_excluded():
    # 2026-06 부터 2026-09 까지 — 2026-08-31 뒤 봉은 사건 · 수익률 · 기준선 어디에도 들어가면 안 된다
    df = _doji_df(120, start="2026-05-01")
    assert df.index[-1] > pd.Timestamp(ps.SEAL_START)
    ev, base = ps.event_study(df, end="2026-12-31")             # 끝날을 넘겨 줘도 봉인 구간 전날로 줄인다
    last_ok = df.index[df.index < pd.Timestamp(ps.SEAL_START)][-1 - ps.HORIZON]
    assert ev["date"].max() <= last_ok.strftime("%Y-%m-%d")
    p_last = int(np.flatnonzero(df.index == last_ok)[0])
    assert base["baseline_days"] == p_last - (ps.MIN_BARS - 1) + 1


def test_no_trade_day_is_not_an_event():
    df = _doji_df(100)
    df.iloc[64:100, df.columns.get_loc("volume")] = 0.0         # 거래정지 — 평평한 봉도 도지 모양이다
    df.iloc[70, df.columns.get_loc("volume")] = 500.0
    ev = ps.detect_events(df)
    assert ev[ev["key"] == "doji"]["pos"].tolist() == [70]


def test_summarize_counts_and_baseline_gap():
    events = pd.DataFrame({
        "symbol": ["A", "A", "B"], "date": ["2024-01-02", "2024-02-01", "2024-01-05"],
        "key": ["doji", "doji", "hammer"], "forward_ret_5d": [0.02, -0.01, 0.05],
        "excess_ret_5d": [0.01, np.nan, 0.03], "baseline": [0.001, 0.001, 0.002],
    })
    rows = {r["key"]: r for r in ps.summarize(events)}
    assert set(rows) == set(ps.STAT_PATTERNS)
    d = rows["doji"]
    assert (d["events"], d["symbols"], d["up_ratio"]) == (2, 1, 0.5)
    assert d["mean_ret_5d"] == pytest.approx(0.005) and d["mean_excess_5d"] == pytest.approx(0.01)
    assert d["mean_vs_baseline"] == pytest.approx(0.004)
    assert rows["golden_cross"]["events"] == 0 and "mean_ret_5d" not in rows["golden_cross"]
