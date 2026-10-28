"""#212: 실패/접수는 체결이 아니며 KIS 주문은 가상 보유·현금을 바꾸지 않는다."""
import asyncio
import copy
import json
import os
import time
import uuid
import subprocess
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import settings
from app.models import BrokerSettings, LiveOrder, Order, Portfolio, QuantVirtualAccount, User
from app.services import auto_trade, kis_execution
from app.services.brokers import kis_token
from app.services.brokers.kis import KISClient, OrderSubmissionUnknown
from app.services.trade_outcome import describe_trade


class Store:
    def __init__(self): self.data = {}; self.expires = {}
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def get(self, key):
        if self.expires.get(key, 0) <= time.time(): self.data.pop(key, None)
        return self.data.get(key)
    async def set(self, key, value, nx=False, ex=60):
        if nx and await self.get(key): return False
        self.data[key], self.expires[key] = value, time.time() + ex
        return True


@pytest.fixture
def token_store(monkeypatch):
    store = Store()
    monkeypatch.setattr(kis_token.redis, "from_url", lambda *a, **kw: store)
    return store


def transport(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))


def test_two_orders_share_token_and_expired_token_is_refreshed(monkeypatch, token_store):
    calls = []
    def handler(req):
        calls.append(req.url.path)
        if req.url.path.endswith('tokenP'):
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        return httpx.Response(200, json={"rt_cd": "0", "output": {"ODNO": "123"}})
    transport(monkeypatch, handler)
    async def run():
        a, b = KISClient('a', 's'), KISClient('a', 's')
        await asyncio.gather(a.place_order('1234567801', '005930', 'buy', 1, 100), b.place_order('1234567801', '000660', 'buy', 1, 100))
        assert calls.count('/oauth2/tokenP') == 1
        key = kis_token.cache_key(a.base_url, 'a', 's')
        token_store.expires[key] = token_store.expires[key + ':issue'] = 0
        a._token_exp = datetime(2000, 1, 1, tzinfo=timezone.utc)
        await a.place_order('1234567801', '005930', 'buy', 1, 100)
        assert calls.count('/oauth2/tokenP') == 2
    asyncio.run(run())


def test_tokens_are_isolated_by_environment_key_and_secret(monkeypatch, token_store):
    calls = []
    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(200, json={"access_token": str(len(calls)), "expires_in": 86400})
    transport(monkeypatch, handler)
    async def run():
        clients = [KISClient('a', 's'), KISClient('a', 's', paper=False), KISClient('b', 's'), KISClient('a', 'rotated')]
        values = await asyncio.gather(*(c.get_token() for c in clients))
        assert len({v.access_token for v in values}) == 4
        assert all('rotated' not in k and ':a:' not in k for k in token_store.data)
    asyncio.run(run())


def test_token_403_never_sends_order_or_reissues_immediately(monkeypatch, token_store):
    calls = []
    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(403, json={"error_code": "EGW00133"})
    transport(monkeypatch, handler)
    monkeypatch.setattr(kis_token.asyncio, 'sleep', AsyncMock())
    for _ in range(2):
        with pytest.raises(kis_token.KISTokenError):
            asyncio.run(KISClient('a', 's').place_order('1234567801', '005930', 'buy', 1, 100))
    assert calls == ['/oauth2/tokenP']


@pytest.mark.parametrize('response', ['timeout', 'invalid_json', 'missing_result'])
def test_order_response_lost_is_unknown_and_not_retried(monkeypatch, token_store, response):
    calls = []
    def handler(req):
        calls.append(req.url.path)
        if req.url.path.endswith('tokenP'):
            return httpx.Response(200, json={"access_token": "test", "expires_in": 86400})
        if response == 'invalid_json': return httpx.Response(200, text='<html>upstream error</html>')
        if response == 'missing_result': return httpx.Response(200, json={})
        raise httpx.ReadTimeout('response lost', request=req)
    transport(monkeypatch, handler)
    with pytest.raises(OrderSubmissionUnknown):
        asyncio.run(KISClient('a', 's').place_order('1234567801', '005930', 'buy', 1, 100))
    assert len(calls) == 2


def test_token_store_outage_blocks_issuance(monkeypatch):
    from redis.exceptions import ConnectionError
    def unavailable(*args, **kwargs): raise ConnectionError('offline')
    monkeypatch.setattr(kis_token.redis, 'from_url', unavailable)
    issue = AsyncMock()
    with pytest.raises(kis_token.KISTokenError):
        asyncio.run(kis_token.shared_token('test', issue))
    issue.assert_not_awaited()


