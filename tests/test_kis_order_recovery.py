"""격리 PostgreSQL의 부분체결·취소·재주문·경합. 외부 증권사만 합성한다."""
import asyncio
from datetime import timedelta
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func

from test_kis_connection_probe import runtime, user  # noqa: F401
from app.models import BrokerCancelRequest, BrokerPositionBaseline, BrokerSettings, LiveOrder
from app.services import kis_order_recovery as recovery
from app.services.brokers.kis import OrderSubmissionUnknown

pytestmark = [pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="격리 PostgreSQL 필요"),
              pytest.mark.usefixtures("rebalance_db_schema")]


@pytest.fixture
def env(runtime, monkeypatch):
    sessions, client = runtime
    monkeypatch.setattr(recovery, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(recovery, "datetime", recovery.control.datetime)
    monkeypatch.setattr(recovery, "pause", AsyncMock())
    monkeypatch.setattr(recovery, "live_trading_allowed", lambda: False)
    monkeypatch.setattr(recovery.etf_execution, "describe", lambda symbol: {"is_etf": False})
    client.cancel_order = AsyncMock(return_value={"cancel_order_no": "000124"})
    latest = {"status": "CANCELLED", "orderedQuantity": 3, "filledQuantity": 1, "avgFilledPrice": 70000,
              "cancelled": True, "remainingQuantity": 0, "cancelledQuantity": 2, "organization": "00950",
              "otherOpenOrders": 0, "quantityEvidenceComplete": True}
    async def status(parent, row):
        return {**latest, "account_key": parent.account_ref, "orderNo": parent.order_no}
    monkeypatch.setattr(recovery.kis_execution, "direct_status", AsyncMock(side_effect=status))
    recovery.kis_execution.account_snapshot.return_value = {
        "cash": 1000000, "equity": 1350000, "holdings": {"005930.KS": {"quantity": 5, "value": 350000}}}
    return sessions, client, latest


async def setup(sessions, **settings):
    uid = await user(sessions, **settings)
    ref = recovery.kis_execution.account_key("synthetic-"+uid.hex, "1234567801", "paper")
    now = recovery.datetime.now(recovery.control.KST)
    async with sessions() as db:
        db.add(BrokerPositionBaseline(account_ref=ref, symbol="005930.KS", quantity=1))
        db.add(LiveOrder(user_id=uid, account_ref=ref, client_order_id="buy:"+uid.hex,
            strategy_id="strategy", strategy_version=1, broker="kis-direct", environment="paper",
            symbol="005930.KS", side="BUY", quantity=5, filled_quantity=5, avg_filled_price=70000,
            price=70000, status="FILLED", created_at=now-timedelta(days=1)))
        parent = LiveOrder(user_id=uid, account_ref=ref, client_order_id="sell:"+uid.hex,
            strategy_id="strategy", strategy_version=1, broker="kis-direct", environment="paper",
            symbol="005930.KS", side="SELL", quantity=3, filled_quantity=1, avg_filled_price=70000,
            price=70000, status="CANCELLED", order_no="000122", created_at=now-timedelta(minutes=2),
            raw=json.dumps({"account_key": ref, "organization": "00950"}))
        db.add(parent)
        await db.commit()
        return uid, parent.id


def test_confirmed_partial_sell_retries_only_remaining_once_and_keeps_settings(env):
    sessions, client, latest = env
    async def scenario():
        uid, pid = await setup(sessions)
        result = await recovery.retry(uid, pid)
        assert result["status"] == "submitted", result
        again = await recovery.retry(uid, pid)
        assert again["duplicate"]
        assert client.place_order.await_count == 1
        assert client.place_order.call_args.args[2:] == ("sell", 2, 70000)
        async with sessions() as db:
            child = await db.scalar(select(LiveOrder).where(LiveOrder.retry_of == pid))
            assert child.retry_number == 1 and child.strategy_id == "strategy"
            assert child.quantity == 2 and child.status == "ACCEPTED"
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert not row.quant_auto_enabled and not (row.quant_execution_policy or {}).get("retry_enabled", False)
    asyncio.run(scenario())


@pytest.mark.parametrize("case,code", [("not_cancelled", "CANCEL_UNCONFIRMED"), ("remaining", "CANCEL_UNCONFIRMED"),
    ("cancel_qty", "CANCEL_UNCONFIRMED"), ("overfill", "ORDER_UNCONFIRMED"), ("regression", "ORDER_UNCONFIRMED"),
    ("kill", "KILL_SWITCH"), ("real", "PAPER_ONLY"), ("automatic_off", "DISABLED"),
    ("expired", "RETRY_EXPIRED"), ("limit", "RETRY_LIMIT"), ("price", "PRICE_DEVIATION"),
    ("ownership", "OWNERSHIP_UNCONFIRMED"), ("external_open", "OPEN_ORDER"),
    ("other_user", "ORDER_NOT_FOUND"), ("wrong_account", "SETTINGS_CHANGED"), ("buy", "UNSUPPORTED_ORDER"),
    ("orders_limit", "ORDER_LIMIT"), ("cooldown", "COOLDOWN"), ("missing_evidence", "ORDER_UNCONFIRMED")])
def test_unsafe_retry_never_sends(env, case, code):
    sessions, client, latest = env
    async def scenario():
        uid, pid = await setup(sessions)
        async with sessions() as db:
            parent = await db.get(LiveOrder, pid)
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            if case == "not_cancelled": latest.update(status="ACCEPTED", cancelled=False)
            if case == "remaining": latest["remainingQuantity"] = 1
            if case == "cancel_qty": latest["cancelledQuantity"] = 1
            if case == "overfill": latest["filledQuantity"] = 4
            if case == "missing_evidence": latest["quantityEvidenceComplete"] = False
            if case == "regression": latest["filledQuantity"] = 0
            if case == "kill": row.risk_kill_switch = True
            if case == "real": client.paper = False
            if case == "expired": parent.created_at -= timedelta(hours=1)
            if case == "limit": parent.retry_number = 1
            if case == "price": client.get_price.return_value = SimpleNamespace(current=72000)
            if case == "ownership": recovery.kis_execution.account_snapshot.return_value["holdings"]["005930.KS"]["quantity"] = 6
            if case == "external_open": latest["otherOpenOrders"] = 1
            if case == "wrong_account": row.account_no = "9999999901"
            if case == "buy": parent.side = "BUY"
            if case == "orders_limit": row.risk_max_orders_per_day = 1
            if case == "cooldown":
                from app.models import OrderIntent
                row.risk_cooldown_min = 30
                db.add(OrderIntent(intent_id="1"*64, user_id=uid, account_ref=parent.account_ref, book="KIS",
                    strategy_id="strategy", strategy_version=1, symbol=parent.symbol, side="SELL", source="test",
                    input_hash="2"*64, status="submitted", result={}, created_at=recovery.datetime.now(recovery.control.KST)))
            await db.commit()
        if case == "other_user": uid = await user(sessions)
        result = await recovery.retry(uid, pid, automatic=case == "automatic_off")
        assert result["code"] == code, result
        client.place_order.assert_not_awaited()
    asyncio.run(scenario())


def test_auto_retry_requires_opt_in_current_strategy_and_preserves_single_child(env):
    sessions, client, latest = env
    async def scenario():
        uid, pid = await setup(sessions, quant_auto_enabled=True, quant_mode="live", quant_strategy_id="strategy",
            quant_strategy_version=1, quant_execution_policy={"retry_enabled": True})
        result = await recovery.retry_cancelled_orders()
        assert result["submitted"] == 1, result
        second = await recovery.retry_cancelled_orders()
        assert second["submitted"] == 0
        assert client.place_order.await_count == 1
    asyncio.run(scenario())


def test_response_loss_and_concurrent_retry_never_resends(env):
    sessions, client, latest = env
    async def scenario():
        uid, pid = await setup(sessions)
        client.place_order.side_effect = OrderSubmissionUnknown("synthetic lost response")
        await asyncio.gather(recovery.retry(uid, pid), recovery.retry(uid, pid))
        again = await recovery.retry(uid, pid)
        assert again["duplicate"] and again["status"] == "unknown", again
        assert client.place_order.await_count == 1
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(LiveOrder).where(LiveOrder.retry_of == pid)) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("lost", [False, True])
def test_cancel_persists_before_send_and_never_treats_acceptance_as_confirmation(env, lost):
    sessions, client, latest = env
    async def scenario():
        uid, pid = await setup(sessions, risk_kill_switch=True)
        latest.update(status="PARTIALLY_FILLED", cancelled=False, remainingQuantity=2, cancelledQuantity=0)
        async def send(*args):
            async with sessions() as db:
                assert (await db.get(BrokerCancelRequest, pid)).status == "UNKNOWN"
                assert (await db.get(LiveOrder, pid)).status == "CANCEL_REQUESTED"
            if lost: raise OrderSubmissionUnknown("synthetic")
            return {"cancel_order_no": "000124"}
        client.cancel_order.side_effect = send
        first = await recovery.cancel(uid, pid)
        assert first["status"] == ("UNKNOWN" if lost else "ACCEPTED"), first
        again = await recovery.cancel(uid, pid)
        assert again["duplicate"] and client.cancel_order.await_count == 1
        async with sessions() as db:
            assert (await db.get(LiveOrder, pid)).status == "CANCEL_REQUESTED"
    asyncio.run(scenario())


