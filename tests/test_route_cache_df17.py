"""DF-17 시험 — 일봉 · 지표 라우트가 수집 DB 다리 앞에서 옛 캐시를 돌려주지 않는가.

무엇이 틀렸었나 —
DF-08 다리(`collector_db`)는 `stock.get_candles` 안에서 캐시를 거치지 않는다(「12:30 갱신이 바로 보인다」).
그런데 그 위의 라우트 두 곳 — `/api/stocks/candles` · `/api/stocks/quant/indicators` — 이 **자기 캐시**
(`data_cache` · PostgreSQL · 6시간)를 다리보다 먼저 보고, 다리가 준 결과를 그 캐시에 다시 써 넣었다
(옛 `stocks.py:62-66` · `:78-82` · API 명세서 v0.1 F2). `sync_scheduler` 도 매시간 31종목의 지표를
같은 키(`indicators:{기호}:2y`)에 채웠다. 그래서 12:30 일일 갱신 뒤에도 최대 6시간 동안 화면에 옛 `as_of` 가
`from_cache: true` 와 함께 나갔다. S57 의 TC-CD 는 서비스 함수만 불러서 이 층을 보지 못했다 —
여기서는 **라우트 함수를 직접 부른다**. (자동매매는 서비스 함수를 직접 불러 이 캐시와 무관하다 — `auto_trade.py:267`.)

여기서 지키는 것 —
1. 다리가 맡는 요청(국내 주식 · 일봉 · 아는 기간 · DB 파일 있음)은 라우트 캐시에 옛 사전이 있어도
   **새 as_of** 가 나오고, 라우트 캐시를 읽지도 쓰지도 않는다              ← 옛 코드에서 실패
2. 캐시 데우기가 아무도 읽지 않을 키를 쓰지 않는다                          ← 옛 코드에서 실패
3. 다리가 안 맡는 요청(지수 · 주봉 · DB 없음)은 옛 동작 그대로 — `from_cache: true` 까지 (짝 시험)

네트워크 · PostgreSQL 은 쓰지 않는다. 캐시 함수 · 외부 차트는 대역이다.
"""
from __future__ import annotations

import asyncio
import copy
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.routes import stocks as stocks_route
from app.services import collector_db, stock, sync_scheduler
from collector.db import SCHEMA  # 수집기의 실제 스키마 — 픽스처 DB 가 실제와 같은 모양이게

SYMBOL = "005930.KS"
NEW_AS_OF = "2026-09-28"   # 12:30 갱신이 막 넣은 날
OLD_AS_OF = "2026-09-25"   # 라우트 캐시에 남아 있던 옛 응답의 기준일
N_DAYS = 30                # 지표는 봉 20개 이상이어야 계산한다(get_quant_indicators)

STALE_CANDLES = {
    "symbol": SYMBOL, "interval": "1d", "period": "max",
    "candles": [{"time": int(datetime(2026, 9, 25, tzinfo=timezone.utc).timestamp()),
                 "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0}],
    "source": "collector", "as_of": OLD_AS_OF,
}
STALE_INDICATORS = {"symbol": SYMBOL, "current_price": 1.0, "signal": {}, "source": "collector", "as_of": OLD_AS_OF}


def _weekdays_until(last: date, n: int) -> list[date]:
    days, d = [], last
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1]


def _last_close() -> float:
    return float(70_000 + 100 * (N_DAYS - 1))


@pytest.fixture
def fresh_db(tmp_path, monkeypatch) -> Path:
    """12:30 갱신이 끝난 수집 DB — 005930 의 마지막 봉이 NEW_AS_OF 다. 계수 1(조정 없음)."""
    p = tmp_path / "market.sqlite3"
    conn = sqlite3.connect(p)
    conn.executescript(SCHEMA)
    for i, d in enumerate(_weekdays_until(date.fromisoformat(NEW_AS_OF), N_DAYS)):
        bas_dt, px = d.strftime("%Y%m%d"), 70_000 + 100 * i
        conn.execute(
            "INSERT INTO price_daily (bas_dt, srtn_cd, clpr, mkp, hipr, lopr, trqu) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bas_dt, "005930", px, px, px + 500, px - 500, 1_000_000))
        conn.execute(
            "INSERT INTO price_adjusted (bas_dt, srtn_cd, adj_clpr, adj_mkp, adj_hipr, adj_lopr, cum_factor)"
            " VALUES (?, ?, ?, ?, ?, ?, 1.0)",
            (bas_dt, "005930", px, px, px + 500, px - 500))
    conn.commit()
    conn.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(p))
    return p


@pytest.fixture
def no_db(tmp_path, monkeypatch):
    """수집 DB 를 받지 않은 환경(데이터 파트 밖의 팀원) — 다리는 None 을 돌려준다."""
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(tmp_path / "없음.sqlite3"))


