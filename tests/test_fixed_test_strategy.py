"""고정 시험 입력은 합격 표시나 증권사 주문 경로로 넘어가지 않는다."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from fastapi import HTTPException
from app.config import settings
from app.routes import stocks
from app.services import auto_trade, order_preflight


@pytest.fixture(autouse=True)
def fixed(monkeypatch):
    monkeypatch.setattr(settings, 'STRATEGY_SPEC_SOURCE', 'fixed_test')


def test_strategy_list_distinguishes_test_input():
    result = asyncio.run(stocks.list_quant_strategies({'id': str(uuid.uuid4())}))
    assert result['configured'] and result['test_only'] and result['source'] == 'fixed_test'
    assert result['strategies'][0]['test_only']


def test_live_settings_are_rejected_before_account_mutation(monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(stocks, '_get_or_create_broker_settings_row', create)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stocks.save_quant_settings(stocks.QuantSettingsBody(mode='live',
            strategy_id='ma_cross_20_60', strategy_version=1), {'id': str(uuid.uuid4())}, None))
    assert exc.value.status_code == 422
    create.assert_not_awaited()


def test_paper_settings_save_pins_version_without_enabling_automation(monkeypatch):
    row = SimpleNamespace(quant_auto_enabled=False)
    monkeypatch.setattr(stocks, '_get_or_create_broker_settings_row', AsyncMock(return_value=row))
    monkeypatch.setattr(stocks, '_apply_credentials', lambda *args: None)
    monkeypatch.setattr(stocks, 'audit', AsyncMock())
    db = SimpleNamespace(commit=AsyncMock())
    body = stocks.QuantSettingsBody(mode='paper', strategy_id='ma_cross_20_60', strategy_version=1)
    asyncio.run(stocks.save_quant_settings(body, {'id': str(uuid.uuid4())}, db))
    assert (row.quant_strategy_id, row.quant_strategy_version, row.quant_mode) == ('ma_cross_20_60', 1, 'paper')
    assert not row.quant_auto_enabled
    db.commit.assert_awaited_once()


def test_order_guard_rejects_live_before_account_or_broker_access(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(order_preflight.control, 'execute', execute)
    result = asyncio.run(order_preflight.execute_quant(None, uuid.uuid4(), None, 'live',
        '005930.KS', '삼성전자', 'buy', 1, 'test', {}))
    assert result['code'] == 'TEST_STRATEGY_PAPER_ONLY'
    execute.assert_not_awaited()


def test_scheduled_live_cycle_blocks_before_quotes_or_orders(monkeypatch):
    row = SimpleNamespace(quant_mode='live', paper=True, quant_execution_policy={})
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def execute(self, query):
            return SimpleNamespace(scalar_one_or_none=lambda: row)
    monkeypatch.setattr(auto_trade, 'get_session_factory', lambda: Session)
    saved = AsyncMock()
    quote = AsyncMock()
    sender = AsyncMock()
    monkeypatch.setattr(auto_trade, '_persist_cycle', saved)
    monkeypatch.setattr(auto_trade, 'get_quant_indicators', quote)
    monkeypatch.setattr(auto_trade, '_place_live_order', sender)
    asyncio.run(auto_trade._run_quant_cycle(str(uuid.uuid4())))
    log = saved.call_args.args[1]
    assert log['execution_state'] == 'FAILED' and log['test_only'] and log['strategy_source'] == 'fixed_test'
    quote.assert_not_awaited()
    sender.assert_not_awaited()
