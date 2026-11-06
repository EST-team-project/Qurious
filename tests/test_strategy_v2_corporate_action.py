"""TC-SV2CA · #561: 가상 장부의 조정일 실행 누락·보류 지속·알림 경계.

P02-⑤-2(위험 시 실행 보류), P02-⑤-3(정기 실행·알림 기록)의 일부를 확인한다.
8사례(함수 7개, 첫 함수 2조건). 실제 KIS 주문·외부 알림 수신은 이 묶음 밖이다.
"""
import asyncio
from copy import deepcopy
from datetime import date
import os
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models import Order, StrategyRuntime, NotificationLog, ExecutionRun
from app.services import strategy_v2_execution as runner, auto_trade, notification
from tests.test_strategy_v2_execution import runtime, user, next_bar
from tests.test_strategy_v2 import bar

pytestmark = [pytest.mark.skipif(not os.getenv('QURIOUS_TEST_DATABASE_URL'), reason='일회용 PG 필요'),
              pytest.mark.usefixtures('rebalance_db_schema')]
NOTIFY_HOLD = notification.notify_corporate_action_hold


def split_history(source):
    # 수집기는 과거 봉을 다시 조정하며 최신 날 누적계수는 1이다.
    for row in source['bars']:
        row['factor'] = .5
        for key in ('open', 'high', 'low', 'close'):
            row['adjusted_' + key] = row[key] * .5
    source['bars'].append(bar(date(2026, 8, 31), 80))


async def holding(sessions, source, **settings):
    uid = await user(sessions, **settings)
    await runner.run(uid, execute=True)
    next_bar(source, date(2026, 8, 30), 160, 160)
    bought = await runner.run(uid, execute=True)
    assert bought['status'] == 'filled', bought
    assert bought['decision']['action'] == 'HOLD', bought
    return uid


@pytest.mark.parametrize('miss_event_day', [False, True])
def test_corporate_action_holds_without_changing_position_across_restarts(runtime, miss_event_day):
    sessions, source = runtime
    async def scenario():
        uid = await holding(sessions, source)
        key = runner.runtime_id(runner.context(uid))
        async with sessions() as db:
            before = deepcopy((await db.get(StrategyRuntime, key)).state)
        split_history(source)
        if miss_event_day:
            next_bar(source, date(2026, 9, 1), 80)
        first = await runner.run(uid, execute=True)
        assert first['status'] == 'skipped' and first['code'] == 'CORPORATE_ACTION_RECONCILIATION', first
        assert '손절·익절' in first['reason']
        # 새 DB 세션·같은 날 재실행·다음 날 모두 보류가 유지된다.
        same_day = await runner.run(uid, execute=True)
        next_bar(source, date(2026, 9, 2), 80)
        later = await runner.run(uid, execute=True)
        for result in (same_day, later):
            assert result['status'] == 'skipped' and result['hold']['ref'] == first['hold']['ref']
        async with sessions() as db:
            state = (await db.get(StrategyRuntime, key)).state
            for field in ('quantity', 'avg_price', 'stop_price', 'take_price'):
                assert state[field] == before[field]
            assert state['blocked'] == 'CORPORATE_ACTION_RECONCILIATION'
            assert len((await db.scalars(select(Order).where(Order.user_id == uid))).all()) == 1
        calls = runner.notification.notify_corporate_action_hold.await_args_list
        assert len(calls) == 3 and {c.kwargs['ref'] for c in calls} == {first['hold']['ref']}
        assert {c.kwargs['user_id'] for c in calls} == {str(uid)}
        runner.notification.notify_corporate_action_hold.reset_mock()
        preview = await runner.run(uid)
        assert preview['status'] == 'DRY_RUN' and preview['code'] == first['code']
        runner.notification.notify_corporate_action_hold.assert_not_awaited()
    asyncio.run(scenario())


def test_detected_hold_is_logged_as_blocked_with_visible_reason(runtime, monkeypatch):
    sessions, source = runtime
    logs = []
    async def persist(uid, record):
        logs.append(record)
    monkeypatch.setattr(auto_trade, '_persist_cycle', persist)
    monkeypatch.setattr(auto_trade.strategy_loader.settings, 'STRATEGY_SPEC_SOURCE', 'fixed_test')
    monkeypatch.setattr(auto_trade.strategy_loader.settings, 'DOMAIN_RAG_LAB_BASE_URL', '')
    async def scenario():
        uid = await holding(sessions, source, quant_auto_enabled=True)
        split_history(source)
        for _ in range(2):
            await auto_trade._run_quant_cycle(str(uid))
            assert logs[-1]['execution_state'] == 'BLOCKED', logs[-1]
            assert logs[-1]['v2']['code'] == 'CORPORATE_ACTION_RECONCILIATION'
            assert '자동 청산(손절·익절 포함)' in logs[-1]['note']
            assert '보류 중에는 자동 손절·익절도 실행되지 않습니다.' in logs[-1]['note']
            assert not logs[-1]['trades']
    asyncio.run(scenario())


