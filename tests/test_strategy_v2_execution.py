"""실제 QUANT 장부·PG 공통 관문·판 2 상태의 왕복. KIS/알림 외부 호출 없음."""
import asyncio
from copy import deepcopy
from datetime import date, timedelta, time
import os
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.models import User, BrokerSettings, QuantVirtualAccount, Order, Portfolio, OrderIntent, StrategyRuntime
from app.services import strategy_v2_execution as runner, strategy_v2 as v2, execution_control as control, auto_trade
from tests.test_strategy_v2 import bars, bar

pytestmark=[pytest.mark.skipif(not os.getenv('QURIOUS_TEST_DATABASE_URL'),reason='일회용 PG 필요'),pytest.mark.usefixtures('rebalance_db_schema')]


@pytest.fixture
def runtime(monkeypatch):
    engine=create_async_engine(os.environ['QURIOUS_TEST_DATABASE_URL'],poolclass=NullPool)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    source={'bars':bars()}
    monkeypatch.setattr(runner,'get_session_factory',lambda:sessions)
    monkeypatch.setattr(control,'get_session_factory',lambda:sessions)
    monkeypatch.setattr(auto_trade,'get_session_factory',lambda:sessions)
    monkeypatch.setattr(control.risk_guard,'_redis',lambda:AsyncMock(ping=AsyncMock(return_value=True)))
    monkeypatch.setattr(v2.market_calendar,'trading_days',lambda start,end:{'partial':False,'days':[
        {'date':str(start+timedelta(days=i)),'is_trading_day':True} for i in range((end-start).days+1)]})
    monkeypatch.setattr(runner,'inputs',lambda:(deepcopy(source['bars']),{'data_as_of':source['bars'][-1]['date'],'source_commit':'verified-fixture','data_ready_at':'2026-10-29T12:31:00+09:00'}))
    yield sessions,source
    asyncio.run(engine.dispose())


async def user(sessions, cash=100000, **overrides):
    uid=uuid.uuid4()
    async with sessions() as db:
        db.add(User(id=uid,name='v2-exec',email=f'{uid}@example.test',password_hash='test',client_id=uid.hex))
        await db.flush()
        values=dict(quant_mode='paper',quant_auto_enabled=False,risk_kill_switch=False,
            quant_strategy_id='ma_cross_20_60',quant_strategy_version=2,quant_per_trade_budget=100000,
            quant_buy_ratio=1,risk_max_position_pct=30,risk_daily_loss_limit_pct=0,risk_cooldown_min=0)
        db.add(BrokerSettings(user_id=uid,**(values|overrides)))
        db.add(QuantVirtualAccount(user_id=uid,initial_capital=cash,cash_balance=cash))
        await db.commit()
    return uid


def next_bar(source, day, close, opening=None):
    row=bar(day,close)
    if opening is not None:
        row.update(open=opening,low=min(opening,close)-2,high=max(opening,close)+2)
        row.update({'adjusted_'+k:row[k] for k in ('open','high','low','close')})
    source['bars'].append(row)


def test_next_open_writes_real_quant_ledger_and_full_owned_exit(runtime):
    sessions,source=runtime
    async def scenario():
        uid=await user(sessions)
        dry=await runner.run(uid)
        assert dry['status']=='DRY_RUN'
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(StrategyRuntime).where(StrategyRuntime.user_id==uid))==0
        first=await runner.run(uid,execute=True)
        assert first['status']=='initialized'
        next_bar(source,date(2026,8,30),180,160)
        bought=await runner.run(uid,execute=True)
        assert bought['status']=='filled',bought
        quantity=bought['quantity']
        assert quantity>0 and bought['decision']['action']=='SELL'
        async with sessions() as db:
            order=await db.scalar(select(Order).where(Order.user_id==uid))
            assert order.filled_quantity==quantity and order.execution_intent_id==bought['intent_id']
            assert order.filled_at.astimezone(v2.KST).time()==time(9)
            assert order.filled_at.astimezone(v2.KST).date()==date(2026,8,30)
            assert order.created_at>order.filled_at
        assert (await runner.run(uid,execute=True))['status']=='duplicate'
        next_bar(source,date(2026,8,31),181,180)
        sold=await runner.run(uid,execute=True)
        assert sold['status']=='filled' and sold['quantity']==quantity,sold
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Portfolio).where(Portfolio.user_id==uid))==0
            state=await db.get(StrategyRuntime,runner.runtime_id(runner.context(uid)))
            assert state.state['quantity']==0 and not state.state['reentry_armed']
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id==uid))==2
    asyncio.run(scenario())


