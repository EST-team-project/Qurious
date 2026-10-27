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


def write_hf_proof(ready_data):
    from app.services import hf_snapshot
    from scripts.hf_collector_follower import atomic_json
    folder = ready_data[0].parent
    record = json.loads((ready_data[1] / 'daily_update_last.json').read_text())
    record.update(finished_at=None, recorded_at='2026-10-06T12:47:00+09:00',
                  pending_steps=['upload', 'ohlcv_upload', 'journal_upload', 'sector_laws'])
    record['steps'] += [{'name': 'export', 'rc': 0}, {'name': 'verify', 'rc': 0}]
    manifest = {'partial': False, 'generated_at': '2026-10-06T12:45:00+09:00', 'tables': {
        name: {'files': [{'path': name + '/2026.parquet', 'sha256': 'a' * 64, 'bytes': 4}]}
        for name in ('price_daily', 'price_adjusted', 'market_calendar')}}
    verify = {'at': '2026-10-06T12:46:00+09:00', 'fails': 0, 'checks': 97, 'full': True,
              'manifest_fp': hf_snapshot.manifest_fingerprint(manifest), 'manifest_generated_at': manifest['generated_at']}
    receipt = hf_snapshot.validate_snapshot('a' * 40, {'run': record}, manifest, verify)
    receipt.update(files_verified=True, data_ready_at='2026-10-06T13:00:00+09:00')
    for path, value in {'provenance.json': receipt, 'meta/run_record.json': {'run': record},
                        'meta/manifest.json': manifest, 'meta/last_verify.json': verify,
                        'state/daily_update_last.json': record}.items():
        atomic_json(folder / path, value)


def test_verified_hf_snapshot_is_ready_without_fabricating_finished_at(clock, ready_data):
    write_hf_proof(ready_data)
    result = daily.readiness()
    assert result['ready'] and result['data_as_of'] == '2026-10-02'
    assert result['update_finished_at'] is None
    assert result['data_ready_at'] == '2026-10-06T13:00:00+09:00'
    assert result['source_commit'] == 'a' * 40
    status = data_status.runner_state(ready_data[1], clock.current)
    assert status['state'] == 'attention' and status['label'] == '회차 종료 확인 전'


@pytest.mark.parametrize('bad', ['verify', 'receipt', 'local_run', 'future_publication'])
def test_hf_proof_mismatch_never_falls_back_to_old_completion(clock, ready_data, bad):
    write_hf_proof(ready_data)
    folder = ready_data[0].parent
    path = folder / ('meta/last_verify.json' if bad == 'verify' else 'state/daily_update_last.json' if bad == 'local_run' else 'provenance.json')
    value = json.loads(path.read_text())
    if bad == 'verify': value['fails'] = 1
    if bad == 'receipt': value['files_verified'] = False
    if bad == 'local_run': value['finished_at'] = '2026-10-06T13:00:00+09:00'
    if bad == 'future_publication': value['data_ready_at'] = '2026-10-06T14:00:00+09:00'
    path.write_text(json.dumps(value))
    result = daily.readiness()
    assert not result['ready'] and result['state'] == 'data_unavailable'


@pytest.mark.parametrize('failed_step', ['dividend', 'disclosure', 'news', 'ohlcv', 'signals'])
def test_nonessential_failure_allows_readiness_without_hiding_runner_warning(clock, ready_data, failed_step):
    ready_data[2](ok=False, steps=[{'name': 'price', 'rc': 0}, {'name': 'calendar', 'rc': 0},
                                 {'name': failed_step, 'rc': 1, 'fatal': False}])
    path = ready_data[1] / 'daily_update_last.json'
    original = path.read_bytes()
    result = daily.readiness()
    assert result['ready'] and result['data_as_of'] == '2026-10-02'
    # 리밸런싱 허용이 관제의 전체 회차 실패를 성공으로 바꾸면 안 된다.
    runner = data_status.runner_state(ready_data[1], clock.current)
    assert runner['last']['ok'] is False
    assert next(s for s in runner['last']['steps'] if s['name'] == failed_step)['status'] == 'warning'
    assert path.read_bytes() == original


@pytest.mark.parametrize('changes,expected', [
    ({'finished_at': None}, 'waiting'),
    ({'finished_at': '2026-10-06T14:00:00+09:00'}, 'waiting'),
    ({'started_at': '2026-10-05T12:30:00+09:00'}, 'waiting'),
    ({'started_at': '2026-10-06T11:00:00+09:00'}, 'waiting'),
    ({'started_at': '2026-10-06T12:30:00'}, 'data_unavailable'),
    ({'ok': False, 'stopped': 'price failed'}, 'update_failed'),
    ({'ok': False, 'steps': [{'name':'price','rc':1},{'name':'calendar','rc':0}]}, 'update_failed'),
    ({'steps': [{'name':'price','rc':0}]}, 'update_failed'),
    ({'steps': [{'name':'price','rc':0},{'name':'calendar','rc':3}]}, 'update_failed'),
    ({'after': {'price_max': '20260930'}}, 'stale_data'),
])
def test_incomplete_failed_old_or_invalid_update_waits(clock, ready_data, changes, expected):
    ready_data[2](**changes)
    result = daily.readiness()
    assert not result['ready'] and result['state'] == expected


@pytest.mark.parametrize('name', ['price', 'calendar'])
@pytest.mark.parametrize('rc', [None, 1, '0', False])
def test_required_step_needs_explicit_success(clock, ready_data, name, rc):
    ready_data[2](steps=[{'name': step, 'rc': rc if step == name else 0}
                         for step in ('price', 'calendar')])
    assert daily.readiness()['state'] == 'update_failed'


@pytest.mark.parametrize('name', ['price', 'calendar'])
def test_duplicate_required_step_cannot_hide_failure(clock, ready_data, name):
    ready_data[2](steps=[{'name': name, 'rc': 1}, {'name': 'price', 'rc': 0},
                         {'name': 'calendar', 'rc': 0}])
    assert daily.readiness()['state'] == 'update_failed'


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
    ready_data[2](ok=False, steps=[{'name': 'price', 'rc': 1}, {'name': 'calendar', 'rc': 0}])
    async def go():
        async with scenario(monkeypatch, symbols=('005930.KS', '000660.KS')) as (factory, uid):
            result = await rb.check_all_due(factory)
            assert result['checked'] == 0 and result['readiness']['state'] == 'update_failed'
            async with factory() as db:
                assert (await rb.get_plan(db, uid)).last_auto_check_date is None
            ready_data[2](ok=True, steps=[{'name': 'price', 'rc': 0}, {'name': 'calendar', 'rc': 0}])
            result = await rb.check_all_due(factory)
            assert result['checked'] >= 1
            assert (await rb.check_all_due(factory))['checked'] == 0
    asyncio.run(go())
