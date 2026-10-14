"""#162: 비용 뒤 손익비와 수동 비상 정지 계약."""
import asyncio
import os
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from app.config import settings
from app.services import trading_cost as costs
from app.services.risk_execution import exit_cost_example, execution_guidance


@pytest.mark.parametrize("year", [2025, 2026])
def test_cost_example_matches_cash_settlement_on_each_leg(year):
    day = date(year, 10, 14)
    example = exit_cost_example(1.5, 1.0, day)
    # 가상의 100,000원 주식 10주. 기존 주문 정산 모듈과 독립적으로 비교한다.
    buy = costs.order_costs("buy", 100000, 10, day).net_amount
    win = (costs.order_costs("sell", 101500, 10, day).net_amount / buy - 1) * 100
    loss = -(costs.order_costs("sell", 99000, 10, day).net_amount / buy - 1) * 100
    assert example["net_take_profit_pct"] == pytest.approx(win, abs=.00005)
    assert example["net_stop_loss_pct"] == pytest.approx(-loss, abs=.00005)
    assert example["reward_risk_ratio"] == pytest.approx(win / loss, abs=.00005)
    assert example["break_even_win_rate_pct"] == pytest.approx(loss / (loss + win) * 100, abs=.00005)


def test_slippage_reduces_reward_and_raises_break_even_rate():
    zero = exit_cost_example(1.5, 1, "2026-10-14", 0)
    slip = exit_cost_example(1.5, 1, "2026-10-14", 10)
    assert slip["net_take_profit_pct"] < zero["net_take_profit_pct"]
    assert slip["net_stop_loss_pct"] < zero["net_stop_loss_pct"]
    assert slip["reward_risk_ratio"] < zero["reward_risk_ratio"]
    assert slip["break_even_win_rate_pct"] > zero["break_even_win_rate_pct"]


def test_unprofitable_take_profit_has_no_misleading_break_even_number():
    result = exit_cost_example(.1, 1, "2026-10-14", 10)
    assert result["net_take_profit_pct"] < 0
    assert result["reward_risk_ratio"] is None
    assert result["break_even_win_rate_pct"] is None


@pytest.mark.parametrize("tp,sl,slip", [(0, 1, 0), (1, 0, 0), (1, 100, 0), (1, 1, -1),
                                        (float("nan"), 1, 0), (1, float("inf"), 0)])
def test_invalid_cost_inputs(tp, sl, slip):
    with pytest.raises(ValueError):
        exit_cost_example(tp, sl, "2026-10-14", slip)


def test_guidance_uses_active_settings_and_korean_date(monkeypatch):
    monkeypatch.setattr(settings, "QUANT_CYCLE_SEC", 180)
    monkeypatch.setattr(settings, "QUANT_AGGRESSIVE_MODE", True)
    monkeypatch.setattr(settings, "QUANT_AGGRESSIVE_TAKE_PROFIT_PCT", 2)
    monkeypatch.setattr(settings, "QUANT_AGGRESSIVE_STOP_LOSS_PCT", .8)
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_CANCEL_OPEN_AFTER_MIN", 15)
    monkeypatch.setattr(costs, "today_kst", lambda: date(2026, 10, 14))
    g = execution_guidance()
    assert g["cycle_seconds"] == 180 and g["aggressive_enabled"]
    assert g["take_profit_pct"] == 2 and g["stop_loss_pct"] == .8
    assert g["cancel_open_after_min"] == 15
    assert g["cost_example"]["as_of"] == "2026-10-14"
    assert g["cost_example"]["scenarios"][0] == exit_cost_example(2, .8, "2026-10-14")


