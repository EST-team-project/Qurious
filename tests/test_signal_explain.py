"""신호 설명 층 1 — T2 한 줄 → 쉬운 말 문장 · 근거 표 (TC-XR · `P01-①-5`).

목표 기능 ② 설계서 5.4.1 · 5.4.3 <표 11> 설명 기준(정확 · 충분 · 정직) · 7절 <표 13> `GET /api/explain`.
계산 시험은 합성 봉으로 DB 없이 돈다. T2 읽기 시험은 일회용 시험 DB(`QURIOUS_TEST_DATABASE_URL`)가 있을 때만 돈다.
"""
import re
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import mtf_signals as ms
from app.services import signal_explain as se
from app.services.patterns import timeframe_score
from tests.test_mtf_signals import DB_URL, _bars, _run


def _series(closes) -> list[dict]:
    t0 = int(datetime(2025, 1, 2, tzinfo=timezone.utc).timestamp())
    return [{"time": t0 + i * 86400, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1000}
            for i, c in enumerate(closes)]


def _snapshots(seeds=range(1, 13), step=9) -> list[dict]:
    out = []
    for seed in seeds:
        b = _bars(seed=seed)
        out += [ms.signal_at(b, r["trade_date"]) for r in b.daily[-90::step]]
    return out


# ── 규칙 표 = 화면 점수 ───────────────────────────────────────────────────

def test_rule_table_covers_every_reason_and_sums_to_score():
    """`timeframe_score` 의 근거 열한 가지를 모두 읽고, 근거 점수의 합 = 그 주기 점수 (설명 기준 「충분」)."""
    rng = np.random.default_rng(7)
    series = [100 * np.cumprod(1 + rng.normal(0, 0.02, 120)) for _ in range(60)]
    series += [np.linspace(100, 200, 80), np.linspace(200, 100, 80),                       # 꾸준히 오름 · 내림
               np.r_[np.full(60, 100.0), np.linspace(100, 130, 5)], np.r_[np.full(60, 100.0), np.linspace(100, 70, 5)]]
    seen = set()
    for closes in series:
        r = timeframe_score(_series([float(c) for c in closes]))
        rules = [se.match_rule(t)[0] for t in r["reasons"]]
        seen |= {x.key for x in rules}
        assert sum(x.points for x in rules) == r["score"]
    assert seen == {x.key for x in se.RULES}


def test_unknown_reason_is_an_error():
    with pytest.raises(se.UnknownReason):
        se.match_rule("RSI 다이버전스")


def test_contributions_add_up_to_composite():
    for s in _snapshots():
        e = se.explain(s)
        assert sum(r["contribution"] for r in e["evidence"]) == pytest.approx(s["composite"], abs=1e-9)
        assert {r["key"] for r in e["reasons"]} <= {r["key"] for r in e["evidence"]}
        # 근거와 반대 근거는 신호 방향으로 나뉜다
        sign = {"매수": 1, "매도": -1}.get(s["signal"])
        if sign:
            assert all(r["points"] * sign > 0 for r in e["reasons"])
            assert all(r["points"] * sign < 0 for r in e["counter_reasons"])


# ── 정확 — 같은 입력 · 같은 문장 · 문장 숫자 = 응답 값 ─────────────────────

def test_same_input_same_sentence():
    s = _snapshots(seeds=[3])[0]
    assert se.explain(s) == se.explain(dict(s))


ALLOWED_CONSTANTS = {"1", "5", "20", "30", "60", "70"}


def test_numbers_in_sentence_are_response_values():
    for s in _snapshots():
        e = se.explain(s)
        allowed = set(ALLOWED_CONSTANTS) | {f"{abs(round(e['composite'], 1)):.1f}"}
        allowed |= {r["observed"].split()[-1] for r in e["evidence"] if r["observed"]}
        for n in re.findall(r"\d+(?:\.\d+)?", e["summary"]):
            assert n in allowed, (n, e["summary"])


def _row(tf, label, weight, score, reasons, rsi=50.0, **extra):
    return {"timeframe": tf, "label": label, "weight": weight, "score": score, "rsi": rsi, "reasons": reasons, **extra}


