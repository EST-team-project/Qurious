"""일회용 PG + 모의 증권사: 재주문 경합·잔량·중지·통신 실패 경계."""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.models import User, BrokerSettings, LiveOrder
from app.services import order_retry as retry

pytestmark = [pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요"),
              pytest.mark.usefixtures("rebalance_db_schema")]


async def seed(factory, **changes):
    async with factory() as db:
        uid = uuid.uuid4()
        db.add(User(id=uid, name="retry test", email=f"{uid}@example.com", client_id=uid.hex, password_hash="test"))
        await db.flush()
        bs = BrokerSettings(user_id=uid, broker="kis", quant_auto_enabled=True, quant_mode="live",
            risk_cooldown_min=0, quant_execution_policy={"retry_enabled": True})
        parent = LiveOrder(user_id=uid, client_order_id=uid.hex, environment="paper", symbol="005930.KS",
            name="삼성전자", side="SELL", order_type="LIMIT", quantity=10, price=70000, order_no=uid.hex[:20],
            status="CANCELLED", created_at=datetime.now(timezone.utc))
        for k, v in changes.items():
            setattr(bs if hasattr(BrokerSettings, k) else parent, k, v)
        db.add_all([bs, parent])
        await db.commit()
        return parent.id, uid, parent.order_no


def mocks(monkeypatch):
    monkeypatch.setattr(settings, "QUANT_AGGRESSIVE_MODE", False)
    monkeypatch.setattr(retry.gateway, "environment", lambda: "paper")
    monkeypatch.setattr(retry.gateway, "is_configured", lambda: True)
    monkeypatch.setattr(retry.gateway, "is_krx_market_open", lambda: True)
    monkeypatch.setattr(retry, "coordination_ready", AsyncMock(return_value=True))
    async def status(no, **kw):
        return {"orderNo": no, "status": "CANCELLED", "side": "SELL", "symbol": "005930",
                "orderedQuantity": 10, "filledQuantity": 4}
    monkeypatch.setattr(retry.gateway, "get_order_status", AsyncMock(side_effect=status))
    monkeypatch.setattr(retry.gateway, "list_today_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(retry.gateway, "get_balance", AsyncMock(return_value={"totalEvalAmount": 1000000,
        "holdings": [{"symbol": "005930", "quantity": 5, "currentPrice": 70000}]}))
    monkeypatch.setattr(retry.risk_guard, "day_start_equity", AsyncMock(return_value=1000000))
    monkeypatch.setattr(retry.risk_guard, "orders_today", AsyncMock(return_value=0))
    monkeypatch.setattr(retry.risk_guard, "acquire_order_slot", AsyncMock(return_value=True))
    monkeypatch.setattr(retry.risk_guard, "increment_orders_today", AsyncMock(return_value=1))
    place = AsyncMock(return_value={"order": {"orderNo": "child", "status": "ACCEPTED"}})
    monkeypatch.setattr(retry.gateway, "place_order", place)
    return place


