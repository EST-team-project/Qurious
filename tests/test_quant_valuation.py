"""#284: 같은 장부의 평가 일치, 가격 누락 차단, 출처·날짜 보존."""
import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.models import QuantVirtualAccount, Portfolio
from app.services import quant_valuation as v


class DB:
    def __init__(self):
        self.account = SimpleNamespace(cash_balance=1000, initial_capital=2000)
        self.positions = [SimpleNamespace(symbol='005930.KS', quantity=2, avg_price=1)]

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]['entity']
        if entity is QuantVirtualAccount:
            return SimpleNamespace(scalar_one_or_none=lambda: self.account)
        assert entity is Portfolio
        assert 'QUANT' in stmt.compile().params.values()
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.positions))


def quoted(price=600, source='kis_user', as_of='2026-10-27 14:00'):
    return {'price': price, 'source': source, 'as_of': as_of, 'fetched_at': '2026-10-27 14:00:00',
            'label': '증권사 조회 · 14:00:00', 'fallback': []}


def test_cycle_snapshot_risk_screen_and_dashboard_use_identical_equity(monkeypatch):
    from app.routes import stocks, dashboard
    db, uid = DB(), uuid.uuid4()
    query = AsyncMock(return_value=quoted())
    monkeypatch.setattr(v.quote_now, 'quote_now', query)
    monkeypatch.setattr(stocks, '_get_broker_settings_row', AsyncMock(return_value=None))
    monkeypatch.setattr(stocks.auto_trade, 'get_status', AsyncMock(return_value={}))
    start = AsyncMock(side_effect=lambda key, equity: equity)
    monkeypatch.setattr(stocks.risk_guard, 'day_start_equity', start)
    monkeypatch.setattr(stocks.risk_guard, 'orders_today', AsyncMock(return_value=0))
    async def go():
        snap = await v.snapshot(db, uid)
        status = await stocks.quant_risk_status({'id': str(uid)}, db)
        tab = await dashboard.quant_tab(db, uid)
        assert snap['equity'] == status['current_equity'] == tab['total'] == 2200
        assert status['valuation'] == tab['valuation'] == v.basis(snap)
        assert start.call_args.args == (f'{uid}:quant', 2200)
        assert all(c.kwargs['user_id'] == uid for c in query.call_args_list)
    asyncio.run(go())


def test_missing_holding_price_hides_pnl_and_does_not_initialize_day_baseline(monkeypatch):
    from app.routes import stocks, dashboard
    db, uid = DB(), uuid.uuid4()
    monkeypatch.setattr(v.quote_now, 'quote_now', AsyncMock(side_effect=RuntimeError('offline')))
    monkeypatch.setattr(stocks, '_get_broker_settings_row', AsyncMock(return_value=None))
    monkeypatch.setattr(stocks.auto_trade, 'get_status', AsyncMock(return_value={}))
    start = AsyncMock()
    monkeypatch.setattr(stocks.risk_guard, 'day_start_equity', start)
    monkeypatch.setattr(stocks.risk_guard, 'orders_today', AsyncMock(return_value=0))
    async def go():
        status = await stocks.quant_risk_status({'id': str(uid)}, db)
        tab = await dashboard.quant_tab(db, uid)
        assert status['current_equity'] is None and status['day_pnl_pct'] is None
        assert tab['total'] is None and tab['invested'] is None and tab['pnl'] is None
        assert not status['valuation']['complete'] and '005930.KS' in tab['note']
    asyncio.run(go())
    start.assert_not_awaited()


def test_explicit_dated_close_is_preserved_instead_of_labelled_current(monkeypatch):
    q = quoted(source='collector', as_of='2026-10-23')
    q['label'] = '10월 23일 종가'
    fetch = AsyncMock(return_value=q)
    monkeypatch.setattr(v.quote_now, 'quote_now', fetch)
    result = asyncio.run(v.quote(DB(), uuid.uuid4(), '005930.KS', fresh=True))
    assert result['source'] == 'collector' and result['as_of'] == '2026-10-23'
    assert result['label'] == '10월 23일 종가' and fetch.call_args.kwargs['fresh']


@pytest.mark.parametrize('field,value', [('price', float('nan')), ('price', float('inf')), ('price', 0),
                                        ('price', True), ('source', None), ('as_of', None), ('label', '')])
def test_invalid_price_or_missing_basis_fails_closed(monkeypatch, field, value):
    q = quoted(); q[field] = value
    monkeypatch.setattr(v.quote_now, 'quote_now', AsyncMock(return_value=q))
    with pytest.raises(ValueError, match='가격·출처'):
        asyncio.run(v.quote(DB(), uuid.uuid4(), '005930.KS'))


@pytest.mark.skipif(not os.getenv('QURIOUS_TEST_DATABASE_URL'), reason='일회용 PostgreSQL 필요')
@pytest.mark.usefixtures('rebalance_db_schema')
@pytest.mark.parametrize('side,quantity,remaining', [('sell', 1, 1), ('sell', 2, 0), ('buy', 1, 3)])
def test_snapshot_refreshes_positions_and_cash_after_other_session_fill(monkeypatch, side, quantity, remaining):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.models import User
    from app.services.auto_trade import _execute_virtual_trade

    monkeypatch.setattr(v.quote_now, 'quote_now', AsyncMock(return_value=quoted()))

    async def scenario():
        engine = create_async_engine(os.environ['QURIOUS_TEST_DATABASE_URL'], poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        uid = uuid.uuid4()
        try:
            async with sessions() as db:
                db.add(User(id=uid, name='valuation test', email=f'{uid}@example.test',
                            password_hash='test', client_id=uid.hex))
                await db.flush()
                db.add(QuantVirtualAccount(user_id=uid, cash_balance=10000, initial_capital=11200))
                db.add(Portfolio(user_id=uid, book='QUANT', symbol='005930.KS', name='삼성전자',
                                 quantity=2, avg_price=600))
                await db.commit()
            async with sessions() as reader:
                # Keep both ORM objects alive just as the executing cycle does.
                cached_account = await reader.scalar(select(QuantVirtualAccount).where(QuantVirtualAccount.user_id == uid))
                cached_position = await reader.scalar(select(Portfolio).where(Portfolio.user_id == uid))
                assert (await v.snapshot(reader, uid))['equity'] == 11200
                async with sessions() as writer:
                    fill = await _execute_virtual_trade(writer, uid, '005930.KS', '삼성전자', side,
                                                        600, quantity, 'isolated valuation regression')
                    assert fill['status'] == 'filled'
                assert cached_account.cash_balance == 10000 and cached_position.quantity == 2
                refreshed = await v.snapshot(reader, uid)
                async with sessions() as independent:
                    fresh = await v.snapshot(independent, uid)
                assert refreshed == fresh
                assert refreshed['cash'] == pytest.approx(fill['cash_balance'], abs=.005)
                assert refreshed['values'].get('005930.KS', 0) == remaining * 600
                assert refreshed['equity'] == pytest.approx(fill['cash_balance'] + remaining * 600, abs=.005)
        finally:
            await engine.dispose()

    asyncio.run(scenario())
