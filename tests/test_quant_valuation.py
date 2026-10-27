"""#284: 같은 장부의 평가 일치, 가격 누락 차단, 출처·날짜 보존."""
import asyncio
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
