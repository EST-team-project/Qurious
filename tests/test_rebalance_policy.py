"""TC-RB 정책: 실제 주문 방향·경계·예산·PG 동시 승인 회귀 시험."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import os
import uuid

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.services import rebalance as rb, rebalance_policy as p, paper_trading as pt
from app.models import User, PaperAccount, Portfolio, RebalanceRun, CashflowEvent, Order


def target(symbol='A.KS', weight=60):
    return dict(symbol=symbol, name=symbol, weight_pct=weight)


def position(symbol, amount, price=1000):
    return dict(symbol=symbol, name=symbol, quantity=int(amount/price), currentPrice=price, evalAmount=amount)


@pytest.mark.parametrize('amount,expected', [(650000,500),(550000,500),(549900,501),(550100,499)])
def test_exact_drift_boundaries(amount, expected):
    snap=p.weights(1000000-amount-200000,[position('A.KS',amount),position('B.KS',200000)],
                   [target(),target('B.KS',20)],5,True,False)
    assert snap['max_drift_bp']==expected
    assert snap['drift_exceeded']==(expected>=500)


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,'abc'])
def test_invalid_numeric_values(value):
    with pytest.raises(ValueError): p.number(value,'금액')


def test_unplanned_asset_not_in_denominator_or_orders():
    snap=p.weights(400000,[position('A.KS',600000),position('B.KS',2000000)], [target()],5,True,True)
    assert snap['total_asset']==1000000
    assert snap['excluded_asset']==2000000
    assert snap['max_drift_bp']==0
    assert p.orders(snap,{'A.KS':1000,'B.KS':1000},10000)['orders']==[]


def test_costs_keep_cash_reserve_and_minimum_order():
    snap=p.weights(1000000,[],[target(weight=100)],5,True,True)
    result=p.orders(snap,{'A.KS':1000},10000)
    assert result['orders'][0]['quantity']==999
    assert result['estimated_cash_after']>=0
    assert result['estimated_cost']>0
    assert p.orders(snap,{'A.KS':1000},1000000)['orders']==[]


def test_cashflow_buy_only_and_budget_cap():
    snap=p.weights(400000,[position('A.KS',400000),position('B.KS',300000)],
                   [target(),target('B.KS',20)],5,True,False)
    result=p.orders(snap,{'A.KS':1000,'B.KS':1000},1000,'buy_only',50000)
    assert result['orders'] and all(o['side']=='BUY' for o in result['orders'])
    assert sum(o['net_amount'] for o in result['orders'])<=50000


def test_cashflow_sell_only_stops_at_cash_deficit():
    snap=p.weights(100000,[position('A.KS',600000),position('B.KS',200000)],
                   [target(),target('B.KS',20)],5,True,False)
    result=p.orders(snap,{'A.KS':1000,'B.KS':1000},1000,'sell_only',80000)
    assert all(o['side']=='SELL' for o in result['orders'])
    assert result['estimated_cash_after']<=180000
    assert result['estimated_cash_after']>178000


@pytest.mark.parametrize('excess,budget,threshold,due',[
    (60000,60000,100000,False),(120000,120000,100000,True),
    (500000,0,0,False),(500000,-100000,0,False),(-120000,-120000,100000,True),
])
def test_external_cashflow_gate(excess,budget,threshold,due):
    assert p.cashflow_signal(excess,budget,threshold)['cashflow_due']==due


@pytest.mark.parametrize('time,drift,mode,cf,expected',[
    (True,True,'always',True,['TIME','DRIFT','CASHFLOW']),
    (True,False,'scheduled',False,[]),(False,True,'scheduled',False,[]),
    (True,True,'scheduled',False,['TIME','DRIFT']),
    (False,False,'always',True,['CASHFLOW']),
])
def test_combined_conditions(time,drift,mode,cf,expected):
    assert p.choose_triggers(time,drift,mode,cf)==expected


DB_URL=os.getenv('QURIOUS_TEST_DATABASE_URL','')
needs_db=pytest.mark.skipif(not DB_URL,reason='시험 DB URL 필요')


@pytest.fixture
def time_calendar(rebalance_calendar, monkeypatch):
    # Calendar-aware tests must not depend on the wall clock or the CI weekday.
    fixed = datetime(2026, 10, 6, 3, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
    monkeypatch.setattr(rb, 'datetime', Clock)
    return fixed


@asynccontextmanager
async def scenario(monkeypatch, symbols=('A.KS', 'B.KS')):
    assert 'test' in DB_URL, '시험 DB만 사용'
    engine=create_async_engine(DB_URL)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    uid=uuid.uuid4()
    async def quote(sym):
        return dict(symbol=sym,name=sym,price=1000,market='KOSPI')
    monkeypatch.setattr(pt,'resolve_stock',quote)
    async with factory() as db:
        db.add(User(id=uid,name='RB test',email=f'{uid}@example.com',password_hash='test',client_id=uid.hex))
        await db.flush()
        db.add(PaperAccount(user_id=uid,cash=200000,initial_cash=1000000))
        db.add_all([Portfolio(user_id=uid,symbol=symbols[0],name=symbols[0],quantity=600,avg_price=1000,book='PAPER'),
                    Portfolio(user_id=uid,symbol=symbols[1],name=symbols[1],quantity=200,avg_price=1000,book='PAPER')])
        plan=await rb.get_plan(db,uid)
        rb.apply_plan_update(plan,dict(targets=[target(symbols[0]),target(symbols[1],20)],drift_enabled=False,
                                      cashflow_min_amount=100000,min_order_amount=1000))
        await db.commit()
    try:
        yield factory,uid
    finally:
        from app.services.account import delete_user_data
        async with factory() as db:
            await delete_user_data(db,uid)
            await db.commit()
        await engine.dispose()


@needs_db
def test_small_deposits_accumulate_and_approval_preserves_buy_only(monkeypatch):
    async def go():
        async with scenario(monkeypatch) as (factory,uid):
            async with factory() as db:
                first=await rb.record_cashflow(db,uid,'DEPOSIT',100000)
                assert first['run'] is None # investable part 80k
                second=await rb.record_cashflow(db,uid,'DIVIDEND',100000)
                run=second['run']
                assert run['plan_kind']=='buy_only'
                assert all(o['side']=='BUY' for o in run['orders'])
                await db.commit()
                result=await rb.execute_proposal(db,uid,uuid.UUID(run['id']))
                assert str(result.id)==run['id']
                assert result.status=='executed'
                assert all(o['side']=='BUY' for o in result.orders)
                assert result.context['actual_cost']>0
                assert 0<=sum(e.remaining_budget for e in await rb.pending_cashflows(db,uid))<3000
                await db.commit()
                with pytest.raises(rb.RebalanceError):
                    await rb.execute_proposal(db,uid,result.id)
    asyncio.run(go())


@needs_db
def test_withdrawal_and_deposit_netting(monkeypatch):
    async def go():
        async with scenario(monkeypatch) as (factory,uid):
            async with factory() as db:
                await rb.record_cashflow(db,uid,'DEPOSIT',100000)
                await rb.record_cashflow(db,uid,'WITHDRAW',100000)
                assert sum(e.remaining_budget for e in await rb.pending_cashflows(db,uid))==0
                result=await rb.record_cashflow(db,uid,'WITHDRAW',150000)
                assert result['run']['plan_kind']=='sell_only'
                assert all(o['side']=='SELL' for o in result['run']['orders'])
                await db.commit()
                done=await rb.execute_proposal(db,uid,uuid.UUID(result['run']['id']))
                assert done.status=='executed'
                assert all(o['side']=='SELL' for o in done.orders)
                await db.commit()
    asyncio.run(go())


@needs_db
def test_concurrent_checks_and_approvals_execute_once(monkeypatch):
    async def go():
        async with scenario(monkeypatch) as (factory,uid):
            async with factory() as db:
                await rb.record_cashflow(db,uid,'DEPOSIT',200000)
                await db.commit()
            async def check():
                async with factory() as db:
                    plan=await rb.get_plan(db,uid)
                    result=await rb.check_due(db,uid,plan)
                    await db.commit()
                    return result['run_id']
            ids=await asyncio.gather(*[check() for _ in range(4)])
            assert len(set(ids))==1
            async def approve():
                async with factory() as db:
                    try:
                        result=await rb.execute_proposal(db,uid,uuid.UUID(ids[0]))
                        await db.commit()
                        return len(result.orders)
                    except rb.RebalanceError:
                        await db.rollback()
                        return 0
            counts=await asyncio.gather(approve(),approve())
            assert sum(c>0 for c in counts)==1
            async with factory() as db:
                assert (await db.execute(select(func.count(Order.id)).where(Order.user_id==uid))).scalar()==sum(counts)
                assert (await db.execute(select(func.count(RebalanceRun.id)).where(RebalanceRun.user_id==uid))).scalar()==1
    asyncio.run(go())


@needs_db
def test_setting_change_rejects_old_approval(monkeypatch):
    async def go():
        async with scenario(monkeypatch) as (factory,uid):
            async with factory() as db:
                result=await rb.record_cashflow(db,uid,'DEPOSIT',200000)
                plan=await rb.get_plan(db,uid)
                rb.apply_plan_update(plan,{'targets':[target(weight=50),target('B.KS',20)]})
                await db.commit()
                with pytest.raises(rb.RebalanceError,match='설정이 바뀌었'):
                    await rb.execute_proposal(db,uid,uuid.UUID(result['run']['id']))
    asyncio.run(go())


@needs_db
def test_same_day_conditions_merge_and_auto_execution_once(monkeypatch, time_calendar):
    async def go():
        async with scenario(monkeypatch) as (factory,uid):
            async with factory() as db:
                plan=await rb.get_plan(db,uid)
                rb.apply_plan_update(plan,{'time_period':'monthly','drift_enabled':True,'drift_threshold_pct':5})
                plan.next_run_at=time_calendar-timedelta(days=1)
                await db.commit()
                # Date is due; no orders at balanced weights. A deposit now fires all three conditions.
                result=await rb.record_cashflow(db,uid,'DEPOSIT',200000)
                assert result['run']['triggers']==['TIME','DRIFT','CASHFLOW']
                plan.auto_execute=True
                await db.commit()
                again=await rb.check_due(db,uid,plan)
                assert again['run_id']==result['run']['id']
                assert again['status']=='executed'
                await db.commit()
                last=await rb.check_due(db,uid,plan)
                assert last['already_processed']
    asyncio.run(go())

@needs_db
def test_batch_continues_after_one_plan_fails(monkeypatch):
    monkeypatch.setattr(rb.daily, 'readiness', lambda: dict(ready=True,
        decision_date=datetime.now(rb.KST).date().isoformat(), data_as_of='2026-10-02',
        update_finished_at='2026-10-06T13:00:00+09:00'))
    async def go():
        async with scenario(monkeypatch) as (factory, first_uid):
            async with scenario(monkeypatch) as (_, second_uid):
                checked = []
                async def check(db, user_id, plan, **kwargs):
                    checked.append(user_id)
                    if len(checked) == 1:
                        raise rb.RebalanceError('시세 조회 실패')
                    assert plan.user_id == user_id
                    return {'status': 'proposed'}
                monkeypatch.setattr(rb, 'check_due', check)
                result = await rb.check_all_due(factory)
                assert {first_uid, second_uid}.issubset(checked)
                assert result['checked'] == len(checked) - 1
                assert result['errors'] == 1
                assert result['proposed'] == len(checked) - 1
    asyncio.run(go())


@needs_db
@pytest.mark.parametrize('mode', ['always', 'scheduled'])
def test_pending_time_proposal_survives_next_check(monkeypatch, mode, time_calendar):
    async def go():
        async with scenario(monkeypatch) as (factory, uid):
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                rb.apply_plan_update(plan, {'time_period': 'monthly', 'drift_check_mode': mode,
                                           'drift_enabled': mode == 'scheduled'})
                plan.next_run_at = time_calendar - timedelta(days=1)
                account = await pt.get_account(db, uid, lock=True)
                account.cash = 400000
                await db.commit()
                first = await rb.check_due(db, uid, plan)
                assert first['status'] == 'proposed'
                assert 'TIME' in first['triggers']
                assert plan.next_run_at > time_calendar
                await db.commit()
                second = await rb.check_due(db, uid, plan)
                assert second['run_id'] == first['run_id']
                assert second['status'] == 'proposed'
                assert 'TIME' in second['triggers']
                await db.commit()
                # Removing the schedule must invalidate its pending time condition.
                rb.apply_plan_update(plan, {'time_period': 'none', 'drift_check_mode': 'always',
                                           'drift_enabled': False})
                await db.commit()
                assert (await rb.check_due(db, uid, plan))['run_id'] is None
                row = await db.get(RebalanceRun, uuid.UUID(first['run_id']))
                assert row.status == 'skipped'
                await db.commit()
    asyncio.run(go())


@needs_db
def test_ordinary_cash_change_does_not_create_cashflow_plan(monkeypatch):
    async def go():
        async with scenario(monkeypatch) as (factory,uid):
            async with factory() as db:
                account=await pt.get_account(db,uid,lock=True)
                account.cash+=300000 # simulate cash proceeds from an unrelated trade, not an external event
                await db.commit()
                plan=await rb.get_plan(db,uid)
                result=await rb.check_due(db,uid,plan)
                assert not result['cashflow_due'] and result['run_id'] is None
    asyncio.run(go())


@needs_db
def test_event_survives_quote_failure(monkeypatch):
    async def go():
        async with scenario(monkeypatch) as (factory,uid):
            async def unavailable(sym):
                raise pt.PaperTradeError('시세 없음')
            monkeypatch.setattr(pt,'resolve_stock',unavailable)
            async with factory() as db:
                result=await rb.record_cashflow(db,uid,'DEPOSIT',200000)
                assert result['check_error']
                await db.commit()
                assert (await pt.get_account(db,uid)).cash==400000
                assert sum(e.remaining_budget for e in await rb.pending_cashflows(db,uid))==160000
    asyncio.run(go())


@needs_db
def test_partial_fill_is_recorded_and_not_retried_automatically(monkeypatch):
    async def go():
        async with scenario(monkeypatch) as (factory,uid):
            async with factory() as db:
                result=await rb.record_cashflow(db,uid,'DEPOSIT',200000)
                await db.commit()
                original=pt.stock_order
                async def fail_second(db, user_id, symbol, side, quantity, **kwargs):
                    if symbol=='B.KS': raise pt.PaperTradeError('시험용 주문 실패')
                    return await original(db,user_id,symbol,side,quantity,**kwargs)
                monkeypatch.setattr(pt,'stock_order',fail_second)
                run=await rb.execute_proposal(db,uid,uuid.UUID(result['run']['id']))
                assert run.status=='partial'
                assert run.orders[-1]['status']=='failed'
                await db.commit()
                plan=await rb.get_plan(db,uid)
                again=await rb.check_due(db,uid,plan)
                assert again['already_processed']
                assert sum(e.remaining_budget for e in await rb.pending_cashflows(db,uid))>0
    asyncio.run(go())


@needs_db
def test_calendar_api_repairs_saved_schedule_and_reports_missing_data(monkeypatch, time_calendar, tmp_path):
    from app.routes import rebalance as routes
    async def no_audit(*args, **kwargs):
        pass
    monkeypatch.setattr(routes, 'audit', no_audit)
    async def go():
        async with scenario(monkeypatch) as (factory, uid):
            user = {'id': str(uid)}
            async with factory() as db:
                saved = await routes.update_plan(routes.PlanBody(time_period='monthly'), user, db)
                assert saved['next_run_at'].startswith('2026-11-02T00:00:00')
                plan = await rb.get_plan(db, uid)
                plan.next_run_at = datetime(2026, 11, 1, tzinfo=timezone.utc)
                await db.commit()
                restored = await routes.get_plan(user, db)
                assert restored['next_run_at'] == saved['next_run_at']
                status = await routes.status(user, db)
                assert not status['triggers']['time_due']
                monkeypatch.setenv('COLLECTOR_DB_PATH', str(tmp_path / 'absent.sqlite3'))
                unavailable = await routes.status(user, db)
                assert unavailable['plan']['next_run_at'] is None
                assert unavailable['plan']['time_schedule_error']
                saved = await routes.update_plan(routes.PlanBody(time_period='quarterly'), user, db)
                assert saved['time_period'] == 'quarterly' and saved['time_schedule_error']
    asyncio.run(go())


@needs_db
def test_missing_calendar_blocks_time_but_preserves_cashflow(monkeypatch, time_calendar, tmp_path):
    monkeypatch.setenv('COLLECTOR_DB_PATH', str(tmp_path / 'absent.sqlite3'))
    async def go():
        async with scenario(monkeypatch) as (factory, uid):
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                rb.apply_plan_update(plan, {'time_period': 'monthly'})
                plan.next_run_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
                await db.commit()
                result = await rb.record_cashflow(db, uid, 'DEPOSIT', 200000)
                assert result['event']['cash_after'] == 400000
                assert result['run']['triggers'] == ['CASHFLOW']
                assert result['run']['plan_kind'] == 'buy_only'
                await db.commit()
    asyncio.run(go())


@needs_db
def test_next_year_calendar_missing_does_not_cancel_pending_time_approval(monkeypatch, rebalance_calendar):
    fixed = datetime(2027, 1, 4, 3, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
    monkeypatch.setattr(rb, 'datetime', Clock)
    async def go():
        async with scenario(monkeypatch) as (factory, uid):
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                rb.apply_plan_update(plan, {'time_period': 'yearly'})
                plan.next_run_at = datetime(2027, 1, 1, tzinfo=timezone.utc)
                account = await pt.get_account(db, uid, lock=True)
                account.cash = 400000
                await db.commit()
                first = await rb.check_due(db, uid, plan)
                assert first['triggers'] == ['TIME'] and first['status'] == 'proposed'
                assert plan.time_schedule_error  # 2028 is beyond the calendar
                await db.commit()
                second = await rb.check_due(db, uid, plan)
                assert second['run_id'] == first['run_id'] and second['triggers'] == ['TIME']
                await db.commit()
                run = await rb.execute_proposal(db, uid, uuid.UUID(first['run_id']))
                assert run.status == 'executed'
                await db.commit()
    asyncio.run(go())


@needs_db
@pytest.mark.parametrize('mode', ['always', 'scheduled'])
def test_calendar_correction_blocks_pending_time_approval(monkeypatch, time_calendar, rebalance_calendar, mode):
    import sqlite3
    async def go():
        async with scenario(monkeypatch) as (factory, uid):
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                rb.apply_plan_update(plan, {'time_period': 'monthly', 'drift_check_mode': mode,
                                           'drift_enabled': mode == 'scheduled'})
                plan.next_run_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
                account = await pt.get_account(db, uid, lock=True)
                account.cash = 400000
                await db.commit()
                first = await rb.check_due(db, uid, plan)
                assert 'TIME' in first['triggers']
                await db.commit()
                with sqlite3.connect(rebalance_calendar) as calendar_db:
                    calendar_db.execute("UPDATE market_calendar SET is_trading_day=0 WHERE cal_date='2026-10-06'")
                with pytest.raises(rb.RebalanceError, match='시간 제안 승인 대기'):
                    await rb.execute_proposal(db, uid, uuid.UUID(first['run_id']))
                if mode == 'scheduled':
                    second = await rb.record_cashflow(db, uid, 'DEPOSIT', 200000)
                    assert second['run']['triggers'] == ['CASHFLOW']
                    assert second['run']['plan_kind'] == 'buy_only'
                else:
                    second = await rb.check_due(db, uid, plan)
                    assert not second['time_due'] and second['run_id'] is None
                await db.commit()
    asyncio.run(go())
