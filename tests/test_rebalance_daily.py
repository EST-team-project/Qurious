"""갱신 완료 gate + 관망 포함 일별 판정. 실제 SQLite 자료/러너 기록과 PostgreSQL 잠금 검증."""
import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.services import rebalance as rb, rebalance_daily as daily, data_status
from tests.test_rebalance_policy import scenario, needs_db

pytestmark = pytest.mark.usefixtures("rebalance_db_schema")


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 10, 6, 13, 30, tzinfo=rb.KST)
        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)
    monkeypatch.setattr(rb, 'datetime', Clock)
    monkeypatch.setattr(daily, 'datetime', Clock)
    return Clock


@pytest.fixture
def ready_data(rebalance_calendar, monkeypatch):
    # Background row counts are a UI optimization, not part of completion/freshness.
    monkeypatch.setattr(data_status, 'counts_view', lambda **kw: ({}, 'fresh'))
    with sqlite3.connect(rebalance_calendar) as db:
        db.executemany("INSERT INTO price_daily (bas_dt,srtn_cd,clpr) VALUES ('20261002',?,1000)", [('005930',), ('000660',)])
    folder = rebalance_calendar.parent / 'state'
    folder.mkdir()
    record = {'started_at': '2026-10-06T12:30:01+09:00', 'finished_at': '2026-10-06T13:00:00+09:00',
              'ok': True, 'stopped': None, 'steps': [{'name': 'price', 'rc': 0}, {'name': 'calendar', 'rc': 0}],
              'after': {'price_max': '20261002'}}
    def write(**changes):
        record.update(changes)
        (folder / 'daily_update_last.json').write_text(json.dumps(record))
    write()
    return rebalance_calendar, folder, write


def test_complete_after_holiday_uses_previous_trading_day(clock, ready_data):
    result = daily.readiness()
    assert result['ready'] and result['data_as_of'] == '2026-10-02'  # Oct 5 holiday
    assert result['update_finished_at'] == '2026-10-06T13:00:00+09:00'


@pytest.mark.parametrize('changes,expected', [
    ({'finished_at': None}, 'waiting'),
    ({'finished_at': '2026-10-06T14:00:00+09:00'}, 'waiting'),
    ({'started_at': '2026-10-05T12:30:00+09:00'}, 'waiting'),
    ({'started_at': '2026-10-06T11:00:00+09:00'}, 'waiting'),
    ({'started_at': '2026-10-06T12:30:00'}, 'data_unavailable'),
    ({'ok': False, 'stopped': 'price failed'}, 'update_failed'),
    ({'ok': False}, 'update_failed'),
    ({'steps': [{'name':'price','rc':0}]}, 'update_failed'),
    ({'steps': [{'name':'price','rc':0},{'name':'calendar','rc':3}]}, 'update_failed'),
    ({'after': {'price_max': '20260930'}}, 'stale_data'),
])
def test_incomplete_failed_old_or_invalid_update_waits(clock, ready_data, changes, expected):
    ready_data[2](**changes)
    result = daily.readiness()
    assert not result['ready'] and result['state'] == expected


def test_running_update_blocks_previous_success_then_retries(clock, ready_data):
    lock = ready_data[1] / 'daily_update.lock'
    lock.write_text(json.dumps({'started_at':'2026-10-06T13:15:00+09:00'}))
    assert daily.readiness()['state'] == 'updating'
    clock.current += timedelta(hours=5)
    assert daily.readiness()['state'] == 'updating'  # stale lock is not proof of completion
    lock.unlink()
    assert daily.readiness()['ready']


def test_before_update_and_closed_day(clock, ready_data):
    clock.current = datetime(2026, 10, 6, 12, 29, tzinfo=rb.KST)
    assert daily.readiness()['state'] == 'before_update'
    clock.current = datetime(2026, 10, 5, 14, tzinfo=rb.KST)
    assert daily.readiness()['state'] == 'closed'


