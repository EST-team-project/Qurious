"""두 사용자 로그·즉시 실행·중지·손실 한도 간섭 회귀 시험. 외부 주문 없음."""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
from weakref import WeakValueDictionary

import pytest

from app.services import auto_trade as svc

A, B = uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def control(monkeypatch):
    enabled = {}
    cache = {}

    async def read_enabled(db, uid):
        await asyncio.sleep(0)
        return enabled.get(uid, False)

    async def write_enabled(db, uid, value):
        await asyncio.sleep(0)
        enabled[uid] = value

    async def cache_get(key, **kwargs):
        return cache.get(key)

    async def cache_set(key, value):
        cache[key] = value

    monkeypatch.setattr(svc, '_auto_trade_tasks', {})
    monkeypatch.setattr(svc, '_control_locks', WeakValueDictionary())
    monkeypatch.setattr(svc, 'is_enabled', read_enabled)
    monkeypatch.setattr(svc, 'set_enabled', write_enabled)
    monkeypatch.setattr(svc, 'cache_get', cache_get)
    monkeypatch.setattr(svc, 'cache_set', cache_set)
    monkeypatch.setattr(svc, 'audit', AsyncMock())
    for name in ['notify_auto_trade_started', 'notify_auto_trade_stopped', 'notify_risk_halt']:
        monkeypatch.setattr(svc.notification, name, AsyncMock())
    monkeypatch.setattr(svc, 'cancel_open_live_orders', AsyncMock(return_value={}))
    return enabled, cache


@pytest.mark.parametrize('own_cache', [None, {'cycles': []}])
def test_new_user_never_receives_another_users_log(control, own_cache):
    async def run():
        await svc._persist_cycle(A, {'time': 'a-private-time', 'trades': [{'quantity': 17}], 'risk': {'equity': 123}})
        control[1][svc._log_key(B)] = own_cache
        a = await svc.get_status(None, A)
        b = await svc.get_status(None, B)
        assert a['log'][0]['trades'] == [{'quantity': 17}]
        assert b['log'] == [] and b['risk'] == {} and b['last_cycle_at'] is None
    asyncio.run(run())


def test_cache_miss_after_expiry_or_deletion_never_revives_memory_log(control):
    async def run():
        await svc._persist_cycle(A, {'time': 'old', 'risk': {'equity': 123}})
        control[1].clear()
        assert (await svc.get_status(None, A))['log'] == []
        assert (await svc.get_status(None, B))['log'] == []
    asyncio.run(run())


def test_interleaved_persistence_keeps_each_users_last_50_cycles(control):
    async def run():
        for i in range(55):
            await svc._persist_cycle(A, {'time': f'a-{i}', 'risk': {'owner': 'a'}})
            await svc._persist_cycle(B, {'time': f'b-{i}', 'risk': {'owner': 'b'}})
        for uid, owner in [(A, 'a'), (B, 'b')]:
            result = await svc.get_status(None, uid)
            assert len(result['log']) == 50
            assert result['log'][0]['time'] == f'{owner}-5'
            assert result['last_cycle_at'] == f'{owner}-54'
            assert result['risk'] == {'owner': owner}
    asyncio.run(run())


@pytest.mark.parametrize('start_b', [False, True])
def test_stopping_b_never_cancels_a(control, monkeypatch, start_b):
    async def run():
        entered = {str(A): asyncio.Event(), str(B): asyncio.Event()}
        release = asyncio.Event()
        finished = []
        cancelled = []

        async def cycle(uid):
            entered[uid].set()
            try:
                await release.wait()
                finished.append(uid)
            except asyncio.CancelledError:
                cancelled.append(uid)
                raise

        monkeypatch.setattr(svc, '_run_quant_cycle', cycle)
        assert await svc.start_auto_trade(None, str(A))
        await entered[str(A)].wait()
        if start_b:
            assert await svc.start_auto_trade(None, str(B))
            await entered[str(B)].wait()
        assert await svc.stop_auto_trade_for(None, str(B)) is start_b
        assert svc.is_running(str(A)) and control[0][A]
        assert not svc.is_running(str(B)) and not control[0][B]
        assert cancelled == ([str(B)] if start_b else [])
        release.set()
        await asyncio.gather(*svc._auto_trade_tasks.values())
        await asyncio.sleep(0)
        assert finished == [str(A)]
        assert not svc.is_running() and not svc._auto_trade_tasks
    asyncio.run(run())


