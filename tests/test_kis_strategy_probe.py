"""판 1 평가·미수 없는 수량·실제 PostgreSQL의 재시작/동시 선점 경계."""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.models import BrokerSettings, LiveOrder, StrategyDecision, User
from app.services import kis_strategy_probe as probe
from app.services.brokers.kis import KISClient, OrderSubmissionUnknown

SPEC = json.loads(Path("docs/phase-3/02-design/system/예시/strategy-card-ma-cross-v1.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)
CALENDAR = {"days": [{"date": "2026-10-26", "is_trading_day": True},
                     {"date": "2026-10-27", "is_trading_day": True}]}


def indicators(closes=None):
    closes = closes if closes is not None else list(range(100, 160))
    end = datetime(2026, 10, 26, tzinfo=timezone.utc)
    return {"closes": closes, "times": [(end - timedelta(days=len(closes) - 1 - i)).timestamp() for i in range(len(closes))]}


@pytest.mark.parametrize("closes,action", [(list(range(100, 160)), "BUY"), (list(range(160, 100, -1)), "SELL"), ([100] * 60, "HOLD")])
def test_fixed_rule_actions(closes, action):
    result = probe.prepare(SPEC, indicators(closes), NOW, CALENDAR)
    assert result["action"] == action
    assert result["bar_end_at"] == "2026-10-26T15:30:00+09:00"


@pytest.mark.parametrize("closes", [[100] * 59, [100] * 59 + [None], [100] * 59 + [float('nan')]])
def test_invalid_bars_never_fall_back_to_score(closes):
    with pytest.raises(ValueError):
        probe.prepare(SPEC, indicators(closes), NOW, CALENDAR)


def test_today_bar_is_excluded_and_stale_or_future_bars_rejected():
    data = indicators()
    data["closes"].append(1)
    data["times"].append(datetime(2026, 10, 27, tzinfo=timezone.utc).timestamp())
    assert probe.prepare(SPEC, data, NOW, CALENDAR)["action"] == "BUY"
    data["times"][-1] += 86400
    with pytest.raises(ValueError, match="미래"):
        probe.prepare(SPEC, data, NOW, CALENDAR)
    old = indicators()
    old["times"] = [t - 86400 for t in old["times"]]
    with pytest.raises(ValueError, match="직전 거래일"):
        probe.prepare(SPEC, old, NOW, CALENDAR)


@pytest.mark.parametrize("change", [{"version": 2}, {"universe": ["000660"]}, {"stops": {}}, {"timeframe": "5m"},
                                      {"warmup_bars": 60}, {"price_basis": "adjusted"}])
def test_other_card_is_rejected(change):
    with pytest.raises(ValueError):
        probe.prepare({**SPEC, **change}, indicators(), NOW, CALENDAR)


@pytest.mark.parametrize("change", [{"entry_mode": "open"}, {"exit_mode": "open"}, {"reentry": "new_signal"},
    {"stops": {"judge": "close"}}, {"warmup_bars": 60}, {"price_basis": "adjusted"},
    {"position_sizing": {"size_kind": "risk_pct", "risk_pct": 1.0}}])
def test_regular_card_path_rejects_unimplemented_execution_rules(change):
    from app.services.strategy_execution import validate_rule_input
    with pytest.raises(ValueError, match="지원하지 않는 카드 실행"):
        validate_rule_input({**SPEC, **change}, indicators())


@pytest.mark.parametrize("output", [{}, {"nrcvb_buy_amt": "nan", "nrcvb_buy_qty": "3"},
    {"nrcvb_buy_amt": "10000", "nrcvb_buy_qty": "1.5"}, {"max_buy_amt": "1000000", "max_buy_qty": "100"}])
def test_buying_power_rejects_missing_or_invalid_non_margin_fields(monkeypatch, output):
    cls = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: cls(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"rt_cd": "0", "output": output})), **kw))
    client = KISClient("test", "test")
    monkeypatch.setattr(client, "_ensure_token", AsyncMock())
    with pytest.raises(RuntimeError, match="미수 없는"):
        asyncio.run(client.get_buying_power("1234567801", "005930.KS", 10000))


