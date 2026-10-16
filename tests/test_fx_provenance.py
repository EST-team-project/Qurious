"""환율의 출처 · 기준 시각 — 대체값을 말없이 쓰지 않는다 (TC-FX · `P01-①-2` · 시장 범위 조사 D12 · L2).

왜 — `app/services/fx.py` 는 환율을 못 받으면 마지막 값 → 고정 대체값(USD 1,350 등) → 모르는 통화 1.0 을
쓰는데, 응답에는 그 사실이 없어 화면이 「실제 환율」 처럼 보였다(말없는 fallback).

여기서 지키는 것 —
1. `rate_info` 가 환율과 함께 출처(`live` · `last` · `fallback` · `missing` · 원화는 None) · 받은 시각 · 한 줄 글을 준다.
2. 옛 약속(`get_rate_to_krw` → 숫자 · `to_krw` → (원화 값, 환율))은 그대로다 — 값도 `rate_info` 와 같다.
3. 모의투자 시세(`resolve_stock`)가 `fx_source` · `fx_as_of` · `fx_note` 를 싣는다 — 이름 · 부르는 꼴 · 돌려주는 꼴은
   그대로(리밸런싱 시험이 이 함수를 갈아 끼운다) · 대체값이어도 동작(주문 막기)은 바꾸지 않는다(주담당 몫 · 사용자 결정).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import fx
from app.services import paper_trading as pt
from app.services import stock

T0 = 1_792_022_400.0            # 2026-10-15 00:00 UTC = 09:00 KST


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    fx._CACHE.clear()
    pt._STOCK_CACHE.clear()
    yield
    fx._CACHE.clear()
    pt._STOCK_CACHE.clear()


def _clock(monkeypatch, t: float):
    monkeypatch.setattr(fx, "time", SimpleNamespace(time=lambda: t))


def _quote(monkeypatch, price):
    calls = []

    async def fake(symbol):
        calls.append(symbol)
        if isinstance(price, Exception):
            raise price
        return {"price": price}

    monkeypatch.setattr(stock, "get_quote", fake)
    return calls


def _info(cur):
    return asyncio.run(fx.rate_info(cur))


def test_krw_needs_no_conversion(monkeypatch):
    calls = _quote(monkeypatch, AssertionError("원화는 환율을 묻지 않는다"))
    for cur in ("KRW", "", None):
        assert _info(cur) == {"rate": 1.0, "source": None, "as_of": None, "note": None}
    assert calls == []


def test_live_rate_records_when_it_was_fetched(monkeypatch):
    _clock(monkeypatch, T0)
    _quote(monkeypatch, 1385.2)
    i = _info("usd")
    assert i["rate"] == 1385.2 and i["source"] == "live"
    assert i["as_of"] == "2026-10-15T09:00:00+09:00"
    assert "1,385.20" in i["note"] and "10-15 09:00" in i["note"]


def test_cached_rate_keeps_the_fetch_time(monkeypatch):
    _clock(monkeypatch, T0)
    _quote(monkeypatch, 1385.2)
    _info("USD")
    _clock(monkeypatch, T0 + 300)
    calls = _quote(monkeypatch, AssertionError("10분 안에는 다시 묻지 않는다"))
    i = _info("USD")
    assert i["source"] == "live" and i["as_of"] == "2026-10-15T09:00:00+09:00"
    assert calls == []


def test_failed_fetch_after_ttl_uses_last_value_and_says_so(monkeypatch):
    _clock(monkeypatch, T0)
    _quote(monkeypatch, 1385.2)
    _info("USD")
    _clock(monkeypatch, T0 + 700)
    _quote(monkeypatch, RuntimeError("timeout"))
    i = _info("USD")
    assert i["rate"] == 1385.2 and i["source"] == "last"
    assert i["as_of"] == "2026-10-15T09:00:00+09:00"
    assert "마지막" in i["note"] and "10-15 09:00" in i["note"]


@pytest.mark.parametrize("bad", [RuntimeError("down"), 0, None])
def test_never_fetched_uses_fixed_fallback_and_says_so(monkeypatch, bad):
    _clock(monkeypatch, T0)
    _quote(monkeypatch, bad)
    i = _info("USD")
    assert i["rate"] == 1350.0 and i["source"] == "fallback" and i["as_of"] is None
    assert i["note"].startswith("대체 환율") and "1,350" in i["note"]


def test_unknown_currency_is_flagged_missing(monkeypatch):
    _clock(monkeypatch, T0)
    _quote(monkeypatch, RuntimeError("down"))
    i = _info("TWD")
    assert i["rate"] == 1.0 and i["source"] == "missing" and i["as_of"] is None
    assert i["note"].startswith("환율 없음") and "TWD" in i["note"]


def test_old_contract_is_kept(monkeypatch):
    _clock(monkeypatch, T0)
    _quote(monkeypatch, 1385.2)
    rate = asyncio.run(fx.get_rate_to_krw("USD"))
    assert isinstance(rate, float) and rate == 1385.2
    assert asyncio.run(fx.to_krw(2, "USD")) == (2770.4, 1385.2)
    krw, info = asyncio.run(fx.to_krw_info(2, "USD"))
    assert krw == 2770.4 and info["rate"] == rate and info["source"] == "live"


def _paper_quote(monkeypatch, quote: dict):
    async def no_companies():
        return []

    async def fake_quote(symbol):
        return dict(quote)

    monkeypatch.setattr(pt, "get_krx_companies", no_companies)
    monkeypatch.setattr(pt, "get_quote", fake_quote)


def test_resolve_stock_tells_when_fx_is_a_fallback(monkeypatch):
    _clock(monkeypatch, T0)
    _quote(monkeypatch, RuntimeError("down"))          # 환율 길(fx → stock.get_quote)만 실패
    _paper_quote(monkeypatch, {"price": 200.0, "currency": "USD", "name": "Apple Inc.", "market": "NASDAQ"})
    d = asyncio.run(pt.resolve_stock("AAPL"))
    assert d["fx_rate"] == 1350.0 and d["price"] == 270_000.0 and d["price_local"] == 200.0
    assert d["fx_source"] == "fallback" and d["fx_as_of"] is None
    assert d["fx_note"].startswith("대체 환율")
    assert d["settlement_currency"] == "KRW"


def test_resolve_stock_won_quote_has_no_fx(monkeypatch):
    calls = _quote(monkeypatch, AssertionError("원화 종목은 환율을 묻지 않는다"))
    _paper_quote(monkeypatch, {"price": 74_000.0, "currency": "KRW", "name": "삼성전자", "market": "KOSPI"})
    d = asyncio.run(pt.resolve_stock("TESTKR"))
    assert d["fx_rate"] == 1.0 and d["fx_source"] is None and d["fx_as_of"] is None and d["fx_note"] is None
    assert calls == []