def test_same_user_concurrent_start_runs_once_and_notifies_correct_user(control, monkeypatch):
    async def run():
        release = asyncio.Event()
        runs = []

        async def cycle(uid):
            runs.append(uid)
            await release.wait()

        monkeypatch.setattr(svc, '_run_quant_cycle', cycle)
        results = await asyncio.gather(*(svc.start_auto_trade(None, str(A)) for _ in range(8)))
        assert results.count(True) == 1 and results.count(False) == 7
        assert runs == [str(A)]
        svc.notification.notify_auto_trade_started.assert_awaited_once_with(user_id=str(A))
        await svc.stop_auto_trade_for(None, str(A))
        assert not svc.is_running()
    asyncio.run(run())


def test_stop_waits_for_cancel_cleanup_before_restart(control, monkeypatch):
    async def run():
        entered = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        order = []

        async def first_cycle(uid):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await cleanup_release.wait()
                order.append('old-cleaned')

        async def next_cycle(uid):
            order.append('new-started')
            await asyncio.Event().wait()

        monkeypatch.setattr(svc, '_run_quant_cycle', first_cycle)
        await svc.start_auto_trade(None, str(A))
        await entered.wait()
        stop = asyncio.create_task(svc.stop_auto_trade_for(None, str(A)))
        await cleanup_started.wait()
        monkeypatch.setattr(svc, '_run_quant_cycle', next_cycle)
        start = asyncio.create_task(svc.start_auto_trade(None, str(A)))
        await asyncio.sleep(0)
        assert not start.done()
        cleanup_release.set()
        assert await stop
        assert await start
        await asyncio.sleep(0)
        assert order == ['old-cleaned', 'new-started']
        assert svc.is_running(str(A))
        await svc.stop_auto_trade_for(None, str(A))
    asyncio.run(run())


def test_loss_halt_finishes_own_audit_and_log_without_stopping_other_user(control, monkeypatch):
    async def run():
        b_entered = asyncio.Event()
        a_finished = asyncio.Event()
        row = SimpleNamespace(risk_kill_switch=False, risk_halt_reason='', quant_auto_enabled=True)
        db = SimpleNamespace(commit=AsyncMock())

        async def cycle(uid):
            if uid == str(B):
                b_entered.set()
                await asyncio.Event().wait()
            else:
                await svc.emergency_halt(db, row, uid, 'loss limit', -5)
                # Cancellation must not interrupt notification/audit/final persistence.
                await asyncio.sleep(0)
                await svc._persist_cycle(A, {'time': 'halted', 'risk': {'halted': True}})
                a_finished.set()

        monkeypatch.setattr(svc, '_run_quant_cycle', cycle)
        await svc.start_auto_trade(None, str(B))
        await b_entered.wait()
        await svc.start_auto_trade(None, str(A))
        await asyncio.wait_for(a_finished.wait(), 1)
        assert row.risk_kill_switch and not row.quant_auto_enabled
        assert svc.is_running(str(B))
        svc.cancel_open_live_orders.assert_awaited_once_with(db, A, 'loss limit')
        svc.notification.notify_risk_halt.assert_awaited_once_with('loss limit', -5, user_id=str(A))
        assert (await svc.get_status(None, A))['risk'] == {'halted': True}
        await svc.stop_auto_trade_for(None, str(B))
    asyncio.run(run())


def test_external_emergency_halt_only_cancels_target_user(control, monkeypatch):
    async def run():
        events = {str(A): asyncio.Event(), str(B): asyncio.Event()}

        async def cycle(uid):
            events[uid].set()
            await asyncio.Event().wait()

        monkeypatch.setattr(svc, '_run_quant_cycle', cycle)
        for uid in [A, B]:
            await svc.start_auto_trade(None, str(uid))
            await events[str(uid)].wait()
        a_task = svc._auto_trade_tasks[A]
        row = SimpleNamespace(risk_kill_switch=False, risk_halt_reason='', quant_auto_enabled=True)
        await svc.emergency_halt(SimpleNamespace(commit=AsyncMock()), row, str(A), 'worker loss')
        await asyncio.gather(a_task, return_exceptions=True)
        assert a_task.cancelled() and svc.is_running(str(B))
        await svc.stop_auto_trade_for(None, str(B))
    asyncio.run(run())


def test_failed_cycle_releases_only_its_own_task(control, monkeypatch):
    async def run():
        b_entered = asyncio.Event()

        async def cycle(uid):
            if uid == str(A):
                raise RuntimeError('synthetic failure')
            b_entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(svc, '_run_quant_cycle', cycle)
        await svc.start_auto_trade(None, str(B))
        await b_entered.wait()
        await svc.start_auto_trade(None, str(A))
        a_task = svc._auto_trade_tasks[A]
        await a_task
        await asyncio.sleep(0)
        assert A not in svc._auto_trade_tasks and svc.is_running(str(B))
        await svc.stop_auto_trade_for(None, str(B))
    asyncio.run(run())