def test_stale_database_cannot_pass_using_only_success_record(clock, ready_data):
    with sqlite3.connect(ready_data[0]) as db:
        db.execute("UPDATE price_daily SET bas_dt='20260930'")
    assert daily.readiness()['state'] == 'stale_data'


def test_missing_state_or_calendar_waits(clock, ready_data, monkeypatch, tmp_path):
    (ready_data[1] / 'daily_update_last.json').unlink()
    assert not daily.readiness()['ready']
    monkeypatch.setenv('COLLECTOR_DB_PATH', str(tmp_path / 'missing.sqlite3'))
    assert daily.readiness()['state'] == 'data_unavailable'


@needs_db
def test_no_action_is_checked_once_even_after_reopening_session(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=('005930.KS', '000660.KS')) as (factory, uid):
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                result = await rb.check_daily(db, uid, plan)
                assert result['checked'] and result['run_id'] is None
                assert plan.last_auto_check_result['status'] == 'no_action'
                await db.commit()
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                result = await rb.check_daily(db, uid, plan)
                assert result == {'checked':False, 'reason':'already_checked'}
                assert daily.view(plan, daily.readiness())['state'] == 'checked'
                # Explicit manual check is independent and does not reset the completion date.
                assert (await rb.check_due(db, uid, plan))['run_id'] is None
                assert plan.last_auto_check_date == clock.current.date()
                await db.commit()
    asyncio.run(go())


@needs_db
def test_concurrent_daily_checks_only_evaluate_once(monkeypatch, clock, ready_data):
    calls = []
    original = rb.check_due
    async def counted(*args, **kwargs):
        calls.append(1)
        return await original(*args, **kwargs)
    monkeypatch.setattr(rb, 'check_due', counted)
    async def go():
        async with scenario(monkeypatch, symbols=('005930.KS', '000660.KS')) as (factory, uid):
            async def check():
                async with factory() as db:
                    plan = await rb.get_plan(db, uid)
                    result = await rb.check_daily(db, uid, plan)
                    await db.commit()
                    return result
            result = await asyncio.gather(*(check() for _ in range(4)))
            assert sum(r['checked'] for r in result) == 1
            assert len(calls) == 1
    asyncio.run(go())


@needs_db
def test_quote_failure_retries_and_next_day_can_check_again(monkeypatch, clock, ready_data):
    original = rb.check_due
    async def fail(*args, **kwargs):
        raise rb.RebalanceError('시세 조회 실패')
    async def go():
        async with scenario(monkeypatch, symbols=('005930.KS', '000660.KS')) as (factory, uid):
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                monkeypatch.setattr(rb, 'check_due', fail)
                with pytest.raises(rb.RebalanceError):
                    await rb.check_daily(db, uid, plan)
                await db.rollback()
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                assert plan.last_auto_check_date is None
                monkeypatch.setattr(rb, 'check_due', original)
                assert (await rb.check_daily(db, uid, plan))['checked']
                await db.commit()
            clock.current += timedelta(days=1)
            ready_data[2](started_at='2026-10-07T12:30:01+09:00', finished_at='2026-10-07T13:00:00+09:00',
                          after={'price_max':'20261006'})
            with sqlite3.connect(ready_data[0]) as c:
                c.execute("UPDATE price_daily SET bas_dt='20261006'")
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                assert (await rb.check_daily(db, uid, plan))['checked']
                assert plan.last_auto_check_date == clock.current.date()
                await db.commit()
    asyncio.run(go())


@needs_db
def test_waiting_batch_does_not_consume_day(monkeypatch, clock, ready_data):
    ready_data[2](ok=False)
    async def go():
        async with scenario(monkeypatch, symbols=('005930.KS', '000660.KS')) as (factory, uid):
            result = await rb.check_all_due(factory)
            assert result['checked'] == 0 and result['readiness']['state'] == 'update_failed'
            async with factory() as db:
                assert (await rb.get_plan(db, uid)).last_auto_check_date is None
            ready_data[2](ok=True)
            result = await rb.check_all_due(factory)
            assert result['checked'] >= 1
            assert (await rb.check_all_due(factory))['checked'] == 0
    asyncio.run(go())
