"""실제 PostgreSQL 선점/추적과 HTTP 계약. 증권사·알림은 합성 대역이다."""
import asyncio
from datetime import datetime as RealDatetime, timezone
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.models import User, BrokerSettings, LiveOrder, OrderIntent, RiskDay, BrokerPositionBaseline, Order, Portfolio
from app.routes import stocks
from app.services import manual_broker_order as manual
from app.services.brokers.kis import OrderSubmissionUnknown

pytestmark = [pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="격리 PostgreSQL 필요"),
              pytest.mark.usefixtures("rebalance_db_schema")]
SECRET = "PRIVATE-MANUAL-ORDER-SECRET"


@pytest.fixture
def runtime(monkeypatch):
    engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(manual, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(manual.control, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(manual.control.risk_guard, "_redis", lambda: AsyncMock(ping=AsyncMock(return_value=True)))
    class Clock(RealDatetime):
        @classmethod
        def now(cls, tz=None):
            now = cls.fromtimestamp(RealDatetime.now().timestamp(), tz or manual.control.KST)
            return now.replace(hour=1 if tz == timezone.utc else 10, minute=0, second=0)
    monkeypatch.setattr(manual, "datetime", Clock)
    monkeypatch.setattr(manual.control, "datetime", Clock)
    today = RealDatetime.now(manual.control.KST).date().isoformat()
    monkeypatch.setattr(manual.market_calendar, "trading_days", lambda *a: {"days": [{"date": today, "is_trading_day": True}]})
    monkeypatch.setattr(manual.pattern_view, "resolve_symbol", lambda s: s + ".KS")
    monkeypatch.setattr(manual.gateway, "is_configured", lambda: False)
    monkeypatch.setattr(manual, "live_trading_allowed", lambda: False)
    client = SimpleNamespace(paper=True,
        get_balance=AsyncMock(return_value=SimpleNamespace(cash=1000000., total_eval=1000000., holdings=[])),
        get_price=AsyncMock(return_value=SimpleNamespace(current=70000.)),
        get_buying_power=AsyncMock(return_value={"amount": 1000000., "quantity": 10}),
        place_order=AsyncMock(return_value={"rt_cd": "0", "output": {"ODNO": "000123"}, "private": SECRET}))
    monkeypatch.setattr(manual.kis_execution, "client_for", lambda row: (client,
        SimpleNamespace(paper=True, app_key=row.app_key, account_no=row.account_no)))
    monkeypatch.setattr(manual.auto_trade, "get_broker_client", lambda *a, **kw: client)
    for name in ("notify_order_placed", "notify_order_error"):
        monkeypatch.setattr(manual.auto_trade.notification, name, AsyncMock())
    yield sessions, client
    asyncio.run(engine.dispose())


async def user(sessions, **overrides):
    uid = uuid.uuid4()
    async with sessions() as db:
        db.add(User(id=uid, name="manual", email=f"{uid}@example.test", password_hash="synthetic", client_id=uid.hex))
        await db.flush()
        values = dict(broker="kis", paper=True, app_key="synthetic-"+uid.hex, app_secret="synthetic",
                      account_no="1234567801", quant_auto_enabled=False, risk_cooldown_min=0)
        db.add(BrokerSettings(user_id=uid, **{**values, **overrides}))
        await db.commit()
    return uid


def request(**overrides):
    return {**dict(request_id=uuid.uuid4(), symbol="005930.KS", side="buy", quantity=1, price=70000.), **overrides}


def account(uid):
    return manual.kis_execution.account_key("synthetic-"+uid.hex, "1234567801", "paper")


async def orders(sessions, uid):
    async with sessions() as db:
        return (await db.scalars(select(LiveOrder).where(LiveOrder.user_id == uid))).all()


def test_tracks_before_send_and_replays_after_new_session(runtime, monkeypatch):
    sessions, client = runtime
    async def scenario():
        uid = await user(sessions)
        body = request(price=69000.)
        async def send(*args):
            tracked = await orders(sessions, uid)
            assert len(tracked) == 1 and tracked[0].status == "PENDING"
            async with sessions() as db:
                intent = await db.get(OrderIntent, manual.request_key(uid, body["request_id"]))
                assert intent.status == "PENDING"
            return {"output": {"ODNO": "000123"}, "private": SECRET}
        client.place_order.side_effect = send
        first = await manual.submit(uid, **body)
        assert first["status"] == "submitted", first
        assert first["order"]["status"] == "ACCEPTED"
        assert first["order"]["price"] == 69000. and first["order"]["filled_quantity"] == 0
        again = await manual.submit(uid, **{**body, "symbol": "005930"})
        assert again["duplicate"] and again["order"] == first["order"]
        client.place_order.assert_awaited_once_with("1234567801", "005930.KS", "buy", 1, 69000.)
        assert SECRET not in json.dumps(first)
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert not row.quant_auto_enabled and row.quant_mode == "paper" and not row.quant_strategy_id
            for model in (Order, Portfolio):
                assert await db.scalar(select(func.count()).select_from(model).where(model.user_id == uid)) == 0
        assert (await orders(sessions, uid))[0].strategy_id == manual.STRATEGY
        manual.auto_trade.notification.notify_order_placed.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize("changed", [dict(symbol="000660.KS"), dict(side="sell"), dict(quantity=2), dict(price=71000.)])
def test_same_request_id_cannot_change_payload(runtime, changed):
    sessions, client = runtime
    async def scenario():
        uid = await user(sessions)
        body = request()
        assert (await manual.submit(uid, **body))["status"] == "submitted"
        result = await manual.submit(uid, **{**body, **changed})
        assert result["code"] == "INPUT_CONFLICT" and "order" not in result
        assert client.place_order.await_count == 1
    asyncio.run(scenario())


def test_concurrency_unknown_and_other_request_are_not_resent(runtime, caplog):
    sessions, client = runtime
    async def scenario():
        uid = await user(sessions)
        body = request()
        async def lost(*args):
            await asyncio.sleep(.05)
            raise OrderSubmissionUnknown(SECRET)
        client.place_order.side_effect = lost
        results = await asyncio.gather(*(manual.submit(uid, **body) for _ in range(3)))
        assert client.place_order.await_count == 1
        assert any(r["status"] == "unknown" for r in results), results
        repeat = await manual.submit(uid, **body)
        assert repeat["duplicate"] and repeat["status"] == "unknown"
        assert repeat["order"]["status"] == "UNKNOWN"
        other = await manual.submit(uid, **request())
        assert other["code"] == "OPEN_ORDER"
        assert client.place_order.await_count == 1
        assert SECRET not in caplog.text and SECRET not in json.dumps(results)
    asyncio.run(scenario())


@pytest.mark.parametrize("case,code", [
    ("kill", "KILL_SWITCH"), ("real", "PAPER_ONLY"), ("gateway", "PAPER_ONLY"),
    ("holiday", "OUTSIDE_WINDOW"), ("calendar_partial", "OUTSIDE_WINDOW"),
    ("balance_timeout", "BALANCE_TIMEOUT"), ("balance_invalid", "BALANCE_UNAVAILABLE"),
    ("balance_auth", "BROKER_AUTH_REJECTED"), ("balance_rate", "BALANCE_RATE_LIMIT"),
    ("power_error", "BUYING_POWER_UNAVAILABLE"), ("power_invalid", "BUYING_POWER_UNAVAILABLE"),
    ("power_quantity", "BUYING_POWER_LIMIT"), ("cash", "CASH_LIMIT"), ("fees", "CASH_LIMIT"),
    ("position", "POSITION_LIMIT"), ("loss", "LOSS_LIMIT"), ("count", "ORDER_LIMIT"),
    ("redis", "CACHE_UNAVAILABLE"), ("db", "EXECUTION_STORE_UNAVAILABLE"),
    ("open", "OPEN_ORDER"), ("foreign_sell", "OWNERSHIP_UNCONFIRMED"),
    ("drift", "OWNERSHIP_UNCONFIRMED"), ("cooldown", "COOLDOWN"),
])
def test_unconfirmed_or_unsafe_state_never_sends(runtime, monkeypatch, caplog, case, code):
    sessions, client = runtime
    async def scenario():
        uid = await user(sessions, **({"risk_kill_switch": True} if case == "kill" else
                                    {"risk_max_position_pct": 1} if case == "position" else
                                    {"risk_max_orders_per_day": 1} if case == "count" else
                                    {"risk_cooldown_min": 30} if case == "cooldown" else {}))
        body = request(side="sell" if case == "foreign_sell" else "buy")
        if case == "real": monkeypatch.setattr(manual, "live_trading_allowed", lambda: True)
        if case == "gateway": monkeypatch.setattr(manual.gateway, "is_configured", lambda: True)
        if case.startswith("calendar") or case == "holiday":
            monkeypatch.setattr(manual.market_calendar, "trading_days", lambda *a: {"days": [], "partial": True})
        if case == "balance_timeout": client.get_balance.side_effect = httpx.ReadTimeout(SECRET)
        if case == "balance_invalid": client.get_balance.return_value.cash = float("nan")
        if case == "balance_auth":
            client.get_balance.side_effect = httpx.HTTPStatusError(SECRET, request=httpx.Request("GET", "https://example.test"), response=httpx.Response(403))
        if case == "balance_rate":
            from app.services.brokers.quote_feedback import BrokerBalanceError
            client.get_balance.side_effect = BrokerBalanceError("EGW00201")
        if case == "power_error": client.get_buying_power.side_effect = RuntimeError(SECRET)
        if case == "power_invalid": client.get_buying_power.return_value = {"amount": float("nan"), "quantity": 1}
        if case == "power_quantity": client.get_buying_power.return_value["quantity"] = 0
        if case == "cash": client.get_buying_power.return_value["amount"] = 60000.
        if case == "fees": client.get_buying_power.return_value["amount"] = 70000.
        if case == "redis": monkeypatch.setattr(manual.control.risk_guard, "_redis", lambda: None)
        if case in ("foreign_sell", "drift"):
            client.get_balance.return_value.holdings = [SimpleNamespace(symbol="005930", quantity=3, avg_price=70000., eval_amount=210000.)]
        async with sessions() as db:
            if case == "loss": db.add(RiskDay(account_ref=account(uid), day=RealDatetime.now(manual.control.KST).date(), equity=2000000.))
            if case == "open": db.add(LiveOrder(user_id=uid, account_ref=account(uid), symbol="000660.KS", side="BUY", quantity=1, price=100., status="UNKNOWN", client_order_id=uuid.uuid4().hex))
            if case == "drift": db.add(BrokerPositionBaseline(account_ref=account(uid), symbol="005930.KS", quantity=2))
            if case in ("count", "cooldown"):
                db.add(OrderIntent(intent_id=uuid.uuid4().hex, user_id=uid, account_ref=account(uid), book="KIS",
                    strategy_id="other", strategy_version=1, symbol="005930.KS", side="BUY", source="test",
                    input_hash="test", status="filled", result={}))
            await db.commit()
        if case == "db": monkeypatch.setattr(manual, "get_session_factory", lambda: (_ for _ in ()).throw(RuntimeError(SECRET)))
        result = await manual.submit(uid, **body)
        assert result["status"] == "skipped" and result["code"] == code, result
        client.place_order.assert_not_awaited()
        manual.auto_trade.notification.notify_order_placed.assert_not_awaited()
        assert SECRET not in json.dumps(result) and SECRET not in caplog.text
    asyncio.run(scenario())


def test_only_own_confirmed_manual_holdings_can_be_sold(runtime):
    sessions, client = runtime
    async def scenario():
        uid = await user(sessions)
        buy = request(quantity=2)
        first = await manual.submit(uid, **buy)
        async with sessions() as db:
            row = await db.scalar(select(LiveOrder).where(LiveOrder.user_id == uid))
            row.status, row.filled_quantity, row.avg_filled_price = "FILLED", 2, 70000.
            await db.commit()
        client.get_balance.return_value.holdings = [SimpleNamespace(symbol="005930", quantity=2, avg_price=70000., eval_amount=140000.)]
        view = await manual.lookup(uid, buy["request_id"])
        assert view["status"] == "filled" and view["order"]["filled_quantity"] == 2
        too_many = await manual.submit(uid, **request(side="sell", quantity=3))
        assert too_many["code"] == "OWNERSHIP_UNCONFIRMED"
        sold = await manual.submit(uid, **request(side="sell", quantity=2))
        assert sold["status"] == "submitted", sold
        assert client.place_order.await_count == 2
        assert await manual.lookup(uuid.uuid4(), buy["request_id"]) is None
    asyncio.run(scenario())


def test_http_request_id_validation_and_status_contract(runtime, monkeypatch):
    sessions, broker = runtime
    async def scenario():
        uid = await user(sessions)
        app = FastAPI()
        app.include_router(stocks.router)
        app.dependency_overrides[get_current_user] = lambda: {"id": str(uid)}
        app.dependency_overrides[get_pg_session] = lambda: None
        setup = AsyncMock(return_value=(broker, "kis", "1234567801"))
        monkeypatch.setattr(stocks, "_get_broker_client_and_account", setup)
        body = {**request(), "request_id": str(uuid.uuid4())}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
            no_id = {k: v for k, v in body.items() if k != "request_id"}
            assert (await http.post("/api/broker/order", json=no_id)).status_code == 422
            for change in ({"side": "BUY"}, {"quantity": True}, {"quantity": 0}, {"price": True}, {"price": -1}, {"symbol": "AAPL"}):
                assert (await http.post("/api/broker/order", json={**body, **change})).status_code == 422
            broker.place_order.assert_not_awaited()
            result = await http.post("/api/broker/order", json=body)
            assert result.status_code == 200 and result.json()["order_submitted"] is True, result.text
            assert result.json()["result"]["order"]["status"] == "ACCEPTED"
            view = await http.get("/api/broker/order/" + body["request_id"])
            assert view.status_code == 200 and view.json()["order"]["filled_quantity"] == 0
            assert SECRET not in view.text and "1234567801" not in view.text
            app.dependency_overrides[get_current_user] = lambda: {"id": str(uuid.uuid4())}
            assert (await http.get("/api/broker/order/" + body["request_id"])).status_code == 404
            app.dependency_overrides.pop(get_current_user)
            assert (await http.post("/api/broker/order", json=body)).status_code == 401
            assert (await http.get("/api/broker/order/" + body["request_id"])).status_code == 401
    asyncio.run(scenario())


def test_changed_account_cannot_reuse_previous_request_id(runtime):
    sessions, broker = runtime
    async def scenario():
        uid = await user(sessions)
        body = request()
        assert (await manual.submit(uid, **body))["status"] == "submitted"
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            row.account_no = "8765432101"
            await db.commit()
        result = await manual.submit(uid, **body)
        assert result["code"] == "INPUT_CONFLICT"
        assert broker.place_order.await_count == 1
    asyncio.run(scenario())


def test_stop_changed_after_reservation_blocks_actual_submission(runtime, monkeypatch):
    sessions, broker = runtime
    async def scenario():
        uid = await user(sessions)
        calls = 0
        async def ping():
            nonlocal calls
            calls += 1
            if calls == 2:
                async with sessions() as db:
                    row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                    row.risk_kill_switch = True
                    await db.commit()
            return True
        monkeypatch.setattr(manual.control.risk_guard, "_redis", lambda: SimpleNamespace(ping=ping))
        result = await manual.submit(uid, **request())
        assert result["code"] in ("KILL_SWITCH", "SETTINGS_CHANGED"), result
        broker.place_order.assert_not_awaited()
        assert not await orders(sessions, uid)
    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["submitted", "error", "unknown"])
def test_notification_failure_never_changes_or_replays_order(runtime, caplog, outcome):
    sessions, broker = runtime
    async def scenario():
        uid = await user(sessions)
        body = request()
        if outcome == "error": broker.place_order.side_effect = RuntimeError(SECRET)
        if outcome == "unknown": broker.place_order.side_effect = OrderSubmissionUnknown(SECRET)
        for name in ("notify_order_placed", "notify_order_error"):
            getattr(manual.auto_trade.notification, name).side_effect = RuntimeError(SECRET)
        result = await manual.submit(uid, **body)
        assert result["status"] == outcome, result
        assert result["order"]["status"] == {"submitted": "ACCEPTED", "error": "ERROR", "unknown": "UNKNOWN"}[outcome]
        repeat = await manual.submit(uid, **body)
        assert repeat["duplicate"] and repeat["status"] == outcome
        assert broker.place_order.await_count == 1
        assert SECRET not in caplog.text and SECRET not in json.dumps([result, repeat])
    asyncio.run(scenario())


def test_pending_intent_without_order_survives_restart_without_resend(runtime):
    sessions, broker = runtime
    async def scenario():
        uid = await user(sessions)
        body = request()
        key = manual.request_key(uid, body["request_id"])
        async with sessions() as db:
            db.add(OrderIntent(intent_id=key, user_id=uid, account_ref=account(uid), book="KIS",
                strategy_id=manual.STRATEGY, strategy_version=manual.VERSION, symbol=body["symbol"], side="BUY",
                source="manual_broker", input_hash=manual.control.digest([account(uid), body["symbol"], "buy", 1, 70000.]),
                status="PENDING", result={}))
            await db.commit()
        result = await manual.submit(uid, **body)
        assert result["duplicate"] and result["status"] == "unknown"
        assert (await manual.lookup(uid, body["request_id"]))["status"] == "unknown"
        broker.place_order.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["intent", "order"])
