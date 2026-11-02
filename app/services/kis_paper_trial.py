"""한 번의 KIS 모의 통합 시험: 준비 매수 1주 → 실제 MA20/60 매도 판단.

준비 매수는 전략 신호가 아니다. 기존 보유를 편입하지 않고 시험 소유권만 판다.
자동매매 설정을 켜지 않으며 만료된 시험·실전·다른 카드·미확인 주문은 거절한다.
"""
import asyncio
from datetime import datetime, time, timedelta, timezone
import math
from types import SimpleNamespace
import uuid

from sqlalchemy import func, select

from app.database.postgres import get_session_factory
from app.models import BrokerSettings, LiveOrder, OrderIntent, RiskDay, LIVE_ORDER_OPEN_STATUSES
from app.services import (auto_trade, execution_control as control, kis_connection_probe,
    kis_execution, kis_strategy_probe, live_ownership, market_calendar, order_preflight,
    strategy_loader, trading_cost)
from app.services.brokers import stock_coin_trade_gateway as gateway

SYMBOL = '005930.KS'
STRATEGY = 'kis_ma20_60_trial'
VERSION = 1


async def pause():
    await asyncio.sleep(1.1)


def eligible(row, day, expires):
    now = datetime.now(control.KST)
    if expires.tzinfo is None or now >= expires or expires.astimezone(control.KST).date() != day:
        raise control.Rejected('TRIAL_EXPIRED', '모의 시험 허용 시간이 끝났습니다.')
    return kis_connection_probe.eligible(row, day)


async def decision_for(client):
    now = datetime.now(control.KST)
    await pause()
    bars = await client.get_daily_ohlcv(SYMBOL, (now.date()-timedelta(days=180)).strftime('%Y%m%d'), now.strftime('%Y%m%d'))
    indicators = {'closes':[b['close'] for b in bars],
        'times':[datetime.strptime(b['date'],'%Y%m%d').replace(tzinfo=timezone.utc).timestamp() for b in bars]}
    spec = strategy_loader._fixed_card()
    if spec is None:
        raise control.Rejected('CARD_UNAVAILABLE', '고정 시험 카드 내용을 확인하지 못했습니다.')
    result = kis_strategy_probe.prepare(spec, indicators, now,
        market_calendar.trading_days(now.date()-timedelta(days=14),now.date()))
    return {**result, 'source':'kis_adjusted_daily', 'test_only':True}


