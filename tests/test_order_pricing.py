"""실제 공통 관문에서 최종 조회 가격·위험 수량·영속 근거를 함께 검증한다."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from app.models import BrokerSettings, OrderIntent
from app.services import auto_trade, kis_execution, order_preflight, live_ownership, execution_control as control
from app.services.execution_policy import risk_quantity
from app.services import trading_cost
from tests.test_execution_control import runtime, user

pytestmark = [pytest.mark.skipif(not os.getenv('QURIOUS_TEST_DATABASE_URL'), reason='일회용 PG 필요'),
              pytest.mark.usefixtures('rebalance_db_schema')]


@pytest.mark.parametrize('current,broker_cap,unknown', [(5000, 1000, False), (20000, 1000, False),
                                                       (5000, 1, False), (5000, 1000, True)])
def test_final_price_resizes_risk_quantity_and_persists_basis(runtime, monkeypatch, current, broker_cap, unknown):
    client = SimpleNamespace(paper=True, get_price=AsyncMock(return_value=SimpleNamespace(current=current)),
        get_buying_power=AsyncMock(return_value={'amount': 1000000, 'quantity': broker_cap}))
    monkeypatch.setattr(kis_execution, 'client_for', lambda row: (client, SimpleNamespace(account_no='test')))
    monkeypatch.setattr(order_preflight.gateway, 'is_configured', lambda: False)
    monkeypatch.setattr(kis_execution, 'account_snapshot', AsyncMock(return_value={'cash': 1000000, 'equity': 1000000, 'holdings': {}}))
    monkeypatch.setattr(live_ownership, 'reconcile', AsyncMock(return_value=([], {})))
    monkeypatch.setattr(live_ownership, 'account_ref', lambda *args: 'a' * 64)
    sent = []
    async def send(db, uid, row, mode, symbol, name, action, price, quantity, reason):
        sent.append((price, quantity))
        if unknown:
            raise RuntimeError('response lost')
        return {'status': 'submitted', 'price': price, 'quantity': quantity}
    monkeypatch.setattr(auto_trade, '_execute_trade_unchecked', send)
    async def scenario():
        uid = await user(runtime, quant_mode='live', quant_per_trade_budget=1000000, quant_buy_ratio=1,
                         quant_execution_policy={'size_kind':'risk_pct', 'risk_pct':1, 'stop_loss_pct':5})
        async with runtime() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            result = await auto_trade._execute_trade(db, uid, row, 'live', '005930.KS', '삼성전자', 'buy',
                10000, 19, 'test', decision={'signal_key':'2026-10-28', 'input_hash':'test',
                'signal_price':10000, 'signal_as_of':'2026-10-28', 'size_from_budget':True})
            sizing = risk_quantity(equity=1000000, cash=1000000, price=current, stop_price=current*.95,
                budget=1000000, existing_value=0, position_cap_pct=100, risk_pct=1, slippage_bps=10,
                when=trading_cost.today_kst())
            expected = min(sizing['quantity'], broker_cap)
            assert result['status'] == ('unknown' if unknown else 'submitted'), result
            assert sent == [(current, expected)]
            saved = await db.get(OrderIntent, result['intent_id'])
            assert saved.result['price_basis'] == result['price_basis']
            assert saved.result['price_basis']['quote']['source'] == 'kis_user'
            assert saved.result['price_basis']['quote']['fetched_at']
            assert saved.result['price_basis']['signal_price'] == 10000
            assert saved.result['price_basis']['sizing']['estimated_loss'] <= 10000
            assert saved.result['price_basis']['sizing']['estimated_cash'] == pytest.approx(
                sizing['estimated_cash'] * expected / sizing['quantity'])
    asyncio.run(scenario())


@pytest.mark.parametrize('case,expected', [('quote_error', 'PRICE_UNAVAILABLE'),
    ('recovered', 'STOP_NOT_CONFIRMED'), ('delayed', 'PRICE_UNAVAILABLE'), ('already_held', 'ALREADY_HELD')])
def test_final_preflight_refuses_unconfirmed_price_stop_and_extra_entry(runtime, monkeypatch, case, expected):
    client = SimpleNamespace(paper=True, get_price=AsyncMock(return_value=SimpleNamespace(current=10000)),
        get_buying_power=AsyncMock(return_value={'amount': 1000000, 'quantity': 1000}))
    if case == 'quote_error':
        client.get_price.side_effect = RuntimeError('price unavailable')
    monkeypatch.setattr(kis_execution, 'client_for', lambda row: (client, SimpleNamespace(account_no='test')))
    monkeypatch.setattr(kis_execution, 'account_snapshot', AsyncMock(return_value={
        'cash': 900000, 'equity': 1000000, 'holdings': {'005930.KS': {'quantity': 10, 'value': 100000}}}))
    monkeypatch.setattr(live_ownership, 'reconcile', AsyncMock(return_value=(
        [SimpleNamespace(symbol='005930.KS', quantity=10, avg_price=10000)], {})))
    monkeypatch.setattr(live_ownership, 'account_ref', lambda *args: 'b' * 64)
    if case == 'delayed':
        monkeypatch.setattr(order_preflight, 'current_quote', AsyncMock(return_value={
            'price': 9000, 'source': 'collector', 'as_of': '2026-10-28'}))
    sender = AsyncMock()
    monkeypatch.setattr(auto_trade, '_execute_trade_unchecked', sender)
    async def scenario():
        uid = await user(runtime, quant_mode='live', quant_execution_policy={
            'size_kind': 'risk_pct', 'risk_pct': 1, 'stop_loss_pct': 5})
        async with runtime() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            result = await auto_trade._execute_trade(db, uid, row, 'live', '005930.KS', '삼성전자',
                'buy' if case == 'already_held' else 'sell', 9000, 10, 'test',
                decision={'signal_key': '2026-10-28', 'input_hash': 'test', 'risk_stop': case != 'already_held'})
            assert result['code'] == expected, result
        sender.assert_not_awaited()
    asyncio.run(scenario())


def test_policy_changed_during_prepare_blocks_send(runtime, monkeypatch):
    async def scenario():
        uid = await user(runtime)
        from tests.test_execution_control import intent, prepare
        async def changed(db):
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            signature = control.settings_signature(row)
            async with runtime() as other:
                latest = await other.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                latest.quant_execution_policy = {'size_kind': 'risk_pct', 'risk_pct': 2}
                await other.commit()
            return {**await prepare(db), 'settings': signature}
        sender = AsyncMock()
        result = await control.execute(intent(uid), 1, changed, sender)
        assert result['code'] == 'SETTINGS_CHANGED'
        sender.assert_not_awaited()
    asyncio.run(scenario())