def test_cancel_without_routing_or_remainder_never_sends(env):
    sessions, client, latest = env
    async def scenario():
        uid, pid = await setup(sessions)
        latest.update(status="ACCEPTED", cancelled=False, remainingQuantity=None, organization="")
        result = await recovery.cancel(uid, pid)
        assert result["code"] == "CANCEL_UNCONFIRMED", result
        client.cancel_order.assert_not_awaited()
    asyncio.run(scenario())


def test_http_actions_authenticate_and_cannot_target_another_user(env):
    from fastapi import FastAPI
    import httpx
    from app.lib.session import get_current_user
    from app.routes.kis_monitor import router
    sessions, client, latest = env
    async def scenario():
        uid, pid = await setup(sessions)
        app = FastAPI()
        app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
            assert (await http.post(f"/api/quant/kis/orders/{pid}/retry")).status_code == 401
            outsider = await user(sessions)
            app.dependency_overrides[get_current_user] = lambda: {"id": str(outsider)}
            for action in ("cancel", "retry"):
                response = await http.post(f"/api/quant/kis/orders/{pid}/{action}")
                assert response.json()["code"] == "ORDER_NOT_FOUND"
            app.dependency_overrides[get_current_user] = lambda: {"id": str(uid)}
            response = await http.post(f"/api/quant/kis/orders/{pid}/retry")
            assert response.status_code == 200 and response.json()["status"] == "submitted", response.text
        assert client.place_order.await_count == 1
        client.cancel_order.assert_not_awaited()
    asyncio.run(scenario())


