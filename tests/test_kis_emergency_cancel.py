"""실제 정지 API·PG·취소 선점 연결. KIS 응답과 외부 알림만 합성한다."""
import asyncio
from datetime import timedelta
import os
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from test_kis_connection_probe import runtime  # noqa: F401
from test_kis_order_recovery import env, setup  # noqa: F401
from app.lib.session import get_current_user
from app.models import BrokerCancelRequest, BrokerSettings, LiveOrder
from app.routes import stocks
from app.services import auto_trade, kis_order_recovery as recovery

pytestmark = [pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="격리 PostgreSQL 필요"),
              pytest.mark.usefixtures("rebalance_db_schema")]


@pytest.fixture
def connected(env, monkeypatch):
    sessions, client, latest = env
    monkeypatch.setattr(auto_trade, "get_session_factory", lambda: sessions)
    for name in ("notify_risk_halt", "notify_auto_trade_stopped", "notify_order_filled"):
        monkeypatch.setattr(auto_trade.notification, name, AsyncMock())
    monkeypatch.setattr(auto_trade, "audit", AsyncMock())
    monkeypatch.setattr(stocks, "audit", AsyncMock())
    latest.update(status="PARTIALLY_FILLED", cancelled=False, remainingQuantity=2, cancelledQuantity=0)
    return sessions, client, latest


async def open_order(sessions, status="PARTIALLY_FILLED", side="SELL"):
    uid, pid = await setup(sessions, quant_auto_enabled=True)
    async with sessions() as db:
        parent = await db.get(LiveOrder, pid)
        parent.status, parent.side = status, side
        await db.commit()
    return uid, pid


def http_app(sessions, uid):
    app = FastAPI()
    app.include_router(stocks.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": str(uid)}

    async def session():
        async with sessions() as db:
            yield db
    app.dependency_overrides[stocks.get_pg_session] = session
    return app


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("lost", [False, True])
def test_http_halt_cancels_only_remaining_once_and_confirmation_is_separate(connected, side, lost, monkeypatch):
    sessions, client, latest = connected

    async def scenario():
        uid, pid = await open_order(sessions, side=side)
        other_uid, other_pid = await open_order(sessions)

        async def send(*args):
            async with sessions() as db:
                settings = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                assert settings.risk_kill_switch and not settings.quant_auto_enabled
                assert (await db.get(BrokerCancelRequest, pid)).quantity == 2
                assert (await db.get(LiveOrder, pid)).status == "CANCEL_REQUESTED"
            if lost:
                raise httpx.ReadTimeout("synthetic lost cancel response")
            return {"cancel_order_no": "000124"}
        client.cancel_order.side_effect = send
        async with httpx.AsyncClient(transport=httpx.ASGITransport(http_app(sessions, uid)), base_url="http://test") as http:
            first = await http.post("/api/quant/risk/kill-switch", json={"enabled": True})
            assert first.status_code == 200
            result = first.json()
            assert result["kill_switch"] and result["auto_trade_stopped"]
            assert result["cancellation"]["requested"] == int(not lost)
            assert result["cancellation"]["unknown"] == int(lost)
            assert result["cancellation"]["closed"] == 0
            repeated = (await http.post("/api/quant/risk/kill-switch", json={"enabled": True})).json()
            assert repeated["cancellation"]["requested"] == 0
            assert repeated["cancellation"]["unknown" if lost else "pending"] == 1
            client.cancel_order.assert_awaited_once_with("1234567801", "000122", "00950", 2)
            async with sessions() as db:
                parent = await db.get(LiveOrder, pid)
                assert parent.status == "CANCEL_REQUESTED" and parent.filled_quantity == 1
                assert (await db.get(LiveOrder, other_pid)).status == "PARTIALLY_FILLED"
                other = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == other_uid))
                assert other.quant_auto_enabled and not other.risk_kill_switch
                assert await db.get(BrokerCancelRequest, other_pid) is None

            latest.update(status="CANCELLED", cancelled=True, remainingQuantity=0, cancelledQuantity=2)
            original = recovery.kis_execution.direct_status
            async def own_status(parent, row):
                return await original(parent, row) if parent.id == pid else None
            monkeypatch.setattr(recovery.kis_execution, "direct_status", own_status)
            await auto_trade.confirm_live_fills(limit=1000)
            async with sessions() as db:
                parent = await db.get(LiveOrder, pid)
                assert parent.status == "CANCELLED" and parent.filled_quantity == 1
                settings = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                assert settings.risk_kill_switch and not settings.quant_auto_enabled
            cleared = await http.post("/api/quant/risk/kill-switch", json={"enabled": False})
            assert cleared.status_code == 200 and cleared.json()["cancellation"] is None
        client.place_order.assert_not_awaited()
        assert client.cancel_order.await_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["PENDING", "ACCEPTED", "PARTIALLY_FILLED", "UNKNOWN", "LOST"])
