"""최신 시세 한 곳 시험 (TC-QL · DF-123) — 미국주식 대시보드 · 거시경제 지표 · 산업 분석의 「전일 대비」 · 시세 시각.

무엇이 틀렸었나 —
`/api/macro/us-stocks` · `/indicators` · `/industry` 와 그 저장본을 채우는 예약 동기화가 시세를 **기간 5일** 차트로 받아
`chartPreviousClose`(차트 첫 봉 바로 앞 종가 = 5거래일 전 종가)를 전일 종가로 썼다. 2026-10-16 20:3x KST 실측(앱 컨테이너 ·
같은 시각에 두 기간으로 받음): AAPL 전일 대비 −0.28%(공급자 등락률 −0.28)가 +0.46% 로, TSLA −1.29%(−1.286)가 −3.35% 로
보였다 — 미국주식 대시보드의 ±1.5% 규칙이 TSLA 를 「SELL」 로 칠했다. 9-28 에 `get_quote` 만 기간 1일로 고쳤고(TC-A1),
같은 꼴 둘(`macro._get_latest` · `sync_scheduler._yahoo_latest`)이 남아 있었다.

여기서 지키는 것 —
1. 최신 시세는 **기간 1일** 차트에서 읽는다(요청 인자를 본다).
2. 전일 대비는 `stock._change_from_prev` 한 곳으로 — 모르면 None(0 으로 채우지 않는다).
3. 현재가가 없으면 오류 줄(가격 0 으로 채우지 않는다).
4. 시세 시각(공급자의 마지막 체결 시각)을 KST 로 싣는다 — 화면이 「언제 값인지」 말하게.
5. 라우트(`macro._get_latest`)와 예약 동기화가 **같은 함수**를 쓴다(SSoT) — 둘 중 하나만 고쳐지지 않게.
6. 산업 분석 정렬은 등락률을 모르는 줄을 맨 뒤로(None 비교로 500 이 나지 않게) — 라우트 · 동기화가 같은 정렬 함수.

네트워크 · DB 를 쓰지 않는다. 시세 요청 함수(`_yahoo_chart`) · 저장본 함수를 가짜로 바꿔 끼운다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.routes import macro
from app.services import sync_scheduler as SS

KST = timezone(timedelta(hours=9))


@pytest.fixture(autouse=True)
def _no_real_collector_db(monkeypatch, tmp_path):
    """이 PC 의 실제 수집 DB 를 열지 않는다(S110 규칙 · 시세 함수 곁에 수집 DB 다리가 있다)."""
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없는-수집DB.sqlite3"))


# 2026-10-16(금) 20:3x KST 실측 — 미국 장은 10-15 16:00 ET(= 10-16 05:00 KST)에 닫힌 뒤.
# (종목, 현재가, 기간 1일의 chartPreviousClose, 기간 5일의 chartPreviousClose, 공급자 등락률 regularMarketChangePercent)
LIVE_SAMPLES_20261016 = [
    ("AAPL", 342.0, 342.96, 340.42, -0.28),
    ("TSLA", 362.44, 367.16, 375.0, -1.286),
    ("^GSPC", 7744.06, 7718.94, 7765.36, 0.325),
]
CLOSE_1015_ET = int(datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc).timestamp())   # 16:00 ET = 05:00 KST(10-16)


def _fake_chart(by_range: dict, calls: list | None = None):
    """`_yahoo_chart` 대역 — 기간마다 다른 meta(None 이면 응답 없음). 받은 인자를 `calls` 에 적는다."""
    async def fake(symbol: str, interval: str, range_: str):
        if calls is not None:
            calls.append((symbol, interval, range_))
        meta = by_range.get(range_)
        return None if meta is None else {"meta": dict(meta)}
    return fake


def _both(meta: dict) -> dict:
    """기간과 상관없이 같은 meta — 기간이 아닌 것을 보는 시험이 기간 탓에 우연히 통과하지 않게(S98 · 깨 보기 전 확인)."""
    return {"1d": meta, "5d": meta}


def _run(coro):
    return asyncio.run(coro)


def test_latest_reads_one_day_range_and_matches_provider(monkeypatch):
    """TC-QL-01 · 기간 1일로 받고, 그 값으로 낸 등락률이 공급자 등락률과 소수 둘째 자리까지 같다(5일 값이 아니다)."""
    for sym, price, prev_1d, prev_5d, provider in LIVE_SAMPLES_20261016:
        calls: list = []
        monkeypatch.setattr(SS, "_yahoo_chart", _fake_chart(
            {"1d": {"regularMarketPrice": price, "chartPreviousClose": prev_1d, "regularMarketTime": CLOSE_1015_ET},
             "5d": {"regularMarketPrice": price, "chartPreviousClose": prev_5d, "regularMarketTime": CLOSE_1015_ET}}, calls))
        out = _run(SS._yahoo_latest(sym, "USD"))
        assert calls and all(c[2] == "1d" for c in calls), calls
        assert out["change_p"] == pytest.approx(provider, abs=0.01), (sym, out)
        assert out["change"] == pytest.approx(price - prev_1d, abs=1e-4)
        assert out["price"] == price and out["unit"] == "USD"


def test_latest_prefers_previous_close_and_unknown_is_none(monkeypatch):
    """TC-QL-02 · `previousClose` 가 오면 그것이 먼저 · 둘 다 없으면 None(0 이 아니다 — 0 은 「보합」 이라는 거짓)."""
    monkeypatch.setattr(SS, "_yahoo_chart", _fake_chart(
        _both({"regularMarketPrice": 110.0, "previousClose": 100.0, "chartPreviousClose": 50.0})))
    out = _run(SS._yahoo_latest("X", ""))
    assert out["change_p"] == pytest.approx(10.0) and out["change"] == pytest.approx(10.0)
    monkeypatch.setattr(SS, "_yahoo_chart", _fake_chart(_both({"regularMarketPrice": 110.0})))
    out = _run(SS._yahoo_latest("X", ""))
    assert out["change_p"] is None and out["change"] is None and out["price"] == 110.0


def test_latest_without_price_is_error_not_zero(monkeypatch):
    """TC-QL-03 · 현재가가 없거나 응답이 없으면 오류 줄 — 가격을 0 이나 전일 종가로 채우지 않는다."""
    monkeypatch.setattr(SS, "_yahoo_chart", _fake_chart(_both({"chartPreviousClose": 100.0})))
    out = _run(SS._yahoo_latest("X", "USD"))
    assert out.get("error") and "price" not in out
    monkeypatch.setattr(SS, "_yahoo_chart", _fake_chart({}))
    out = _run(SS._yahoo_latest("X", "USD"))
    assert out.get("error") and "price" not in out


def test_latest_as_of_is_kst(monkeypatch):
    """TC-QL-04 · 시세 시각 = 공급자의 마지막 체결 시각을 KST 로(「YYYY-MM-DD HH:MM」) · 없으면 None."""
    monkeypatch.setattr(SS, "_yahoo_chart", _fake_chart(
        _both({"regularMarketPrice": 342.0, "chartPreviousClose": 342.96, "regularMarketTime": CLOSE_1015_ET})))
    assert _run(SS._yahoo_latest("AAPL", "USD"))["as_of"] == "2026-10-16 05:00"
    monkeypatch.setattr(SS, "_yahoo_chart", _fake_chart(_both({"regularMarketPrice": 342.0})))
    assert _run(SS._yahoo_latest("AAPL", "USD"))["as_of"] is None


def test_route_and_sync_share_one_function(monkeypatch):
    """TC-QL-05 · 라우트의 `_get_latest` 는 동기화의 `_yahoo_latest` 를 모듈 이름으로 부른다 — 갈아 끼우면 따라간다(별칭 아님)."""
    async def sentinel(symbol, unit):
        return {"symbol": symbol, "unit": unit, "price": 1.0, "change": None, "change_p": None, "as_of": None, "from": "ss"}
    monkeypatch.setattr(SS, "_yahoo_latest", sentinel)
    out = _run(macro._get_latest("AAPL", "USD"))
    assert out["from"] == "ss" and out["symbol"] == "AAPL"


def test_industry_sort_puts_unknown_last(monkeypatch):
    """TC-QL-06 · 산업 분석은 등락률 큰 차례 · 모르는 줄(None · 오류)은 맨 뒤 — 라우트 · 동기화가 같은 정렬 함수를 쓴다."""
    rows = [{"symbol": "A", "change_p": -1.0}, {"symbol": "B", "change_p": None}, {"symbol": "C", "change_p": 2.5},
            {"symbol": "D", "error": "데이터 없음"}, {"symbol": "E", "change_p": 0.0}]
    assert [r["symbol"] for r in SS.sort_by_change(rows)] == ["C", "E", "A", "B", "D"]

    vals = {"XLK": 1.2, "XLF": None, "XLE": -0.4}

    async def fake_latest(symbol, unit):
        v = vals.get(symbol, 0.1)
        return {"symbol": symbol, "price": 10.0, "change": None if v is None else v / 10, "change_p": v, "unit": unit,
                "as_of": "2026-10-16 05:00"}

    async def no_cache(*a, **k):
        return None

    async def keep(*a, **k):
        return None
    monkeypatch.setattr(SS, "_yahoo_latest", fake_latest)
    monkeypatch.setattr(macro, "cache_get", no_cache)
    monkeypatch.setattr(macro, "cache_set", keep)
    out = _run(macro.macro_industry(_user=None))
    order = [s["symbol"] for s in out["sectors"]]
    assert order.index("XLK") < order.index("XLE") and order[-1] == "XLF", order


# ── L8 · 지연 · 시각 글(2026-10-16) ───────────────────────────────────────────
# 미국 정규장 10-16(목 · 현지): 09:30 ~ 16:00 ET = 10-16 22:30 ~ 10-17 05:00 KST(서머타임).
REG_1016 = {"start": int(datetime(2026, 10, 16, 13, 30, tzinfo=timezone.utc).timestamp()),
            "end": int(datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc).timestamp())}


class _Clock:
    def __init__(self, kst: datetime):
        self.t = kst.timestamp()

    def time(self):
        return self.t


def test_latest_market_open_and_fetched_at(monkeypatch):
    """TC-QL-07 · 받은 때 그 종목 정규장 안이었나(`market_open`) · 받은 시각(`fetched_at` · KST) — 공급자가 준 정규장으로만 판정 ·
    정규장 칸이 없으면 None(지어내지 않는다)."""
    meta = {"regularMarketPrice": 342.0, "chartPreviousClose": 342.96, "regularMarketTime": CLOSE_1015_ET,
            "currentTradingPeriod": {"regular": REG_1016}}
    monkeypatch.setattr(SS, "_yahoo_chart", _fake_chart(_both(meta)))
    monkeypatch.setattr(SS, "time", _Clock(datetime(2026, 10, 16, 20, 41, tzinfo=KST)))   # 장 전(오늘 밤 22:30 열림)
    out = _run(SS._yahoo_latest("AAPL", "USD"))
    assert out["market_open"] is False and out["fetched_at"] == "2026-10-16 20:41"
    monkeypatch.setattr(SS, "time", _Clock(datetime(2026, 10, 16, 23, 5, tzinfo=KST)))    # 장중
    assert _run(SS._yahoo_latest("AAPL", "USD"))["market_open"] is True
    monkeypatch.setattr(SS, "_yahoo_chart", _fake_chart(_both({k: v for k, v in meta.items() if k != "currentTradingPeriod"})))
    assert _run(SS._yahoo_latest("AAPL", "USD"))["market_open"] is None


def test_quote_note_never_says_live(monkeypatch):
    """TC-QL-08 · 머리 글은 서버 한 곳(`data_provenance.quote_note`) — 「지연 시세」 · 장 닫힘 · 마지막 체결 · 받은 시각 · 저장본 나이 ·
    「실시간」 · 「LIVE」 는 어떤 경우에도 쓰지 않는다 · 옛 저장본(시각 칸 없음)은 「모름」."""
    from app.services import data_provenance as DP
    now = datetime(2026, 10, 16, 21, 0, tzinfo=KST)
    closed = [{"as_of": "2026-10-16 05:00", "fetched_at": "2026-10-16 20:41", "market_open": False},
              {"as_of": "2026-10-16 04:59", "fetched_at": "2026-10-16 20:41", "market_open": False}]
    s = DP.quote_note(closed, from_cache=True, now=now)
    assert s == "야후 파이낸스 지연 시세 · 장이 닫힌 뒤 받은 값 · 마지막 체결 10-16 05:00(KST) · 받은 시각 10-16 20:41(저장본 · 19분 전)"
    live = [{"as_of": "2026-10-16 23:04", "fetched_at": "2026-10-16 23:05", "market_open": True}]
    assert DP.quote_note(live, from_cache=False, now=now) == \
        "야후 파이낸스 지연 시세 · 장중에 받은 값 · 마지막 체결 10-16 23:04(KST) · 받은 시각 10-16 23:05"
    mixed = closed[:1] + [{"as_of": "2026-10-16 20:40", "fetched_at": "2026-10-16 20:41", "market_open": True}]
    assert "장" not in DP.quote_note(mixed, from_cache=False, now=now).split(" · ")[1]   # 섞이면 장 상태를 말하지 않는다
    old = [{"symbol": "AAPL", "price": 1.0, "change_p": 0.1}]
    assert DP.quote_note(old, from_cache=True, now=now) == \
        "야후 파이낸스 지연 시세 · 체결 시각 모름 · 저장본 · 받은 시각 모름(최대 2시간 전)"
    for rows in (closed, live, mixed, old, []):
        for fc in (True, False):
            s = DP.quote_note(rows, from_cache=fc, now=now)
            assert "실시간" not in s and "LIVE" not in s.upper()


def test_get_quote_carries_as_of(monkeypatch):
    """TC-QL-10 · `get_quote`(외부 시세 길)도 그 값이 생긴 시각을 싣는다 — 미국주식 차트 머리가 「마지막 체결 …」 을 말하게 · 모르면 None."""
    from app.services import kis_market_data, stock
    monkeypatch.setattr(kis_market_data, "is_enabled", lambda: False)
    monkeypatch.setattr(stock, "_yahoo_chart", _fake_chart(_both(
        {"regularMarketPrice": 342.0, "chartPreviousClose": 342.96, "regularMarketTime": CLOSE_1015_ET})))
    q = _run(stock.get_quote("AAPL"))
    assert q["as_of"] == "2026-10-16 05:00" and q["change_pct"] == pytest.approx(-0.28, abs=0.01)
    monkeypatch.setattr(stock, "_yahoo_chart", _fake_chart(_both({"regularMarketPrice": 342.0})))
    assert _run(stock.get_quote("AAPL"))["as_of"] is None


def test_us_stocks_route_carries_note_on_both_paths(monkeypatch):
    """TC-QL-09 · `/api/macro/us-stocks` · `/indicators` · `/industry` 는 저장본에서 읽어도 새로 받아도 같은 함수로 지은 `note` 를 싣는다."""
    rows = [{"symbol": "AAPL", "price": 342.0, "change": -0.96, "change_p": -0.28, "unit": "USD",
             "as_of": "2026-10-16 05:00", "fetched_at": "2026-10-16 20:41", "market_open": False}]

    async def cached(*a, **k):
        return rows

    async def no_cache(*a, **k):
        return None

    async def keep(*a, **k):
        return None

    async def fake_latest(symbol, unit):
        return dict(rows[0], symbol=symbol, unit=unit)
    monkeypatch.setattr(SS, "_yahoo_latest", fake_latest)
    monkeypatch.setattr(macro, "cache_set", keep)
    for getter, fc in ((cached, True), (no_cache, False)):
        monkeypatch.setattr(macro, "cache_get", getter)
        for route, key in ((macro.macro_us_stocks, "stocks"), (macro.macro_indicators, "indicators"),
                           (macro.macro_industry, "sectors")):
            out = _run(route(_user=None))
            assert out["from_cache"] is fc and out[key]
            assert out["note"].startswith("야후 파이낸스 지연 시세 · 장이 닫힌 뒤 받은 값 · 마지막 체결 10-16 05:00(KST)"), out["note"]