@pytest.mark.skipif(not os.getenv('QURIOUS_TEST_REDIS_URL'), reason='격리 Redis 필요')
def test_real_redis_shares_token_across_concurrent_calls_and_processes(monkeypatch):
    monkeypatch.setattr(settings, 'REDIS_URL', os.environ['QURIOUS_TEST_REDIS_URL'])
    key = 'issue212-test:' + uuid.uuid4().hex
    calls = []
    async def issue():
        calls.append(1)
        await asyncio.sleep(0.05)
        return {'token': 'isolated-dummy-token', 'expires_at': time.time() + 3600}
    async def run():
        results = await asyncio.gather(*(kis_token.shared_token(key, issue) for _ in range(8)))
        assert all(x['token'] == 'isolated-dummy-token' for x in results)
    try:
        asyncio.run(run())
        assert len(calls) == 1
        script = '''import asyncio,os,sys
from app.config import settings
from app.services.brokers.kis_token import shared_token
settings.REDIS_URL = os.environ['QURIOUS_TEST_REDIS_URL']
async def forbidden(): raise AssertionError('second process reissued token')
assert asyncio.run(shared_token(sys.argv[1], forbidden))['token'] == 'isolated-dummy-token'
'''
        subprocess.run([sys.executable, '-c', script, key], check=True, capture_output=True, text=True)
    finally:
        async def cleanup():
            async with kis_token.redis.from_url(settings.REDIS_URL) as store:
                await store.delete(key, key + ':issue')
        asyncio.run(cleanup())


@pytest.mark.parametrize('live,expected', [
    ({'status': 'error', 'error': '403 Forbidden /oauth2/tokenP'}, 'broker_failed'),
    ({'status': 'submitted'}, 'broker_submitted'),
    ({'status': 'error', 'code': 'GATEWAY_UNREACHABLE'}, 'broker_unknown'),
    ({'status': 'skipped', 'reason': 'market_closed'}, 'broker_skipped'),
])
def test_old_filled_logs_are_never_broker_fill_evidence(live, expected):
    trade = {'status': 'filled', 'live_order': live}
    out = describe_trade(trade, 'live')
    assert out['status'] == expected and out['virtual_status'] == 'filled'
    assert '403 Forbidden' not in out['detail']
    assert describe_trade({'status': 'filled'}, 'paper')['status'] == 'virtual_filled'


def test_status_projects_confirmed_fill_without_mutating_cached_log(monkeypatch):
    uid = uuid.uuid4()
    source = {'cycles': [{'time': 'now', 'settings': {'mode': 'live'}, 'trades': [
        {'status': 'submitted', 'virtual_status': 'not_recorded', 'live_order': {'status': 'submitted', 'client_order_id': 'own'}}]}]}
    original = copy.deepcopy(source)
    monkeypatch.setattr(auto_trade, 'is_enabled', AsyncMock(return_value=True))
    monkeypatch.setattr(auto_trade, 'cache_get', AsyncMock(return_value=source))
    class DB:
        async def execute(self, stmt):
            params = stmt.compile().params
            assert uid in params.values() and ['own'] in params.values()
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [SimpleNamespace(
                client_order_id='own', status='FILLED', filled_quantity=1, avg_filled_price=217400)]))
    out = asyncio.run(auto_trade.get_status(DB(), uid))
    trade = out['log'][0]['trades'][0]
    assert trade['status'] == 'broker_filled' and trade['execution']['filled_quantity'] == 1
    assert trade['virtual_status'] == 'not_recorded' and source == original