@pytest.mark.parametrize("cancel_fails", [False, True])
def test_manual_kill_switch_stops_before_cancelling_and_never_liquidates(monkeypatch, cancel_fails):
    from app.routes import stocks
    uid = str(uuid.uuid4())
    row = SimpleNamespace(risk_kill_switch=False, risk_halt_reason="", quant_auto_enabled=True)
    db = SimpleNamespace(commit=AsyncMock())
    order = []
    async def stop(*args):
        assert row.risk_kill_switch and db.commit.await_count == 1
        row.quant_auto_enabled = False
        order.append("stop")
        return True
    async def cancel(*args):
        assert not row.quant_auto_enabled
        order.append("cancel")
        if cancel_fails:
            raise RuntimeError("취소 응답 없음")
        return {"requested": 1, "failed": 0, "skipped": 0}
    monkeypatch.setattr(stocks, "_get_or_create_broker_settings_row", AsyncMock(return_value=row))
    monkeypatch.setattr(stocks.auto_trade, "stop_auto_trade_for", stop)
    monkeypatch.setattr(stocks.auto_trade, "cancel_open_live_orders", cancel)
    placed = AsyncMock(side_effect=AssertionError("비상 정지는 새 청산 주문을 내지 않는다"))
    monkeypatch.setattr(stocks.auto_trade, "_place_live_order", placed)
    monkeypatch.setattr(stocks.notification, "notify_risk_halt", AsyncMock())
    monkeypatch.setattr(stocks, "audit", AsyncMock())
    result = asyncio.run(stocks.quant_kill_switch(stocks.KillSwitchBody(enabled=True), {"id": uid}, db))
    assert order == ["stop", "cancel"] and result["kill_switch"]
    assert result["cancellation"]["failed"] == int(cancel_fails)
    placed.assert_not_awaited()
    # 해제는 실행 재개나 새 주문/취소를 일으키지 않는다.
    asyncio.run(stocks.quant_kill_switch(stocks.KillSwitchBody(enabled=False), {"id": uid}, db))
    assert not row.risk_kill_switch and not row.quant_auto_enabled
    assert order == ["stop", "cancel"]


def test_risk_status_displays_effective_aggressive_limits(monkeypatch):
    from app.routes import stocks
    monkeypatch.setattr(settings, "QUANT_AGGRESSIVE_MODE", True)
    monkeypatch.setattr(settings, "QUANT_AGGRESSIVE_MAX_ORDERS_PER_DAY", 77)
    monkeypatch.setattr(settings, "QUANT_AGGRESSIVE_COOLDOWN_MIN", 4)
    row = SimpleNamespace(risk_max_orders_per_day=5, risk_cooldown_min=30, risk_halt_reason="", quant_auto_enabled=True)
    monkeypatch.setattr(stocks, "_get_broker_settings_row", AsyncMock(return_value=row))
    monkeypatch.setattr(stocks.auto_trade, "get_status", AsyncMock(return_value={}))
    async def risk_status(uid, limits, equity, reason):
        return {"limits": limits.to_dict()}
    monkeypatch.setattr(stocks.risk_guard, "risk_status", risk_status)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
    result = asyncio.run(stocks.quant_risk_status({"id": str(uuid.uuid4())}, db))
    assert result["limits"]["max_orders_per_day"] == 77
    assert result["limits"]["cooldown_min"] == 4
    assert result["execution_guidance"]["aggressive_enabled"]


@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요")
@pytest.mark.usefixtures("rebalance_db_schema")
def test_unknown_replay_checks_each_owners_persisted_state(monkeypatch):
    from datetime import datetime, timezone
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.models import User, BrokerSettings, LiveOrder
    from app.services import auto_trade
    from app.services.brokers import stock_coin_trade_gateway as gw

    async def go():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        users = [uuid.uuid4(), uuid.uuid4()]
        async with factory() as db:
            for i, uid in enumerate(users):
                db.add(User(id=uid, name="risk test", email=f"{uid}@example.com", client_id=uid.hex, password_hash="test"))
            await db.flush()
            for i, uid in enumerate(users):
                db.add(BrokerSettings(user_id=uid, quant_auto_enabled=True, risk_kill_switch=(i == 0), quant_mode="live"))
                db.add(LiveOrder(user_id=uid, client_order_id=f"risk-{uid}", symbol="005930.KS", side="SELL", quantity=2,
                                 price=70000, status="UNKNOWN", environment="paper", order_type="MARKET",
                                 created_at=datetime.now(timezone.utc)))
            await db.commit()
        monkeypatch.setattr(auto_trade, "get_session_factory", lambda: factory)
        monkeypatch.setattr(gw, "is_configured", lambda: True)
        monkeypatch.setattr(gw, "is_krx_market_open", lambda: True)
        monkeypatch.setattr(settings, "STOCK_COIN_TRADE_UNKNOWN_RESUBMIT_MIN", 10)
        place = AsyncMock(return_value={"duplicate": True, "order": {"orderNo": "123", "status": "ACCEPTED"}})
        monkeypatch.setattr(gw, "place_order", place)
        try:
            result = await auto_trade.confirm_live_fills()
            assert result["skipped"] == 1 and result["resubmitted"] == 1
            place.assert_awaited_once()
            assert place.call_args.kwargs["client_order_id"] == f"risk-{users[1]}"
        finally:
            await engine.dispose()
    asyncio.run(go())