def run(coro):
    async def go():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"])
        try:
            await coro(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            async with engine.begin() as conn:
                await conn.execute(delete(LiveOrder))
            await engine.dispose()
    asyncio.run(go())


def test_concurrent_prepare_one_child_only_and_remaining_holding_clamp(monkeypatch):
    place = mocks(monkeypatch)
    async def go(factory):
        pid, uid, _ = await seed(factory)
        async with factory() as first, factory() as second:
            child = await retry.prepare_retry(first, pid)
            assert child
            assert await retry.prepare_retry(second, pid) is None  # 커밋 전 부모 행 잠금
            await first.commit()
            assert await retry.prepare_retry(second, pid) is None  # 커밋 후 부모당 자식 하나
            await second.rollback()
            row = await first.get(LiveOrder, child)
            assert row.quantity == 5 and row.retry_number == 1 and row.price == 70000
            assert row.client_order_id == f"retry:{pid.hex}"
            assert (await first.get(LiveOrder, pid)).filled_quantity == 4
            assert await retry.send_retry(first, child)
            assert not await retry.send_retry(second, child)
            place.assert_awaited_once()
            assert place.call_args.args[2] == 5 and place.call_args.kwargs["env"] == "paper"
    run(go)


@pytest.mark.parametrize("case", ["off", "stopped", "kill", "real", "buy", "market", "unknown", "requested",
    "expired", "attempts", "unconfirmed", "inferred", "open_order", "price", "holdings", "loss", "daily", "cooldown", "redis"])
def test_retry_guards_never_submit(monkeypatch, case):
    place = mocks(monkeypatch)
    overrides = {
        "off": {"quant_execution_policy": {}}, "stopped": {"quant_auto_enabled": False},
        "kill": {"risk_kill_switch": True}, "real": {"environment": "real"}, "buy": {"side": "BUY"},
        "market": {"order_type": "MARKET", "price": 0}, "unknown": {"status": "UNKNOWN"},
        "requested": {"status": "CANCEL_REQUESTED"},
        "expired": {"created_at": datetime.now(timezone.utc) - timedelta(minutes=16)}, "attempts": {"retry_number": 1},
    }
    if case == "unconfirmed":
        retry.gateway.get_order_status.side_effect = None
        retry.gateway.get_order_status.return_value = {"status": "ACCEPTED"}
    if case == "inferred":
        async def inferred(no, **kw):
            return {"orderNo": no, "status": "CANCELLED", "lookup": "holdings", "side": "SELL", "symbol": "005930",
                    "orderedQuantity": 10, "filledQuantity": 4}
        retry.gateway.get_order_status.side_effect = inferred
    if case == "open_order":
        retry.gateway.list_today_orders.return_value = [{"symbol": "005930", "status": "ACCEPTED"}]
    if case == "price":
        retry.gateway.get_balance.return_value["holdings"][0]["currentPrice"] = 72000
    if case == "holdings":
        retry.gateway.get_balance.return_value["holdings"] = []
    if case == "loss": retry.risk_guard.day_start_equity.return_value = 1100000
    if case == "daily": retry.risk_guard.orders_today.return_value = 10000
    if case == "cooldown": retry.risk_guard.acquire_order_slot.return_value = False
    if case == "redis": retry.coordination_ready.return_value = False
    async def go(factory):
        pid, _, _ = await seed(factory, **overrides.get(case, {}))
        async with factory() as db:
            assert await retry.prepare_retry(db, pid) is None
            place.assert_not_awaited()
    run(go)


@pytest.mark.parametrize("failure", ["stop", "unreachable"])
def test_send_rechecks_stop_and_unknown_does_not_create_new_child(monkeypatch, failure):
    place = mocks(monkeypatch)
    async def go(factory):
        pid, uid, _ = await seed(factory)
        async with factory() as db:
            child = await retry.prepare_retry(db, pid)
            await db.commit()
            if failure == "stop":
                async with factory() as other:
                    bs = await other.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                    bs.risk_kill_switch = True
                    await other.commit()
            else:
                place.side_effect = retry.gateway.GatewayError("down", code="GATEWAY_UNREACHABLE")
            await retry.send_retry(db, child)
            row = await db.get(LiveOrder, child)
            assert row.status == ("ERROR" if failure == "stop" else "UNKNOWN")
            assert await retry.prepare_retry(db, pid) is None
            if failure == "stop": place.assert_not_awaited()
            else: place.assert_awaited_once()
            # 열린 응답 불명 주문은 다른 시험에 남기지 않는다.
            row.status = "ERROR"
            await db.commit()
    run(go)


@pytest.mark.parametrize("enabled", [True, False])
def test_unknown_retry_reuses_identical_intent_only_while_enabled(monkeypatch, enabled):
    from app.services import auto_trade
    place = mocks(monkeypatch)
    monkeypatch.setattr(auto_trade.notification, "notify_order_filled", AsyncMock())
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_UNKNOWN_RESUBMIT_MIN", 10)
    async def go(factory):
        monkeypatch.setattr(auto_trade, "get_session_factory", lambda: factory)
        pid, uid, _ = await seed(factory)
        async with factory() as db:
            child = await retry.prepare_retry(db, pid)
            await db.commit()
            place.side_effect = retry.gateway.GatewayError("timeout", code="GATEWAY_UNREACHABLE")
            await retry.send_retry(db, child)
            initial = place.call_args
            bs = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            bs.quant_execution_policy = {"retry_enabled": enabled}
            await db.commit()
        place.side_effect = None
        place.return_value = {"duplicate": True, "order": {"orderNo": "recovered", "status": "ACCEPTED"}}
        result = await auto_trade.confirm_live_fills()
        assert result.get("resubmitted", 0) == int(enabled)
        assert place.await_count == (2 if enabled else 1)
        if enabled:
            assert place.call_args == initial
        async with factory() as db:
            assert (await db.get(LiveOrder, child)).status == ("ACCEPTED" if enabled else "UNKNOWN")
            assert len((await db.scalars(select(LiveOrder).where(LiveOrder.retry_of == pid))).all()) == 1
    run(go)
