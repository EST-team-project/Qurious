import asyncio
from datetime import datetime, timedelta
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import httpx
import pytest
from sqlalchemy import select
from app.models import BrokerSettings, BrokerPositionBaseline, LiveOrder
from scripts import kis_recovery_session as session
from test_kis_connection_probe import runtime  # noqa: F401
from test_kis_order_recovery import env, setup  # noqa: F401


@pytest.mark.parametrize('method,status,retries', [
    ('GET', 500, True), ('GET', 503, True), ('GET', 429, True),
    ('GET', 401, False), ('GET', 400, False), ('POST', 500, False),
])
def test_only_transient_get_failure_is_retried(monkeypatch, method, status, retries):
    request = httpx.Request(method, 'https://broker.invalid/read')
    error = httpx.HTTPStatusError('synthetic', request=request, response=httpx.Response(status, request=request))
    call = AsyncMock(side_effect=[error, {'ok': True}])
    sleep = AsyncMock()
    monkeypatch.setattr(session.asyncio, 'sleep', sleep)
    if retries:
        assert asyncio.run(session.read(call)) == {'ok': True}
        assert call.await_count == 2
        sleep.assert_awaited_once_with(2)
    else:
        with pytest.raises(httpx.HTTPStatusError): asyncio.run(session.read(call))
        assert call.await_count == 1
        sleep.assert_not_awaited()


def test_unavailable_get_stops_after_three_reads(monkeypatch):
    error = httpx.ReadTimeout('synthetic', request=httpx.Request('GET', 'https://broker.invalid/read'))
    call = AsyncMock(side_effect=error)
    sleep = AsyncMock()
    monkeypatch.setattr(session.asyncio, 'sleep', sleep)
    with pytest.raises(httpx.ReadTimeout): asyncio.run(session.read(call))
    assert call.await_count == 3
    assert [x.args[0] for x in sleep.await_args_list] == [2, 4]


@pytest.mark.parametrize('minute,allowed', [(9, False), (10, True), (11, True), (12, False), (40, False)])
def test_only_scheduled_start_window(monkeypatch, minute, allowed):
    clock = datetime(2026, 11, 3, 9, minute, tzinfo=session.recovery.control.KST)
    monkeypatch.setattr(session, 'now', lambda: clock)
    monkeypatch.setattr(session.recovery, 'check_window', lambda day: None)
    if allowed:
        assert session.start_window({'day': '2026-11-03'}).hour == 10
    else:
        with pytest.raises(ValueError): session.start_window({'day': '2026-11-03'})
    with pytest.raises(ValueError): session.start_window({'day': '2026-11-02'})


@pytest.mark.parametrize('day,hour,minute,second,allowed', [
    (3, 8, 59, 59, False), (3, 9, 0, 0, True), (3, 9, 20, 0, True),
    (3, 14, 30, 0, True), (3, 14, 30, 1, False), (3, 15, 0, 0, False),
    (4, 9, 20, 0, False),
])
def test_manual_start_preserves_day_and_cleanup_deadline(monkeypatch, day, hour, minute, second, allowed):
    current = datetime(2026, 11, day, hour, minute, second, tzinfo=session.recovery.control.KST)
    monkeypatch.setattr(session, 'now', lambda: current)
    checked = []
    monkeypatch.setattr(session.recovery, 'check_window', checked.append)
    config = {'day': '2026-11-03'}
    if allowed:
        assert session.start_window(config, start_now=True) == current + timedelta(minutes=50)
        assert checked == [current.date()]
    else:
        with pytest.raises(ValueError): session.start_window(config, start_now=True)
        assert not checked


def test_manual_start_does_not_bypass_market_calendar(monkeypatch):
    monkeypatch.setattr(session, 'now', lambda: datetime(2026, 11, 3, 9, 20, tzinfo=session.recovery.control.KST))
    def reject(day):
        raise session.recovery.control.Rejected('OUTSIDE_WINDOW', 'unverified')
    monkeypatch.setattr(session.recovery, 'check_window', reject)
    with pytest.raises(session.recovery.control.Rejected):
        session.start_window({'day': '2026-11-03'}, start_now=True)