def _stub_caches(monkeypatch, cached: dict | None) -> dict[str, list]:
    """라우트 캐시가 `cached` 를 돌려주게 하고, 옛 경로(외부 차트 · 서비스 캐시)는 대역으로 바꾼다."""
    calls: dict[str, list] = {"route_get": [], "route_set": [], "stock_get": [], "chart": []}

    async def route_get(key, max_age_hours=24):
        calls["route_get"].append(key)
        return copy.deepcopy(cached)   # 라우트가 from_cache 를 덧붙이므로 원본을 지킨다

    async def route_set(key, value):
        calls["route_set"].append(key)

    async def stock_get(key, max_age_hours=24):
        calls["stock_get"].append(key)
        return None

    async def stock_set(key, value):
        return None

    async def chart(symbol, interval, range_):
        calls["chart"].append(symbol)
        return None

    monkeypatch.setattr(stocks_route, "cache_get", route_get)
    monkeypatch.setattr(stocks_route, "cache_set", route_set)
    monkeypatch.setattr(stock, "cache_get", stock_get)
    monkeypatch.setattr(stock, "cache_set", stock_set)
    monkeypatch.setattr(stock, "_yahoo_chart", chart)
    return calls


# ── 1. 다리가 맡는 요청 — 라우트 캐시를 건너뛴다 ─────────────────────────
def test_candles_route_returns_fresh_as_of_over_stale_cache(fresh_db, monkeypatch):
    """옛 코드에서는 실패한다 — 캐시의 OLD_AS_OF 를 from_cache: true 와 함께 돌려줬다."""
    calls = _stub_caches(monkeypatch, STALE_CANDLES)
    out = asyncio.run(stocks_route.stock_candles(symbol=SYMBOL, period="max", interval="1d"))
    assert out["as_of"] == NEW_AS_OF
    assert out["source"] == "collector"
    assert "from_cache" not in out
    assert len(out["candles"]) == N_DAYS
    assert calls["route_get"] == []    # 파일 읽기가 캐시 조회보다 싸다
    assert calls["route_set"] == []    # 다리 결과를 캐시에 다시 쓰지 않는다 — 다음 요청이 옛 값을 읽지 않게
    assert calls["chart"] == []


def test_indicators_route_returns_fresh_as_of_over_stale_cache(fresh_db, monkeypatch):
    """옛 코드에서는 실패한다. 지표 3화면(`indicator-strategy` · `quant-backtest` · `quant-dashboard`)의
    「현재가」는 마지막 봉 종가라, 옛 캐시면 12:30 갱신 전 가격을 오늘 것처럼 보여 줬다."""
    calls = _stub_caches(monkeypatch, STALE_INDICATORS)
    out = asyncio.run(stocks_route.quant_indicators(symbol=SYMBOL, period="max"))
    assert out["as_of"] == NEW_AS_OF
    assert out["current_price"] == _last_close()
    assert "from_cache" not in out
    assert calls["route_get"] == []
    assert calls["route_set"] == []


def test_bridge_shape_without_rows_falls_to_old_path_cache(fresh_db, monkeypatch):
    """DB 에 행이 없는 6자리 기호(ETF 등) — 라우트 캐시는 건너뛰지만 옛 경로가 **같은 키**로 캐시한다.
    그래서 외부 호출이 늘지 않는다(짝 시험 · 옛 코드도 이 경로에서 서비스 캐시를 본다)."""
    calls = _stub_caches(monkeypatch, None)
    out = asyncio.run(stocks_route.stock_candles(symbol="069500.KS", period="1y", interval="1d"))
    assert out == {"symbol": "069500.KS", "candles": []}
    assert calls["stock_get"] == ["candles:069500.KS:1y:1d"]


