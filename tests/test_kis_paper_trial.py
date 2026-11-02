"""실제 공통 주문 관문·전략 소유권으로 한 번의 모의 시험을 제한한다. 증권사는 합성이다."""
import asyncio
from datetime import datetime as RealDatetime, timedelta
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func

from test_kis_connection_probe import runtime, user  # noqa: F401 -- shared isolated PG fixture
from app.models import BrokerSettings, BrokerPositionBaseline, LiveOrder, OrderIntent
from app.services import kis_paper_trial as trial

pytestmark = [pytest.mark.skipif(not os.getenv('QURIOUS_TEST_DATABASE_URL'), reason='격리 PostgreSQL 필요'),
              pytest.mark.usefixtures('rebalance_db_schema')]


@pytest.fixture
def env(request, monkeypatch):
    sessions, client = request.getfixturevalue('runtime')
    monkeypatch.setattr(trial, 'get_session_factory', lambda: sessions)
    monkeypatch.setattr(trial, 'datetime', trial.kis_connection_probe.datetime)
    monkeypatch.setattr(trial, 'pause', AsyncMock())
    monkeypatch.setattr(trial, 'decision_for', AsyncMock(return_value={
        'action':'SELL','input_hash':'actual-test-input','source':'kis_adjusted_daily'}))
    expires = (trial.datetime.now(trial.control.KST)+timedelta(minutes=30)).isoformat()
    return sessions, client, expires


async def existing_holding(sessions, uid):
    ref = trial.kis_execution.account_key('synthetic-'+uid.hex,'1234567801','paper')
    async with sessions() as db:
        db.add(BrokerPositionBaseline(account_ref=ref,symbol=trial.SYMBOL,quantity=0))
        order = LiveOrder(user_id=uid,account_ref=ref,client_order_id='existing-'+uid.hex,
            strategy_id='kis_connection_check',strategy_version=1,symbol=trial.SYMBOL,
            side='BUY',quantity=1,price=70000,status='FILLED',filled_quantity=1,avg_filled_price=70000,
            environment='paper',created_at=RealDatetime.now(trial.control.KST)-timedelta(days=1))
        db.add(order)
        await db.commit()
        return ref, order.id


def snapshot(qty):
    return {'cash':1000000,'equity':1000000+qty*70000,
        'holdings':{trial.SYMBOL:{'quantity':qty,'value':qty*70000,'name':'삼성전자'}}}


def test_setup_then_strategy_sell_preserves_existing_share_and_never_resends(env):
    sessions, client, expires = env
    async def scenario():
        uid = await user(sessions)
        ref, old_id = await existing_holding(sessions,uid)
        trial.kis_execution.account_snapshot.return_value=snapshot(1)
        dry = await trial.prepare_trial(uid,max_price=70000,expires_at=expires)
        assert dry['status']=='DRY_RUN' and dry['decision']['action']=='SELL'
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(OrderIntent))==0
        first = await trial.prepare_trial(uid,max_price=70000,expires_at=expires,execute=True)
        assert first['status']=='submitted',first
        assert first['price_basis']['strategy_signal'] is False
        duplicate = await trial.prepare_trial(uid,max_price=70000,expires_at=expires,execute=True)
        assert duplicate['duplicate'] and client.place_order.await_count==1
        pending = await trial.run_signal(first['intent_id'])
        assert pending['code']=='OPEN_ORDER'
        async with sessions() as db:
            seeded=await db.scalar(select(LiveOrder).where(LiveOrder.strategy_id==trial.STRATEGY))
            seeded.status='FILLED';seeded.filled_quantity=1;seeded.avg_filled_price=70000
            await db.commit()
        trial.kis_execution.account_snapshot.return_value=snapshot(2)
        sold = await trial.run_signal(first['intent_id'])
        assert sold['status']=='submitted',sold
        assert sold['price_basis']['strategy_signal'] is True
        assert client.place_order.call_args.args[2:]==('sell',1,70000)
        repeated = await trial.run_signal(first['intent_id'])
        assert repeated['duplicate'] and client.place_order.await_count==2
        async with sessions() as db:
            sell = await db.scalar(select(LiveOrder).where(LiveOrder.strategy_id==trial.STRATEGY,LiveOrder.side=='SELL'))
            sell.status='FILLED';sell.filled_quantity=1;sell.avg_filled_price=70000
            await db.commit()
            owned,blocked=await trial.live_ownership.reconcile(db,ref,snapshot(1),uid,trial.STRATEGY,1)
            old=await db.get(LiveOrder,old_id)
            assert owned==[] and not blocked and old.filled_quantity==1 and old.status=='FILLED'
            settings=await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id==uid))
            assert not settings.quant_auto_enabled and settings.quant_mode=='paper' and settings.quant_strategy_id==''
    asyncio.run(scenario())


