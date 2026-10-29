"""실제 PG에서 판 2의 동시 판단·중복·재시작·계좌/장부 분리를 검증한다."""
import asyncio
from copy import deepcopy
from datetime import date, timedelta
import os
import uuid

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.models import User, StrategyRuntime, StrategyRuntimeEvent
from app.services import strategy_v2 as v2
from tests.test_strategy_v2 import bars, SPEC

pytestmark = [pytest.mark.skipif(not os.getenv('QURIOUS_TEST_DATABASE_URL'),reason='일회용 PostgreSQL 필요'),
              pytest.mark.usefixtures('rebalance_db_schema')]


@pytest.fixture
def runtime(monkeypatch):
    engine=create_async_engine(os.environ['QURIOUS_TEST_DATABASE_URL'],poolclass=NullPool)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(v2.market_calendar,'trading_days',lambda start,end:{'partial':False,'days':[
        {'date':str(start+timedelta(days=i)),'is_trading_day':True} for i in range((end-start).days+1)]})
    yield sessions
    asyncio.run(engine.dispose())


async def identity(sessions):
    uid=uuid.uuid4()
    async with sessions() as db:
        db.add(User(id=uid,name='v2-test',email=f'{uid}@example.test',password_hash='test',client_id=uid.hex))
        await db.commit()
    return dict(user_id=uid,account_ref=v2.digest([str(uid),'paper']),book='V2_VIRTUAL',symbol='005930.KS',spec=SPEC)


async def apply(sessions, who, key, event):
    async with sessions() as db:
        result=await v2.apply_event(db,**who,event_key=key,event=event)
        await db.commit()
        return result


def test_concurrent_same_bar_has_one_event_and_one_pending_entry(runtime):
    async def scenario():
        who=await identity(runtime);event={'kind':'bar','bars':bars()}
        results=await asyncio.gather(*(apply(runtime,who,'bar:2026-08-29',event) for _ in range(5)))
        assert sum(not r['duplicate'] for r in results)==1
        async with runtime() as db:
            count=await db.scalar(select(func.count()).select_from(StrategyRuntimeEvent).where(StrategyRuntimeEvent.runtime_id==results[0]['runtime_id']))
            assert count==1
        changed=deepcopy(event);changed['bars'][-1]['close']=158
        with pytest.raises(ValueError,match='입력'):await apply(runtime,who,'bar:2026-08-29',changed)
    asyncio.run(scenario())


def test_restart_unknown_blocks_reservation_and_duplicate_does_not_rewind(runtime):
    async def scenario():
        who=await identity(runtime)
        first=await apply(runtime,who,'bar:2026-08-29',{'kind':'bar','bars':bars()})
        reserve={'kind':'reserve','order_key':'order-1','quantity':10,'mode':'virtual_next_open','target_date':'2026-08-30'}
        await apply(runtime,who,'reserve:order-1',reserve)
        await apply(runtime,who,'unknown:order-1',{'kind':'fill','order_key':'order-1','cumulative_quantity':0,'average_price':None,'status':'UNKNOWN'})
        # 새로운 세션 = 저장 상태만 읽는다. 이전 bar의 중복 결과가 DB를 덮지 않는다.
        assert (await apply(runtime,who,'bar:2026-08-29',{'kind':'bar','bars':bars()}))['duplicate']
        with pytest.raises(ValueError):await apply(runtime,who,'reserve:order-2',{**reserve,'order_key':'order-2'})
        async with runtime() as db:
            row=await db.get(StrategyRuntime,first['runtime_id'])
            assert row.state['pending']['phase']=='UNKNOWN' and row.state['quantity']==0
        done=await apply(runtime,who,'fill:order-1',{'kind':'fill','order_key':'order-1','cumulative_quantity':10,'average_price':160,'status':'FILLED','filled_at':'2026-08-30T09:00:00+09:00'})
        assert done['state']['stop_price']==152
    asyncio.run(scenario())