BUY = {
    "as_of": date(2026, 8, 31), "symbol": "005930", "definition": "tv-2026",
    # 종합 = (4 × 0.5 − 1 × 0.3) ÷ 0.8 · 일치도 = 0.5 ÷ 0.8 · 신뢰도 = ½ × 0.625 + ½ × 2.125 ÷ 4 (`mtf_signals.combine`)
    "signal": "매수", "strength": "보통", "confidence": 0.578125, "composite": 2.125, "agreement": 0.625,
    "timeframes": [
        {"timeframe": "60m", "label": "분봉(60분)", "weight": 0.2, "error": "시세 없음"},
        _row("1d", "일봉", 0.5, 4, ["RSI 27 과매도", "MA5 > MA20 상승 배열", "MACD > 시그널", "20MA 아래 (추세 비우호)"],
             rsi=27.4),
        _row("1w", "주봉", 0.3, -1, ["RSI 45 중립", "MA5 > MA20 상승 배열", "MACD < 시그널", "20MA 아래 (추세 비우호)"],
             rsi=45.0, partial=True, last_bar="2026-08-31"),
    ],
    "pattern_bias": "bullish",
    "patterns": [{"key": "hammer", "name": "해머", "direction": "bullish", "date": "2026-08-31"},
                 {"key": "doji", "name": "도지", "direction": "neutral", "date": "2026-08-28"}],
}


def test_buy_sentence_follows_template():
    """설계서 5.4.1 의 틀 — 가장 크게 민 주기 · 그 주기의 큰 근거 둘 · 다른 주기의 반대 근거 하나."""
    e = se.explain(BUY)
    assert e["summary"] == ("일봉 기준으로 RSI 가 30 아래인 27.4까지 떨어진 상태고 5일선이 20일선 위라 매수 쪽입니다. "
                            "다만 같은 일봉에서 종가가 20일선 아래입니다.")
    assert e["confidence_text"] == "주기 둘 중 하나가 매수 쪽 · 기운 정도 보통"
    assert e["notes"][0] == "분봉(60분)은 시세 없음 — 나머지 주기로만 셈했습니다."
    assert e["notes"][1].startswith("주봉은 이번 주가 끝나지 않아 2026-08-31 까지")
    assert "해머" in e["notes"][2] and "도지" not in e["notes"][2]          # 그날 패턴만
    assert e["reasons"][0]["key"] == "rsi_low" and e["reasons"][0]["observed"] == "RSI 27.4"
    assert e["as_of"] == "2026-08-31" and e["method"] == "rule" and e["kind"] == "signal"


def test_hold_sentence_names_both_sides():
    hold = {**BUY, "signal": "관망", "strength": None, "composite": 0.2,
            "timeframes": [_row("1d", "일봉", 0.5, 1, ["RSI 50 중립", "MA5 > MA20 상승 배열", "MACD > 시그널",
                                                       "20MA 아래 (추세 비우호)"]),
                           _row("1w", "주봉", 0.3, -1, ["RSI 50 중립", "MA5 < MA20 하락 배열", "MACD > 시그널",
                                                       "20MA 아래 (추세 비우호)"])]}
    e = se.explain(hold)
    assert e["summary"].startswith("두 주기를 합친 점수(+0.2)가 매수 · 매도 기준(±1)에 닿지 않아 관망입니다.")
    assert "엇갈립니다" in e["summary"]
    assert e["confidence_text"] == "주기 둘 — 매수 쪽 하나 · 매도 쪽 하나"
    assert "점수(0.0)가" in se.explain({**hold, "composite": 0.04})["summary"]       # 0 에는 부호 없음


def test_no_prices_no_judgement():
    empty = {**BUY, "signal": "관망", "strength": None, "composite": 0.0, "confidence": 0.0,
             "timeframes": [{"timeframe": "1d", "label": "일봉", "weight": 0.5, "error": "시세 없음"}], "patterns": None}
    e = se.explain(empty)
    assert e["summary"] == "시세가 없어 판단하지 않았습니다(관망)." and e["evidence"] == [] and e["reasons"] == []


#: 근거마다 관측값이 규칙과 같은 방향인가 — 반올림 때문에 같아질 수는 있다(≥ · ≤)
_SAME_SIDE = {
    "ma_up": lambda v: v["ma5"] >= v["ma20"], "ma_down": lambda v: v["ma5"] <= v["ma20"],
    "macd_up": lambda v: v["macd"] >= v["macd_signal"], "macd_down": lambda v: v["macd"] <= v["macd_signal"],
    "bb_upper": lambda v: v["last"] >= v["bb_upper"], "bb_lower": lambda v: v["last"] <= v["bb_lower"],
    "mid_up": lambda v: v["last"] >= v["ma20"], "mid_down": lambda v: v["last"] <= v["ma20"],
}


