"""A1 회귀 시험 — `get_quote` 가 등락률을 채워서 돌려주는가 (#26 A1 · C3 의 뿌리).

무엇이 틀렸었나 —
`get_quote` 는 전일 종가(`prev_close`)를 받아 놓고 `change`·`change_pct` 를 **`None` 으로
고정**해 돌려줬다. 그래서 스크리닝 카드는 `+--%`, 표는 `+0.00%`(화면이 `?? 0` 으로 채움)로
나왔다. 같은 파일의 `get_market_summary` 만 따로 계산하고 있어서 지수 줄은 멀쩡했다.

여기서 지키는 것은 셋이다 —
1. 값이 있으면 **계산한다** — 공급자가 준 등락률과 소수 둘째 자리까지 같아야 한다.
2. 값이 없으면 **`None`** 이다 — 0 으로 채우지 않는다(0 은 '보합'이라는 거짓 정보다).
3. 전일 종가는 **기간 1일 차트**에서 읽는다 — `chartPreviousClose` 는 '차트 첫 봉 앞 종가'라
   기간이 길어지면 전일 종가가 아니게 된다.

네트워크는 쓰지 않는다. 시세 요청 함수(`_yahoo_chart`)를 가짜로 바꿔 끼운다.
"""
from __future__ import annotations

import math

import pytest

from app.services import stock
from app.services.stock import _change_from_prev

# 2026-09-28(월) 13:26 KST 장중 실측 — 추석 연휴(09-24·25) 뒤 첫 거래일이라 전일 = 09-23.
# (종목, 현재가, chartPreviousClose, 공급자 등락률 regularMarketChangePercent)
LIVE_SAMPLES_20260928 = [
    ("005930.KS", 273_500.0, 285_500.0, -4.203),
    ("035720.KS", 34_250.0, 33_450.0, 2.392),
    ("000660.KS", 1_789_000.0, 1_862_000.0, -3.921),
    ("247540.KQ", 112_400.0, 105_000.0, 7.048),
    ("^KS11", 6_943.4, 7_080.92, -1.942),
    ("KRW=X", 1_357.87, 1_355.28, 0.1911),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _fake_chart(meta: dict | None, calls: list | None = None):
    """`_yahoo_chart` 대역. 받은 인자를 `calls` 에 적어 둔다."""
    async def fake(symbol: str, interval: str, range_: str):
        if calls is not None:
            calls.append((symbol, interval, range_))
        return None if meta is None else {"meta": dict(meta)}
    return fake


# ── 1. 계산식 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("symbol,price,prev,provider_pct", LIVE_SAMPLES_20260928)
def test_change_matches_provider_percent(symbol, price, prev, provider_pct):
    change, pct = _change_from_prev(price, prev)
    assert change == pytest.approx(price - prev)
    # 우리는 둘째 자리에서 반올림한다 — 공급자 값과 반올림 오차(0.005) 안에서 같아야 한다.
    assert abs(pct - provider_pct) <= 0.005, symbol


def test_change_rounding_hides_float_noise():
    # 1357.87 − 1355.28 = 2.5899999999999181 → 화면에 그대로 나가면 안 된다.
    assert _change_from_prev(1_357.87, 1_355.28) == (2.59, 0.19)
    assert _change_from_prev(273_500, 285_500) == (-12_000.0, -4.2)


@pytest.mark.parametrize("price,prev", [
    (None, 285_500.0),          # 현재가 없음
    (273_500.0, None),          # 전일 종가 없음 — 옛 코드는 여기서 0.00% 로 보였다
    (273_500.0, 0),             # 0 으로 나누기
    (0, 285_500.0),             # 현재가 0 은 결측이다(보합이 아니다)
    (float("nan"), 285_500.0),  # 숫자가 아님 — JSON 응답이 깨지지 않게
    (273_500.0, float("inf")),
    ("abc", 285_500.0),
    (273_500.0, -1.0),          # 음수 기준으로 낸 백분율은 뜻이 없다
])
def test_missing_or_bad_input_is_none_not_zero(price, prev):
    assert _change_from_prev(price, prev) == (None, None)


def test_numeric_strings_are_accepted():
    change, pct = _change_from_prev("34250", "33450")
    assert (change, pct) == (800.0, 2.39)
    assert math.isfinite(pct)


# ── 2. get_quote 가 실제로 채워서 돌려주는가 ─────────────────────────────
@pytest.mark.anyio
async def test_get_quote_fills_change_when_previous_close_is_null(monkeypatch):
    """실측과 같은 모양 — `previousClose` 는 null, `chartPreviousClose` 만 있다."""
    calls: list = []
    monkeypatch.setattr(stock, "_yahoo_chart", _fake_chart({
        "regularMarketPrice": 273_500.0, "previousClose": None,
        "chartPreviousClose": 285_500.0, "longName": "Samsung Electronics Co., Ltd.",
        "currency": "KRW", "exchangeName": "KSC",
    }, calls))

    q = await stock.get_quote("005930.KS")

    assert q["prev_close"] == 285_500.0
    assert q["change"] == -12_000.0
    assert q["change_pct"] == -4.2
    assert q["price"] == 273_500.0
    # 전일 종가를 '차트 첫 봉 앞 종가'에서 읽으므로 기간은 반드시 1일이어야 한다.
    assert calls == [("005930.KS", "1d", "1d")]


@pytest.mark.anyio
async def test_get_quote_prefers_previous_close_when_present(monkeypatch):
    monkeypatch.setattr(stock, "_yahoo_chart", _fake_chart({
        "regularMarketPrice": 110.0, "previousClose": 100.0, "chartPreviousClose": 90.0,
    }))
    q = await stock.get_quote("TEST")
    assert (q["prev_close"], q["change"], q["change_pct"]) == (100.0, 10.0, 10.0)


@pytest.mark.anyio
async def test_get_quote_without_previous_close_returns_none_not_zero(monkeypatch):
    monkeypatch.setattr(stock, "_yahoo_chart", _fake_chart({"regularMarketPrice": 273_500.0}))
    q = await stock.get_quote("005930.KS")
    assert q["change"] is None
    assert q["change_pct"] is None


@pytest.mark.anyio
async def test_get_quote_keeps_error_shape_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(stock, "_yahoo_chart", _fake_chart(None))
    assert await stock.get_quote("005930.KS") == {"symbol": "005930.KS", "error": "데이터 없음"}


# ── 3. 지수 요약이 같은 값을 쓰는가 (식은 한 곳에만) ───────────────────────
@pytest.mark.anyio
async def test_market_summary_uses_the_same_numbers_as_get_quote(monkeypatch):
    by_symbol = {s: (p, prev) for s, p, prev, _ in LIVE_SAMPLES_20260928}

    async def fake(symbol, interval, range_):
        if symbol == "^KQ11":        # 한 줄은 실패시켜 본다
            return None
        price, prev = by_symbol[symbol]
        return {"meta": {"regularMarketPrice": price, "chartPreviousClose": prev}}

    monkeypatch.setattr(stock, "_yahoo_chart", fake)
    rows = {r["symbol"]: r for r in await stock.get_market_summary()}

    assert rows["^KS11"]["change_pct"] == -1.94
    assert rows["KRW=X"]["change_pct"] == 0.19
    assert rows["^KQ11"] == {"symbol": "^KQ11", "name": "KOSDAQ", "price": None, "change_pct": None}
    assert list(rows) == [i["symbol"] for i in stock.MARKET_INDICES]
