import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.models import CryptoHolding, CryptoOrder
from app.services import crypto_trading_cost as ct
from app.services import paper_trading as pt


def _market():
    return {"market": "KRW-BTC", "koreanName": "비트코인"}


def test_buy_records_fee_and_slippage_in_cash_and_cost_basis(monkeypatch):
    async def scenario():
        uid = uuid.uuid4()
        account = SimpleNamespace(cash=20_000_000.0)
        db = SimpleNamespace(add=Mock(), delete=AsyncMock())

        monkeypatch.setattr(pt, "upbit_market_info", AsyncMock(return_value=_market()))
        monkeypatch.setattr(pt, "upbit_trade_price", AsyncMock(return_value=100_000_000.0))
        monkeypatch.setattr(pt, "get_account", AsyncMock(return_value=account))
        monkeypatch.setattr(pt, "_crypto_holding", AsyncMock(return_value=None))

        result = await pt.crypto_buy(db, uid, "KRW-BTC", 10_000_000.0)

        quantity = round(10_000_000 / 100_100_000, 8)
        expected = ct.order_costs("BUY", 100_000_000, quantity)
        holding = next(x for x in db.add.call_args_list[0].args if isinstance(x, CryptoHolding))
        order = next(c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], CryptoOrder))

        assert order.quantity == quantity
        assert order.reference_price == 100_000_000
        assert order.price == pytest.approx(expected.execution_price)
        assert order.commission == pytest.approx(expected.commission)
        assert order.net_amount == pytest.approx(expected.net_amount)
        assert order.cost_basis == "estimated"
        assert holding.total_krw == pytest.approx(expected.net_amount)
        assert holding.avg_price == pytest.approx(expected.net_amount / quantity)
        assert account.cash == pytest.approx(20_000_000 - expected.net_amount)
        assert result["netAmount"] == pytest.approx(expected.net_amount)

    asyncio.run(scenario())


def test_buy_rejects_when_commission_exceeds_available_cash(monkeypatch):
    async def scenario():
        uid = uuid.uuid4()
        account = SimpleNamespace(cash=10_000_000.0)
        db = SimpleNamespace(add=Mock(), delete=AsyncMock())

        monkeypatch.setattr(pt, "upbit_market_info", AsyncMock(return_value=_market()))
        monkeypatch.setattr(pt, "upbit_trade_price", AsyncMock(return_value=100_000_000.0))
        monkeypatch.setattr(pt, "get_account", AsyncMock(return_value=account))
        monkeypatch.setattr(pt, "_crypto_holding", AsyncMock())

        with pytest.raises(pt.PaperTradeError, match="수수료"):
            await pt.crypto_buy(db, uid, "KRW-BTC", 10_000_000.0)

        db.add.assert_not_called()
        assert account.cash == 10_000_000.0
        pt._crypto_holding.assert_not_awaited()

    asyncio.run(scenario())


def test_partial_sell_allocates_original_cost_and_records_realized_pnl(monkeypatch):
    async def scenario():
        uid = uuid.uuid4()
        account = SimpleNamespace(cash=100_000.0)
        holding = SimpleNamespace(
            quantity=2.0,
            total_krw=20_000_000.0,
            avg_price=10_000_000.0,
            korean_name="비트코인",
        )
        db = SimpleNamespace(add=Mock(), delete=AsyncMock())

        monkeypatch.setattr(pt, "get_account", AsyncMock(return_value=account))
        monkeypatch.setattr(pt, "_crypto_holding", AsyncMock(return_value=holding))
        monkeypatch.setattr(pt, "upbit_trade_price", AsyncMock(return_value=100_000_000.0))

        result = await pt.crypto_sell(db, uid, "KRW-BTC", 0.5)
        expected = ct.order_costs("SELL", 100_000_000, 0.5)
        allocated = 5_000_000.0

        order = next(c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], CryptoOrder))
        assert order.price == pytest.approx(expected.execution_price)
        assert order.commission == pytest.approx(expected.commission)
        assert order.net_amount == pytest.approx(expected.net_amount)
        assert order.allocated_cost_basis == pytest.approx(allocated)
        assert order.realized_pnl == pytest.approx(expected.net_amount - allocated)
        assert holding.quantity == pytest.approx(1.5)
        assert holding.total_krw == pytest.approx(15_000_000)
        assert account.cash == pytest.approx(100_000 + expected.net_amount)
        assert result["realizedPnl"] == pytest.approx(expected.net_amount - allocated)
        db.delete.assert_not_awaited()

    asyncio.run(scenario())


def test_full_sell_allocates_all_remaining_cost_basis(monkeypatch):
    async def scenario():
        uid = uuid.uuid4()
        account = SimpleNamespace(cash=0.0)
        holding = SimpleNamespace(
            quantity=0.25,
            total_krw=5_000_000.0,
            avg_price=20_000_000.0,
            korean_name="비트코인",
        )
        db = SimpleNamespace(add=Mock(), delete=AsyncMock())

        monkeypatch.setattr(pt, "get_account", AsyncMock(return_value=account))
        monkeypatch.setattr(pt, "_crypto_holding", AsyncMock(return_value=holding))
        monkeypatch.setattr(pt, "upbit_trade_price", AsyncMock(return_value=100_000_000.0))

        await pt.crypto_sell(db, uid, "KRW-BTC", 0.25)

        order = next(c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], CryptoOrder))
        assert order.allocated_cost_basis == pytest.approx(5_000_000)
        assert order.realized_pnl is not None
        db.delete.assert_awaited_once_with(holding)

    asyncio.run(scenario())


def test_preview_and_order_use_same_cost_calculation(monkeypatch):
    async def scenario():
        uid = uuid.uuid4()
        account = SimpleNamespace(cash=20_000_000.0)
        db = SimpleNamespace()
        monkeypatch.setattr(pt, "upbit_market_info", AsyncMock(return_value=_market()))
        monkeypatch.setattr(pt, "upbit_trade_price", AsyncMock(return_value=100_000_000.0))
        monkeypatch.setattr(pt, "get_account", AsyncMock(return_value=account))
        monkeypatch.setattr(pt, "_crypto_holding", AsyncMock(return_value=None))

        preview = await pt.crypto_preview(
            db, uid, "KRW-BTC", "BUY", buy_krw=10_000_000
        )
        quantity = round(10_000_000 / 100_100_000, 8)
        expected = ct.order_costs("BUY", 100_000_000, quantity)

        assert preview["estimatedPrice"] == pytest.approx(expected.execution_price)
        assert preview["estimatedCommission"] == pytest.approx(expected.commission)
        assert preview["estimatedNetAmount"] == pytest.approx(expected.net_amount)
        assert preview["executable"] is True

    asyncio.run(scenario())