def test_parallel_calls_send_one_order(runtime):
    sessions,source=runtime
    async def scenario():
        uid=await user(sessions)
        await runner.run(uid,execute=True)
        next_bar(source,date(2026,8,30),165,160)
        results=await asyncio.gather(*(runner.run(uid,execute=True) for _ in range(5)))
        assert any(r['status']=='filled' for r in results),results
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id==uid))==1
    asyncio.run(scenario())


def test_committed_fill_is_recovered_after_lost_result(runtime,monkeypatch):
    sessions,source=runtime
    original=auto_trade._execute_virtual_trade
    async def lost(*args,**kwargs):
        await original(*args,**kwargs)
        raise RuntimeError('lost after atomic ledger commit')
    monkeypatch.setattr(auto_trade,'_execute_virtual_trade',lost)
    async def scenario():
        uid=await user(sessions)
        await runner.run(uid,execute=True)
        next_bar(source,date(2026,8,30),165,160)
        result=await runner.run(uid,execute=True)
        assert result['status']=='filled' and result['reconciled_from_order'],result
        again=await runner.run(uid,execute=True)
        assert again['status']=='duplicate'
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id==uid))==1
    asyncio.run(scenario())


def test_failure_before_fill_stays_unknown_without_retry(runtime,monkeypatch):
    sessions,source=runtime
    sender=AsyncMock(side_effect=RuntimeError('before book commit'))
    monkeypatch.setattr(auto_trade,'_execute_virtual_trade',sender)
    async def scenario():
        uid=await user(sessions)
        await runner.run(uid,execute=True)
        next_bar(source,date(2026,8,30),165,160)
        for _ in range(2):
            result=await runner.run(uid,execute=True)
            assert result['status']=='unknown',result
        assert sender.await_count==1
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id==uid))==0
    asyncio.run(scenario())


def test_manual_holding_is_not_sold(runtime):
    sessions,source=runtime
    async def scenario():
        uid=await user(sessions)
        async with sessions() as db:
            db.add(Portfolio(user_id=uid,symbol='005930.KS',name='manual',book='QUANT',quantity=5,avg_price=100))
            await db.commit()
        await runner.run(uid,execute=True)
        next_bar(source,date(2026,8,30),180,160)
        bought=await runner.run(uid,execute=True);assert bought['status']=='filled',bought
        next_bar(source,date(2026,8,31),181,180)
        sold=await runner.run(uid,execute=True);assert sold['quantity']==bought['quantity']
        async with sessions() as db:
            pos=await db.scalar(select(Portfolio).where(Portfolio.user_id==uid))
            assert pos.quantity==5
    asyncio.run(scenario())


@pytest.mark.parametrize('change,code', [({'quant_mode':'live'},'V2_PAPER_ONLY'),({'risk_kill_switch':True},'DISABLED')])
def test_live_and_kill_switch_block(runtime,change,code):
    sessions,source=runtime
    async def scenario():
        uid=await user(sessions,**change)
        result=await runner.run(uid,execute=True)
        assert result['code']==code
    asyncio.run(scenario())


def test_zero_quantity_does_not_force_share(runtime):
    sessions,source=runtime
    async def scenario():
        uid=await user(sessions,cash=100)
        await runner.run(uid,execute=True)
        next_bar(source,date(2026,8,30),165,160)
        result=await runner.run(uid,execute=True)
        assert result['code']=='ZERO_QUANTITY',result
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id==uid))==0
    asyncio.run(scenario())


def test_scheduled_cycle_routes_only_exact_v2_and_leaves_auto_off(runtime,monkeypatch):
    sessions,source=runtime
    logs=[]
    async def persist(uid,record):logs.append(record)
    monkeypatch.setattr(auto_trade,'_persist_cycle',persist)
    monkeypatch.setattr(auto_trade.strategy_loader,'get_strategy',AsyncMock(return_value=deepcopy(v2.CONTRACT)))
    market=AsyncMock(side_effect=AssertionError('v2 must not enter v1 indicator/current quote loop'))
    monkeypatch.setattr(auto_trade,'get_quant_indicators',market)
    async def scenario():
        uid=await user(sessions)
        await auto_trade._run_quant_cycle(str(uid))
        assert logs[-1]['execution_state']=='BLOCKED' and logs[-1]['v2']['code']=='DISABLED'
        async with sessions() as db:
            row=await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id==uid))
            assert not row.quant_auto_enabled
            row.quant_auto_enabled=True
            await db.commit()
        await auto_trade._run_quant_cycle(str(uid))
        assert logs[-1]['execution_state']=='COMPLETED' and logs[-1]['v2']['status']=='initialized'
        next_bar(source,date(2026,8,30),165,160)
        await auto_trade._run_quant_cycle(str(uid))
        assert len(logs[-1]['trades'])==1 and logs[-1]['trades'][0]['status']=='filled'
        assert market.await_count==0
    asyncio.run(scenario())