def test_persistence_failure_never_reaches_broker(runtime, monkeypatch, stage):
    from sqlalchemy.ext.asyncio import AsyncSession
    sessions, broker = runtime
    async def scenario():
        uid = await user(sessions)
        body = request()
        commit = AsyncSession.commit
        async def failing_commit(db):
            model = OrderIntent if stage == "intent" else LiveOrder
            if any(isinstance(row, model) for row in db.new):
                raise RuntimeError(SECRET)
            return await commit(db)
        monkeypatch.setattr(AsyncSession, "commit", failing_commit)
        result = await manual.submit(uid, **body)
        assert result["status"] == ("skipped" if stage == "intent" else "unknown"), result
        broker.place_order.assert_not_awaited()
        assert not await orders(sessions, uid)
    asyncio.run(scenario())


def test_http_unknown_is_202_and_not_success(runtime, monkeypatch):
    sessions, broker = runtime
    async def scenario():
        uid = await user(sessions)
        app = FastAPI()
        app.include_router(stocks.router)
        app.dependency_overrides[get_current_user] = lambda: {"id": str(uid)}
        app.dependency_overrides[get_pg_session] = lambda: None
        monkeypatch.setattr(stocks, "_get_broker_client_and_account", AsyncMock(return_value=(broker, "kis", "1234567801")))
        broker.place_order.side_effect = OrderSubmissionUnknown(SECRET)
        body = {**request(), "request_id": str(uuid.uuid4())}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
            response = await http.post("/api/broker/order", json=body)
            assert response.status_code == 202 and response.json()["ok"] is False
            assert response.json()["order_submitted"] is None
            assert response.json()["result"]["order"]["status"] == "UNKNOWN"
    asyncio.run(scenario())