@pytest.fixture
def flow(monkeypatch):
    clock = [datetime(2026, 11, 3, 9, 10, tzinfo=session.recovery.control.KST)]
    uid, pid, cid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    config = {'user_id': str(uid), 'day': '2026-11-03', 'account_ref': 'synthetic', 'settings_hash': 'synthetic'}
    parent = SimpleNamespace(id=pid, order_no='1')
    child = SimpleNamespace(id=cid, order_no='2')
    state = {'parent': None, 'child': None, 'created_at': clock[0].isoformat()}
    async def sleep(seconds): clock[0] += timedelta(seconds=max(0, seconds))
    async def submit(*args, **kwargs):
        assert kwargs['quantity'] == 1 and kwargs['side'] == 'sell'
        state['parent'] = parent
        return {'status': 'submitted'}
    async def retry(*args, **kwargs):
        assert clock[0] >= datetime.fromisoformat(state['created_at']) + timedelta(minutes=30)
        assert kwargs['execute']
        state['child'] = child
        return {'status': 'submitted', 'policy_restored': True}
    async def confirmed(user, order, expected, deadline):
        return {'id': str(order), 'status': expected, 'filled': int(expected == 'FILLED'),
                'created_at': state['created_at'], 'price': 70100, 'order_no': '2',
                'cancelled': expected == 'CANCELLED', 'remaining': 0, 'cancelled_quantity': 1}
    monkeypatch.setattr(session, 'now', lambda: clock[0])
    monkeypatch.setattr(session.asyncio, 'sleep', sleep)
    monkeypatch.setattr(session.recovery, 'check_window', lambda day: None)
    monkeypatch.setattr(session, 'account', AsyncMock(return_value={'protected_quantity': 1, 'trial_quantity': 0}))
    monkeypatch.setattr(session, 'quote', AsyncMock(side_effect=[70000, 70100]))
    monkeypatch.setattr(session.manual, 'submit', AsyncMock(side_effect=submit))
    monkeypatch.setattr(session.trial, 'run', AsyncMock(side_effect=retry))
    monkeypatch.setattr(session, 'orders', AsyncMock(side_effect=lambda *args: (state['parent'], state['child'])))
    monkeypatch.setattr(session.recovery, 'cancel', AsyncMock(return_value={'status': 'ACCEPTED'}))
    monkeypatch.setattr(session, 'confirmed', AsyncMock(side_effect=confirmed))
    monkeypatch.setattr(session, 'cleanup', AsyncMock(return_value=[]))
    return config, state, clock


def test_one_attempt_then_replay_never_submits_again(flow, tmp_path):
    config, _, _ = flow
    async def scenario():
        result = await session.run(config, tmp_path)
        assert result['status'] == 'passed' and result['filled_quantity'] == 1
        assert result['retry_result']['policy_restored']
        assert (await session.run(config, tmp_path)) == {'status': 'already_started', 'previous': 'passed'}
        assert session.manual.submit.await_count == session.trial.run.await_count == 1
        assert session.account.call_args.kwargs['trial_quantity'] == 0
        assert json.loads(next(tmp_path.glob('*.json')).read_text())['status'] == 'passed'
    asyncio.run(scenario())


def test_manual_start_shares_scheduled_attempt_and_preserves_wait(flow, tmp_path):
    config, state, clock = flow
    clock[0] += timedelta(minutes=10)
    state['created_at'] = clock[0].isoformat()
    async def scenario():
        result = await session.run(config, tmp_path, start_now=True)
        assert result['status'] == 'passed' and result['start_mode'] == 'manual'
        assert clock[0] >= datetime.fromisoformat(state['created_at']) + timedelta(minutes=30)
        assert (await session.run(config, tmp_path))['status'] == 'already_started'
        assert (await session.run(config, tmp_path, start_now=True))['status'] == 'already_started'
        assert session.manual.submit.await_count == session.trial.run.await_count == 1
    asyncio.run(scenario())


def test_broker_reads_and_submission_stages_are_spaced(flow, tmp_path):
    config, _, clock = flow
    last = [clock[0]]
    prices = iter([70000, 70100])
    async def quote(*args):
        last[0] = clock[0]
        return next(prices)
    async def account(*args, **kwargs):
        last[0] = clock[0]
        return {'protected_quantity': 1, 'trial_quantity': kwargs.get('trial_quantity', 1)}
    def spaced(original):
        async def call(*args, **kwargs):
            assert (clock[0] - last[0]).total_seconds() >= 1.1
            last[0] = clock[0]
            return await original(*args, **kwargs)
        return call
    async def cancel(*args): return {'status': 'ACCEPTED'}
    session.quote.side_effect = quote
    session.account.side_effect = account
    session.manual.submit.side_effect = spaced(session.manual.submit.side_effect)
    session.recovery.cancel.side_effect = spaced(cancel)
    session.trial.run.side_effect = spaced(session.trial.run.side_effect)
    assert asyncio.run(session.run(config, tmp_path))['status'] == 'passed'