def test_observed_values_shown_and_agree_with_rule():
    """근거 표에 지표 값(지표 · 값 · 규칙 · 방향 — 설계서 5.4.1)이 있고, 그 값이 규칙과 같은 쪽이다."""
    seen = set()
    for s in _snapshots():
        tfs = {t["timeframe"]: t for t in s["timeframes"]}
        for r in se.explain(s)["evidence"]:
            if r["key"] == "rsi_mid":
                continue
            assert r["observed"], r
            seen.add(r["key"])
            t = tfs[r["timeframe"]]
            assert all(t[k] == v for k, v in r["values"].items())       # 응답 값 = T2 값
            if r["key"] in _SAME_SIDE:
                assert _SAME_SIDE[r["key"]](r["values"]), r
    assert {"ma_up", "ma_down", "macd_up", "macd_down", "mid_up", "mid_down"} <= seen


def test_old_rows_without_values_still_explained():
    """값을 저장하지 않던 옛 T2 줄 — RSI 만 값이 있고 나머지는 방향만, 문장은 그대로."""
    e = se.explain(BUY)
    assert e["summary"] and {r["key"]: r["observed"] for r in e["evidence"] if r["timeframe"] == "1d"} == {
        "rsi_low": "RSI 27.4", "ma_up": None, "macd_up": None, "mid_down": None}


def test_observed_text_format():
    t = {"ma5": 70120.4, "ma20": 69800.0, "macd": 1.2345, "macd_signal": 0.85, "last": 71000.0, "bb_upper": 72100.0}
    ma = se._observed(se.match_rule("MA5 > MA20 상승 배열")[0], t, "일")
    assert ma == ("5일선 70,120 · 20일선 69,800", {"ma5": 70120.4, "ma20": 69800.0})
    assert se._observed(se.match_rule("MACD > 시그널")[0], t, "일")[0] == "MACD 1.23 · 신호선 0.85"


def test_rsi_number_dropped_at_rounding_edge():
    """T2 는 RSI 를 소수 첫째 자리로 둔다 — 29.96 → 30.0 이면 「30 아래인 30.0」 이 되므로 숫자를 뺀다."""
    snap = {**BUY, "timeframes": [_row("1d", "일봉", 0.5, 2, ["RSI 30 과매도"], rsi=30.0)], "composite": 2.0}
    r = se.explain(snap)["evidence"][0]
    assert r["text"] == "RSI 가 30 아래로 떨어진 상태" and r["observed"] is None


# ── 정직 — 쓰지 않는 말 ──────────────────────────────────────────────────

def test_forbidden_words_absent():
    for s in _snapshots() + [BUY]:
        e = se.explain(s)
        texts = [e["summary"], e["confidence_text"], *e["notes"], *(r["text"] for r in e["evidence"]),
                 *(r["rule"] for r in e["evidence"])]
        for t in texts:
            assert not any(w in t for w in se.FORBIDDEN), t
        assert "확률이 아니" in e["disclaimer"]


def test_korean_particles():
    assert se._topic("분봉(60분)") == "분봉(60분)은" and se._topic("주봉") == "주봉은"
    assert se._and("위") == "위고" and se._and("구간") == "구간이고"
    assert se._because("아래") == "아래라" and se._because("사이인 45.0") == "사이인 45.0이라"


def test_symbol_suffix():
    assert se.normalize_symbol(" 005930.ks ") == "005930" and se.normalize_symbol("035720.KQ") == "035720"
    assert se.normalize_symbol("005930") == "005930"


# ── API ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from app.database.postgres import get_pg_session
    from app.lib.session import get_current_user
    from app.routes import explain as explain_routes

    async def fake_session():
        yield object()

    calls = []

    async def fake_load(db, symbol, on=None):
        calls.append((symbol, on))
        return BUY if se.normalize_symbol(symbol) == "005930" else None

    monkeypatch.setattr(se, "load_snapshot", fake_load)
    app = FastAPI()
    app.include_router(explain_routes.router)
    app.dependency_overrides[get_pg_session] = fake_session
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": ["user"]}
    c = TestClient(app)
    c.calls, c.app_ref = calls, app
    return c


def test_explain_endpoint(client):
    r = client.get("/api/explain?kind=signal&symbol=005930.KS&date=2026-08-31")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == se.explain(BUY)["summary"] and body["method"] == "rule"
    assert client.calls[-1] == ("005930.KS", date(2026, 8, 31))
    assert client.get("/api/explain?symbol=005930").status_code == 200 and client.calls[-1][1] is None


def test_explain_endpoint_errors(client):
    r = client.get("/api/explain?symbol=000660&date=2026-08-31")
    assert r.status_code == 404 and "000660" in r.json()["detail"] and "2026-08-31" in r.json()["detail"]
    assert client.get("/api/explain?kind=allocation&symbol=005930").status_code == 422
    assert client.get("/api/explain?symbol=005930&date=2026-13-01").status_code == 422
    assert client.get("/api/explain").status_code == 422