def test_notification_failure_never_releases_held_position(runtime, monkeypatch):
    sessions, source = runtime
    monkeypatch.setattr(runner.notification, 'notify_corporate_action_hold', AsyncMock(side_effect=RuntimeError('synthetic')))
    async def scenario():
        uid = await holding(sessions, source)
        split_history(source)
        for _ in range(2):
            result = await runner.run(uid, execute=True)
            assert result['status'] == 'skipped' and result['notification'] == 'unconfirmed'
        async with sessions() as db:
            assert len((await db.scalars(select(Order).where(Order.user_id == uid))).all()) == 1
    asyncio.run(scenario())


def test_scheduler_persists_blocked_run_and_user_facing_reason(runtime, monkeypatch):
    from app.services import execution_runs
    sessions, source = runtime
    monkeypatch.setattr(execution_runs, 'get_session_factory', lambda: sessions)
    monkeypatch.setattr(auto_trade, 'cache_get', AsyncMock(return_value=None))
    monkeypatch.setattr(auto_trade, 'cache_set', AsyncMock())
    monkeypatch.setattr(auto_trade.strategy_loader.settings, 'STRATEGY_SPEC_SOURCE', 'fixed_test')
    monkeypatch.setattr(auto_trade.strategy_loader.settings, 'DOMAIN_RAG_LAB_BASE_URL', '')
    async def scenario():
        uid = await holding(sessions, source, quant_auto_enabled=True)
        split_history(source)
        result = await execution_runs.run(uid, 600, lambda: auto_trade._run_quant_cycle(str(uid)))
        assert result['status'] == 'BLOCKED', result
        async with sessions() as db:
            saved = await db.get(ExecutionRun, result['run_id'])
            assert saved.status == 'BLOCKED' and saved.detail['orders'] == 0
            assert '자동 청산(손절·익절 포함)' in saved.detail['note']
        cached = auto_trade.cache_set.await_args.args[1]['cycles'][-1]
        assert cached['note'] == saved.detail['note']
    asyncio.run(scenario())


def test_pending_exit_is_cancelled_before_split_fill(runtime):
    sessions, source = runtime
    async def scenario():
        uid = await holding(sessions, source)
        next_bar(source, date(2026, 8, 31), 180)
        planned = await runner.run(uid, execute=True)
        assert planned['decision']['action'] == 'SELL'
        for row in source['bars']:
            row['factor'] = .5
            for key in ('open', 'high', 'low', 'close'):
                row['adjusted_' + key] = row[key] * .5
        next_bar(source, date(2026, 9, 1), 90)
        result = await runner.run(uid, execute=True)
        assert result['code'] == 'CORPORATE_ACTION_RECONCILIATION', result
        async with sessions() as db:
            state = (await db.get(StrategyRuntime, runner.runtime_id(runner.context(uid)))).state
            assert state['quantity'] > 0 and state['pending'] is None
            assert len((await db.scalars(select(Order).where(Order.user_id == uid))).all()) == 1
    asyncio.run(scenario())


def test_corporate_action_notification_is_deduplicated_per_user(runtime, monkeypatch):
    from app.database import postgres
    sessions, _ = runtime
    monkeypatch.setattr(postgres, 'get_session_factory', lambda: sessions)
    monkeypatch.setattr(notification, '_load_user_settings', AsyncMock(return_value={
        'channels': ['slack'], 'slack_webhook_url': 'https://example.invalid/synthetic'}))
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(notification, 'send_slack', send)
    async def scenario():
        for _ in range(2):
            uid = await user(sessions)
            for _ in range(2):
                await NOTIFY_HOLD(symbol='005930.KS', strategy_id='ma_cross_20_60',
                    reason=runner.CORPORATE_ACTION_REASON, ref='same-review-event', user_id=str(uid))
            async with sessions() as db:
                logs = (await db.scalars(select(NotificationLog).where(NotificationLog.user_id == uid))).all()
                assert len(logs) == 1 and logs[0].kind == 'strategy_corporate_action_hold'
        assert send.await_count == 2
    asyncio.run(scenario())


def test_hold_warning_is_explicit_in_short_and_full_notifications(monkeypatch):
    from app.services import alert_format
    dispatch = AsyncMock()
    monkeypatch.setattr(notification, 'dispatch_event', dispatch)
    asyncio.run(NOTIFY_HOLD(symbol='005930.KS', strategy_id='ma_cross_20_60',
        reason=runner.CORPORATE_ACTION_REASON, ref='synthetic', user_id='synthetic-user'))
    event = dispatch.await_args.args[0]
    warning = '보류 중에는 자동 손절·익절도 실행되지 않습니다.'
    assert warning in alert_format.render_sms(event)
    assert warning in alert_format.render_plain(event)
    assert warning in alert_format.render_telegram(event)
    assert warning in str(alert_format.render_discord(event))
    _, html, text = alert_format.render_email(event)
    assert warning in html and warning in text