def test_buying_power_uses_paper_non_margin_query(monkeypatch):
    cls = httpx.AsyncClient
    def handler(req):
        assert req.headers["tr_id"] == "VTTC8908R"
        assert req.url.params["ORD_DVSN"] == "01"
        assert req.url.params["CMA_EVLU_AMT_ICLD_YN"] == "N"
        return httpx.Response(200, json={"rt_cd": "0", "output": {"nrcvb_buy_amt": "20000", "nrcvb_buy_qty": "0", "max_buy_qty": "100"}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: cls(transport=httpx.MockTransport(handler), **kw))
    client = KISClient("test", "test")
    monkeypatch.setattr(client, "_ensure_token", AsyncMock())
    assert asyncio.run(client.get_buying_power("1234567801", "005930.KS", 10000)) == {"amount": 20000.0, "quantity": 0}


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(probe.execution_control, "coordination_ready", AsyncMock())
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(probe, "datetime", Clock)
    monkeypatch.setattr(probe.market_calendar, "trading_days", lambda *a: CALENDAR)
    monkeypatch.setattr(probe, "get_quant_indicators", AsyncMock(return_value=indicators()))
    monkeypatch.setattr(probe.gateway, "is_configured", lambda: False)
    client = SimpleNamespace(paper=True, get_price=AsyncMock(return_value=SimpleNamespace(current=70000)),
        get_buying_power=AsyncMock(return_value={"amount": 1000000, "quantity": 10}),
        place_order=AsyncMock(return_value={"output": {"ODNO": "000123"}}))
    creds = SimpleNamespace(paper=True, app_key="test-key", account_no="1234567801")
    monkeypatch.setattr(probe.kis_execution, "client_for", lambda row: (client, creds))
    monkeypatch.setattr(probe.auto_trade, "get_broker_client", lambda *a, **kw: client)
    monkeypatch.setattr(probe.kis_execution, "account_snapshot", AsyncMock(return_value={
        "cash": 1000000, "equity": 1000000, "holdings": {}, "checked_at": NOW.isoformat()}))
    for name in ("notify_order_placed", "notify_order_error"):
        monkeypatch.setattr(probe.auto_trade.notification, name, AsyncMock())
    return client


def factory():
    engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def make_user(session):
    uid = uuid.uuid4()
    async with session() as db:
        db.add(User(id=uid, name="probe test", email=f"{uid}@example.test", password_hash="test", client_id=uid.hex))
        await db.flush()
        db.add(BrokerSettings(user_id=uid, broker="kis", paper=True, quant_auto_enabled=False,
            app_key="test-key", app_secret="test-secret", account_no="1234567801", quant_per_trade_budget=1000000,
            risk_kill_switch=False))
        await db.commit()
    return uid


db_test = pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PostgreSQL 필요")


@db_test
@pytest.mark.usefixtures("rebalance_db_schema")
def test_repeat_and_concurrent_workers_send_at_most_once(runtime):
    async def scenario():
        engine, sessions = factory()
        uid = await make_user(sessions)
        async def once():
            async with sessions() as db:
                return await probe.run(db, uid, SPEC, execute=True)
        try:
            results = await asyncio.gather(once(), once())
            assert runtime.place_order.await_count == 1
            repeated = await once()
            assert repeated["duplicate"] and repeated["status"] == "submitted"
            assert len({r["decision_key"] for r in results + [repeated]}) == 1
            async with sessions() as db:
                record = await db.get(StrategyDecision, repeated["decision_key"])
                order = (await db.execute(select(LiveOrder).where(LiveOrder.client_order_id == record.client_order_id))).scalar_one()
                assert order.status == "ACCEPTED" and order.filled_quantity == 0
                assert order.client_order_id.startswith("card:")
        finally:
            await engine.dispose()
    asyncio.run(scenario())


@db_test
@pytest.mark.usefixtures("rebalance_db_schema")
@pytest.mark.parametrize("case", ["zero", "hold", "sell_unowned", "unknown", "dry_run", "input_conflict", "db_failure", "kill_before_send"])
def test_order_boundaries(runtime, monkeypatch, case):
    # 계좌별 1일 제한과 다른 시험이 섞이지 않도록 시험마다 계좌 지문을 분리한다.
    account = uuid.uuid4().hex
    original_key = probe.kis_execution.account_key
    monkeypatch.setattr(probe.kis_execution, "account_key", lambda *a: original_key(a[0], account, a[2]))
    if case == "zero":
        runtime.get_buying_power.return_value = {"amount": 1000000, "quantity": 0}
    if case in ("hold", "sell_unowned"):
        data = indicators([100] * 60 if case == "hold" else list(range(160, 100, -1)))
        monkeypatch.setattr(probe, "get_quant_indicators", AsyncMock(return_value=data))
    if case == "unknown":
        runtime.place_order.side_effect = OrderSubmissionUnknown("response lost")
    async def scenario():
        engine, sessions = factory()
        uid = await make_user(sessions)
        try:
            if case == "kill_before_send":
                async def change_setting(*args):
                    async with sessions() as other:
                        broker = (await other.execute(select(BrokerSettings).where(BrokerSettings.user_id == uid))).scalar_one()
                        broker.risk_kill_switch = True
                        await other.commit()
                    return {"amount": 1000000, "quantity": 10}
                runtime.get_buying_power.side_effect = change_setting
            async with sessions() as db:
                if case == "db_failure":
                    monkeypatch.setattr(db, "commit", AsyncMock(side_effect=RuntimeError("database unavailable")))
                    with pytest.raises(RuntimeError, match="database unavailable"):
                        await probe.run(db, uid, SPEC, execute=True)
                    runtime.place_order.assert_not_awaited()
                    return
                first = await probe.run(db, uid, SPEC, execute=case != "dry_run")
            if case == "input_conflict":
                changed = indicators()
                changed["closes"][0] += 0.5
                monkeypatch.setattr(probe, "get_quant_indicators", AsyncMock(return_value=changed))
                async with sessions() as db:
                    with pytest.raises(ValueError, match="입력이 변경"):
                        await probe.run(db, uid, SPEC, execute=True)
                assert runtime.place_order.await_count == 1
            elif case == "unknown":
                async with sessions() as db:
                    again = await probe.run(db, uid, SPEC, execute=True)
                assert first["status"] == again["status"] == "unknown"
                assert again["duplicate"] and runtime.place_order.await_count == 1
            else:
                runtime.place_order.assert_not_awaited()
                assert first["status"] in ("HOLD", "BLOCKED", "DRY_RUN")
                if case == "dry_run":
                    async with sessions() as db:
                        assert await db.get(StrategyDecision, first["decision_key"]) is None
        finally:
            await engine.dispose()
    asyncio.run(scenario())


@db_test
@pytest.mark.usefixtures("rebalance_db_schema")
@pytest.mark.parametrize("owner", ["manual", "other_strategy", "other_version", "other_account", "own", "sold"])
def test_sell_only_uses_same_strategy_version_confirmed_holdings(runtime, monkeypatch, owner):
    """같은 종목 잔고가 있어도 수동·다른 전략/판/계좌의 체결을 전용하지 않는다."""
    account_ref = uuid.uuid4().hex * 2
    monkeypatch.setattr(probe.kis_execution, "account_key", lambda *a: account_ref)
    monkeypatch.setattr(probe, "get_quant_indicators", AsyncMock(return_value=indicators(list(range(160, 100, -1)))))
    probe.kis_execution.account_snapshot.return_value["holdings"] = {probe.SYMBOL: {"quantity": 10, "value": 700000}}

    async def scenario():
        engine, sessions = factory()
        uid = await make_user(sessions)
        try:
            async with sessions() as db:
                for side in (["BUY", "SELL"] if owner == "sold" else ["BUY"]):
                    order_id = uuid.uuid4().hex
                    db.add(LiveOrder(user_id=uid, client_order_id=order_id, environment="paper",
                        broker="kis-direct", symbol=probe.SYMBOL, side=side, quantity=1,
                        status="FILLED", filled_quantity=1))
                    await db.flush()
                    if owner != "manual":
                        db.add(StrategyDecision(decision_key=uuid.uuid4().hex * 2, user_id=uid,
                            account_ref="other" if owner == "other_account" else account_ref,
                            input_hash="test", strategy_id="other" if owner == "other_strategy" else SPEC["strategy_id"],
                            strategy_version=2 if owner == "other_version" else 1,
                            symbol=probe.SYMBOL, bar_end_at=NOW - timedelta(days=1), action=side,
                            status="submitted", client_order_id=order_id, detail={}, created_at=NOW - timedelta(days=1)))
                await db.commit()
                result = await probe.run(db, uid, SPEC, execute=False)
                assert result["quantity"] == (1 if owner == "own" else 0)
                assert result["would_status"] == ("PENDING" if owner == "own" else "BLOCKED")
                runtime.place_order.assert_not_awaited()
        finally:
            await engine.dispose()
    asyncio.run(scenario())


@db_test
@pytest.mark.usefixtures("rebalance_db_schema")
def test_migration_upgrade_downgrade_preserves_existing_accounts(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from app.config import settings
    monkeypatch.setattr(settings, "DATABASE_URL", os.environ["QURIOUS_TEST_DATABASE_URL"])
    async def check(drop=False):
        engine, sessions = factory()
        try:
            async with engine.begin() as conn:
                count = (await conn.execute(text("SELECT count(*) FROM users"))).scalar_one()
                if drop:
                    await conn.run_sync(StrategyDecision.__table__.drop)
                present = (await conn.execute(text("SELECT to_regclass('strategy_decisions')"))).scalar_one()
                return count, present
        finally:
            await engine.dispose()
    count, _ = asyncio.run(check(drop=True))
    cfg = Config("alembic.ini")
    command.stamp(cfg, "0026_paper_journal")
    command.upgrade(cfg, "0027_strategy_decisions")
    assert asyncio.run(check()) == (count, "strategy_decisions")
    command.downgrade(cfg, "0026_paper_journal")
    assert asyncio.run(check()) == (count, None)
    command.upgrade(cfg, "0027_strategy_decisions")
    assert asyncio.run(check()) == (count, "strategy_decisions")