@pytest.mark.parametrize('previous', [None, 'started', 'needs_review', 'passed', 'not_executed'])
def test_additional_attempt_requires_completed_early_fill(flow, tmp_path, previous):
    config, _, _ = flow
    base = tmp_path / f"session-{config['user_id']}-{config['day']}.json"
    if previous: base.write_text(json.dumps({'status': previous}))
    with pytest.raises(ValueError):
        asyncio.run(session.run(config, tmp_path, start_now=True, additional_attempt=True))
    session.manual.submit.assert_not_awaited()


def test_only_one_explicit_additional_attempt_preserves_first_record(flow, tmp_path):
    config, _, _ = flow
    base = tmp_path / f"session-{config['user_id']}-{config['day']}.json"
    first = json.dumps({'status': 'parent_filled_without_retry', 'original_evidence': 'keep'})
    base.write_text(first)
    session.quote.side_effect = [70000, 70200]
    with pytest.raises(ValueError):
        asyncio.run(session.run(config, tmp_path, additional_attempt=True))
    async def scenario():
        result = await session.run(config, tmp_path, start_now=True, additional_attempt=True)
        assert result['status'] == 'passed' and result['parent_price'] == 70200
        assert result['additional_attempt']
        original_key = uuid.uuid5(uuid.NAMESPACE_URL, f"qurious:c5-session:{config['user_id']}:{config['day']}")
        assert result['request_id'] != str(original_key)
        assert base.read_text() == first
        assert (await session.run(config, tmp_path, start_now=True, additional_attempt=True))['status'] == 'already_started'
        assert (await session.run(config, tmp_path))['status'] == 'already_started'
        assert session.manual.submit.await_count == session.trial.run.await_count == 1
    asyncio.run(scenario())


def test_parent_filled_does_not_buy_another_share_or_retry(flow, tmp_path):
    config, _, _ = flow
    session.confirmed.side_effect = None
    session.confirmed.return_value = {'status': 'FILLED', 'filled': 1}
    result = asyncio.run(session.run(config, tmp_path))
    assert result['status'] == 'parent_filled_without_retry'
    session.trial.run.assert_not_awaited()
    assert session.manual.submit.await_count == 1
    session.cleanup.assert_awaited_once()


def test_price_condition_timeout_does_not_weaken_limits(flow, tmp_path):
    config, _, clock = flow
    session.quote.side_effect = None
    session.quote.return_value = 70000
    result = asyncio.run(session.run(config, tmp_path))
    assert result['code'] == 'PRICE_CONDITION_NOT_MET' and result['status'] == 'not_executed'
    assert clock[0].hour == 9 and clock[0].minute == 52
    session.trial.run.assert_not_awaited()


@pytest.mark.parametrize('failure', ['parent_unknown', 'retry_unknown', 'fill_timeout', 'cleanup_unknown', 'settings_changed'])
def test_unconfirmed_steps_never_claim_success_or_start_second_attempt(flow, tmp_path, failure):
    config, _, _ = flow
    if failure == 'parent_unknown':
        session.manual.submit.side_effect = None
        session.manual.submit.return_value = {'status': 'unknown'}
    if failure == 'retry_unknown':
        session.trial.run.side_effect = None
        session.trial.run.return_value = {'status': 'unknown', 'policy_restored': True}
    if failure == 'fill_timeout':
        original = session.confirmed.side_effect
        async def fail(user, order, expected, deadline):
            if expected == 'FILLED': raise TimeoutError
            return await original(user, order, expected, deadline)
        session.confirmed.side_effect = fail
    if failure == 'cleanup_unknown': session.cleanup.return_value = [{'status': 'needs_review'}]
    if failure == 'settings_changed': session.account.side_effect = [{'trial_quantity': 1}, ValueError('changed')]
    async def scenario():
        result = await session.run(config, tmp_path)
        assert result['status'] == 'needs_review'
        assert (await session.run(config, tmp_path))['status'] == 'already_started'
        assert session.manual.submit.await_count == 1 and session.trial.run.await_count <= 1
        session.cleanup.assert_awaited_once()
    asyncio.run(scenario())


def test_journal_failure_before_submission_sends_nothing(flow, tmp_path, monkeypatch):
    config, _, _ = flow
    monkeypatch.setattr(session.trial, 'write', lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError): asyncio.run(session.run(config, tmp_path))
    session.manual.submit.assert_not_awaited()
    session.trial.run.assert_not_awaited()