async def execute_phase(uid, *, setup, day, expires, max_price, seed_id=None, execute=False):
    if (isinstance(max_price,bool) or not isinstance(max_price,(int,float))
            or not math.isfinite(max_price) or max_price <= 0):
        raise ValueError('모의 시험 지정가 상한이 필요합니다.')
    async with get_session_factory()() as db:
        row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id==uid))
        client, ref, _ = eligible(row, day, expires)
        decision = await decision_for(client)
    if decision['action'] != 'SELL':
        return control.blocked('WAIT_SELL_SIGNAL', '현재 실제 청산 신호가 없어 준비 매수/시험 매도를 하지 않습니다.')
    side = 'BUY' if setup else 'SELL'
    intent = control.Intent(uid,ref,'KIS',STRATEGY,VERSION,SYMBOL,side,
        day.isoformat()+(':setup' if setup else ':signal'),
        'kis_trial_setup' if setup else 'kis_trial_signal',
        control.digest([decision['input_hash'],max_price,expires.isoformat(),seed_id]))

    async def prepare(db):
        row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id==uid))
        client, current_ref, creds = eligible(row,day,expires)
        if current_ref != ref:
            raise control.Rejected('SETTINGS_CHANGED','시험 계좌가 변경됐습니다.')
        signature = control.settings_signature(row)
        opened = await db.scalar(select(LiveOrder.id).where(
            (LiveOrder.account_ref==ref) | LiveOrder.raw.contains(ref),
            LiveOrder.status.in_((*LIVE_ORDER_OPEN_STATUSES,'LOST'))).limit(1))
        if opened:
            raise control.Rejected('OPEN_ORDER','계좌의 미확정 주문을 먼저 확인해야 합니다.')
        used = await db.scalar(select(func.count()).select_from(LiveOrder).where(
            (LiveOrder.account_ref == ref) | LiveOrder.raw.contains(ref),
            LiveOrder.created_at >= datetime.combine(day, time.min, control.KST)))
        if used >= 3:
            raise control.Rejected('PROBE_DAILY_LIMIT', '계좌의 하루 경로 점검 상한 3건에 도달했습니다.')
        if not setup:
            seed = await db.get(OrderIntent,seed_id)
            seeded = await db.scalar(select(LiveOrder).where(LiveOrder.client_order_id=='intent:'+seed_id[:57]))
            if (not seed or seed.user_id!=uid or seed.account_ref!=ref or seed.strategy_id!=STRATEGY
                    or seed.source!='kis_trial_setup' or not seeded or seeded.status!='FILLED'
                    or seed.strategy_version!=VERSION or seed.side!='BUY' or seed.symbol!=SYMBOL
                    or seeded.user_id!=uid or seeded.account_ref!=ref or seeded.strategy_id!=STRATEGY
                    or seeded.strategy_version!=VERSION or seeded.side!='BUY' or seeded.symbol!=SYMBOL
                    or seeded.quantity!=1 or seeded.filled_quantity!=1 or seeded.environment!='paper'):
                raise control.Rejected('SETUP_UNCONFIRMED','이 시험의 준비 매수 1주 체결이 확인되지 않았습니다.')
        await pause()
        snapshot = await kis_execution.account_snapshot(row,gateway,{SYMBOL:{'symbol':SYMBOL}})
        owned, blocked = await live_ownership.reconcile(db,ref,snapshot,uid,STRATEGY,VERSION)
        if SYMBOL in blocked:
            raise control.Rejected('OWNERSHIP_UNCONFIRMED',blocked[SYMBOL])
        held = next((p.quantity for p in owned if p.symbol==SYMBOL),0)
        if (setup and held) or (not setup and held!=1):
            raise control.Rejected('TRIAL_POSITION','준비 전 0주/청산 전 1주인 시험 소유권이 필요합니다.')
        await pause()
        quote = await order_preflight.current_quote(db,uid,row,'live',SYMBOL)
        price = quote['price']
        if not float(price).is_integer() or (setup and price>max_price):
            raise control.Rejected('PRICE_CAP','시험의 지정가 상한 또는 원 단위 가격을 확인하세요.')
        holding = snapshot['holdings'].get(SYMBOL,{})
        value = holding.get('quantity',0)*price
        equity = snapshot['equity']+value-holding.get('value',0)
        cash = snapshot['cash']
        if setup:
            await pause()
            power = await client.get_buying_power(creds.account_no,SYMBOL,price)
            cash = min(cash,power['amount'])
            cost = price*(1+trading_cost.cost_rate('buy',day,slippage_bps=0,market='KOSPI'))
            budget = row.quant_per_trade_budget*row.quant_buy_ratio
            if not math.isfinite(budget) or power['quantity']<1 or cash<cost or budget<cost:
                raise control.Rejected('ZERO_QUANTITY','기존 예산·현금·매수 가능 수량으로 1주를 살 수 없습니다.')
            await live_ownership.ensure_baseline(db,ref,SYMBOL,snapshot)
        baseline = await db.get(RiskDay, (ref,day))
        control.check_limits(row=row,quantity=1,price=price,cash=cash,equity=equity,
            start_equity=baseline.equity if baseline else equity,orders_today=used,
            position_value=value,owned_quantity=held,side=side)
        return {'db':db,'broker':row,'settings':signature,'quantity':1,'cash':cash,'equity':equity,
            'price':price,'position_value':value,'owned_quantity':held,'checked_at':datetime.now(control.KST),
            'price_basis':{'purpose':'prepare_position' if setup else 'strategy_signal',
                'strategy_signal':not setup,'decision':decision,'expires_at':expires.isoformat(),
                'day':day.isoformat(),'max_price':max_price,'seed_intent_id':seed_id,'quote':quote}}

    async def send(order_id,qty,basis):
        await pause()
        _, current_ref, _ = eligible(basis['broker'],day,expires)
        if current_ref!=ref or qty!=1:
            raise control.Rejected('TRIAL_CHANGED','전송 직전 시험 계좌/수량이 달라졌습니다.')
        row = SimpleNamespace(**{c.name:getattr(basis['broker'],c.name) for c in BrokerSettings.__table__.columns})
        row.quant_mode='live'
        return await auto_trade._place_live_order(row,SYMBOL,'삼성전자',side.lower(),1,basis['price'],str(uid),
            db=basis['db'],client_order_id=order_id)

    if not execute:
        async with get_session_factory()() as db:
            try:
                basis = await prepare(db)
                return {'status':'DRY_RUN','quantity':1,'side':side,'price':basis['price'],
                        'decision':decision,'intent_id':intent.key,'expires_at':expires.isoformat()}
            finally:
                await db.rollback()
    outcome = await control.execute(intent,1,prepare,send)
    return {k:v for k,v in outcome.items() if k in ('status','code','reason','intent_id','duplicate',
        'client_order_id','order_no','environment','price_basis')}


async def prepare_trial(uid, *, max_price, expires_at, execute=False):
    expires = datetime.fromisoformat(expires_at)
    now = datetime.now(control.KST)
    if expires.tzinfo is None or not 0<(expires-now).total_seconds()<=7200:
        raise ValueError('시험 만료는 현재부터 2시간 안의 시간대 있는 시각이어야 합니다.')
    return await execute_phase(uuid.UUID(str(uid)),setup=True,day=now.date(),expires=expires,
        max_price=max_price,execute=execute)


async def run_signal(seed_id):
    async with get_session_factory()() as db:
        seed = await db.get(OrderIntent,seed_id)
        if not seed or seed.source!='kis_trial_setup' or seed.strategy_id!=STRATEGY or seed.book!='KIS':
            return control.blocked('NO_TRIAL','기록된 준비 매수 시험이 없습니다.')
        basis = seed.result.get('price_basis') or {}
        uid=seed.user_id
    try:
        return await execute_phase(uid,setup=False,day=datetime.fromisoformat(basis['day']).date(),
            expires=datetime.fromisoformat(basis['expires_at']),max_price=basis['max_price'],
            seed_id=seed_id,execute=True)
    except control.Rejected as exc:
        return control.blocked(exc.code,str(exc))
    except (ValueError,KeyError) as exc:
        return control.blocked('TRIAL_INVALID',str(exc))