def test_automatic_loss_halt_uses_direct_cancel_with_confirmed_order_evidence(connected, status):
    sessions, client, _ = connected
    async def scenario():
        uid, pid = await open_order(sessions, status)
        async with sessions() as db:
            settings = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            await auto_trade.emergency_halt(db, settings, str(uid), "일손실 한도 초과", -3.5)
        async with sessions() as db:
            settings = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert settings.risk_kill_switch and not settings.quant_auto_enabled
            assert (await db.get(LiveOrder, pid)).status == "CANCEL_REQUESTED"
        assert auto_trade.audit.call_args.args[3]["actions"]["cancel_orders"]["requested"] == 1
        client.cancel_order.assert_awaited_once()
        client.place_order.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("case,category", [
    ("real", "skipped"), ("account_changed", "failed"), ("missing_number", "skipped"),
    ("missing_account", "skipped"), ("old_order", "failed"), ("missing_evidence", "failed"),
    ("no_remainder", "failed"), ("missing_routing", "failed"), ("outside_session", "failed"),
])
def test_unsafe_order_is_reported_without_cancelling_or_releasing_halt(connected, monkeypatch, case, category):
    sessions, client, latest = connected
    async def scenario():
        uid, pid = await open_order(sessions)
        async with sessions() as db:
            parent = await db.get(LiveOrder, pid)
            settings = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            if case == "real": parent.environment = "real"
            if case == "account_changed": settings.account_no = "8765432101"
            if case == "missing_number": parent.order_no = ""
            if case == "missing_account": parent.account_ref = ""
            if case == "old_order": parent.created_at -= timedelta(days=1)
            await db.commit()
        if case == "missing_evidence": latest["quantityEvidenceComplete"] = False
        if case == "no_remainder": latest["remainingQuantity"] = None
        if case == "missing_routing": latest["organization"] = ""
        if case == "outside_session":
            monkeypatch.setattr(recovery, "check_window", lambda day: (_ for _ in ()).throw(
                recovery.control.Rejected("OUTSIDE_WINDOW", "장외 시험")))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(http_app(sessions, uid)), base_url="http://test") as http:
            result = (await http.post("/api/quant/risk/kill-switch", json={"enabled": True})).json()
        assert result["kill_switch"] and result["cancellation"][category] == 1
        assert result["cancellation"]["requested"] == 0
        async with sessions() as db:
            settings = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert settings.risk_kill_switch and not settings.quant_auto_enabled
            assert await db.get(BrokerCancelRequest, pid) is None
        client.cancel_order.assert_not_awaited()
        client.place_order.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("terminal", ["FILLED", "CANCELLED"])
def test_fill_or_cancel_before_request_is_not_counted_as_new_cancel(connected, terminal):
    sessions, client, latest = connected
    async def scenario():
        uid, pid = await open_order(sessions)
        latest.update(status=terminal, filledQuantity=3 if terminal == "FILLED" else 1,
                      remainingQuantity=0, cancelled=terminal == "CANCELLED")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(http_app(sessions, uid)), base_url="http://test") as http:
            result = (await http.post("/api/quant/risk/kill-switch", json={"enabled": True})).json()
        assert result["cancellation"]["closed"] == 1 and result["cancellation"]["requested"] == 0
        async with sessions() as db:
            assert (await db.get(LiveOrder, pid)).status == terminal
        client.cancel_order.assert_not_awaited()
        client.place_order.assert_not_awaited()
    asyncio.run(scenario())


def test_concurrent_halts_and_manual_cancel_share_one_persistent_claim(connected):
    sessions, client, _ = connected
    async def scenario():
        uid, pid = await open_order(sessions)
        async def halt():
            async with sessions() as db:
                return await auto_trade.cancel_open_live_orders(db, uid)
        await asyncio.gather(halt(), halt(), recovery.cancel(uid, pid))
        result = await halt()
        assert result["requested"] == 0 and result["pending"] == 1
        client.cancel_order.assert_awaited_once()
        client.place_order.assert_not_awaited()
    asyncio.run(scenario())


def test_unconfirmed_order_does_not_prevent_cancelling_the_next_order(connected):
    sessions, client, _ = connected
    async def scenario():
        uid, pid = await open_order(sessions)
        async with sessions() as db:
            parent = await db.get(LiveOrder, pid)
            bad = LiveOrder(user_id=uid, account_ref=parent.account_ref, client_order_id="bad:"+str(pid),
                broker="kis-direct", environment="paper", symbol=parent.symbol, side="BUY", quantity=3,
                price=70000, status="UNKNOWN", created_at=parent.created_at-timedelta(seconds=1))
            db.add(bad)
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(http_app(sessions, uid)), base_url="http://test") as http:
            result = (await http.post("/api/quant/risk/kill-switch", json={"enabled": True})).json()
        assert result["cancellation"]["skipped"] == 1 and result["cancellation"]["requested"] == 1
        client.cancel_order.assert_awaited_once()
    asyncio.run(scenario())