def test_missing_or_changed_remote_v2_never_falls_back(runtime,monkeypatch):
    sessions,source=runtime
    logs=[]
    async def persist(uid,record):logs.append(record)
    monkeypatch.setattr(auto_trade,'_persist_cycle',persist)
    async def scenario():
        uid=await user(sessions,quant_auto_enabled=True)
        for spec in (None,{**v2.CONTRACT,'entry_mode':'close'}):
            monkeypatch.setattr(auto_trade.strategy_loader,'get_strategy',AsyncMock(return_value=spec))
            await auto_trade._run_quant_cycle(str(uid))
            assert logs[-1]['v2']['code']=='V2_INPUT_INVALID'
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(StrategyRuntime).where(StrategyRuntime.user_id==uid))==0
    asyncio.run(scenario())


def test_corporate_action_blocks_before_book_fill(runtime):
    sessions,source=runtime
    async def scenario():
        uid=await user(sessions)
        await runner.run(uid,execute=True)
        source['bars'].append(bar(date(2026,8,30),320,factor=.5))
        result=await runner.run(uid,execute=True)
        assert result['code']=='CORPORATE_ACTION_OR_HALT'
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id==uid))==0
    asyncio.run(scenario())


def test_foreign_position_blocks_unsupported_same_time_valuation(runtime):
    sessions,source=runtime
    async def scenario():
        uid=await user(sessions)
        async with sessions() as db:
            db.add(Portfolio(user_id=uid,symbol='000660.KS',name='other',book='QUANT',quantity=1,avg_price=100))
            await db.commit()
        await runner.run(uid,execute=True)
        next_bar(source,date(2026,8,30),165,160)
        assert (await runner.run(uid,execute=True))['code']=='VALUATION_UNAVAILABLE'
    asyncio.run(scenario())


def test_materially_changed_source_blocks_before_reservation(runtime,monkeypatch):
    sessions,source=runtime
    original=runner.prepare
    async def changed(*args,**kwargs):
        source['bars'][-1]['adjusted_close']+=1
        return await original(*args,**kwargs)
    monkeypatch.setattr(runner,'prepare',changed)
    async def scenario():
        uid=await user(sessions)
        await runner.run(uid,execute=True)
        next_bar(source,date(2026,8,30),165,160)
        result=await runner.run(uid,execute=True)
        assert result['code']=='DATA_CHANGED',result
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id==uid))==0
    asyncio.run(scenario())


def test_missing_next_session_never_executes_at_later_open(runtime):
    sessions,source=runtime
    async def scenario():
        uid=await user(sessions)
        await runner.run(uid,execute=True)
        next_bar(source,date(2026,8,31),165,160)
        result=await runner.run(uid,execute=True)
        assert result['code']=='V2_INPUT_INVALID',result
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id==uid))==0
    asyncio.run(scenario())


def test_cash_change_before_fill_does_not_resize_or_retry(runtime,monkeypatch):
    sessions,source=runtime
    original=auto_trade._execute_virtual_trade
    calls=[]
    async def changed(db,uid,*args,**kwargs):
        calls.append(uid)
        account=await db.scalar(select(QuantVirtualAccount).where(QuantVirtualAccount.user_id==uid))
        account.cash_balance=0
        await db.flush()
        return await original(db,uid,*args,**kwargs)
    monkeypatch.setattr(auto_trade,'_execute_virtual_trade',changed)
    async def scenario():
        uid=await user(sessions)
        await runner.run(uid,execute=True)
        next_bar(source,date(2026,8,30),165,160)
        for _ in range(2):
            result=await runner.run(uid,execute=True)
            assert result['status']=='unknown',result
        assert len(calls)==1
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.user_id==uid))==0
    asyncio.run(scenario())
