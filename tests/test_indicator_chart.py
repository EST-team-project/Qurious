"""TC-ICH — U7 지표 차트(기본 인디케이터 전략 화면 · #392) — app/services/indicator_chart.py · /api/indicator-strategy/chart · 2026-10-29

1. 값은 정의 한 벌(ta_utils) 그대로 — 이동평균 · 볼린저 · RSI · MACD · DMI · 상대 강도가 같은 함수로 잰 값과 같다 · 봉과 길이가 같다. (TC-ICH-01)
2. 미래 안 보기 — 뒤 봉을 더해도 앞 봉의 지표 · 표식이 바뀌지 않는다. (TC-ICH-02)
3. 표식 — 카드 조건(단기 > 장기 상태)이 바뀐 봉에만 매수 · 매도 · 고른 기간 안만. (TC-ICH-03)
4. 상대 강도 기준선 — 코스피 · 코스닥은 지수, 모르는 시장 · 받지 못한 기준선은 비우고 까닭. (TC-ICH-04)
5. 라우트 — 로그인 · 단기 ≥ 장기 422 · 기간 밖 422 · main 에 등록. (TC-ICH-05)
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import indicator_strategy
from app.services import indicator_chart as ic
from app.services import ta_utils

T0 = 1_700_000_000


def _bars(n: int, base: float = 100.0, amp: float = 10.0) -> list[dict]:
    out = []
    for i in range(n):
        c = base + amp * math.sin(i / 9) + i * 0.05
        out.append({"time": T0 + i * 86400, "open": c - 0.5, "high": c + 1.5, "low": c - 1.5, "close": c, "volume": 1000})
    return out


BENCH = [{"time": T0 + i * 86400, "open": 50, "high": 51, "low": 49, "close": 50 + i * 0.02, "volume": 1} for i in range(600)]


def test_values_are_ta_utils():
    """TC-ICH-01"""
    bars = _bars(600)
    out = ic.build(bars, "1y", 5, 20, BENCH, ("^KS11", "코스피"))
    df = pd.DataFrame(bars).set_index("time")
    keep = df.index[-252:]
    assert [b["time"] for b in out["bars"]] == list(keep) and all(len(v) == 252 for v in out["series"].values())
    plus, minus, adx = ta_utils.dmi(df["high"], df["low"], df["close"])
    m, s, _h = ta_utils.macd(df["close"])
    rs60 = ta_utils.relative_strength(df["close"], pd.DataFrame(BENCH).set_index("time")["close"], 60) * 100
    for key, ref in [("ma60", ta_utils.sma(df["close"], 60)), ("rsi", ta_utils.rsi(df["close"], 14)), ("adx", adx),
                     ("macd", m), ("macd_signal", s), ("bb_lower", ta_utils.bollinger(df["close"])[2]), ("rs60", rs60)]:
        assert out["series"][key][-1] == pytest.approx(float(ref.iloc[-1]), abs=0.01), key
        assert out["series"][key][0] is not None, key                                # 기간 첫 봉도 창이 찬 값
    assert out["benchmark"] == {"symbol": "^KS11", "name": "코스피"} and out["rs_note"] is None


def test_no_lookahead():
    """TC-ICH-02"""
    bars = _bars(600)
    a = ic.build(bars[:500], "2y", 5, 20, BENCH, ("^KS11", "코스피"))
    b = ic.build(bars, "2y", 5, 20, BENCH, ("^KS11", "코스피"))
    ta = {x["time"]: i for i, x in enumerate(a["bars"])}
    tb = {x["time"]: i for i, x in enumerate(b["bars"])}
    common = sorted(set(ta) & set(tb))
    assert len(common) > 300
    for key in ("ma20", "bb_upper", "rsi", "macd", "adx", "rs20"):
        for t in common:
            assert a["series"][key][ta[t]] == b["series"][key][tb[t]], (key, t)
    early = [m for m in b["markers"] if m["time"] <= a["bars"][-1]["time"]]
    assert [m for m in a["markers"] if m["time"] >= b["bars"][0]["time"]] == [m for m in early if m["time"] >= a["bars"][0]["time"]]


def test_markers_follow_card_condition():
    """TC-ICH-03"""
    bars = _bars(600)
    out = ic.build(bars, "1y", 5, 20)
    close = pd.DataFrame(bars).set_index("time")["close"]
    state = ta_utils.sma(close, 5) > ta_utils.sma(close, 20)
    assert out["markers"], "사인파라 교차가 있어야 한다"
    for m in out["markers"]:
        i = close.index.get_loc(m["time"])
        assert bool(state.iloc[i]) is (m["side"] == "buy") and bool(state.iloc[i - 1]) is (m["side"] != "buy")
        assert m["time"] >= out["bars"][0]["time"]
    assert out["card_condition"] == {"indicator": "ma_cross", "short_window": 5, "long_window": 20, "condition": "short_above_long"}


def test_benchmark_choice_and_missing():
    """TC-ICH-04"""
    assert ic.benchmark_for("005930.KS") == ("^KS11", "코스피") and ic.benchmark_for("035720.kq") == ("^KQ11", "코스닥")
    assert ic.benchmark_for("AAPL") is None
    none = ic.build(_bars(300), "6mo", 5, 20, None, None)
    assert "rs20" not in none["series"] and none["benchmark"] is None and "기준선" in none["rs_note"]
    lost = ic.build(_bars(300), "6mo", 5, 20, [], ("^KS11", "코스피"))
    assert "rs20" not in lost["series"] and "받지 못해" in lost["rs_note"]
    assert ic.build(_bars(10), "6mo", 5, 20)["error"] == "데이터 부족"


def test_route(monkeypatch):
    """TC-ICH-05"""
    async def fake_candles(symbol, period="1y", **_):
        return {"candles": BENCH if symbol.startswith("^") else _bars(600), "as_of": "2026-10-28", "source": "test"}
    monkeypatch.setattr(indicator_strategy, "get_candles", fake_candles)
    app = FastAPI()
    app.include_router(indicator_strategy.router)
    anon = TestClient(app)
    assert anon.get("/api/indicator-strategy/chart", params={"symbol": "005930.KS"}).status_code == 401
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": []}
    c = TestClient(app)
    res = c.get("/api/indicator-strategy/chart", params={"symbol": "005930.KS", "period": "6mo", "short": 10, "long": 60})
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["bars"]) == 126 and body["benchmark"]["name"] == "코스피" and body["definition"] == ta_utils.DEFINITION
    assert body["card_condition"]["short_window"] == 10 and body["as_of"] == "2026-10-28"
    assert c.get("/api/indicator-strategy/chart", params={"symbol": "005930.KS", "short": 20, "long": 20}).status_code == 422
    assert c.get("/api/indicator-strategy/chart", params={"symbol": "005930.KS", "period": "10y"}).status_code == 422
    main = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.routes import indicator_strategy as indicator_strategy_routes" in main
    assert "app.include_router(indicator_strategy_routes.router)" in main