def test_abandoned_attempt_never_restarts_trading(flow, tmp_path):
    config, _, _ = flow
    path = tmp_path / f"session-{config['user_id']}-{config['day']}.json"
    path.write_text(json.dumps({'status': 'parent_sending'}))
    assert asyncio.run(session.run(config, tmp_path))['status'] == 'already_started'
    assert asyncio.run(session.run(config, tmp_path, start_now=True))['status'] == 'already_started'
    session.account.assert_not_awaited()
    session.manual.submit.assert_not_awaited()


@pytest.mark.skipif(not os.getenv('QURIOUS_TEST_DATABASE_URL'), reason='격리 PostgreSQL 필요')
@pytest.mark.usefixtures('rebalance_db_schema')
@pytest.mark.parametrize('case', ['valid', 'wrong_account', 'changed_settings', 'missing_trial', 'open_order', 'external_open'])
def test_real_database_preflight_preserves_original_share(env, monkeypatch, case):
    sessions, client, _ = env
    monkeypatch.setattr(session.pg, 'get_session_factory', lambda: sessions)
    client.get_daily_fills = AsyncMock(return_value=[])
    if case == 'external_open':
        client.get_daily_fills.return_value = [SimpleNamespace(order_quantity=1, filled_quantity=0,
            cancelled=False, raw={'ord_qty': '1', 'tot_ccld_qty': '0', 'rmn_qty': '1'})]
    async def scenario():
        uid, pid = await setup(sessions, risk_cooldown_min=30)
        async with sessions() as db:
            parent = await db.get(LiveOrder, pid)
            parent.strategy_id = 'manual_broker'
            parent.quantity, parent.filled_quantity = 1, 0
            ref = parent.account_ref
            baseline = await db.get(BrokerPositionBaseline, (ref, parent.symbol))
            baseline.quantity = 0
            buy = await db.scalar(select(LiveOrder).where(LiveOrder.user_id == uid, LiveOrder.side == 'BUY'))
            buy.strategy_id = 'manual_broker'
            buy.quantity = buy.filled_quantity = 1
            db.add(LiveOrder(user_id=uid, account_ref=ref, client_order_id='protected:'+uid.hex,
                strategy_id='kis_connection_check', strategy_version=1, broker='kis-direct', environment='paper',
                symbol=parent.symbol, side='BUY', quantity=1, filled_quantity=1, avg_filled_price=70000,
                price=70000, status='FILLED', created_at=parent.created_at-timedelta(days=1)))
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            config = {'account_ref': ref, 'settings_hash': session.signature(row)}
            if case == 'wrong_account': config['account_ref'] = 'other'
            if case == 'changed_settings': row.risk_cooldown_min = 0
            if case == 'missing_trial': buy.quantity = buy.filled_quantity = 0
            if case == 'open_order': parent.status = 'ACCEPTED'
            await db.commit()
        session.recovery.kis_execution.account_snapshot.return_value = {
            'cash': 1000000, 'equity': 1140000, 'holdings': {'005930.KS': {'quantity': 2, 'value': 140000}}}
        if case == 'valid':
            result = await session.account(uid, config)
            assert result['protected_quantity'] == result['trial_quantity'] == 1
        else:
            with pytest.raises(ValueError): await session.account(uid, config)
        client.place_order.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize('state', ['FILLED', 'ACCEPTED', 'lookup_failure'])
def test_cleanup_cancels_only_tracked_unfilled_orders(monkeypatch, state):
    uid, pid = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(session, 'orders', AsyncMock(return_value=(SimpleNamespace(id=pid), None)))
    lookup = AsyncMock(return_value={'id': str(pid), 'status': state})
    if state == 'lookup_failure': lookup.side_effect = ValueError('unknown')
    monkeypatch.setattr(session, 'refresh', lookup)
    cancel = AsyncMock(return_value={'status': 'ACCEPTED'})
    monkeypatch.setattr(session.recovery, 'cancel', cancel)
    monkeypatch.setattr(session, 'confirmed', AsyncMock(return_value={'id': str(pid), 'status': 'CANCELLED'}))
    result = asyncio.run(session.cleanup(uid, uuid.uuid4()))
    if state == 'ACCEPTED':
        cancel.assert_awaited_once_with(uid, pid)
        assert result[0]['status'] == 'CANCELLED'
    else:
        cancel.assert_not_awaited()
        assert result[0]['status'] == ('FILLED' if state == 'FILLED' else 'needs_review')
