"""지금 값(quote_now) 시험 (TC-QUOT) — `app/services/quote_now.py` · `app/routes/quote_now.py` · 모의 주문 체결 직전 확인.

까닭(사용자 2026-10-19): 투자 인디케이터의 「현재가」 가 수집 DB 의 지난 종가(210,000)였고 실제는 217,000 이었다.
결정(같은 날): 「현재가」 칸과 모의 주문 체결가는 지금 값 — 내 증권사 키 → 지연 시세(게이트웨이 · 야후) → 지난 종가 차례,
출처 · 시각 글은 서버 한 곳에서, 「실시간」 이라는 낱말은 쓰지 않는다. 판단 · 백테스트는 저장 자료 그대로.

여기서 지키는 것 —
1. 차례: 키가 있으면 증권사 조회 · 없으면 게이트웨이 / 야후 · 다 못 받으면 지난 종가 · 그것도 없으면 price=None 과 까닭.
2. 글: 출처마다 한 줄 · 국내 장이 닫히면 「장 마감 · 」 · 해외는 국내 장 시간으로 판정하지 않음 · 어디에도 「실시간」 없음.
   출처 이름은 kis_user · kis_gateway · delayed(강사님 시세 함수의 야후 길) · collector — 야후 봉인 시험(TC 기준선)의 글자를 늘리지 않는다.
3. 10초 저장본 · fresh=True 는 다시 받음 · 사람마다 따로.
4. 모의 주문: 체결 직전 확인(키가 있으면 지금 값으로 체결) · 미리보기와 손절 · 익절 점검은 10초 저장본 허용.
5. 수집 DB 거래일 달력을 열지 않는다(DF-81 꼴) — 시험도 이 PC 의 실제 수집 DB 를 열지 않는다(S110 규칙).

네트워크 · DB · 증권사를 쓰지 않는다(모두 가짜로 바꿔 끼운다).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import paper_trading as pt
from app.services import quote_now as Q

ROOT = Path(__file__).resolve().parents[1]
MON_1402 = datetime(2026, 10, 19, 14, 2, 31, tzinfo=Q.KST)     # 월요일 장중
MON_1610 = datetime(2026, 10, 19, 16, 10, 5, tzinfo=Q.KST)     # 월요일 장 마감 뒤
CREDS = SimpleNamespace(app_key="k", app_secret="s", paper=True)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """실제 수집 DB 를 열지 않는다 · 저장본은 시험마다 비운다 · 모의 주문 시세 저장본도 비운다."""
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없는-수집DB.sqlite3"))
    Q._cache.clear()
    pt._STOCK_CACHE.clear()
    yield
    Q._cache.clear()
    pt._STOCK_CACHE.clear()


def _calls(monkeypatch, *, creds=None, user=None, quote=None, quote_exc=None, close=None):
    """세 길을 가짜로 — 몇 번 불렸는지 센다."""
    n = {"creds": 0, "user": 0, "quote": 0, "close": 0}

    async def fake_creds(db, user_id):
        n["creds"] += 1
        return creds

    async def fake_user(symbol, c):
        n["user"] += 1
        return user

    async def fake_quote(symbol):
        n["quote"] += 1
        if quote_exc:
            raise quote_exc
        return quote or {}

    async def fake_close(symbol):
        n["close"] += 1
        return close

    monkeypatch.setattr(Q, "_user_creds", fake_creds)
    monkeypatch.setattr(Q, "_from_user_key", fake_user)
    monkeypatch.setattr(Q.stock, "get_quote", fake_quote)
    monkeypatch.setattr(Q, "_last_close", fake_close)
    return n


def test_market_state_weekday_hours_only():
    """TC-QUOT-01 · 국내 정규장은 평일 09:00 ~ 15:30 — 08:59 · 15:30 · 토요일은 닫힘."""
    assert Q.market_state(MON_1402) == "open"
    assert Q.market_state(datetime(2026, 10, 19, 8, 59, tzinfo=Q.KST)) == "closed"
    assert Q.market_state(datetime(2026, 10, 19, 15, 30, tzinfo=Q.KST)) == "closed"
    assert Q.market_state(datetime(2026, 10, 17, 10, 0, tzinfo=Q.KST)) == "closed"


def test_labels_per_source_and_never_realtime():
    """TC-QUOT-02 · 출처마다 한 줄 · 장 마감 머리 · 해외는 국내 장으로 판정하지 않음 · 「실시간」 없음."""
    lab = Q._label
    assert lab("kis_user", as_of=None, fetched=MON_1402, state="open") == "증권사 조회 · 14:02:31"
    assert lab("kis_gateway", as_of=None, fetched=MON_1402, state="open") == "증권사 연계 조회 · 14:02"
    assert lab("delayed", as_of="2026-10-19 13:40", fetched=MON_1402, state="open") == "지연 시세(약 20분) · 13:40 체결"
    assert lab("delayed", as_of=None, fetched=MON_1402, state="open") == "지연 시세(약 20분)"
    assert lab("collector", as_of="2026-10-16", fetched=MON_1402, state="open") == "10월 16일 종가"
    assert lab("collector", as_of=None, fetched=MON_1402, state="open") == "종가(날짜 모름)"
    assert lab("kis_user", as_of=None, fetched=MON_1610, state="closed") == "장 마감 · 증권사 조회 · 16:10:05"
    assert lab("delayed", as_of="2026-10-17 05:00", fetched=MON_1610, state="closed", domestic=False) == "야후 시세 · 10월 17일 05:00 체결"
    assert Q.label_for("delayed", "2026-10-19 05:00", symbol="AAPL", now=MON_1610) == "야후 시세 · 05:00 체결"
    assert lab("delayed", as_of="2026-10-16 15:19", fetched=MON_1402, state="open") == "지연 시세(약 20분) · 10월 16일 15:19 체결"   # 지난 날 값엔 날짜
    every = [lab(s, as_of="2026-10-16 13:40", fetched=t, state=st, domestic=d)
             for s in ("kis_user", "kis_gateway", "delayed", "collector", None)
             for t, st in ((MON_1402, "open"), (MON_1610, "closed"))
             for d in (True, False)]
    assert all("실시간" not in x for x in every)


def test_user_key_first(monkeypatch):
    """TC-QUOT-03 · 키가 있으면 증권사 조회 값 — 지연 시세 · 지난 종가는 부르지 않는다."""
    n = _calls(monkeypatch, creds=CREDS, user={"price": 217000.0, "change_pct": 3.33, "name": "삼성전자"})
    out = asyncio.run(Q.quote_now("005930.ks", db=object(), user_id="u1", now=MON_1402))
    assert out["price"] == 217000.0 and out["source"] == "kis_user" and out["symbol"] == "005930.KS"
    assert out["label"] == "증권사 조회 · 14:02:31" and out["market_state"] == "open" and out["fallback"] == []
    assert n == {"creds": 1, "user": 1, "quote": 0, "close": 0}


def test_no_key_uses_gateway_or_yahoo(monkeypatch):
    """TC-QUOT-04 · 키가 없으면 게이트웨이(증권사 연계 조회) 또는 야후(지연 시세) — 까닭에 「증권사 키 없음」."""
    _calls(monkeypatch, quote={"price": 216500, "change_pct": 3.1, "source": "kis", "name": "삼성전자"})
    out = asyncio.run(Q.quote_now("005930.KS", db=object(), user_id="u1", now=MON_1402))
    assert out["source"] == "kis_gateway" and out["label"] == "증권사 연계 조회 · 14:02" and out["fallback"] == ["증권사 키 없음"]
    Q._cache.clear()
    _calls(monkeypatch, quote={"price": 215000, "change_pct": 2.4, "as_of": "2026-10-19 13:40"})
    out = asyncio.run(Q.quote_now("005930.KS", db=object(), user_id="u1", now=MON_1402))
    assert out["source"] == "delayed" and out["label"] == "지연 시세(약 20분) · 13:40 체결" and out["as_of"] == "2026-10-19 13:40"


def test_last_close_then_nothing(monkeypatch):
    """TC-QUOT-05 · 지연 시세가 실패하면 지난 종가(국내만) · 그것도 없으면 price=None 과 까닭 · 해외는 지난 종가 길이 없다."""
    n = _calls(monkeypatch, quote_exc=RuntimeError("x"), close={"price": 210000.0, "change_pct": -0.5, "as_of": "2026-10-16"})
    out = asyncio.run(Q.quote_now("005930.KS", user_id="u1", now=MON_1402))
    assert out["source"] == "collector" and out["price"] == 210000.0 and out["label"] == "10월 16일 종가"
    assert out["fallback"] == ["증권사 키 없음", "지연 시세 실패(RuntimeError)"] and n["close"] == 1
    Q._cache.clear()
    _calls(monkeypatch, quote={}, close=None)
    out = asyncio.run(Q.quote_now("005930.KS", user_id="u1", now=MON_1402))
    assert out["price"] is None and out["label"] == "지금 가격을 받지 못했습니다"
    assert out["fallback"] == ["증권사 키 없음", "지연 시세 없음", "수집 DB 종가 없음"]
    Q._cache.clear()
    n = _calls(monkeypatch, quote={}, close={"price": 1.0, "change_pct": None, "as_of": "2026-10-16"})
    out = asyncio.run(Q.quote_now("AAPL", user_id="u1", now=MON_1402))
    assert out["price"] is None and n == {"creds": 0, "user": 0, "quote": 1, "close": 0} and out["market_state"] == "unknown"


def test_cache_ten_seconds_per_user(monkeypatch):
    """TC-QUOT-06 · 같은 사람 · 같은 종목은 10초 저장본 · fresh=True 는 다시 받음 · 다른 사람은 따로."""
    n = _calls(monkeypatch, quote={"price": 215000, "as_of": "2026-10-19 13:40"})
    for _ in range(3):
        asyncio.run(Q.quote_now("005930.KS", user_id="u1"))
    assert n["quote"] == 1
    asyncio.run(Q.quote_now("005930.KS", user_id="u1", fresh=True))
    asyncio.run(Q.quote_now("005930.KS", user_id="u2"))
    assert n["quote"] == 3


def _info(**kw):
    base = {"symbol": "005930.KS", "code": "005930", "name": "삼성전자", "market": "KOSPI", "currency": "KRW",
            "price": 210000.0, "price_local": 210000.0, "quote_source": "delayed", "quote_as_of": "2026-10-19 13:40",
            "quote_label": "지연 시세(약 20분) · 13:40 체결"}
    base.update(kw)
    return base


def test_confirm_for_order(monkeypatch):
    """TC-QUOT-07 · 키가 없으면 받아 둔 값 그대로(글만) · 있으면 지금 값으로 · 해외는 키를 보지도 않음 · 받은 사전은 고치지 않는다."""
    n = _calls(monkeypatch, creds=None)
    info = _info(quote_label=None)
    out = asyncio.run(Q.confirm_for_order(object(), "u1", info))
    assert out["price"] == 210000.0 and "지연 시세(약 20분) · " in out["quote_label"] and "13:40 체결" in out["quote_label"]
    assert info["quote_label"] is None and n["user"] == 0
    n = _calls(monkeypatch, creds=CREDS, user={"price": 217000.0, "change_pct": 3.33, "name": "삼성전자"})
    info = _info()
    out = asyncio.run(Q.confirm_for_order(object(), "u1", info))
    assert out["price"] == 217000.0 and out["price_local"] == 217000.0 and out["quote_source"] == "kis_user"
    assert "증권사 조회 · " in out["quote_label"] and info["price"] == 210000.0
    n = _calls(monkeypatch, creds=CREDS, user={"price": 1.0, "change_pct": 0, "name": "x"})
    out = asyncio.run(Q.confirm_for_order(object(), "u1", _info(symbol="AAPL", currency="USD", price=300000.0)))
    assert out["price"] == 300000.0 and n["creds"] == 0


def test_paper_order_fills_at_confirmed_price(monkeypatch):
    """TC-QUOT-08 · 모의 주문은 체결 직전 확인값으로 체결 · 응답에 출처 글 · 미리보기는 10초 저장본(fresh=False) · resolve_stock 은 출처를 싣는다."""
    seen = {}

    async def fake_resolve(symbol):
        return _info()

    async def fake_fill(db, user_id, info, side, quantity, *, source, filled_at=None):
        seen["price"] = info["price"]
        return {"status": "ok", "symbol": info["symbol"], "side": side, "quantity": quantity, "price": info["price"]}

    monkeypatch.setattr(pt, "resolve_stock", fake_resolve)
    monkeypatch.setattr(pt, "_fill_stock_order", fake_fill)
    _calls(monkeypatch, creds=CREDS, user={"price": 217000.0, "change_pct": 3.33, "name": "삼성전자"})
    res = asyncio.run(pt.stock_order(None, uuid.uuid4(), "005930", "BUY", 1))
    assert seen["price"] == 217000.0 and res["quote_source"] == "kis_user" and "증권사 조회 · " in res["quote_label"]

    Q._cache.clear()
    _calls(monkeypatch, creds=None)
    res = asyncio.run(pt.stock_order(None, uuid.uuid4(), "005930", "BUY", 1))
    assert seen["price"] == 210000.0 and res["quote_source"] == "delayed" and res["quote_label"] == "지연 시세(약 20분) · 13:40 체결"

    fresh_seen = []
    real_confirm = Q.confirm_for_order

    async def spy_confirm(db, user_id, info, *, fresh=True):
        fresh_seen.append(fresh)
        return await real_confirm(db, user_id, info, fresh=fresh)

    async def fake_account(db, user_id, *, lock=False):
        return SimpleNamespace(cash=10_000_000.0)

    async def fake_position(db, user_id, symbol):
        return None

    monkeypatch.setattr(Q, "confirm_for_order", spy_confirm)
    monkeypatch.setattr(pt, "get_account", fake_account)
    monkeypatch.setattr(pt, "_stock_position", fake_position)
    prev = asyncio.run(pt.stock_preview(None, uuid.uuid4(), "005930", "BUY", 1))
    assert fresh_seen == [False] and prev["quoteSource"] == "delayed" and prev["quoteLabel"] == "지연 시세(약 20분) · 13:40 체결"

    async def fake_companies():
        return [{"code": "005930", "symbol": "005930.KS", "name": "삼성전자", "market": "KOSPI"}]

    async def fake_quote(symbol):
        return {"price": 215000, "prev_close": 210000, "currency": "KRW", "as_of": "2026-10-19 13:40"}

    async def fake_fx(price, currency):
        return price, {"rate": 1.0, "source": None, "as_of": None, "note": None}

    monkeypatch.setattr(pt, "resolve_stock", _real_resolve)   # 아래는 진짜 resolve_stock(가져올 때 잡아 둔 것)
    monkeypatch.setattr(pt, "get_krx_companies", fake_companies)
    monkeypatch.setattr(pt, "get_quote", fake_quote)
    monkeypatch.setattr(pt.fx, "to_krw_info", fake_fx)
    data = asyncio.run(pt.resolve_stock("005930"))
    assert data["quote_source"] == "delayed" and data["quote_as_of"] == "2026-10-19 13:40"
    assert "지연 시세(약 20분) · " in data["quote_label"] and "13:40 체결" in data["quote_label"] and data["price"] == 215000.0


_real_resolve = pt.resolve_stock


def test_stop_orders_use_same_confirmation(monkeypatch):
    """TC-QUOT-09 · 손절 · 익절 발동도 같은 확인(그 주문의 사람 · 10초 저장본) — 지금 값이 손절가 아래면 그 값으로 체결."""
    uid = uuid.uuid4()
    order = SimpleNamespace(id=uuid.uuid4(), symbol="005930.KS", user_id=uid, order_type="sell", stop_price=212000.0,
                            quantity=2, source="PAPER")

    class _Rows:
        def scalars(self):
            return self

        def all(self):
            return [order]

    class _DB:
        async def execute(self, stmt):
            return _Rows()

    async def fake_resolve(symbol):
        return _info(price=213000.0, price_local=213000.0)        # 받아 둔 값으로는 손절가(212,000) 위

    seen = {}

    async def fake_fill(db, user_id, info, side, quantity, *, source, filled_at=None):
        seen.update(user=user_id, price=info["price"])
        return {"status": "ok", "price": info["price"], "quantity": quantity, "net_amount": info["price"] * quantity}

    fresh_seen = []
    real_confirm = Q.confirm_for_order

    async def spy_confirm(db, user_id, info, *, fresh=True):
        fresh_seen.append((user_id, fresh))
        return await real_confirm(db, user_id, info, fresh=fresh)

    monkeypatch.setattr(pt, "resolve_stock", fake_resolve)
    monkeypatch.setattr(pt, "_fill_stock_order", fake_fill)
    monkeypatch.setattr(Q, "confirm_for_order", spy_confirm)
    _calls(monkeypatch, creds=CREDS, user={"price": 211000.0, "change_pct": -1.0, "name": "삼성전자"})
    fired = asyncio.run(pt.check_stop_orders(_DB()))
    assert fresh_seen == [(uid, False)] and seen == {"user": uid, "price": 211000.0}
    assert fired[0]["status"] == "filled" and fired[0]["fill_price"] == 211000.0


def test_guards_route_prompt_and_no_calendar():
    """TC-QUOT-10 · 길 등록 · 인증은 모의투자 길과 같음 · 거래일 달력(수집 DB)을 열지 않음 · AI 답 프롬프트의 주가 규칙."""
    from app.routes import quote_now as R
    from app.services import langgraph_agent as L
    assert "/api/quote/now" in [r.path for r in R.router.routes]
    route_src = (ROOT / "app/routes/quote_now.py").read_text(encoding="utf-8")
    assert "get_current_user_any" in route_src
    main_src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "app.include_router(quote_now_routes.router)" in main_src
    svc_src = (ROOT / "app/services/quote_now.py").read_text(encoding="utf-8")
    assert "market_calendar" not in svc_src.split('"""', 2)[2]        # 설명 글 밖에서
    assert "주가 · 현재가 · 시세 숫자는 위 데이터에 기준 시각과 함께 있을 때만" in L.ANSWER_PROMPT
