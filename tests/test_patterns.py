"""캔들 패턴·지지/저항·돌파·멀티타임프레임 종합 로직."""
import pandas as pd
import pytest

from app.services import patterns as pt
from tests.conftest import make_candles


def _df(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"])


def _flat(n=24, price=100.0):
    return [[price, price + 1, price - 1, price, 1000] for _ in range(n)]


def test_hammer_and_bullish_engulfing_detected():
    rows = _flat() + [[100, 100.5, 90, 99.5, 1000]]                     # 긴 아래꼬리 해머
    keys = {p["key"] for p in pt.detect_candle_patterns(_df(rows), lookback=1)}
    assert "hammer" in keys
    rows = _flat() + [[100, 101, 97, 98, 1000], [97, 104, 96.5, 103, 1500]]  # 음봉 뒤 장악 양봉
    keys = {p["key"] for p in pt.detect_candle_patterns(_df(rows), lookback=1)}
    assert "bullish_engulfing" in keys


def test_doji_and_three_black_crows():
    rows = _flat() + [[100, 103, 97, 100.1, 1000]]
    assert "doji" in {p["key"] for p in pt.detect_candle_patterns(_df(rows), lookback=1)}
    rows = _flat() + [[100, 100.5, 96, 96.5, 1000], [96.5, 97, 92, 92.5, 1000], [92.5, 93, 88, 88.5, 1000]]
    assert "three_black_crows" in {p["key"] for p in pt.detect_candle_patterns(_df(rows), lookback=1)}


def test_support_resistance_levels_found():
    rows = []
    for i in range(120):   # 90~110 사이 진동 → 110 저항, 90 지지 반복 터치
        c = 100 + 10 * (1 if (i // 10) % 2 == 0 else -1) * ((i % 10) / 9)
        rows.append([c, c + 0.5, c - 0.5, c, 1000])
    sr = pt.support_resistance(_df(rows))
    assert sr["levels"]
    prices = [l["price"] for l in sr["levels"]]
    assert any(abs(p - 110) < 2 for p in prices) or any(abs(p - 90) < 2 for p in prices)
    assert all(l["type"] in ("support", "resistance") for l in sr["levels"])


def test_breakout_52w_high_and_20d():
    rows = _flat(300)
    rows.append([100, 130, 100, 128, 5000])  # 급등 신고가 + 거래량 5배
    events = {e["key"]: e for e in pt.detect_breakouts(_df(rows))}
    assert "breakout_20d" in events and events["breakout_20d"]["confirmed"]
    assert "high_52w" in events


def test_pattern_summary_on_synthetic_candles():
    r = pt.pattern_summary(make_candles(300))
    assert {"patterns", "support_resistance", "breakouts", "pattern_score", "pattern_bias"} <= set(r)


def test_combine_timeframes_confidence_and_action():
    r = pt.combine_timeframes([{"label": "m", "weight": .2, "score": 3}, {"label": "d", "weight": .5, "score": 4}, {"label": "w", "weight": .3, "score": 2}])
    assert r["action"] == "강력 매수" and r["agreement"] == 100 and r["confidence"] >= 80
    mixed = pt.combine_timeframes([{"weight": .5, "score": 2}, {"weight": .5, "score": -2}])
    assert mixed["action"] == "관망" and mixed["confidence"] < 30
    assert pt.combine_timeframes([{"weight": 1, "error": "x"}])["action"] == "관망"


def test_timeframe_score_reasons():
    r = pt.timeframe_score(make_candles(120))
    assert -5 <= r["score"] <= 5 and len(r["reasons"]) >= 4
    # 규칙이 비교한 지표 값도 함께 낸다(설명 근거 표의 관측값)
    assert {"rsi", "ma5", "ma20", "last", "macd", "macd_signal", "bb_upper", "bb_lower"} <= set(r)
    assert r["bb_lower"] <= r["ma20"] <= r["bb_upper"]


# ── 그 자리 계산은 기준일(마지막 일봉 날)까지만 (#617) ─────────────────────────

def _daily_until(last: str, n: int = 400, hour_utc: int = 0) -> list[dict]:
    """평일 일봉 n 개 — 마지막 봉 날짜 `last` · 봉 시각 = 그날 hour_utc 시(UTC)."""
    import numpy as np
    from datetime import date, datetime, timedelta, timezone
    days, d = [], date.fromisoformat(last)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return [{"time": int(datetime(x.year, x.month, x.day, hour_utc, tzinfo=timezone.utc).timestamp()),
             "open": float(c), "high": float(c) * 1.01, "low": float(c) * 0.99, "close": float(c), "volume": 1000}
            for x, c in zip(reversed(days), close)]


def _hourly(start_utc, hours: int) -> list[dict]:
    from datetime import timedelta
    return [{"time": int((start_utc + timedelta(hours=h)).timestamp()), "open": 100.0 + h % 7, "high": 102.0 + h % 7,
             "low": 99.0 + h % 7, "close": 100.5 + h % 7, "volume": 10} for h in range(hours)]


def _bar_utc(c: dict) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(c["time"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _run_live(monkeypatch, daily, hourly):
    import asyncio
    seen = {}

    async def fake_get_candles(symbol, period="1y", interval="1d", max_age_hours=6):
        if interval == "1d":
            return {"candles": daily}
        seen[interval] = True
        return {"candles": hourly}

    monkeypatch.setattr("app.services.stock.get_candles", fake_get_candles)
    return asyncio.run(pt.multi_timeframe_signal("TEST01")), seen


def test_live_signal_cuts_60m_and_weekly_at_last_daily_bar(monkeypatch):
    """기준일(수 11-11) 뒤의 60분봉(목 11-12)은 쓰지 않고, 주봉은 일봉으로 그 주 수요일까지만 만든다 · 진행 중 주."""
    from datetime import datetime, timezone
    daily = _daily_until("2026-11-11")
    hourly = _hourly(datetime(2026, 10, 20, 0, tzinfo=timezone.utc), 24 * 24)    # 10-20 00시 ~ 11-12 23시
    assert _bar_utc(hourly[-1]) == "2026-11-12 23:00"
    r, seen = _run_live(monkeypatch, daily, hourly)
    tf = {t["interval"]: t for t in r["timeframes"]}
    assert tf["60m"]["as_of"] == "2026-11-11 23:00" and tf["1d"]["as_of"][:10] == "2026-11-11"
    assert tf["1wk"]["as_of"][:10] == "2026-11-11" and tf["1wk"]["partial"] is True
    assert "1wk" not in seen                       # 주봉은 야후 주봉을 부르지 않고 일봉으로 만든다
    assert "기준일" in r["disclaimer"] and "주봉은 5년" in r["disclaimer"]


def test_live_signal_keeps_same_session_bars_past_midnight(monkeypatch):
    """장이 UTC 자정을 넘는 시장(봉 시각 13:30 UTC)도 같은 거래일 60분봉은 남고, 다음 거래일 봉만 빠진다."""
    from datetime import datetime, timezone
    daily = _daily_until("2026-11-10", hour_utc=13)
    hourly = _hourly(datetime(2026, 10, 20, 13, tzinfo=timezone.utc), 24 * 23)   # 마지막 봉 11-12 12:00 UTC
    assert _bar_utc(hourly[-1]) == "2026-11-12 12:00"
    r, _ = _run_live(monkeypatch, daily, hourly)
    last_60m = r["timeframes"][0]["as_of"]
    assert "2026-11-11 12:00" == last_60m           # 11-10 13:00 + 23시간 — 다음 거래일(11-11 13:00 UTC) 직전까지


def test_live_signal_without_daily_has_no_weekly(monkeypatch):
    """일봉을 못 읽으면 기준일이 없다 — 주봉은 「시세 없음」, 60분봉은 자르지 못한 채 계산된다."""
    from datetime import datetime, timezone
    hourly = _hourly(datetime(2026, 10, 20, 0, tzinfo=timezone.utc), 24 * 10)
    r, _ = _run_live(monkeypatch, [], hourly)
    tf = {t["interval"]: t for t in r["timeframes"]}
    assert tf["1d"]["error"] == "시세 없음" and tf["1wk"]["error"] == "시세 없음" and "score" in tf["60m"]
