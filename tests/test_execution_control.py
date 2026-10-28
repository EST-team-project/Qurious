"""실제 PostgreSQL의 동시 선점·재시작·귀속·알림 경계. 외부 주문과 발송은 가짜다."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.models import (User, BrokerSettings, OrderIntent, RiskDay, BrokerPositionBaseline,
                        LiveOrder, ExecutionRun, NotificationLog)
from app.services import execution_control as control, execution_runs, live_ownership, notification, kis_execution

pytestmark = [pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PostgreSQL 필요"),
              pytest.mark.usefixtures("rebalance_db_schema")]


@pytest.fixture
def runtime(monkeypatch):
    engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(control, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(execution_runs, "get_session_factory", lambda: sessions)
    from app.database import postgres
    monkeypatch.setattr(postgres, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(control.risk_guard, "_redis", lambda: AsyncMock(ping=AsyncMock(return_value=True)))
    yield sessions
    asyncio.run(engine.dispose())


async def user(sessions, **settings):
    uid = uuid.uuid4()
    async with sessions() as db:
        db.add(User(id=uid, name="test", email=f"{uid}@example.test", password_hash="test", client_id=uid.hex))
        await db.flush()
        db.add(BrokerSettings(user_id=uid, quant_auto_enabled=True, risk_kill_switch=False,
                              risk_max_position_pct=100, risk_cooldown_min=0, **settings))
        await db.commit()
    return uid


def intent(uid):
    return control.Intent(uid, control.digest([str(uid), "paper"]), "QUANT", "ma", 1,
                          "005930.KS", "BUY", "2026-10-27", "scheduled", "same-input")


async def prepare(db):
    return {"cash": 1000000.0, "equity": 1000000.0, "price": 10000.0,
            "checked_at": datetime.now(timezone.utc), "db": db}


def test_concurrent_repeat_and_changed_source_share_one_intent(runtime):
    async def scenario():
        uid = await user(runtime)
        item = intent(uid)
        async def send(*args):
            await asyncio.sleep(.05)
            return {"status": "submitted", "quantity": 1}
        sender = AsyncMock(side_effect=send)
        results = await asyncio.gather(*(control.execute(item, 1, prepare, sender) for _ in range(3)))
        assert sender.await_count == 1
        assert sum(r["status"] == "submitted" for r in results) == 1
        again = await control.execute(replace(item, source="immediate"), 1, prepare, sender)
        assert again["duplicate"] and sender.await_count == 1
        conflict = await control.execute(replace(item, input_hash="changed"), 1, prepare, sender)
        assert conflict["code"] == "INPUT_CONFLICT" and sender.await_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["unknown", "interrupted", "redis", "kill", "loss", "limit", "stale", "zero", "db"])
def test_failures_never_send_or_replay(runtime, monkeypatch, case):
    async def scenario():
        uid = await user(runtime)
        item = intent(uid)
        sender = AsyncMock(return_value={"status": "filled"})
        prep = prepare
        if case == "unknown":
            sender.side_effect = RuntimeError("response lost")
            first = await control.execute(item, 1, prep, sender)
            assert first["status"] == "unknown"
            repeated = await control.execute(item, 1, prep, sender)
            assert repeated["duplicate"]
            other = await control.execute(replace(item, signal_key="next"), 1, prep, sender)
            assert other["code"] == "OPEN_ORDER" and sender.await_count == 1
            return
        if case == "interrupted":
            async with runtime() as db:
                db.add(OrderIntent(intent_id=item.key, user_id=uid, account_ref=item.account_ref, book=item.book,
                    strategy_id=item.strategy_id, strategy_version=1, symbol=item.symbol, side="BUY",
                    source=item.source, input_hash=item.input_hash, status="PENDING", result={}))
                await db.commit()
        if case == "redis":
            monkeypatch.setattr(control.risk_guard, "_redis", lambda: AsyncMock(ping=AsyncMock(side_effect=OSError())))
        if case == "db":
            monkeypatch.setattr(control, "get_session_factory", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
        if case in ("kill", "limit"):
            async with runtime() as db:
                row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                if case == "kill": row.risk_kill_switch = True
                else:
                    row.risk_max_orders_per_day = 1
                    other = replace(item, signal_key="yesterday")
                    db.add(OrderIntent(intent_id=other.key, user_id=uid, account_ref=item.account_ref, book=item.book,
                        strategy_id=item.strategy_id, strategy_version=1, symbol=item.symbol, side="BUY",
                        source=item.source, input_hash=item.input_hash, status="filled", result={}))
                await db.commit()
        if case == "loss":
            async with runtime() as db:
                db.add(RiskDay(account_ref=item.account_ref, day=datetime.now(control.KST).date(), equity=2000000))
                await db.commit()
        if case == "stale":
            async def prep(db):
                return {**await prepare(db), "checked_at": datetime.now(timezone.utc) - timedelta(seconds=11)}
        result = await control.execute(item, 0 if case == "zero" else 1, prep, sender)
        assert result["status"] in ("skipped", "unknown")
        sender.assert_not_awaited()
    asyncio.run(scenario())


def test_kill_switch_changed_after_reservation_prevents_send(runtime, monkeypatch):
    async def scenario():
        uid = await user(runtime)
        calls = 0
        async def ping():
            nonlocal calls
            calls += 1
            if calls == 2:
                async with runtime() as db:
                    row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                    row.risk_kill_switch = True
                    await db.commit()
            return True
        monkeypatch.setattr(control.risk_guard, "_redis", lambda: AsyncMock(ping=ping))
        sender = AsyncMock()
        result = await control.execute(intent(uid), 1, prepare, sender, require_enabled=True)
        assert result["code"] in ("SETTINGS_CHANGED", "KILL_SWITCH")
        sender.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["manual", "other_strategy", "other_version", "other_user", "other_account", "owned", "sold", "drift", "pending"])
def test_live_ownership_does_not_adopt_manual_or_foreign_holdings(runtime, case):
    async def scenario():
        uid = await user(runtime)
        other_uid = await user(runtime)
        ref = intent(uid).account_ref
        async with runtime() as db:
            db.add(BrokerPositionBaseline(account_ref=ref, symbol="005930.KS", quantity=10))
            for side in (["BUY", "SELL"] if case == "sold" else ["BUY"]):
                if case != "manual":
                    db.add(LiveOrder(user_id=other_uid if case == "other_user" else uid,
                        account_ref="other" if case == "other_account" else ref,
                        strategy_id="other" if case == "other_strategy" else "ma",
                        strategy_version=2 if case == "other_version" else 1, client_order_id=uuid.uuid4().hex,
                        symbol="005930.KS", side=side, quantity=2, filled_quantity=0 if case == "pending" else 2,
                        avg_filled_price=70000, status="ACCEPTED" if case == "pending" else "FILLED"))
            await db.commit()
            qty = 10 if case in ("manual", "sold", "pending", "other_account") else 12
            if case == "drift": qty = 11
            snapshot = {"holdings": {"005930.KS": {"quantity": qty}}}
            rows, blocked = await live_ownership.reconcile(db, ref, snapshot, uid, "ma", 1)
            assert sum(r.quantity for r in rows) == (2 if case == "owned" else 0)
            if case in ("drift", "pending"): assert "005930.KS" in blocked
    asyncio.run(scenario())


@pytest.mark.parametrize("holdings", [None, {}, [{"symbol": "005930"}], [
    {"symbol": "005930", "quantity": 1.5, "avgPrice": 100, "evalAmount": 100}]])
def test_missing_or_invalid_gateway_holdings_are_not_empty(holdings):
    from types import SimpleNamespace
    gw = SimpleNamespace(is_configured=lambda: True, get_balance=AsyncMock(return_value={
        "cashBalance": 1000, "totalEvalAmount": 1000, "holdings": holdings}))
    with pytest.raises((ValueError, RuntimeError, TypeError)):
        asyncio.run(kis_execution.account_snapshot(SimpleNamespace(broker="kis"), gw, {}))


def test_run_overlap_restart_and_failure_event_are_durable(runtime, monkeypatch):
    async def scenario():
        uid = await user(runtime)
        now = datetime.now(timezone.utc)
        entered, release = asyncio.Event(), asyncio.Event()
        async def operation():
            entered.set()
            await release.wait()
            raise RuntimeError("not a message to log")
        monkeypatch.setattr(notification, "_load_user_settings", AsyncMock(return_value={"channels": ["slack"]}))
        monkeypatch.setattr(notification, "send_slack", AsyncMock(return_value=True))
        one = asyncio.create_task(execution_runs.run(uid, 600, operation, source="immediate", now=now))
        await entered.wait()
        concurrent = await execution_runs.run(uid, 600, operation, now=now)
        assert concurrent["status"] == "busy"
        release.set()
        first = await one
        second = await execution_runs.run(uid, 600, operation, now=now)
        assert first["status"] == second["status"] == "FAILED" and second["duplicate"]
        notification.send_slack.assert_awaited_once()
        async with runtime() as db:
            row = await db.get(ExecutionRun, first["run_id"])
            assert row.finished_at and row.detail == {"code": "EXECUTION_FAILED"}
    asyncio.run(scenario())


def test_notification_claim_is_user_scoped_and_failed_send_is_not_repeated(runtime, monkeypatch):
    async def scenario():
        a, b = await user(runtime), await user(runtime)
        monkeypatch.setattr(notification, "_load_user_settings", AsyncMock(return_value={"channels": ["slack"]}))
        monkeypatch.setattr(notification, "send_slack", AsyncMock(return_value=False))
        await asyncio.gather(*(notification.dispatch("test", user_id=str(a), kind="run", ref="same") for _ in range(4)))
        await notification.dispatch("test", user_id=str(b), kind="run", ref="same")
        assert notification.send_slack.await_count == 2
        async with runtime() as db:
            logs = (await db.execute(select(NotificationLog).where(NotificationLog.user_id.in_((a,b))))).scalars().all()
            assert len(logs) == 2 and all(x.delivery_status == "failed" for x in logs)
    asyncio.run(scenario())


def test_direct_quant_buys_are_tagged_and_only_confirmed_strategy_quantity_can_sell(runtime, monkeypatch):
    from types import SimpleNamespace
    from app.services import auto_trade, order_preflight
    client = SimpleNamespace(paper=True, get_price=AsyncMock(return_value=SimpleNamespace(current=1000)),
        get_buying_power=AsyncMock(return_value={"amount": 1000000, "quantity": 1000}),
        place_order=AsyncMock(return_value={"output": {"ODNO": "123"}}))
    creds = SimpleNamespace(paper=True, app_key="test", app_secret="test", account_no="1234567801")
    snapshot = {"cash": 990000.0, "equity": 1000000.0,
                "holdings": {"005930.KS": {"quantity": 10, "value": 10000, "avg_price": 1000}}}
    monkeypatch.setattr(order_preflight.gateway, "is_configured", lambda: False)
    monkeypatch.setattr(kis_execution, "client_for", lambda row: (client, creds))
    monkeypatch.setattr(kis_execution, "account_snapshot", AsyncMock(side_effect=lambda *a: snapshot))
    monkeypatch.setattr(auto_trade, "get_broker_client", lambda *a, **kw: client)
    for name in ("notify_order_placed", "notify_order_error"):
        monkeypatch.setattr(notification, name, AsyncMock())
    async def scenario():
        uid = await user(runtime, broker="kis", paper=True, quant_mode="live", app_key="test", app_secret="test", account_no="1234567801")
        async with runtime() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            decision = {"signal_key": "2026-10-27", "input_hash": "buy"}
            first = await auto_trade._execute_trade(db, uid, row, "live", "005930.KS", "삼성전자", "buy", 1000, 2, "test", decision=decision)
            assert first["status"] == "submitted"
            repeat = await auto_trade._execute_trade(db, uid, row, "live", "005930.KS", "삼성전자", "buy", 1000, 2, "test", decision=decision)
            assert repeat["status"] == "duplicate" and client.place_order.await_count == 1
            order = await db.scalar(select(LiveOrder).where(LiveOrder.user_id == uid))
            assert order.account_ref and order.strategy_id == "quant_default" and order.strategy_version == 0
            order.status, order.filled_quantity, order.avg_filled_price = "FILLED", 2, 1000
            await db.commit()
            snapshot["holdings"]["005930.KS"]["quantity"] = 12
            sale = {"signal_key": "2026-10-28", "input_hash": "sell"}
            too_many = await auto_trade._execute_trade(db, uid, row, "live", "005930.KS", "삼성전자", "sell", 1000, 12, "test", decision=sale)
            assert too_many["code"] == "OWNERSHIP_UNCONFIRMED"
            valid = await auto_trade._execute_trade(db, uid, row, "live", "005930.KS", "삼성전자", "sell", 1000, 2, "test", decision=sale)
            assert valid["status"] == "submitted" and client.place_order.await_count == 2
    asyncio.run(scenario())


def test_tradingview_gate_does_not_adopt_manual_holdings(runtime, monkeypatch):
    from app.models import PaperAccount, Portfolio, Order
    from app.services import paper_trading as pt, paper_order_control
    info = {"symbol": "005930.KS", "name": "삼성전자", "price": 1000.0, "market": "KOSPI", "currency": "KRW"}
    monkeypatch.setattr(pt, "_confirm_quote", AsyncMock(return_value=info))
    async def scenario():
        uid = await user(runtime)
        async with runtime() as db:
            db.add(PaperAccount(user_id=uid, cash=990000, initial_cash=1000000))
            db.add(Portfolio(user_id=uid, book="PAPER", symbol="005930.KS", name="삼성전자", quantity=10, avg_price=1000))
            await db.commit()
            with pytest.raises(pt.PaperTradeError, match="매도 가능 보유"):
                await paper_order_control.execute(db, uid, info, "SELL", 1, source="TRADINGVIEW", signal_key="sell1", strategy_id="tv:ma")
            bought = await paper_order_control.execute(db, uid, info, "BUY", 1, source="TRADINGVIEW", signal_key="buy1", strategy_id="tv:ma")
            assert bought["status"] == "ok"
            repeated = await paper_order_control.execute(db, uid, info, "BUY", 1, source="TRADINGVIEW", signal_key="buy1", strategy_id="tv:ma")
            assert repeated["duplicate"]
            orders = (await db.execute(select(Order).where(Order.user_id == uid))).scalars().all()
            assert len(orders) == 1 and orders[0].execution_intent_id
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            row.risk_kill_switch = True
            await db.commit()
            with pytest.raises(pt.PaperTradeError, match="비상 정지"):
                await paper_order_control.execute(db, uid, info, "BUY", 1, source="TRADINGVIEW", signal_key="buy2", strategy_id="tv:ma")
    asyncio.run(scenario())


def test_post_send_database_failure_is_unknown_and_cannot_resend(runtime):
    async def scenario():
        uid = await user(runtime)
        sends = []
        session = None
        async def prep(db):
            nonlocal session
            session = db
            return await prepare(db)
        async def send(*args):
            sends.append(1)
            session.commit = AsyncMock(side_effect=RuntimeError("lost database"))
            return {"status": "submitted"}
        item = intent(uid)
        first = await control.execute(item, 1, prep, send)
        assert first["status"] == "unknown"
        repeat = await control.execute(item, 1, prepare, send)
        assert repeat["status"] == "unknown" and repeat["duplicate"] and len(sends) == 1
    asyncio.run(scenario())


def test_process_death_preserves_pending_intent_and_releases_account_lock(runtime):
    """별도 프로세스를 전송 경계에서 종료: 연결 해제 뒤에도 PENDING 의도를 재전송하지 않는다."""
    import subprocess
    import sys
    async def scenario():
        uid = await user(runtime)
        item = intent(uid)
        code = '''import asyncio, os, uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.services import execution_control as c
async def ready(): pass
c.coordination_ready = ready
engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"])
c.get_session_factory = lambda: async_sessionmaker(engine, expire_on_commit=False)
uid = uuid.UUID("UID_VALUE")
item = c.Intent(uid, c.digest([str(uid), "paper"]), "QUANT", "ma", 1, "005930.KS", "BUY", "2026-10-27", "scheduled", "same-input")
async def prep(db):
 return {"cash": 1000000.0, "equity": 1000000.0, "price": 10000.0, "checked_at": datetime.now(timezone.utc)}
async def die(*args): os._exit(23)
asyncio.run(c.execute(item, 1, prep, die))
'''.replace("UID_VALUE", str(uid))
        proc = await asyncio.create_subprocess_exec(sys.executable, "-c", code,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _, error = await asyncio.wait_for(proc.communicate(), 20)
        assert proc.returncode == 23, error.decode()[-500:]
        sender = AsyncMock()
        result = await control.execute(item, 1, prepare, sender)
        assert result["status"] == "unknown" and result["duplicate"]
        sender.assert_not_awaited()
        async with runtime() as db:
            assert (await db.get(OrderIntent, item.key)).status == "PENDING"
    asyncio.run(scenario())


@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_REDIS_URL"), reason="일회용 Redis 필요")
def test_real_redis_connection_failure_blocks_and_recovery_allows_first_send(runtime, monkeypatch):
    import redis.asyncio as redis
    async def scenario():
        uid = await user(runtime)
        offline = redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=.2)
        online = redis.from_url(os.environ["QURIOUS_TEST_REDIS_URL"], socket_connect_timeout=1)
        sender = AsyncMock(return_value={"status": "filled"})
        try:
            monkeypatch.setattr(control.risk_guard, "_redis", lambda: offline)
            result = await control.execute(intent(uid), 1, prepare, sender)
            assert result["code"] == "CACHE_UNAVAILABLE"
            sender.assert_not_awaited()
            monkeypatch.setattr(control.risk_guard, "_redis", lambda: online)
            assert (await control.execute(intent(uid), 1, prepare, sender))["status"] == "filled"
            sender.assert_awaited_once()
        finally:
            await offline.aclose()
            await online.aclose()
    asyncio.run(scenario())


def test_orphan_run_is_interrupted_once_without_repeating_operation(runtime, monkeypatch):
    async def scenario():
        uid = await user(runtime)
        now = datetime.now(timezone.utc)
        slot = int(now.timestamp()) // 600 * 600
        rid = control.digest([str(uid), "quant", slot])
        async with runtime() as db:
            db.add(ExecutionRun(run_id=rid, user_id=uid, scheduled_for=now, source="scheduled", status="RUNNING", detail={}))
            await db.commit()
        monkeypatch.setattr(notification, "_load_user_settings", AsyncMock(return_value={"channels": ["slack"]}))
        monkeypatch.setattr(notification, "send_slack", AsyncMock(return_value=True))
        work = AsyncMock()
        for _ in range(2):
            result = await execution_runs.run(uid, 600, work, now=now)
            assert result["status"] == "INTERRUPTED" and result["duplicate"]
        work.assert_not_awaited()
        notification.send_slack.assert_awaited_once()
    asyncio.run(scenario())


def test_notification_store_failure_never_sends(runtime, monkeypatch):
    from app.database import postgres
    async def scenario():
        uid = await user(runtime)
        monkeypatch.setattr(postgres, "get_session_factory", lambda: (_ for _ in ()).throw(OSError("offline")))
        monkeypatch.setattr(notification, "send_slack", AsyncMock())
        with pytest.raises(OSError):
            await notification.dispatch("test", user_id=str(uid), kind="quant_run_failed", ref="failed-store")
        notification.send_slack.assert_not_awaited()
    asyncio.run(scenario())


def test_new_signal_cannot_bypass_shared_cooldown(runtime):
    async def scenario():
        uid = await user(runtime)
        async with runtime() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            row.risk_cooldown_min = 30
            await db.commit()
        sender = AsyncMock(return_value={"status": "filled"})
        assert (await control.execute(intent(uid), 1, prepare, sender))["status"] == "filled"
        result = await control.execute(replace(intent(uid), signal_key="new", source="other"), 1, prepare, sender)
        assert result["code"] == "COOLDOWN"
        sender.assert_awaited_once()
    asyncio.run(scenario())


def test_tradingview_receipt_to_fill_replay_and_strategy_separation(runtime, monkeypatch):
    from types import SimpleNamespace
    from app.models import PaperAccount, Portfolio, Order, WebhookSignal
    from app.services import tradingview as tv, paper_trading as pt
    info = {"symbol": "005930.KS", "name": "삼성전자", "price": 1000.0, "market": "KOSPI", "currency": "KRW"}
    monkeypatch.setattr(pt, "resolve_stock", AsyncMock(return_value=info))
    monkeypatch.setattr(pt, "_confirm_quote", AsyncMock(return_value=info))
    async def scenario():
        uid = await user(runtime)
        key = SimpleNamespace(user_id=uid, last_used_at=None, call_count=0)
        monkeypatch.setattr(tv, "resolve_user_by_token", AsyncMock(return_value=key))
        async with runtime() as db:
            db.add(PaperAccount(user_id=uid, cash=1000000, initial_cash=1000000))
            await db.commit()
            payload = {"token": "test-only", "strategy": "ma", "ticker": "005930.KS", "action": "buy", "quantity": 2,
                       "bar_time": "2026-10-28T01:00:00Z"}
            one = await tv.handle_alert(db, payload)
            await db.commit()
            replay = await tv.handle_alert(db, payload)
            await db.commit()
            assert one["signal"]["status"] == "filled" and replay["signal"]["status"] == "duplicate"
            assert one["notification_ref"] == replay["notification_ref"]
            assert "추가 주문 없음" in replay["signal"]["message"]
            foreign = await tv.handle_alert(db, {**payload, "strategy": "other", "action": "sell"})
            await db.commit()
            assert foreign["signal"]["status"] == "error" and "매도 가능 보유" in foreign["signal"]["message"]
            sold = await tv.handle_alert(db, {**payload, "action": "sell"})
            await db.commit()
            assert sold["signal"]["status"] == "filled"
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id == uid)) == 2
            assert await db.scalar(select(func.count()).select_from(Portfolio).where(Portfolio.user_id == uid)) == 0
            logs = (await db.scalars(select(WebhookSignal).where(WebhookSignal.user_id == uid))).all()
            assert len(logs) == 4 and all("token" not in x.payload for x in logs)
    asyncio.run(scenario())


def test_virtual_ownership_blocks_other_strategy_and_external_balance_change(runtime):
    from app.models import Portfolio, Order
    async def scenario():
        uid = await user(runtime)
        item = intent(uid)
        async with runtime() as db:
            assert await live_ownership.virtual_quantity(db, item, 10) == 0
            db.add(OrderIntent(intent_id=item.key, user_id=uid, account_ref=item.account_ref, book="QUANT",
                strategy_id="ma", strategy_version=1, symbol=item.symbol, side="BUY", source="quant", input_hash="test", status="filled"))
            db.add(Order(user_id=uid, symbol=item.symbol, name="test", order_type="buy", quantity=2, price=1000,
                source="QUANT", status="filled", execution_intent_id=item.key))
            await db.commit()
            assert await live_ownership.virtual_quantity(db, replace(item, side="SELL"), 12) == 2
            assert await live_ownership.virtual_quantity(db, replace(item, side="SELL", strategy_id="other"), 12) == 0
            with pytest.raises(control.Rejected, match="귀속 확인"):
                await live_ownership.virtual_quantity(db, replace(item, side="SELL"), 11)
    asyncio.run(scenario())


def test_gateway_without_stable_account_identity_never_submits(runtime, monkeypatch):
    from app.services import auto_trade, order_preflight
    async def scenario():
        uid = await user(runtime, broker="kis", paper=True, quant_mode="live")
        monkeypatch.setattr(order_preflight.gateway, "is_configured", lambda: True)
        sender = AsyncMock()
        monkeypatch.setattr(order_preflight.gateway, "place_order", sender)
        async with runtime() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            result = await auto_trade._execute_trade(db, uid, row, "live", "005930.KS", "삼성전자", "buy", 1000, 1,
                "test", decision={"signal_key": "bar", "input_hash": "test"})
        assert result["code"] == "ACCOUNT_IDENTITY_UNAVAILABLE"
        sender.assert_not_awaited()
    asyncio.run(scenario())
