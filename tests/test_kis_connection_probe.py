"""전략 신호 없는 연결 점검의 1주·모의·한도·영속 중복 경계. 증권사는 합성이다."""
import asyncio
from datetime import datetime as RealDatetime, timezone
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.models import User, BrokerSettings, LiveOrder, OrderIntent, BrokerPositionBaseline, RiskDay
from app.services import kis_connection_probe as probe

pytestmark = [pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="격리 PostgreSQL 필요"),
              pytest.mark.usefixtures("rebalance_db_schema")]


@pytest.fixture
def runtime(monkeypatch):
    engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(probe, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(probe.control, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(probe.control, "coordination_ready", AsyncMock())
    # 장중 시각만 고정한다. 날짜는 DB의 오늘 주문 집계와 같게 유지한다.
    class Clock(RealDatetime):
        @classmethod
        def now(cls, tz=None):
            current = cls.fromtimestamp(RealDatetime.now().timestamp(), tz or probe.control.KST)
            return current.replace(hour=1 if tz == timezone.utc else 10, minute=0, second=0)
    monkeypatch.setattr(probe, "datetime", Clock)
    monkeypatch.setattr(probe.control, "datetime", Clock)
    today = RealDatetime.now(probe.control.KST).date().isoformat()
    monkeypatch.setattr(probe.market_calendar, "trading_days", lambda *a: {"days": [{"date": today, "is_trading_day": True}]})
    monkeypatch.setattr(probe.gateway, "is_configured", lambda: False)
    monkeypatch.setattr(probe, "live_trading_allowed", lambda: False)
    client = SimpleNamespace(paper=True,
        get_price=AsyncMock(return_value=SimpleNamespace(current=70000)),
        get_buying_power=AsyncMock(return_value={"amount": 1000000, "quantity": 10}),
        place_order=AsyncMock(return_value={"output": {"ODNO": "000123"}}))
    monkeypatch.setattr(probe.kis_execution, "client_for", lambda row: (client,
        SimpleNamespace(paper=True, app_key=row.app_key, account_no=row.account_no)))
    monkeypatch.setattr(probe.kis_execution, "account_snapshot", AsyncMock(return_value={
        "cash": 1000000, "equity": 1000000, "holdings": {}}))
    monkeypatch.setattr(probe.auto_trade, "get_broker_client", lambda *a, **kw: client)
    for name in ("notify_order_placed", "notify_order_error"):
        monkeypatch.setattr(probe.auto_trade.notification, name, AsyncMock())
    yield sessions, client
    asyncio.run(engine.dispose())


async def user(sessions, **overrides):
    uid = uuid.uuid4()
    async with sessions() as db:
        db.add(User(id=uid, name="probe", email=f"{uid}@example.com", password_hash="synthetic", client_id=uid.hex))
        await db.flush()
        values = {"broker": "kis", "paper": True, "app_key": "synthetic-" + uid.hex, "app_secret": "synthetic",
                  "account_no": "1234567801", "quant_auto_enabled": False, "risk_cooldown_min": 0}
        db.add(BrokerSettings(user_id=uid, **{**values, **overrides}))
        await db.commit()
    return uid


def test_dry_run_leaves_no_decision_order_or_baseline(runtime):
    sessions, client = runtime
    async def scenario():
        uid = await user(sessions)
        result = await probe.run(uid, max_price=70000)
        assert result["status"] == "DRY_RUN" and result["quantity"] == 1
        async with sessions() as db:
            for model in (LiveOrder, OrderIntent, BrokerPositionBaseline, RiskDay):
                assert await db.scalar(select(func.count()).select_from(model)) == 0
        client.place_order.assert_not_awaited()
    asyncio.run(scenario())


def test_one_share_is_tracked_separately_and_replay_never_resends(runtime):
    sessions, client = runtime
    async def scenario():
        uid = await user(sessions)
        first = await probe.run(uid, max_price=70000, execute=True)
        assert first["status"] == "submitted", first
        second = await probe.run(uid, max_price=70000, execute=True)
        assert second["duplicate"]
        changed = await probe.run(uid, max_price=71000, execute=True)
        assert changed["code"] == "INPUT_CONFLICT"
        assert client.place_order.await_count == 1
        assert client.place_order.call_args.args[2:] == ("buy", 1, 70000)
        async with sessions() as db:
            order = await db.scalar(select(LiveOrder).where(LiveOrder.user_id == uid))
            assert order.strategy_id == "kis_connection_check" and order.environment == "paper"
            assert order.status == "ACCEPTED" and order.order_no == "000123"
            settings = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert not settings.quant_auto_enabled and settings.quant_mode == "paper" and settings.quant_strategy_id == ""
    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["auto", "kill", "real", "gateway", "outside", "holiday", "calendar_partial",
    "risk_policy", "price_cap", "cash", "buying_power", "budget", "loss", "open_order", "three_orders", "unknown"])
def test_invalid_conditions_never_send(runtime, monkeypatch, case):
    sessions, client = runtime
    async def scenario():
        changes = {"quant_auto_enabled": True} if case == "auto" else {"risk_kill_switch": True} if case == "kill" else {}
        if case == "budget": changes["quant_per_trade_budget"] = 60000
        if case == "risk_policy": changes["quant_execution_policy"] = {"size_kind": "risk_pct"}
        uid = await user(sessions, **changes)
        ref = probe.kis_execution.account_key("synthetic-" + uid.hex, "1234567801", "paper")
        if case == "real": monkeypatch.setattr(probe, "live_trading_allowed", lambda: True)
        if case == "gateway": monkeypatch.setattr(probe.gateway, "is_configured", lambda: True)
        if case in ("holiday", "calendar_partial"):
            monkeypatch.setattr(probe.market_calendar, "trading_days", lambda *a: {"days": [], "partial": case == "calendar_partial"})
        if case == "outside":
            monkeypatch.setattr(probe.datetime, "now", classmethod(lambda cls, tz=None: RealDatetime.now(probe.control.KST).replace(hour=16)))
        if case == "cash": client.get_buying_power.return_value = {"amount": 60000, "quantity": 10}
        if case == "buying_power": client.get_buying_power.return_value = {"amount": 1000000, "quantity": 0}
        if case == "loss":
            async with sessions() as db:
                db.add(RiskDay(account_ref=ref, day=RealDatetime.now(probe.control.KST).date(), equity=2000000))
                await db.commit()
        if case in ("open_order", "three_orders"):
            async with sessions() as db:
                for _ in range(3 if case == "three_orders" else 1):
                    db.add(LiveOrder(user_id=uid, account_ref=ref, client_order_id=uuid.uuid4().hex,
                        symbol=probe.SYMBOL, side="BUY", quantity=1, price=70000,
                        status="ERROR" if case == "three_orders" else "ACCEPTED"))
                await db.commit()
        if case == "unknown":
            async with sessions() as db:
                db.add(OrderIntent(intent_id="x"*64, user_id=uid, account_ref=ref, book="KIS", strategy_id="other",
                    strategy_version=1, symbol=probe.SYMBOL, side="BUY", source="test", input_hash="x", status="unknown", result={}))
                await db.commit()
        expected = {"auto": "PROBE_DISABLED", "kill": "PROBE_DISABLED", "real": "PAPER_ONLY",
            "gateway": "PAPER_ONLY", "outside": "OUTSIDE_WINDOW", "holiday": "OUTSIDE_WINDOW",
            "calendar_partial": "OUTSIDE_WINDOW", "risk_policy": "UNSUPPORTED_POLICY", "price_cap": "PRICE_CAP",
            "cash": "ZERO_QUANTITY", "buying_power": "ZERO_QUANTITY", "budget": "ZERO_QUANTITY",
            "loss": "LOSS_LIMIT", "open_order": "OPEN_ORDER", "three_orders": "PROBE_DAILY_LIMIT", "unknown": "OPEN_ORDER"}
        try:
            result = await probe.run(uid, max_price=60000 if case == "price_cap" else 70000, execute=True)
            assert result["status"] == "skipped", result
            assert result["code"] == expected[case], result
        except probe.control.Rejected as exc:
            assert exc.code == expected[case]
        client.place_order.assert_not_awaited()
    asyncio.run(scenario())


def test_concurrent_invocations_and_unknown_response_never_resend(runtime):
    from app.services.brokers.kis import OrderSubmissionUnknown
    sessions, client = runtime
    async def scenario():
        uid = await user(sessions)
        async def response_lost(*args):
            await asyncio.sleep(.05)
            raise OrderSubmissionUnknown("synthetic timeout")
        client.place_order.side_effect = response_lost
        results = await asyncio.gather(*(probe.run(uid, max_price=70000, execute=True) for _ in range(3)))
        assert client.place_order.await_count == 1
        assert any(r["status"] == "unknown" for r in results)
        repeat = await probe.run(uid, max_price=70000, execute=True)
        assert repeat["status"] == "unknown" and repeat["duplicate"]
        assert client.place_order.await_count == 1
    asyncio.run(scenario())
