"""#124: 예약 종료·취소·휴장일 변경을 실제 SQLite/격리 PostgreSQL로 검증한다."""
import asyncio
import sqlite3
import uuid
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func

from app.models import Order, RebalanceRun
from app.routes import rebalance as routes
from app.services import rebalance as rb, rebalance_prices as prices, rebalance_settlement as st
from tests.test_rebalance_policy import scenario, needs_db
from tests.test_rebalance_daily import clock, ready_data  # noqa: F401
from tests.test_rebalance_settlement import SYMBOLS, insert_open, ready, queue
from tests.test_rebalance_unified import no_audit, stamp_account_history

pytestmark = pytest.mark.usefixtures('rebalance_db_schema')


def complete(path, source='portal', status='done'):
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT OR REPLACE INTO ingest_day (source,bas_dt,status,updated_at) VALUES (?, '20261007', ?, '2026-10-08T13:00:00+09:00')", (source, status))


@pytest.mark.parametrize('source', ['portal', 'portal_etf'])
def test_missing_price_requires_its_own_completed_source(clock, ready_data, source):
    path = ready_data[0]
    symbol = SYMBOLS[0]
    if source == 'portal_etf':
        symbol = '0000D0.KS'
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO etf_daily (bas_dt,srtn_cd,clpr) VALUES ('20261002','0000D0',1000)")
    complete(path, 'portal_etf' if source == 'portal' else 'portal')
    for state in ['error', 'empty', 'holiday']:
        complete(path, source, state)
        with pytest.raises(prices.PriceUnavailable) as exc:
            prices.read_prices([symbol], date(2026, 10, 7), 'open')
        assert not isinstance(exc.value, prices.OpenNotTradable)
    complete(path, source)
    with pytest.raises(prices.OpenNotTradable):
        prices.read_prices([symbol], date(2026, 10, 7), 'open')
    # 종가 평가는 동일한 미체결 정책을 적용하지 않는다.
    with pytest.raises(prices.PriceUnavailable) as exc:
        prices.read_prices([symbol], date(2026, 10, 7))
    assert not isinstance(exc.value, prices.OpenNotTradable)


def test_unknown_symbol_waits_for_both_sources(clock, ready_data):
    complete(ready_data[0])
    with pytest.raises(prices.PriceUnavailable) as exc:
        prices.read_prices(['999999.KS'], date(2026, 10, 7), 'open')
    assert not isinstance(exc.value, prices.OpenNotTradable)
    complete(ready_data[0], 'portal_etf')
    with pytest.raises(prices.OpenNotTradable):
        prices.read_prices(['999999.KS'], date(2026, 10, 7), 'open')


@needs_db
@pytest.mark.parametrize('kind', ['missing', 'zero_volume', 'halted', 'invalid_open'])
def test_completed_day_closes_only_confirmed_untradable_reservation(monkeypatch, clock, ready_data, kind):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan, run = await queue(db, uid)
                rid = run.id
                await db.commit()
            if kind != 'missing':
                insert_open(ready_data[0], price=0 if kind in ('zero_volume', 'invalid_open') else 900,
                            volume=0 if kind == 'zero_volume' else 1000)
                if kind == 'halted':
                    with sqlite3.connect(ready_data[0]) as conn:
                        conn.execute("UPDATE price_daily SET halted=1 WHERE bas_dt='20261007'")
            state = ready(clock)
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                if kind != 'invalid_open':
                    # 전체 러너 성공만으로 미체결 확정하지 않는다.
                    assert (await st.settle(db, uid, plan, state)).status == 'scheduled'
                complete(ready_data[0])
                result = await st.settle(db, uid, plan, state)
                if kind == 'invalid_open':
                    assert result.status == 'scheduled'  # 거래량 있는 0 시가는 데이터 오류/지연
                else:
                    assert result.status == 'cancelled'
                    assert result.context['cancel_reason'] == 'open_not_tradable'
                    assert result.context['cancelled_at'].startswith('2026-10-08')
                    assert all(o['status'] == 'cancelled' for o in result.orders)
                    assert await st.pending(db, uid) is None
                assert (await rb.pt.get_account(db, uid)).cash == 200000
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
                await db.commit()
                assert (await db.get(RebalanceRun, rid)).status == result.status
    asyncio.run(go())


