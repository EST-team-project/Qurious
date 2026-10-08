"""다중 주기 신호 — 세 단계 · 0 ~ 1 신뢰도 · 그날까지의 봉만 · T2 기록 (TC-MT · `P01-②-3`).

목표 기능 ② 설계서 5.3 <표 10> · 6절 <표 12> · 8절 <표 14>. 계산 시험은 합성 봉으로 DB 없이 돈다.
T2 기록 시험은 일회용 시험 DB(`QURIOUS_TEST_DATABASE_URL` · `scripts/personal/test.ps1`)가 있을 때만 돈다.
"""
import asyncio
import os
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.services import mtf_signals as ms
from app.services import patterns as pt

KST = timezone(timedelta(hours=9))


# ── 신호 · 신뢰도 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("composite, expected", [
    (2.5, ("매수", "강")), (1.0, ("매수", "보통")), (0.99, ("관망", None)), (0.0, ("관망", None)),
    (-0.99, ("관망", None)), (-1.0, ("매도", "보통")), (-2.5, ("매도", "강")), (6, ("매수", "강")),
])
def test_three_signals_and_strength(composite, expected):
    assert ms.classify(composite) == expected


def test_confidence_bounds():
    # 모든 주기가 같은 방향이고 점수가 크면 1
    full = ms.combine([{"weight": .2, "score": 6}, {"weight": .5, "score": 5}, {"weight": .3, "score": 4}])
    assert full["confidence"] == 1.0 and full["agreement"] == 1.0 and full["signal"] == "매수"
    # 같은 크기로 엇갈리면 종합 0 · 일치도 0 → 0
    split = ms.combine([{"weight": .5, "score": 2}, {"weight": .5, "score": -2}])
    assert split["confidence"] == 0.0 and split["signal"] == "관망" and split["strength"] is None
    # 오류 난 주기는 빼고 셈 · 모두 오류면 관망 · 0
    assert ms.combine([{"weight": .5, "error": "x"}, {"weight": .5, "score": -4}])["confidence"] == 1.0
    assert ms.combine([{"weight": 1, "error": "x"}]) == {"signal": "관망", "strength": None, "confidence": 0.0,
                                                         "composite": 0.0, "agreement": 0.0}


def test_confidence_is_screen_formula_on_0_to_1():
    """화면(`patterns.combine_timeframes`)의 0 ~ 100 정수 = round(신뢰도 × 100) · 다섯 단계 = 신호 + 강도."""
    rng = np.random.default_rng(1)
    old_action = {("매수", "강"): "강력 매수", ("매수", "보통"): "매수", ("관망", None): "관망",
                  ("매도", "보통"): "매도", ("매도", "강"): "강력 매도"}
    for _ in range(300):
        rows = [{"weight": w, "score": int(s)} for w, s in zip((.2, .5, .3), rng.integers(-6, 7, 3))]
        new, old = ms.combine(rows), pt.combine_timeframes(rows)
        assert round(new["confidence"] * 100) == old["confidence"]
        assert old_action[(new["signal"], new["strength"])] == old["action"]
        assert new["composite"] == pytest.approx(old["composite"], abs=0.005)


# ── 합성 봉 ──────────────────────────────────────────────────────────────

