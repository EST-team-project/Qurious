"""B5 — 스탑 주문 (감시 주문) 시험.

- 등록 · 취소 · 발동 (매수/매도)
- 갭이면 stop_price 보다 더 나쁘게 체결
- 매도 스탑은 보유 수량 필요
"""
import asyncio
import os
import uuid
from datetime import date, datetime, timezone

import pytest

from app.models import Base, BrokerSettings, Portfolio, User
from app.models.paper import PaperAccount
from app.models.trading import Order, OrderFill
from app.services import paper_trading as pt

DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB_URL, reason="일회용 시험 DB 없음")

TABLES = [User.__table__, Portfolio.__table__, Order.__table__,
          OrderFill.__table__, PaperAccount.__table__, BrokerSettings.__table__]
          

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=TABLES))
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=TABLES))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        uid = uuid.uuid4()
        session.add(User(id=uid, name="s", email=f"{uid.hex}@t.local",
                         password_hash="x", client_id=uid.hex))
        await session.flush()   # ★ User 먼저 INSERT (FK 순서)
        # PAPER 계좌 생성
        session.add(PaperAccount(user_id=uid, cash=10_000_000, initial_cash=10_000_000))
        await session.commit()
        yield session, uid
    await engine.dispose()


def _mock_price(monkeypatch, price: float):
    async def _resolve(symbol):
        return {"symbol": symbol, "name": symbol, "price": price,
                "market": "KOSPI", "is_etf": False}
    monkeypatch.setattr(pt, "resolve_stock", _resolve)


@needs_db
@pytest.mark.anyio
async def test_place_stop_order_pending(db, monkeypatch):
    session, uid = db
    _mock_price(monkeypatch, 70000)

    r = await pt.place_stop_order(session, uid, "005930.KS", "BUY", 5, 75000)
    await session.commit()

    assert r["status"] == "pending"
    assert r["stop_price"] == 75000
    assert r["side"] == "BUY"


@needs_db
@pytest.mark.anyio
async def test_stop_sell_requires_holding(db, monkeypatch):
    session, uid = db
    _mock_price(monkeypatch, 70000)
    with pytest.raises(pt.StopOrderError):
        await pt.place_stop_order(session, uid, "005930.KS", "SELL", 5, 65000)


@needs_db
@pytest.mark.anyio
async def test_stop_sell_fires_when_price_below(db, monkeypatch):
    session, uid = db
    _mock_price(monkeypatch, 70000)
    session.add(Portfolio(user_id=uid, symbol="005930.KS", name="삼성전자",
                          quantity=10, avg_price=70000, book="PAPER"))
    await session.commit()

    r = await pt.place_stop_order(session, uid, "005930.KS", "SELL", 5, 65000)
    await session.commit()

    # 시세 64000 (< 65000) → 발동
    _mock_price(monkeypatch, 64000)
    fired = await pt.check_stop_orders(session, uid)
    await session.commit()

    assert len(fired) == 1
    assert fired[0]["status"] == "filled"
    assert fired[0]["stop_price"] == 65000
    assert fired[0]["fill_price"] == 64000   # 갭 → stop보다 나쁜 가격


@needs_db
@pytest.mark.anyio
async def test_stop_sell_not_fired_when_price_above(db, monkeypatch):
    session, uid = db
    _mock_price(monkeypatch, 70000)
    session.add(Portfolio(user_id=uid, symbol="005930.KS", name="삼성전자",
                          quantity=10, avg_price=70000, book="PAPER"))
    await session.commit()

    await pt.place_stop_order(session, uid, "005930.KS", "SELL", 5, 65000)
    await session.commit()

    _mock_price(monkeypatch, 75000)   # > 65000 → 미발동
    fired = await pt.check_stop_orders(session, uid)
    assert fired == []


@needs_db
@pytest.mark.anyio
async def test_stop_buy_fires_when_price_above(db, monkeypatch):
    session, uid = db
    _mock_price(monkeypatch, 70000)

    await pt.place_stop_order(session, uid, "005930.KS", "BUY", 5, 75000)
    await session.commit()

    _mock_price(monkeypatch, 78000)   # > 75000 → 발동
    fired = await pt.check_stop_orders(session, uid)
    await session.commit()
    assert len(fired) == 1
    assert fired[0]["status"] == "filled"


@needs_db
@pytest.mark.anyio
async def test_cancel_stop_order(db, monkeypatch):
    session, uid = db
    _mock_price(monkeypatch, 70000)
    session.add(Portfolio(user_id=uid, symbol="005930.KS", name="삼성전자",
                          quantity=10, avg_price=70000, book="PAPER"))
    await session.commit()

    r = await pt.place_stop_order(session, uid, "005930.KS", "SELL", 5, 65000)
    await session.commit()

    out = await pt.cancel_stop_order(session, uid, r["order_id"])
    await session.commit()
    assert out["status"] == "cancelled"

    # 이미 취소된 걸 다시 취소 → 에러
    with pytest.raises(pt.StopOrderError):
        await pt.cancel_stop_order(session, uid, r["order_id"])

@needs_db
@pytest.mark.anyio
async def test_stock_order_history_excludes_quant(db):
    """#219 — 모의주문 내역에 QUANT 장부 주문은 안 나온다."""
    session, uid = db
    from app.models.trading import Order
    session.add(Order(user_id=uid, symbol="055550.KS", name="신한지주",
                       order_type="buy", quantity=1, price=50000,
                       status="filled", broker="virtual", source="PAPER"))
    session.add(Order(user_id=uid, symbol="055550.KS", name="신한지주",
                       order_type="buy", quantity=3, price=50000,
                       status="filled", broker="quant_ai", source="QUANT"))
    await session.commit()

    rows = await pt.stock_order_history(session, uid)
    sources = {r.get("source") for r in rows}
    assert "QUANT" not in sources
    assert "PAPER" in sources