@needs_db
@pytest.mark.parametrize('disable', [False, True])
def test_cancel_review_preserves_account_budget_and_daily_gate(monkeypatch, clock, ready_data, disable):
    monkeypatch.setattr(routes, 'audit', no_audit)
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan, run = await queue(db, uid)
                await rb.record_cashflow(db, uid, 'DEPOSIT', 12345)
                run.context = {**run.context, 'review_required': True, 'waiting_reason': '계좌 변경'}
                await db.commit()
                stamp = await st.account_stamp(db, uid)
                budget = sum(e.remaining_budget for e in await rb.pending_cashflows(db, uid))
                ready_data[2](ok=False)
                user = {'id': str(uid)}
                if disable:
                    await routes.update_plan(routes.PlanBody(is_active=False), user, db)
                    await db.refresh(run)
                    assert run.context['cancel_reason'] == 'plan_disabled'
                else:
                    result = await routes.cancel_run(run.id, user, db)
                    assert result['context']['cancel_reason'] == 'user_cancelled'
                    repeat = await routes.cancel_run(run.id, user, db)
                    assert repeat['context']['cancelled_at'] == result['context']['cancelled_at']
                assert run.status == 'cancelled'
                assert await st.account_stamp(db, uid) == stamp
                assert sum(e.remaining_budget for e in await rb.pending_cashflows(db, uid)) == budget
                assert plan.last_auto_check_date == date(2026, 10, 6)
                assert await st.pending(db, uid) is None
    asyncio.run(go())


@needs_db
def test_cancel_ownership_and_terminal_protection(monkeypatch, clock, ready_data):
    monkeypatch.setattr(routes, 'audit', no_audit)
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan, run = await queue(db, uid)
                rid = run.id
                await db.commit()
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await routes.cancel_run(rid, {'id': str(uuid.uuid4())}, db)
                assert exc.value.status_code == 404
            insert_open(ready_data[0])
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                assert (await st.settle(db, uid, plan, ready(clock))).status == 'executed'
                await db.commit()
                with pytest.raises(HTTPException) as exc:
                    await routes.cancel_run(rid, {'id': str(uid)}, db)
                assert exc.value.status_code == 409
                assert (await db.get(RebalanceRun, rid)).status == 'executed'
    asyncio.run(go())


@needs_db
def test_holiday_reschedule_updates_account_change_cutoff(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan, run = await queue(db, uid)
                await db.commit()
                await rb.record_cashflow(db, uid, 'DEPOSIT', 10000)
                await stamp_account_history(db, uid, 7)
                await db.commit()
            with sqlite3.connect(ready_data[0]) as conn:
                conn.execute("UPDATE market_calendar SET is_trading_day=0 WHERE cal_date='2026-10-07'")
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                result = await st.settle(db, uid, plan, ready(clock))
                assert result.status == 'scheduled' and result.context['scheduled_for'] == '2026-10-08'
                change = result.context['reschedules'][0]
                assert change['previous_date'] == '2026-10-07' and change['reason'] == 'calendar_closed'
                await db.commit()
                insert_open(ready_data[0], day='20261008')
                clock.current = datetime(2026, 10, 12, 13, 30, tzinfo=rb.KST)
                result = await st.settle(db, uid, plan, {'ready': True, 'data_as_of': '2026-10-08'})
                assert result.status == 'executed' and result.context['fill_date'] == '2026-10-08'
                assert len(result.context['reschedules']) == 1
    asyncio.run(go())


@needs_db
def test_cancel_and_settle_race_has_one_terminal_outcome(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                _, run = await queue(db, uid)
                rid = run.id
                await db.commit()
            insert_open(ready_data[0])
            state = ready(clock)
            async def cancel():
                async with factory() as db:
                    try:
                        await st.cancel_reservation(db, uid, rid)
                        await db.commit()
                    except rb.RebalanceError:
                        await db.rollback()
            async def settle():
                async with factory() as db:
                    plan = await rb.get_plan(db, uid)
                    await st.settle(db, uid, plan, state)
                    await db.commit()
            await asyncio.gather(cancel(), settle())
            async with factory() as db:
                run = await db.get(RebalanceRun, rid)
                count = await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid))
                assert run.status in ('cancelled', 'executed')
                assert count == (0 if run.status == 'cancelled' else 2)
    asyncio.run(go())


@needs_db
def test_cancel_allows_next_daily_decision_without_repeating_today(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan, run = await queue(db, uid)
                rid = run.id
                await st.cancel_reservation(db, uid, rid)
                await db.commit()
                assert (await rb.check_daily(db, uid, plan))['reason'] == 'already_checked'
                await db.commit()
            insert_open(ready_data[0])
            ready(clock)
            ready_data[2](started_at='2026-10-08T12:30:01+09:00', finished_at='2026-10-08T13:00:00+09:00',
                          after={'price_max': '20261007'})
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                result = await rb.check_daily(db, uid, plan)
                assert result['checked'] and result['status'] == 'scheduled'
                assert result['run_id'] != str(rid)
                old = await db.get(RebalanceRun, rid)
                assert old.status == 'cancelled'
                new = await st.pending(db, uid)
                assert new.context['valuation_date'] == '2026-10-07'
                assert new.context['scheduled_for'] == '2026-10-12'
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
    asyncio.run(go())
