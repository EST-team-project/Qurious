"""미국주식 주문 · 포트폴리오가 원화 모의 장부를 바르게 쓴다 (TC-USO · `P01-④-3` · 2026-10-16 모의투자 점검 🔴).

무엇이 틀렸었나 — 미국주식 › 주문/매매가 달러 시세를 원화 가상 매매(`POST /api/orders` · broker virtual)로 보내,
서버가 그 값을 원화 현금에서 그대로 빼고 국내 매도세까지 매겼다. 포드 1주($12.31)를 사면 현금은 12.31원 빠지고
보유는 원화 환산가(16,466원)로 평가돼 손익이 +133,658% 로 보였다(모의투자 점검 둘째 바퀴 · 15:01 실제로 밟음).

여기서 지키는 것 —
1. 원화 가상 매매는 국내 종목(`.KS` · `.KQ` · `.KN` · 6자리)만 받는다 — 해외 종목은 400 + 까닭(말없이 잘못 적지 않는다).
2. 미국주식 주문 화면은 환율을 곱하는 모의 주문 길(`/api/paper/stocks/orders` · 서버가 시세 · 환율을 정한다)로 보내고,
   가격을 보내지 않는다 · 지정가와 매도는 까닭 글로 막는다(매도는 비용 모듈이 해외 비용을 알 때까지 — 강민석 님 이슈).
3. 주문 내역 · 포트폴리오는 그 장부(원화)를 읽고 단위를 원으로 적는다 · 달러 시세와 환율 글은 서버 응답 그대로(이스케이프).
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routes import stocks
from app.services import overseas_orders as oo

ROOT = Path(__file__).resolve().parents[1]
US_JS = ROOT / "public" / "js" / "us.js"      # 깨 보기가 이 칸을 사본으로 바꿔 끼운다
APP_HTML = ROOT / "public" / "app.html"       # 같은 까닭(주문 칸 안내 글)


# ── 1. 서버 — 원화 가상 매매는 국내 종목만 ───────────────────────────────

@pytest.mark.parametrize("symbol", ["005930", "005930.KS", "035720.KQ", "123456.KN", "0001a0.ks", " 005930.ks "])
def test_domestic_symbols(symbol):
    assert oo.is_domestic(symbol)


@pytest.mark.parametrize("symbol", ["AAPL", "F", "BRK.B", "TSLA", "SPY", "", None, "12345", "ABCDEF"])
def test_overseas_or_unknown_symbols(symbol):
    assert not oo.is_domestic(symbol)


def _body(symbol, side="buy", broker="virtual"):
    return stocks.OrderBody(symbol=symbol, name=symbol, order_type=side, quantity=1, price=12.31, broker=broker)


class _Reached(Exception):
    """거름을 지나 비용 계산까지 왔다는 표시 — DB 는 열지 않는다."""


def test_virtual_order_refuses_overseas_symbol_before_touching_cash(monkeypatch):
    def reached(*a, **k):
        raise _Reached()

    monkeypatch.setattr(stocks.trading_cost, "order_costs", reached)
    for side in ("buy", "sell"):
        with pytest.raises(HTTPException) as e:
            asyncio.run(stocks.place_order(_body("F", side), user={"id": "00000000-0000-0000-0000-000000000001"}, db=None))
        assert e.value.status_code == 400
        assert e.value.detail == oo.VIRTUAL_REFUSAL
    assert "해외 종목" in oo.VIRTUAL_REFUSAL and "미국주식" in oo.VIRTUAL_REFUSAL


def test_virtual_order_lets_domestic_symbol_through(monkeypatch):
    def reached(*a, **k):
        raise _Reached()

    monkeypatch.setattr(stocks.trading_cost, "order_costs", reached)
    for sym in ("005930", "005930.KS"):
        with pytest.raises(_Reached):
            asyncio.run(stocks.place_order(_body(sym), user={"id": "00000000-0000-0000-0000-000000000001"}, db=None))


def test_non_virtual_broker_is_not_filtered_here(monkeypatch):
    """거름은 원화 가상 매매 장부에만 — 다른 증권사 길은 그 길의 관문이 본다."""
    def reached(*a, **k):
        raise _Reached()

    monkeypatch.setattr(stocks.trading_cost, "order_costs", reached)
    with pytest.raises(_Reached):
        asyncio.run(stocks.place_order(_body("AAPL", broker="kis"), user={"id": "00000000-0000-0000-0000-000000000001"}, db=None))


# ── 2 · 3. 화면 — 모의 주문 길 · 원화 장부 읽기 ─────────────────────────────

def _func(name: str) -> str:
    js = US_JS.read_text(encoding="utf-8")
    m = re.search(rf"async function {name}\(.*?\n\}}\n", js, flags=re.S)
    assert m, f"us.js 에서 {name} 를 찾지 못했다"
    return m.group(0)


def test_order_goes_to_the_paper_ledger_path_without_a_price():
    f = _func("placeUsOrder")
    assert '"/api/paper/stocks/orders"' in f
    assert '"/api/orders"' not in f
    body = re.search(r"body:\s*\{(.*?)\}", f, flags=re.S)
    assert body and "price" not in body.group(1), "가격을 보내면 서버가 정한 시세 · 환율을 우회할 수 있다"
    assert re.search(r'side:\s*"BUY"', f)


def test_limit_and_sell_are_refused_with_a_reason():
    f = _func("placeUsOrder")
    lim = f.index('type === "limit"')
    sell = f.index('side === "sell"')
    call = f.index('"/api/paper/stocks/orders"')
    assert lim < call and sell < call, "지정가 · 매도 거름이 주문 부름보다 앞에 있어야 한다"
    assert "지정가" in f and "해외 종목 모의 매도" in f


def test_history_reads_the_ledger_and_marks_units():
    f = _func("loadUsOrderHistory")
    assert '"/api/paper/stocks/orders/history' in f
    assert '"/api/orders"' not in f
    assert "원" in f and 'source === "WEB"' in f, "옛 주문(달러가 원화 장부에 그대로)과 새 주문(원화)을 단위로 가른다"


def test_portfolio_reads_ledger_positions_and_server_fx_note():
    f = _func("loadUsPortfolio")
    assert '"/api/paper/stocks/positions' in f
    assert "/api/paper/stocks/quote" in f
    assert '"/api/portfolio"' not in f
    assert ".fx_note" in f and "escHtml(fxNote)" in f, "환율 글은 서버 글(fx_note) 그대로 · 이스케이프"
    assert "원" in f


def test_screen_does_not_mix_dollar_quotes_into_ledger_math():
    """장부(원화)의 평균단가 · 손익을 달러 시세로 다시 셈하지 않는다 — 옛 결함의 꼴."""
    f = _func("loadUsPortfolio")
    assert "/api/stocks/quote" not in f


def test_order_screen_help_text_matches_the_ledger_path():
    """주문 칸 안내 글이 실제 길과 맞는다 — 옛 글은 「가상 포트폴리오(/api/orders)에 실시간 체결가로 기록」 이었다."""
    html = APP_HTML.read_text(encoding="utf-8")
    m = re.search(r'data-view="us-order">(.*?)data-view=', html, flags=re.S)
    assert m, "app.html 에서 미국주식 주문 칸을 찾지 못했다"
    view = m.group(1)
    assert "/api/orders" not in view
    assert "원화 모의 계좌" in view and "환율" in view
    assert "시장가 매수만" in view, "지정가 · 매도를 막은 사실을 안내 글이 말한다"
    price = re.search(r'id="us-ord-price"[^>]*placeholder="([^"]*)"', view)
    assert price and "시장가만" in price.group(1)


# ── 4. 화면 규칙 = 서버 규칙 (두 곳에 적힐 수밖에 없는 판정 — 시험이 맞댄다) ─────────────

SAMPLES = ["005930", "005930.KS", "035720.KQ", "123456.KN", "0001A0", "0001A0.KS",
           "AAPL", "F", "BRK.B", "TSLA", "SPY", "ABCDEF", "12345", ""]


def test_screen_rule_equals_server_rule(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 규칙을 돌릴 수 없다")
    js = US_JS.read_text(encoding="utf-8")
    m = re.search(r"^const isKrSymbol = (.+);\s*$", js, flags=re.M)
    assert m, "us.js 에서 isKrSymbol 을 찾지 못했다"
    script = tmp_path / "rule.mjs"
    script.write_text(f"const f = {m.group(1)};\nprocess.stdout.write(JSON.stringify({json.dumps(SAMPLES)}.map(f)));\n",
                      encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    assert json.loads(out) == [oo.is_domestic(s) for s in SAMPLES]