def test_explain_endpoint_requires_login(client):
    from app.lib.session import get_current_user
    del client.app_ref.dependency_overrides[get_current_user]
    assert client.get("/api/explain?symbol=005930").status_code == 401


# ── T2 읽기 (일회용 시험 DB) ──────────────────────────────────────────────

@pytest.mark.skipif(not DB_URL, reason="일회용 시험 DB 없음(QURIOUS_TEST_DATABASE_URL)")
def test_load_latest_row_of_current_definition():
    b = _bars()
    days = [r["trade_date"] for r in b.daily[-3:]]
    recs = [ms.signal_at(b, d) for d in days]
    old = {**recs[-1], "definition": "old-def"}

    async def go(session):
        await ms.write_snapshots(session, recs + [old])
        first = await se.load_snapshot(session, "TEST01.KS", date.fromisoformat(days[0]))
        latest = await se.load_snapshot(session, "TEST01")
        before = await se.load_snapshot(session, "TEST01", date.fromisoformat(days[0]) - timedelta(days=1))
        return first, latest, before

    first, latest, before = _run(go)
    assert first["as_of"] == date.fromisoformat(days[0]) and latest["as_of"] == date.fromisoformat(days[-1])
    assert latest["definition"] == ms.DEFINITION and before is None
    assert se.explain(latest)["summary"]


# ── 하루치 읽기 · 근거 세기 — 순위 화면(#197 1 · 2 · 4) ─────────────────────

def test_side_counts_are_the_evidence_table():
    for s in _snapshots():
        rows, c = se.explain(s)["evidence"], se.side_counts(s)
        assert c["buy"] + c["neutral"] + c["sell"] == len(rows) == len(c["components"])
        assert c["buy"] == sum(r["contribution"] > 0 for r in rows) and c["sell"] == sum(r["contribution"] < 0 for r in rows)
        assert [x["reason"] for x in c["components"]] == [r["text"] for r in rows]
        assert sum(x["contribution"] for x in c["components"]) == pytest.approx(s["composite"])


def test_side_counts_without_prices_are_zero():
    s = {**BUY, "timeframes": [{k: v for k, v in t.items() if k != "score"} for t in BUY["timeframes"]]}
    assert se.side_counts(s) == {"buy": 0, "neutral": 0, "sell": 0, "components": []}


@pytest.mark.skipif(not DB_URL, reason="일회용 시험 DB 없음(QURIOUS_TEST_DATABASE_URL)")
def test_load_day_ranks_each_symbols_latest_row(monkeypatch):
    b1, b2, b3 = (_bars(seed=s, symbol=f"TEST0{s}") for s in (1, 2, 3))
    days = [r["trade_date"] for r in b1.daily[-3:]]
    last, first = date.fromisoformat(days[-1]), date.fromisoformat(days[0])
    recs = [ms.signal_at(b1, days[-1]), ms.signal_at(b2, days[-1]), ms.signal_at(b3, days[0])]   # TEST03 은 앞 날짜만
    old = {**recs[0], "definition": "old-def", "composite": 99.0}
    monkeypatch.setattr(se, "_universe", lambda: frozenset({"TEST01", "TEST02", "TEST03", "TEST04"}))

    async def go(session):
        await ms.write_snapshots(session, recs + [old])
        day = await se.load_day(session, last)
        before = await se.load_day(session, first - timedelta(days=1))
        picked = await se.load_day(session, last, ["TEST03.KS", "TEST04", "999999"])
        monkeypatch.setattr(se, "_universe", lambda: None)
        unknown = await se.load_day(session, last, ["999999"])
        return day, before, picked, unknown

    day, before, picked, unknown = _run(go)
    rows = day["rows"]
    keys = [(-r["composite"], -r["confidence"], r["symbol"]) for r in rows]
    assert keys == sorted(keys) and {r["symbol"] for r in rows} == {"TEST01", "TEST02", "TEST03"}
    assert all(r["definition"] == ms.DEFINITION for r in rows) and day["definition"] == ms.DEFINITION
    assert {r["symbol"]: r["as_of"] for r in rows} == {"TEST01": last, "TEST02": last, "TEST03": first}
    assert before["rows"] == [] and before["missing"] == []
    assert [r["symbol"] for r in picked["rows"]] == ["TEST03"]
    assert picked["missing"] == [{"symbol": "TEST04", "reason": se.NONE}, {"symbol": "999999", "reason": se.NOT_UNIVERSE}]
    assert unknown["missing"] == [{"symbol": "999999", "reason": se.NONE}]   # 대상인지 모르면 「아님」 이라 하지 않는다
