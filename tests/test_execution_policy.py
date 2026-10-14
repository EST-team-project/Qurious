"""#162 위험 수량 상한과 설정 계약."""
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from pydantic import ValidationError

from app.services.execution_policy import ExecutionPolicy, policy_for, risk_quantity
from app.services import trading_cost


def sizing(**changes):
    values = dict(equity=1_000_000, cash=1_000_000, price=10_000, stop_price=9900,
                  budget=1_000_000, existing_value=0, position_cap_pct=100,
                  risk_pct=.1, slippage_bps=10, when=date(2026, 10, 14))
    return risk_quantity(**(values | changes))


def test_sizing_covers_round_trip_cost_and_risk_budget():
    result = sizing()
    buy = trading_cost.order_costs("buy", 10000, result["quantity"], date(2026, 10, 14))
    sell = trading_cost.order_costs("sell", 9900, result["quantity"], date(2026, 10, 14))
    slip = (10000 + 9900) * result["quantity"] * .001
    assert result["estimated_loss"] == pytest.approx(buy.net_amount - sell.net_amount + slip)
    assert result["estimated_loss"] <= 1000
    assert result["estimated_loss"] + result["loss_per_share"] > 1000
    assert sizing(slippage_bps=0)["quantity"] > result["quantity"]


@pytest.mark.parametrize("changes,qty", [({"cash": 10000}, 0), ({"budget": 10000}, 0),
    ({"position_cap_pct": 1}, 1), ({"position_cap_pct": 1, "existing_value": 10000}, 0),
    ({"cash": 20100}, 2), ({"budget": 20100}, 2)])
def test_cash_budget_and_position_caps(changes, qty):
    assert sizing(**changes)["quantity"] == qty


@pytest.mark.parametrize("changes", [{"price": "bad"}, {"cash": float("nan")}, {"equity": 0},
    {"stop_price": 10000}, {"risk_pct": 6}, {"slippage_bps": -1}])
def test_invalid_sizing_fails_closed(changes):
    with pytest.raises(ValueError):
        sizing(**changes)


@pytest.mark.parametrize("changes", [{"risk_pct": 0}, {"retry_max_attempts": 4}, {"retry_window_min": 121},
    {"slippage_bps": float("nan")}, {"stop_loss_pct": 100}, {"size_kind": "unknown"}, {"unknown": True}])
def test_policy_validates_limits(changes):
    with pytest.raises(ValidationError):
        ExecutionPolicy(**changes)


def test_legacy_settings_preserve_existing_execution_policy(monkeypatch):
    from app.routes import stocks
    row = SimpleNamespace(quant_execution_policy={"size_kind": "risk_pct"})
    monkeypatch.setattr(stocks, "_get_or_create_broker_settings_row", AsyncMock(return_value=row))
    monkeypatch.setattr(stocks, "_apply_credentials", lambda *args: None)
    monkeypatch.setattr(stocks, "audit", AsyncMock())
    db = SimpleNamespace(commit=AsyncMock())
    uid = {"id": str(uuid.uuid4())}
    asyncio.run(stocks.save_quant_settings(stocks.QuantSettingsBody(), uid, db))
    assert policy_for(row).size_kind == "risk_pct"
    asyncio.run(stocks.save_quant_settings(stocks.QuantSettingsBody(execution_policy=ExecutionPolicy()), uid, db))
    assert policy_for(row).size_kind == "fixed_budget" and not policy_for(row).retry_enabled
    assert policy_for(None) == ExecutionPolicy()


def test_unconnected_stop_type_is_rejected_before_network():
    from app.services.brokers import stock_coin_trade_gateway as gw
    with pytest.raises(gw.GatewayError, match="스탑"):
        gw.build_intent("005930.KS", "SELL", 1, 70000, client_order_id="stop-test", order_type="STOP_LIMIT")