# ── 2. 캐시 데우기 — 아무도 읽지 않을 키를 쓰지 않는다 ────────────────────
def _stub_warmers(monkeypatch) -> dict[str, list]:
    calls: dict[str, list] = {"candles": [], "indicators": [], "cache_set": []}

    async def fake_candles(symbol, period="1y", interval="1d"):
        calls["candles"].append(symbol)
        return {"symbol": symbol, "candles": []}

    async def fake_indicators(symbol, period="2y"):
        calls["indicators"].append(symbol)
        return {"symbol": symbol}

    async def fake_set(key, value):
        calls["cache_set"].append(key)

    monkeypatch.setattr(stock, "get_candles", fake_candles)   # _sync_stock_candles 가 함수 안에서 import 한다
    monkeypatch.setattr(sync_scheduler, "get_quant_indicators", fake_indicators)
    monkeypatch.setattr(sync_scheduler, "cache_set", fake_set)
    return calls


def test_warmer_skips_symbols_the_bridge_serves(fresh_db, monkeypatch):
    """옛 코드에서는 실패한다 — 31종목(전부 .KS)의 지표를 매시간 계산해 라우트 캐시 키에 썼다.
    라우트가 그 키를 건너뛰는 지금은 아무도 읽지 않는 쓰기다. 일봉 데우기도 다리가 파일을 읽고 버릴 뿐이다."""
    calls = _stub_warmers(monkeypatch)
    asyncio.run(sync_scheduler._sync_stock_candles())
    assert calls == {"candles": [], "indicators": [], "cache_set": []}


def test_warmer_without_db_warms_as_before(no_db, monkeypatch):
    """짝 시험 — DB 가 없는 환경은 옛 경로(외부 차트)라 데우기가 그대로 쓸모 있다."""
    calls = _stub_warmers(monkeypatch)
    asyncio.run(sync_scheduler._sync_stock_candles())
    n = len(stock.QUANT_STOCKS)
    assert len(calls["candles"]) == len(calls["indicators"]) == len(calls["cache_set"]) == n


# ── 3. 다리가 안 맡는 요청 — 옛 동작 그대로 (짝 시험) ───────────────────
@pytest.mark.parametrize("symbol,interval", [("^KS11", "1d"), (SYMBOL, "1wk")])
def test_non_bridge_requests_keep_route_cache(fresh_db, monkeypatch, symbol, interval):
    calls = _stub_caches(monkeypatch, {**STALE_CANDLES, "symbol": symbol, "interval": interval})
    out = asyncio.run(stocks_route.stock_candles(symbol=symbol, period="1y", interval=interval))
    assert out["from_cache"] is True
    assert calls["route_get"] == [f"candles:{symbol}:1y:{interval}"]


def test_without_db_route_cache_is_used_as_before(no_db, monkeypatch):
    """수집 DB 가 없으면 다리는 None 이고 옛 경로다 — 라우트 캐시 동작을 바꾸지 않는다."""
    calls = _stub_caches(monkeypatch, STALE_INDICATORS)
    out = asyncio.run(stocks_route.quant_indicators(symbol=SYMBOL, period="2y"))
    assert out["from_cache"] is True
    assert calls["route_get"] == [f"indicators:{SYMBOL}:2y"]


# ── 4. 판정 함수 — 다리가 먼저 받는 요청인가 ─────────────────────────────
@pytest.mark.parametrize("symbol,period,interval,expected", [
    (SYMBOL, "1y", "1d", True),
    ("035720.KQ", "max", "1d", True),
    ("069500.KS", "1y", "1d", True),    # 모양만 본다 — 행이 있는지는 파일을 열어야 안다(위 짝 시험)
    ("^KS11", "1y", "1d", False),       # 지수
    ("AAPL", "1y", "1d", False),        # 해외
    ("005930", "1y", "1d", False),      # 시장 표기 없음
    (SYMBOL, "1y", "1wk", False),       # 주봉
    (SYMBOL, "5m", "1d", False),        # 모르는 기간
])
def test_handles_follows_the_bridge_request_shape(fresh_db, symbol, period, interval, expected):
    assert collector_db.handles(symbol, period, interval) is expected
    if not expected:   # 모양 판정이 다리와 갈라지지 않는다 — 안 맡는다고 한 요청은 다리도 None
        assert collector_db.read_daily_candles(symbol, period, interval) is None


def test_handles_is_false_without_db(no_db):
    assert collector_db.handles(SYMBOL, "1y", "1d") is False
