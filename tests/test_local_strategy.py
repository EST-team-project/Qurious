"""내 전략 선택은 개인 카드의 사본을 고정하며 외부 인증/증권사 주문에 의존하지 않는다."""
import asyncio
from copy import deepcopy
from datetime import date
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import BrokerSettings, Order, Portfolio
from app.routes import stocks
from app.services import local_strategy as local, strategy_card_store as store
from app.services import strategy_v2_execution as runner, auto_trade, strategy_loader, strategy_v2
from tests.test_strategy_card_store import FORM, U1, U2
from tests.test_strategy_v2_execution import runtime, user, next_bar  # noqa: F401


@pytest.fixture
def cards(tmp_path, monkeypatch):
    monkeypatch.setenv('STRATEGY_CARD_DIR', str(tmp_path))
    monkeypatch.setattr(local, 'market_for', lambda code: 'KOSPI')
    card_id, _ = store.save(U1, FORM, set())
    return card_id


def test_private_selection_is_frozen_and_not_accepted(cards):
    saved = local.snapshot(U1, cards)
    row = SimpleNamespace(quant_local_strategy=saved, quant_strategy_id=saved['spec']['strategy_id'], quant_strategy_version=2)
    assert local.selected(row, U1) == saved
    assert saved['test_only'] and 'acceptance' not in saved['spec']
    assert len(saved['spec']['strategy_id']) <= 40
    store.save(U1, {**FORM, 'short_window': 15}, set())
    assert local.selected(row, U1)['spec']['entry']['params']['short_window'] == 10
    assert local.snapshot(U1, cards)['spec']['strategy_id'] != saved['spec']['strategy_id']
    assert store.delete(U1, cards)
    assert local.selected(row, U1) == saved
    with pytest.raises(ValueError):
        local.selected(row, U2)
    with pytest.raises(ValueError):
        local.snapshot(U2, cards)


@pytest.mark.parametrize('change', [{'judge': 'intrabar'}, {'entry_mode': 'close', 'exit_mode': 'close'}, {'symbol': 'AAPL'}])
def test_unsupported_saved_card_is_visible_but_not_executable(cards, change):
    store.save(U1, {**FORM, **change}, set())
    result = local.summaries(U1)
    assert len(result) == 1 and not result[0]['executable'] and result[0]['reason']
    with pytest.raises(ValueError):
        local.snapshot(U1, cards)


def test_corrupt_snapshot_cannot_fall_back_to_another_strategy(cards):
    saved = local.snapshot(U1, cards)
    saved['spec']['position_sizing']['risk_pct'] = 5
    row = SimpleNamespace(quant_local_strategy=saved, quant_strategy_id=saved['spec']['strategy_id'], quant_strategy_version=2)
    with pytest.raises(ValueError):
        local.selected(row, U1)


dbtest = pytest.mark.skipif(not os.getenv('QURIOUS_TEST_DATABASE_URL'), reason='일회용 PostgreSQL 필요')


@dbtest
@pytest.mark.usefixtures('rebalance_db_schema')
def test_select_save_and_edit_preserves_snapshot_without_enabling(runtime, cards, monkeypatch):  # noqa: F811
    sessions, _ = runtime
    monkeypatch.setattr(stocks, 'audit', AsyncMock())
    async def scenario():
        uid = await user(sessions)
        card_id, _ = store.save(str(uid), FORM, set())
        body = stocks.QuantSettingsBody(strategy_card_id=card_id)
        async with sessions() as db:
            await stocks.save_quant_settings(body, {'id': str(uid)}, db)
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            pinned = deepcopy(row.quant_local_strategy)
            assert not row.quant_auto_enabled and row.quant_mode == 'paper'
        store.delete(str(uid), card_id)
        body = stocks.QuantSettingsBody(strategy_card_id=card_id, strategy_card_fingerprint=pinned['original_hash'], per_trade_budget=20000)
        async with sessions() as db:
            await stocks.save_quant_settings(body, {'id': str(uid)}, db)
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert row.quant_local_strategy == pinned and row.quant_per_trade_budget == 20000
        async with sessions() as db:
            db.add(Portfolio(user_id=uid, symbol='005930.KS', name='existing', book='QUANT', quantity=1, avg_price=100))
            await db.commit()
        async with sessions() as db:
            with pytest.raises(HTTPException) as exc:
                await stocks.save_quant_settings(stocks.QuantSettingsBody(), {'id': str(uid)}, db)
            assert exc.value.status_code == 409
            await db.rollback()
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert row.quant_local_strategy == pinned
    asyncio.run(scenario())