@pytest.mark.parametrize('case,code', [('auto','PROBE_DISABLED'),('kill','PROBE_DISABLED'),
    ('real','PAPER_ONLY'),('gateway','PAPER_ONLY'),('budget','ZERO_QUANTITY'),('cap','PRICE_CAP'),
    ('cash','ZERO_QUANTITY'),('buy_signal','WAIT_SELL_SIGNAL'),('ownership','OWNERSHIP_UNCONFIRMED')])
def test_invalid_trial_never_sends(env,monkeypatch,case,code):
    sessions,client,expires=env
    async def scenario():
        overrides={'quant_auto_enabled':True} if case=='auto' else {'risk_kill_switch':True} if case=='kill' else {}
        if case=='budget': overrides['quant_per_trade_budget']=60000
        uid=await user(sessions,**overrides)
        if case=='real': client.paper=False
        if case=='gateway': monkeypatch.setattr(trial.gateway,'is_configured',lambda:True)
        if case=='cash': client.get_buying_power.return_value={'amount':60000,'quantity':0}
        if case=='ownership': trial.kis_execution.account_snapshot.return_value=snapshot(1)
        if case=='buy_signal': trial.decision_for.return_value['action']='BUY'
        try:
            result=await trial.prepare_trial(uid,max_price=60000 if case=='cap' else 70000,expires_at=expires,execute=True)
            assert result['code']==code,result
        except trial.control.Rejected as exc:
            assert exc.code==code
        client.place_order.assert_not_awaited()
    asyncio.run(scenario())


def test_expired_worker_never_sends(env,monkeypatch):
    sessions,client,expires=env
    async def scenario():
        uid=await user(sessions)
        seed=await trial.prepare_trial(uid,max_price=70000,expires_at=expires,execute=True)
        async with sessions() as db:
            intent=await db.get(OrderIntent,seed['intent_id'])
            result=dict(intent.result);basis=dict(result['price_basis'])
            basis['expires_at']=(trial.datetime.now(trial.control.KST)-timedelta(minutes=1)).isoformat()
            result['price_basis']=basis;intent.result=result;await db.commit()
        response=await trial.run_signal(seed['intent_id'])
        assert response['code']=='TRIAL_EXPIRED' and client.place_order.await_count==1
    asyncio.run(scenario())


def test_closed_kis_bars_drive_real_rule_and_ignore_current_bar(monkeypatch):
    class Clock(RealDatetime):
        @classmethod
        def now(cls,tz=None):
            return cls(2026,11,2,10,tzinfo=trial.control.KST).astimezone(tz or trial.control.KST)
    monkeypatch.setattr(trial,'datetime',Clock)
    monkeypatch.setattr(trial,'pause',AsyncMock())
    monkeypatch.setattr(trial.market_calendar,'trading_days',lambda *a:{'days':[
        {'date':'2026-10-30','is_trading_day':True},{'date':'2026-11-02','is_trading_day':True}]})
    end=RealDatetime(2026,10,30)
    bars=[{'date':(end-timedelta(days=79-i)).strftime('%Y%m%d'),'close':1000-i*5} for i in range(80)]
    bars.append({'date':'20261102','close':10000000})
    client=SimpleNamespace(get_daily_ohlcv=AsyncMock(return_value=bars))
    result=asyncio.run(trial.decision_for(client))
    assert result['action']=='SELL' and result['bar_end_at'].startswith('2026-10-30')
    client.get_daily_ohlcv.return_value=bars[:-2]
    with pytest.raises(ValueError,match='직전 거래일'):
        asyncio.run(trial.decision_for(client))
