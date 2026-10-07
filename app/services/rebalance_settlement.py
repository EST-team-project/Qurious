"""자동 정기 리밸런싱의 종가 평가와 일봉 시가 예약 정산.

예약 목표 비중과 판단 근거를 저장하고, 시가 수집 후 수량을 다시 계산한다.
체결일 당일 이후 계좌 변경과 설정 변경은 미확정 정책이므로 확인 대기를 유지한다.
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


async def price_snapshot(db, uid, plan, day, field="close", *, display=False):
    from app.services import rebalance as rb
    account = await pt.get_account(db, uid, lock=True)
    holdings = (await db.execute(select(Portfolio).where(
        Portfolio.user_id == uid, Portfolio.book == PORTFOLIO_BOOK_PAPER))).scalars().all()
    symbols = {t['symbol'] for t in plan.targets}
    if not plan.exclude_unplanned:
        symbols.update(p.symbol for p in holdings)
    quotes = await asyncio.to_thread(prices.read_prices, symbols, day, field)
    if display:
        # Protected holdings are optional for display, never a fallback valuation.
        for symbol in {p.symbol for p in holdings} - symbols:
            try:
                quotes.update(await asyncio.to_thread(prices.read_prices, [symbol], day, field))
            except prices.PriceUnavailable:
                pass
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
    snap.update(observed_at=rb.datetime.now(rb.KST).isoformat(), price_basis='previous_close' if field == 'close' else 'raw_open',
                valuation_date=day.isoformat(), excluded_prices_unavailable=excluded,
                account_stamp=await account_stamp(db, uid))
    return snap


async def close_snapshot(db, uid, plan, day):
    return await price_snapshot(db, uid, plan, day)


async def changed_on_or_after(db, uid, day):
    """일봉에는 개장 시각이 없으므로 체결일 당일 변경도 자동 재계산하지 않는다."""
    from app.services import rebalance as rb
    cutoff = datetime.combine(day, time.min, rb.KST)
    checks = (
        select(PaperAccount.updated_at).where(PaperAccount.user_id == uid),
        select(func.max(Portfolio.updated_at)).where(Portfolio.user_id == uid, Portfolio.book == PORTFOLIO_BOOK_PAPER),
        select(func.max(Order.created_at)).where(Order.user_id == uid),
        select(func.max(CashflowEvent.created_at)).where(CashflowEvent.user_id == uid),
    )
    for query in checks:
        stamp = await db.scalar(query)
        if stamp is not None and stamp >= cutoff:
            return True
    return False


async def pending(db, uid):
    return (await db.execute(select(RebalanceRun).where(RebalanceRun.user_id == uid,
        RebalanceRun.status == 'scheduled').order_by(RebalanceRun.created_at).with_for_update())).scalars().first()


async def reserve(db, uid, plan, run):
    from app.services import rebalance as rb
    await rb.lock_user(db, uid)
    await pt.get_account(db, uid, lock=True)
    if await pending(db, uid):
        raise rb.RebalanceError('이미 시가 체결을 기다리는 예약이 있습니다.')
    await rb.decision_readiness()
    today = rb.datetime.now(rb.KST).date()
    if run.decision_date != today or run.context.get('price_basis') != 'previous_close':
        raise rb.RebalanceError('오늘 생성한 종가 기준 제안만 예약할 수 있습니다.')
    if run.context.get('account_stamp') != await account_stamp(db, uid):
        raise rb.RebalanceError('제안 이후 계좌가 변경되었습니다. 종가 기준으로 다시 미리보기 하세요.')
    day = await asyncio.to_thread(prices.next_trading_day, today)
    run.status = 'scheduled'
    run.orders = [{**o, 'status': 'scheduled'} for o in run.orders]
    run.context = {**run.context, 'scheduled_for': day.isoformat(),
                   'reserved_at': rb.datetime.now(rb.KST).isoformat(), 'execution_basis': 'raw_open',
                   'reservation_policy': 'target_weights_v1'}
    run.note = '목표 비중 예약 · 시가 수집 후 주문 수량 재계산 및 체결 확정'
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
    target_reservation = run.context.get('reservation_policy') == 'target_weights_v1'
    account_changed = run.context.get('account_stamp') != await account_stamp(db, uid)
    if (run.context.get('review_required') or not plan.is_active
            or run.context.get('settings_fingerprint') != rb.fingerprint(plan)):
        run.context = {**run.context, 'review_required': True}
        return wait('플랜 변경 또는 기존 확인 대기 — 처리 규칙 확정 필요')
    if account_changed and (not target_reservation or await changed_on_or_after(db, uid, day)):
        run.context = {**run.context, 'review_required': True}
        return wait('체결일 당일 이후 계좌 변경 또는 이전 방식 예약 — 과거 잔고 확인 필요')
    try:
        if not prices.schedule.days(day, day)[0]['is_trading_day']:
            return wait('예약일이 휴장일로 변경되어 확인 대기')
        if target_reservation:
            snap = await price_snapshot(db, uid, plan, day, 'open')
            triggers = run.triggers or [run.trigger]
            unconditional = 'MANUAL' in triggers or ('TIME' in triggers and plan.drift_check_mode != 'scheduled')
            drift_due = 'DRIFT' in triggers and snap['drift_exceeded']
            cashflow_due = ('CASHFLOW' in triggers and snap['cashflow_due']
                            and (run.plan_kind == 'full' or run.plan_kind == snap['plan_kind']))
            run.context = {**run.context, 'recalculated_at': rb.datetime.now(rb.KST).isoformat(),
                           'indicative_orders': run.orders, 'execution_max_drift_pct': snap['max_drift_pct']}
            if not (unconditional or drift_due or cashflow_due):
                run.status, run.note = 'cancelled', '취소 — 시가 재계산 결과 조건 해소'
                run.orders = []
                run.context = {**run.context, 'waiting_reason': None, 'cancel_reason': 'condition_resolved'}
                await db.flush()
                return run
            recalculated = policy.orders(snap, {r['symbol']: r['price'] for r in snap['rows'] if r['price']},
                plan.min_order_amount, run.plan_kind,
                snap['cashflow_available'] if run.plan_kind != 'full' else None, when=day)
            run.orders = recalculated['orders']
            run.context = {**run.context, 'execution_estimated_cost': recalculated['estimated_cost']}
            if not run.orders:
                run.status, run.note = 'skipped', '시가 재계산 결과 최소 주문금액·정수 수량 조건으로 주문 없음'
                run.context = {**run.context, 'waiting_reason': None}
                await db.flush()
                return run
            # Size and fill from the same SQLite snapshot, even if collection is corrected concurrently.
            quotes = {r['symbol']: r for r in snap['rows'] if r['price']}
        else:
            quotes = await asyncio.to_thread(prices.read_prices, [o['symbol'] for o in run.orders], day, 'open')
    except (prices.PriceUnavailable, prices.schedule.market_calendar.CalendarUnavailable, sqlite3.Error) as exc:
        return wait(str(exc))

    # 일봉에는 정확한 개장 시각이 없다. filled_at은 거래일 표시용 KST 자정이며,
    # context에 시각 정밀도가 date임을 명시해 특별 개장일의 09시 체결로 오인하지 않는다.
    filled_at = datetime.combine(day, time.min, rb.KST)
    records = []
    for order in run.orders:
        rec = dict(order)
        indicative = run.context.get('indicative_orders', run.orders)
        rec['decision_price'] = next((o['price'] for o in indicative if o['symbol'] == order['symbol']), None)
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
    # Changed accounts are allowed only before the execution date; later budgets remain untouched.
    await rb.consume_budget(db, uid, run, records)
    run.note = ('목표 비중으로 수량을 재계산해 시가 정산' if target_reservation else '이전 예약 수량으로 시가 정산') if count else '시가 기준 잔고·수량 조건으로 체결 실패'
    if count:
        plan.last_run_at = rb.datetime.now(rb.KST)
    # Do not attach current-quote weights to a historical fill.
    run.after_weights = {}
    await db.flush()
    return run