@dbtest
@pytest.mark.usefixtures('rebalance_db_schema')
def test_custom_card_runs_through_real_ledger_and_uses_own_rules(runtime, cards, monkeypatch):  # noqa: F811
    sessions, source = runtime
    original_inputs = runner.inputs
    monkeypatch.setattr(runner, 'inputs', lambda *args: original_inputs())
    monkeypatch.setattr(strategy_loader, 'get_strategy', AsyncMock(side_effect=AssertionError('no external provider')))
    persisted = AsyncMock()
    monkeypatch.setattr(auto_trade, '_persist_cycle', persisted)
    async def scenario():
        uid = await user(sessions, quant_auto_enabled=True)
        form = {**FORM, 'symbol': '000660', 'risk_pct': 2, 'take_rr': 2.5}
        card_id, _ = store.save(str(uid), form, set())
        saved = local.snapshot(str(uid), card_id)
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            row.quant_local_strategy = saved
            row.quant_strategy_id = saved['spec']['strategy_id']
            row.quant_strategy_version = 2
            await db.commit()
        await auto_trade._run_quant_cycle(str(uid))
        assert persisted.call_args.args[1]['strategy_source'] == 'user_card'
        assert persisted.call_args.args[1]['v2']['status'] == 'initialized'
        next_bar(source, date(2026,8,30), 195, 160)
        await auto_trade._run_quant_cycle(str(uid))
        bought = persisted.call_args.args[1]['v2']
        assert bought['status'] == 'filled' and bought['quantity'] > 120, bought
        assert bought['decision']['action'] == 'SELL'
        assert (await runner.run(uid, execute=True, spec=saved['spec'], symbol=saved['symbol']))['status'] == 'duplicate'
        next_bar(source, date(2026,8,31), 181, 180)
        sold = await runner.run(uid, execute=True, spec=saved['spec'], symbol=saved['symbol'])
        assert sold['status'] == 'filled' and sold['quantity'] == bought['quantity'], sold
        async with sessions() as db:
            orders = (await db.scalars(select(Order).where(Order.user_id == uid))).all()
            assert len(orders) == 2 and all(o.symbol == '000660.KS' and o.source == 'QUANT' for o in orders)
            assert await db.scalar(select(Portfolio.id).where(Portfolio.user_id == uid)) is None
    asyncio.run(scenario())


def test_live_local_selection_rejected_before_account_mutation(cards, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, 'STRATEGY_SPEC_SOURCE', 'remote')
    create = AsyncMock()
    monkeypatch.setattr(stocks, '_get_or_create_broker_settings_row', create)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stocks.save_quant_settings(stocks.QuantSettingsBody(mode='live', strategy_card_id=cards), {'id': U1}, None))
    assert exc.value.status_code == 422
    create.assert_not_awaited()


@pytest.mark.parametrize('bad', [None, [], True, {'entry': []}])
def test_malformed_card_rejected(bad):
    with pytest.raises(ValueError):
        strategy_v2.validate_card(bad)


def test_custom_symbol_cannot_use_an_older_bar_than_ready_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.rebalance_daily, 'readiness', lambda: {'ready': True, 'data_as_of': '2026-10-30'})
    monkeypatch.setattr(runner.collector_db, 'db_path', lambda: tmp_path/'collector.db')
    monkeypatch.setattr(strategy_v2, 'load_bars', lambda *a, **kw: [{'date':'2026-10-29'}])
    with pytest.raises(runner.control.Rejected, match='최신 확정'):
        runner.inputs(strategy_v2.CONTRACT, '005930.KS')


@dbtest
@pytest.mark.usefixtures('rebalance_db_schema')
def test_switch_rejected_while_enabled_or_account_busy(runtime, cards, monkeypatch):  # noqa: F811
    sessions, _ = runtime
    monkeypatch.setattr(stocks, 'audit', AsyncMock())
    async def scenario():
        uid = await user(sessions, quant_auto_enabled=True)
        card_id, _ = store.save(str(uid), FORM, set())
        body = stocks.QuantSettingsBody(strategy_card_id=card_id)
        async with sessions() as db:
            with pytest.raises(HTTPException) as exc:
                await stocks.save_quant_settings(body, {'id':str(uid)}, db)
            assert exc.value.status_code == 409 and '중지' in exc.value.detail
            await db.rollback()
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            row.quant_auto_enabled = False
            await db.commit()
        async with sessions() as owner:
            async with runner.control.account_lock(owner, runner.context(uid)['account_ref']) as acquired:
                assert acquired
                async with sessions() as db:
                    with pytest.raises(HTTPException) as exc:
                        await stocks.save_quant_settings(body, {'id':str(uid)}, db)
                    assert exc.value.status_code == 409 and '실행 중' in exc.value.detail
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert row.quant_local_strategy is None
    asyncio.run(scenario())
