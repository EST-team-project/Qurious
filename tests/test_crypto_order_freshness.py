import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import paper_trading as pt


def test_crypto_buy_rejects_stale_quote_before_account_mutation(monkeypatch):
    async def scenario():
        now = datetime.now(timezone.utc).isoformat()
        monkeypatch.setattr(
            pt, "upbit_tickers",
            AsyncMock(return_value=[{
                "market": "KRW-BTC",
                "price": 100_000_000,
                "as_of": now,
                "_price_audit": {"cache_age_sec": 31},
            }])
        )
        monkeypatch.setattr(
            pt, "upbit_market_info",
            AsyncMock(return_value={
                "market": "KRW-BTC",
                "koreanName": "비트코인",
            })
        )
        get_account = AsyncMock()
        monkeypatch.setattr(pt, "get_account", get_account)
        db = SimpleNamespace(add=Mock())

        with pytest.raises(pt.PaperTradeError):
            await pt.crypto_buy(db, "test-user", "KRW-BTC", 1000)

        get_account.assert_not_awaited()
        db.add.assert_not_called()

    asyncio.run(scenario())


def test_crypto_sell_rejects_stale_quote_without_holding_mutation(monkeypatch):
    async def scenario():
        now = datetime.now(timezone.utc).isoformat()
        monkeypatch.setattr(
            pt, "upbit_tickers",
            AsyncMock(return_value=[{
                "market": "KRW-BTC",
                "price": 100_000_000,
                "as_of": now,
                "_price_audit": {"cache_age_sec": 31},
            }])
        )

        account = SimpleNamespace(cash=100_000)
        holding = SimpleNamespace(
            quantity=2.0,
            total_krw=200_000,
            korean_name="비트코인",
        )
        monkeypatch.setattr(
            pt, "get_account", AsyncMock(return_value=account)
        )
        monkeypatch.setattr(
            pt, "_crypto_holding", AsyncMock(return_value=holding)
        )
        db = SimpleNamespace(add=Mock(), delete=AsyncMock())

        with pytest.raises(pt.PaperTradeError):
            await pt.crypto_sell(db, "test-user", "KRW-BTC", 1.0)

        assert account.cash == 100_000
        assert holding.quantity == 2.0
        assert holding.total_krw == 200_000
        db.add.assert_not_called()
        db.delete.assert_not_awaited()

    asyncio.run(scenario())