def test_account_and_book_states_are_separate(runtime):
    async def scenario():
        who=await identity(runtime);event={'kind':'bar','bars':bars()}
        a=await apply(runtime,who,'bar',event)
        b=await apply(runtime,{**who,'book':'V2_KIS_PROBE'},'bar',event)
        c=await apply(runtime,{**who,'account_ref':v2.digest('different account')},'bar',event)
        assert len({r['runtime_id'] for r in (a,b,c)})==3
        with pytest.raises(ValueError,match='경로'):
            await apply(runtime,who,'reserve',{'kind':'reserve','order_key':'x','quantity':10,'mode':'kis_intraday_probe','target_date':'2026-08-30'})
    asyncio.run(scenario())


def test_transaction_rollback_removes_state_and_event_together(runtime):
    async def scenario():
        who=await identity(runtime)
        async with runtime() as db:
            result=await v2.apply_event(db,**who,event_key='bar',event={'kind':'bar','bars':bars()})
            await db.rollback()
        async with runtime() as db:
            assert await db.get(StrategyRuntime,result['runtime_id']) is None
            assert await db.get(StrategyRuntimeEvent,(result['runtime_id'],'bar')) is None
    asyncio.run(scenario())


def test_exit_latch_survives_a_fresh_python_process(runtime):
    import subprocess
    import sys
    from tests.test_strategy_v2 import bar
    async def scenario():
        who=await identity(runtime)
        first=await apply(runtime,who,'bar:2026-08-29',{'kind':'bar','bars':bars()})
        await apply(runtime,who,'reserve:buy',{'kind':'reserve','order_key':'buy','quantity':10,'mode':'virtual_next_open','target_date':'2026-08-30'})
        await apply(runtime,who,'fill:buy',{'kind':'fill','order_key':'buy','cumulative_quantity':10,'average_price':160,'status':'FILLED','filled_at':'2026-08-30T09:00:00+09:00'})
        rows=bars()+[bar(date(2026,8,30),180)]
        await apply(runtime,who,'bar:2026-08-30',{'kind':'bar','bars':rows})
        await apply(runtime,who,'reserve:sell',{'kind':'reserve','order_key':'sell','quantity':10,'mode':'virtual_next_open','target_date':'2026-08-31'})
        await apply(runtime,who,'fill:sell',{'kind':'fill','order_key':'sell','cumulative_quantity':10,'average_price':181,'status':'FILLED','filled_at':'2026-08-31T09:00:00+09:00'})
        code='''import asyncio,os,sys
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from app.models import StrategyRuntime
async def main():
 e=create_async_engine(os.environ['QURIOUS_TEST_DATABASE_URL'])
 async with async_sessionmaker(e)() as db:
  r=await db.get(StrategyRuntime,sys.argv[1])
  assert r.state['quantity']==0 and r.state['reentry_armed'] is False
 await e.dispose()
asyncio.run(main())
'''
        subprocess.run([sys.executable,'-c',code,first['runtime_id']],check=True,timeout=20)
        rows+=[bar(date(2026,8,31),182)]
        again=await apply(runtime,who,'bar:2026-08-31',{'kind':'bar','bars':rows})
        assert again['outcome']['action']=='HOLD' and not again['state']['reentry_armed']
    asyncio.run(scenario())


def test_deferred_bar_is_not_deduplicated_before_fill_confirmation(runtime):
    from tests.test_strategy_v2 import bar
    async def scenario():
        who=await identity(runtime)
        await apply(runtime,who,'bar:2026-08-29',{'kind':'bar','bars':bars()})
        await apply(runtime,who,'reserve:buy',{'kind':'reserve','order_key':'buy','quantity':10,'mode':'virtual_next_open','target_date':'2026-08-30'})
        event={'kind':'bar','bars':bars()+[bar(date(2026,8,30),140)]}
        deferred=await apply(runtime,who,'bar:2026-08-30',event)
        assert deferred['deferred']
        async with runtime() as db:
            assert await db.get(StrategyRuntimeEvent,(deferred['runtime_id'],'bar:2026-08-30')) is None
        await apply(runtime,who,'fill:buy',{'kind':'fill','order_key':'buy','cumulative_quantity':10,'average_price':160,'status':'FILLED','filled_at':'2026-08-30T09:00:00+09:00'})
        result=await apply(runtime,who,'bar:2026-08-30',event)
        assert result['outcome']['action']=='SELL' and not result['duplicate']
    asyncio.run(scenario())
