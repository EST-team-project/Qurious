"""자동 정기 리밸런싱의 종가 평가와 일봉 시가 예약 정산.

예약은 RebalanceRun.orders/context에 영속화한다. 기존 수동 현재가 주문과 분리한다.
계좌/설정 변경 정책은 #79 논의 중이므로 자동 취소·재계산하지 않고 대기한다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import date, datetime, time

from sqlalchemy import select, func

from app.models import Portfolio, PaperAccount, Order, CashflowEvent, RebalanceRun
from app.models.trading import PORTFOLIO_BOOK_PAPER
from app.services import paper_trading as pt, rebalance_policy as policy, rebalance_prices as prices


async def account_stamp(db, uid):
    """잔액이 원상복구되어도 중간 주문·현금 이벤트가 있으면 변경으로 취급한다."""
    await db.flush()
    account = (await db.execute(select(PaperAccount.cash, PaperAccount.updated_at).where(
        PaperAccount.user_id == uid))).one()
    positions = (await db.execute(select(Portfolio.symbol, Portfolio.quantity, Portfolio.avg_price,
        Portfolio.updated_at).where(Portfolio.user_id == uid, Portfolio.book == PORTFOLIO_BOOK_PAPER)
        .order_by(Portfolio.symbol))).all()
    orders = (await db.execute(select(func.count(Order.id), func.max(Order.created_at)).where(Order.user_id == uid))).one()
    events = (await db.execute(select(func.count(CashflowEvent.id), func.max(CashflowEvent.created_at)).where(
        CashflowEvent.user_id == uid))).one()
    payload = [list(account), [list(p) for p in positions], list(orders), list(events)]
    return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()


async def close_snapshot(db, uid, plan, day):
    from app.services import rebalance as rb
    account = await pt.get_account(db, uid, lock=True)
    holdings = (await db.execute(select(Portfolio).where(
        Portfolio.user_id == uid, Portfolio.book == PORTFOLIO_BOOK_PAPER))).scalars().all()
    symbols = {t['symbol'] for t in plan.targets}
    if not plan.exclude_unplanned:
        symbols.update(p.symbol for p in holdings)
    quotes = await asyncio.to_thread(prices.read_prices, symbols, day)
    positions, excluded = [], []
    for holding in holdings:
        quote = quotes.get(holding.symbol)
        if quote is None:
            excluded.append(holding.symbol)
        positions.append(dict(symbol=holding.symbol, name=holding.name, quantity=holding.quantity,
                              currentPrice=quote['price'] if quote else None,
                              evalAmount=holding.quantity * quote['price'] if quote else 0))
    snap = policy.weights(float(account.cash), positions, plan.targets, plan.drift_threshold_pct,
                          plan.drift_enabled, plan.exclude_unplanned)
    for row in snap['rows']:
        if row['symbol'] in quotes:
            row.update(price=quotes[row['symbol']]['price'], is_etf=quotes[row['symbol']]['is_etf'],
                       market=quotes[row['symbol']]['market'])
    events = await rb.pending_cashflows(db, uid)
    snap.update(policy.cashflow_signal(snap['cash_excess'], sum(e.remaining_budget for e in events),
                                       plan.cashflow_min_amount))
    snap.update(observed_at=rb.datetime.now(rb.KST).isoformat(), price_basis='previous_close',
                valuation_date=day.isoformat(), excluded_prices_unavailable=excluded,
                account_stamp=await account_stamp(db, uid))
    return snap


async def pending(db, uid):
    return (await db.execute(select(RebalanceRun).where(RebalanceRun.user_id == uid,
        RebalanceRun.status == 'scheduled').order_by(RebalanceRun.created_at).with_for_update())).scalars().first()


async def reserve(db, uid, plan, run):
    from app.services import rebalance as rb
    await rb.lock_user(db, uid)
    await pt.get_account(db, uid, lock=True)
    if await pending(db, uid):
        raise rb.RebalanceError('이미 시가 체결을 기다리는 예약이 있습니다.')
    today = rb.datetime.now(rb.KST).date()
    if run.decision_date != today or run.context.get('price_basis') != 'previous_close':
        raise rb.RebalanceError('오늘 생성한 종가 기준 제안만 예약할 수 있습니다.')
    if run.context.get('account_stamp') != await account_stamp(db, uid):
        raise rb.RebalanceError('제안 이후 계좌가 변경되었습니다. 변경 후 예약 정책은 논의 중입니다.')
    day = await asyncio.to_thread(prices.next_trading_day, today)
    run.status = 'scheduled'
    run.orders = [{**o, 'status': 'scheduled'} for o in run.orders]
    run.context = {**run.context, 'scheduled_for': day.isoformat(),
                   'reserved_at': rb.datetime.now(rb.KST).isoformat(), 'execution_basis': 'raw_open'}
    run.note = '다음 거래일 시가 수집 후 모의 체결 확정 · 수량은 예약 시 고정'
    await db.flush()
    return run


async def settle(db, uid, plan, readiness):
    """준비된 일봉까지만 처리. 행 잠금 + 장부/완료 상태를 한 트랜잭션으로 저장한다."""
    from app.services import rebalance as rb
    await rb.lock_user(db, uid)
    run = await pending(db, uid)
    if run is None:
        return None

    def wait(message):
        run.context = {**run.context, 'waiting_reason': message}
        return run

    if not readiness['ready']:
        return wait('데이터 갱신 완료 대기')
    day = date.fromisoformat(run.context['scheduled_for'])
    if day >= rb.datetime.now(rb.KST).date() or day > date.fromisoformat(readiness['data_as_of']):
        return wait('예약 체결일의 시가 수집 대기')
    await pt.get_account(db, uid, lock=True)
    if (run.context.get('review_required') or not plan.is_active or run.context.get('settings_fingerprint') != rb.fingerprint(plan)
            or run.context.get('account_stamp') != await account_stamp(db, uid)):
        run.context = {**run.context, 'review_required': True}
        return wait('계좌 또는 플랜 변경 확인 대기 — 처리 정책은 #79에서 논의 중입니다.')
    try:
        if not prices.schedule.days(day, day)[0]['is_trading_day']:
            return wait('예약일이 휴장일로 변경되어 확인 대기')
        quotes = await asyncio.to_thread(prices.read_prices, [o['symbol'] for o in run.orders], day, 'open')
    except (prices.PriceUnavailable, prices.schedule.market_calendar.CalendarUnavailable, sqlite3.Error) as exc:
        return wait(str(exc))

    # 일봉에는 정확한 개장 시각이 없다. filled_at은 거래일 표시용 KST 자정이며,
    # context에 시각 정밀도가 date임을 명시해 특별 개장일의 09시 체결로 오인하지 않는다.
    filled_at = datetime.combine(day, time.min, rb.KST)
    records = []
    for order in run.orders:
        rec = {**order, 'decision_price': order['price']}
        try:
            async with db.begin_nested():
                result = await pt._fill_stock_order(db, uid, quotes[order['symbol']], order['side'],
                    int(order['quantity']), source=rb.ORDER_SOURCE, filled_at=filled_at)
            rec.update(status='filled', price=result['price'], amount=result['amount'],
                       net_amount=result['net_amount'], cost=result['cost'], fill_date=day.isoformat())
        except pt.PaperTradeError as exc:
            rec.update(status='failed', error=str(exc))
        records.append(rec)
    count = sum(o['status'] == 'filled' for o in records)
    run.status = ('executed' if count == len(records) else 'partial') if count else 'failed'
    run.orders = records
    run.context = {**run.context, 'waiting_reason': None, 'fill_date': day.isoformat() if count else None,
                   'fill_time_precision': 'date', 'after_weights_unavailable': True, 'confirmed_at': rb.datetime.now(rb.KST).isoformat(),
                   'actual_cost': round(sum(o['cost']['total_cost'] for o in records if o['status'] == 'filled'), 2)}
    # The account stamp ensures no intervening external cashflow can be consumed here.
    await rb.consume_budget(db, uid, run, records)
    run.note = '예약 수량을 수집 시가로 정산' if count else '시가 기준 잔고·수량 조건으로 체결 실패'
    if count:
        plan.last_run_at = rb.datetime.now(rb.KST)
    # Do not attach current-quote weights to a historical fill.
    run.after_weights = {}
    await db.flush()
    return run