def test_settings_change_after_reservation_blocks_retry(env, monkeypatch):
    sessions, client, latest = env
    async def scenario():
        uid, pid = await setup(sessions, quant_auto_enabled=True, quant_mode="live", quant_strategy_id="strategy",
            quant_strategy_version=1, quant_execution_policy={"retry_enabled": True})
        calls = 0
        async def check():
            nonlocal calls
            calls += 1
            if calls == 2:
                async with sessions() as db:
                    row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                    row.quant_auto_enabled = False
                    await db.commit()
        monkeypatch.setattr(recovery.control, "coordination_ready", check)
        result = await recovery.retry(uid, pid, automatic=True)
        assert result["code"] == "SETTINGS_CHANGED", result
        client.place_order.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize('hour,minute,allowed', [(8,59,False),(9,0,True),(15,20,True),(15,29,True),(15,30,False)])
def test_recovery_uses_regular_session_boundary(env, monkeypatch, hour, minute, allowed):
    from datetime import datetime as Clock
    class At(Clock):
        @classmethod
        def now(cls,tz=None):
            return cls(2026,11,2,hour,minute,tzinfo=recovery.control.KST)
    monkeypatch.setattr(recovery,'datetime',At)
    monkeypatch.setattr(recovery.market_calendar,'trading_days',lambda *args:{'days':[{'date':'2026-11-02','is_trading_day':True}]})
    if allowed:
        recovery.check_window(At.now().date())
    else:
        with pytest.raises(recovery.control.Rejected): recovery.check_window(At.now().date())