@pytest.mark.parametrize('side', ['buy', 'sell'])
@pytest.mark.parametrize('result', ['success', 'rejected', 'unknown'])
@pytest.mark.skipif(not os.getenv('QURIOUS_TEST_DATABASE_URL'), reason='격리 PostgreSQL 필요')
def test_kis_order_does_not_change_virtual_book(monkeypatch, rebalance_db_schema, side, result):
    from sqlalchemy import select, func
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    uid = uuid.uuid4()
    engine = create_async_engine(os.environ['QURIOUS_TEST_DATABASE_URL'], poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(settings, 'STOCK_COIN_TRADE_BASE_URL', '')
    monkeypatch.setattr(auto_trade.notification, 'notify_order_placed', AsyncMock())
    monkeypatch.setattr(auto_trade.notification, 'notify_order_error', AsyncMock())
    filled_alert = AsyncMock()
    monkeypatch.setattr(auto_trade.notification, 'notify_order_filled', filled_alert)
    virtual_alert = AsyncMock()
    monkeypatch.setattr(auto_trade.notification, 'notify_auto_trade_executed', virtual_alert)
    async def place(*args):
        if result == 'rejected': raise kis_token.KISTokenError('KIS_TOKEN_UNAVAILABLE', 'token failure')
        if result == 'unknown': raise OrderSubmissionUnknown('timeout')
        return {'rt_cd': '0', 'output': {'ODNO': '000123'}}
    monkeypatch.setattr(auto_trade, 'get_broker_client', lambda *a, **kw: SimpleNamespace(place_order=place))
    async def run():
        async with sessions() as db:
            db.add(User(id=uid, name='시험', email=f'{uid}@test.invalid', password_hash='test', client_id=uid.hex))
            await db.commit()
            row = BrokerSettings(user_id=uid, broker='kis', app_key='test', app_secret='test', account_no='1234567801', quant_mode='live')
            db.add_all([row, QuantVirtualAccount(user_id=uid, initial_capital=10000000, cash_balance=8000000),
                        Portfolio(user_id=uid, book='QUANT', symbol='005930.KS', name='삼성전자', quantity=10, avg_price=70000)])
            await db.commit()
            # 증권사 응답→추적 상태 시험. 공통 관문을 통과한 뒤의 어댑터를 직접 검사한다.
            out = await auto_trade._execute_trade_unchecked(db, uid, row, 'live', '005930.KS', '삼성전자', side, 70000, 2, '시험')
            assert out['virtual_status'] == 'not_recorded'
        async with sessions() as db:
            account = await db.scalar(select(QuantVirtualAccount).where(QuantVirtualAccount.user_id == uid))
            portfolio = await db.scalar(select(Portfolio).where(Portfolio.user_id == uid))
            assert account.cash_balance == 8000000 and portfolio.quantity == 10
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id == uid)) == 0
            order = await db.scalar(select(LiveOrder).where(LiveOrder.user_id == uid))
            assert order.status == {'success': 'ACCEPTED', 'rejected': 'ERROR', 'unknown': 'UNKNOWN'}[result]
            assert order.broker == 'kis-direct'
        if result == 'success':
            monkeypatch.setattr(auto_trade, 'get_session_factory', lambda: sessions)
            async def verified(row, broker):
                if row.user_id != uid: return None
                return {'status': 'FILLED', 'filledQuantity': 2, 'avgFilledPrice': 69900,
                        'account_key': kis_execution.account_key('test', '1234567801', 'paper')}
            monkeypatch.setattr(kis_execution, 'direct_status', verified)
            summary = await auto_trade.confirm_live_fills()
            assert summary['filled'] == 1
            async with sessions() as db:
                order = await db.scalar(select(LiveOrder).where(LiveOrder.user_id == uid))
                account = await db.scalar(select(QuantVirtualAccount).where(QuantVirtualAccount.user_id == uid))
                portfolio = await db.scalar(select(Portfolio).where(Portfolio.user_id == uid))
                assert order.status == 'FILLED' and order.avg_filled_price == 69900
                assert account.cash_balance == 8000000 and portfolio.quantity == 10
            filled_alert.assert_awaited_once()
        await engine.dispose()
    asyncio.run(run())
    virtual_alert.assert_not_awaited()


@pytest.mark.parametrize('filled,cancelled,expected', [(0, False, 'ACCEPTED'), (1, False, 'PARTIALLY_FILLED'), (2, False, 'FILLED'), (1, True, 'CANCELLED')])
def test_direct_fill_confirmation_uses_exact_order_and_account(monkeypatch, filled, cancelled, expected):
    date = datetime.now(timezone.utc)
    order = SimpleNamespace(order_no='000123', created_at=date, environment='paper', symbol='005930.KS', side='BUY', quantity=2,
                            raw=json.dumps({'account_key': kis_execution.account_key('key', '1234567801', 'paper')}))
    fill = SimpleNamespace(broker_order_id='123', order_date=date.astimezone(kis_execution.KST).strftime('%Y%m%d'), symbol='005930',
                           side='buy', order_quantity=2, filled_quantity=filled, avg_fill_price=70000, cancelled=cancelled)
    client = SimpleNamespace(paper=True, get_daily_fills=AsyncMock(return_value=[fill]))
    creds = SimpleNamespace(app_key='key', account_no='1234567801')
    monkeypatch.setattr(kis_execution, 'client_for', lambda _: (client, creds))
    assert asyncio.run(kis_execution.direct_status(order, None))['status'] == expected
    fill.broker_order_id = '456'
    assert asyncio.run(kis_execution.direct_status(order, None)) is None
    creds.account_no = '9999999901'
    with pytest.raises(RuntimeError, match='계좌'):
        asyncio.run(kis_execution.direct_status(order, None))