def _bars(days: int = 400, seed: int = 5, symbol: str = "TEST01") -> ms.Bars:
    """`ohlcv-v1` 모양의 일봉 · 60분봉(하루 6개 · 09:00 ~ 14:00)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-02", periods=days)
    close = 10_000 * np.cumprod(1 + rng.normal(0.0005, 0.02, days))
    daily, intraday = [], []
    for i, d in enumerate(idx):
        c = round(float(close[i]), 2)
        o = round(c * (1 + rng.normal(0, 0.01)), 2)
        h, low = max(o, c) * 1.01, min(o, c) * 0.99
        daily.append({"symbol": symbol, "timeframe": "1d", "trade_date": d.strftime("%Y-%m-%d"), "bar_start": None,
                      "open": o, "high": h, "low": low, "close": c, "volume": 1000 + i, "value": None})
        path = np.linspace(o, c, 6)
        for k in range(6):
            t = datetime(d.year, d.month, d.day, 9 + k, tzinfo=KST)
            p = float(path[k])
            intraday.append({"symbol": symbol, "timeframe": "60m", "trade_date": d.strftime("%Y-%m-%d"),
                             "bar_start": t.isoformat(), "open": p, "high": p * 1.002, "low": p * 0.998,
                             "close": p, "volume": 100})
    return ms.Bars(symbol, daily, intraday)


def test_record_shape():
    b = _bars()
    as_of = b.daily[-1]["trade_date"]
    r = ms.signal_at(b, as_of)
    assert r["as_of"] == date.fromisoformat(as_of) and r["definition"] == ms.DEFINITION and r["symbol"] == "TEST01"
    assert r["signal"] in ("매수", "매도", "관망") and 0.0 <= r["confidence"] <= 1.0 and -6 <= r["composite"] <= 6
    assert [t["timeframe"] for t in r["timeframes"]] == ["60m", "1d", "1w"]
    assert all("score" in t and t["last_bar"] for t in r["timeframes"])
    assert r["timeframes"][0]["last_bar"].startswith(as_of)          # 60분봉은 그날 봉까지
    assert r["reasons"] and {"timeframe", "text"} <= set(r["reasons"][0])


def test_uses_only_bars_until_as_of():
    """날 D 의 신호는 D 뒤 봉을 바꿔도 같다 — 일 · 60분 · 주봉 모두."""
    b = _bars()
    d = b.daily[300]["trade_date"]
    changed = ms.Bars(b.symbol,
                      [{**r, "close": r["close"] * 3, "high": r["high"] * 3} if r["trade_date"] > d else r for r in b.daily],
                      [{**r, "close": r["close"] * 3} if r["trade_date"] > d else r for r in b.intraday])
    assert ms.signal_at(b, d) == ms.signal_at(changed, d)


def test_week_in_progress_is_partial():
    b = _bars()
    weds = [r["trade_date"] for r in b.daily[-30:] if date.fromisoformat(r["trade_date"]).weekday() == 2][-1]
    fri = [r["trade_date"] for r in b.daily[-30:] if date.fromisoformat(r["trade_date"]).weekday() == 4][-1]
    assert ms.signal_at(b, weds)["timeframes"][2]["partial"] is True
    assert ms.signal_at(b, fri)["timeframes"][2]["partial"] is False


def test_no_daily_bar_that_day_means_no_record():
    b = _bars()
    assert ms.signal_at(b, "2024-12-31") is None                      # 첫 봉보다 앞
    sat = (date.fromisoformat(b.daily[-1]["trade_date"]) + timedelta(days=1)).isoformat()
    assert ms.signal_at(b, sat) is None                                # 그날 시세 없음


def test_missing_intraday_still_signals_from_day_and_week():
    b = _bars()
    no60 = ms.Bars(b.symbol, b.daily, [])
    r = ms.signal_at(no60, b.daily[-1]["trade_date"])
    assert "error" in r["timeframes"][0] and "score" in r["timeframes"][1] and "score" in r["timeframes"][2]


def test_one_record_per_symbol_and_trading_day():
    b = _bars()
    days = [r["trade_date"] for r in b.daily[-10:]]
    recs = [x for d in days if (x := ms.signal_at(b, d)) is not None]
    assert len(recs) == len(days) and len({(r["as_of"], r["symbol"], r["definition"]) for r in recs}) == len(days)


# ── T2 기록 (일회용 시험 DB) ──────────────────────────────────────────────

DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")


def _run(coro_fn):
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    url = make_url(DB_URL)
    assert "test" in DB_URL and url.database != "fin_ai" and url.port != 15432, "일회용 시험 DB만 사용"

    async def go():
        from app.models.signal import SignalSnapshot

        engine = create_async_engine(DB_URL, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda c: SignalSnapshot.__table__.drop(c, checkfirst=True))
                await conn.run_sync(lambda c: SignalSnapshot.__table__.create(c))
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await coro_fn(session)
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(lambda c: SignalSnapshot.__table__.drop(c, checkfirst=True))
            await engine.dispose()

    return asyncio.run(go())


@pytest.mark.skipif(not DB_URL, reason="일회용 시험 DB 없음 — scripts/personal/test.ps1 로 돈다")
def test_t2_upsert_same_day_and_keep_old_definition():
    from sqlalchemy import func, select

    from app.models.signal import SignalSnapshot

    b = _bars()
    days = [r["trade_date"] for r in b.daily[-3:]]
    recs = [ms.signal_at(b, d) for d in days]

    async def scenario(session):
        assert await ms.write_snapshots(session, recs) == 3
        # 같은 날 · 같은 판을 다시 쓰면 줄이 늘지 않고 값이 바뀐다
        again = [{**recs[-1], "signal": "관망", "confidence": 0.123}]
        await ms.write_snapshots(session, again)
        # 정의 판이 바뀌면 같은 날 새 줄 — 옛 판 줄은 그대로
        await ms.write_snapshots(session, [{**recs[-1], "definition": "tv-2027"}])
        total = await session.scalar(select(func.count()).select_from(SignalSnapshot))
        last = (await session.execute(select(SignalSnapshot).where(
            SignalSnapshot.as_of == recs[-1]["as_of"]).order_by(SignalSnapshot.definition))).scalars().all()
        return total, [(r.definition, r.signal, r.confidence, len(r.timeframes)) for r in last]

    total, last = _run(scenario)
    assert total == 4
    assert last[0][:3] == ("tv-2026", "관망", 0.123) and last[0][3] == 3
    assert last[1][0] == "tv-2027" and last[1][1] == recs[-1]["signal"]
