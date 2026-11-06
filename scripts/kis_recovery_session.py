"""승인된 KIS 모의 잔량 1주의 당일 1회 시험. 매수·위험 한도 완화·반복 시험은 하지 않는다."""
import argparse
import asyncio
from datetime import date, datetime, time, timedelta
import json
import logging
from pathlib import Path
import sys
import uuid

import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.database import postgres as pg
from app.lib.redis_cache import connect_redis, close_redis
from app.models import BrokerSettings, LiveOrder, LIVE_ORDER_OPEN_STATUSES
from app.services import kis_order_recovery as recovery, manual_broker_order as manual
from app.services.execution_policy import policy_for, within_retry_price_limit
from scripts import kis_recovery_trial as trial

SYMBOL = '005930.KS'
PROTECTED = 'kis_connection_check'


def now():
    return datetime.now(recovery.control.KST)


def signature(row):
    limits = recovery.control.risk_guard.RiskLimits.from_row(row)
    return recovery.control.digest([recovery.control.settings_signature(row), vars(limits), row.risk_kill_switch])


async def read(call, *args, **kwargs):
    """일시적인 GET 실패만 짧게 재조회한다. 주문·취소 POST는 재전송하지 않는다."""
    for attempt in range(3):
        try:
            return await call(*args, **kwargs)
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if (exc.request.method != 'GET' or attempt == 2
                    or isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code != 429 and exc.response.status_code < 500):
                raise
            await asyncio.sleep(2 * (attempt + 1))


async def account(uid, config=None, trial_quantity=1):
    async with pg.get_session_factory()() as db:
        row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
        client, credentials, ref = recovery.context(row)
        policy = policy_for(row)
        if (row.quant_auto_enabled or row.risk_kill_switch or policy.retry_enabled
                or row.risk_cooldown_min != 30 or policy.retry_window_min != 15
                or policy.retry_max_attempts != 1 or policy.retry_price_deviation_pct != 1):
            raise ValueError('시험 승인 시 위험 설정과 다릅니다.')
        fingerprint = signature(row)
        if config and (config['account_ref'] != ref or config['settings_hash'] != fingerprint):
            raise ValueError('예약 후 계좌 또는 설정이 바뀌었습니다.')
        await recovery.pause()
        snapshot = await read(recovery.kis_execution.account_snapshot, row, recovery.gateway, {SYMBOL: {}})
        counts = {}
        for strategy in (PROTECTED, manual.STRATEGY):
            owned, blocked = await recovery.live_ownership.reconcile(db, ref, snapshot, uid, strategy, 1)
            if blocked:
                raise ValueError('전략별 보유를 확인하지 못했습니다.')
            counts[strategy] = sum(p.quantity for p in owned if p.symbol == SYMBOL)
        if counts != {PROTECTED: 1, manual.STRATEGY: trial_quantity} or snapshot['holdings'].get(SYMBOL, {}).get('quantity', 0) != 1 + trial_quantity:
            raise ValueError('기존 전략 1주와 시험 전략 잔량이 예상과 다릅니다.')
        opened = await db.scalar(select(LiveOrder.id).where(LiveOrder.account_ref == ref,
            LiveOrder.status.in_((*LIVE_ORDER_OPEN_STATUSES, 'LOST'))).limit(1))
        if opened:
            raise ValueError('미확인 또는 열린 주문이 있습니다.')
        await recovery.pause()
        day = now().strftime('%Y%m%d')
        fills = await read(client.get_daily_fills, credentials.account_no, day, day)
        if any(not recovery.kis_execution._is_closed(fill) for fill in fills):
            raise ValueError('증권사에 미체결 또는 미확인 주문이 있습니다.')
        return {'account_ref': ref, 'settings_hash': fingerprint, 'protected_quantity': 1,
                'trial_quantity': trial_quantity}


async def quote(uid, config):
    async with pg.get_session_factory()() as db:
        row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
        _, _, ref = recovery.context(row)
        if ref != config['account_ref'] or signature(row) != config['settings_hash']:
            raise ValueError('예약 후 계좌 또는 설정이 바뀌었습니다.')
        await recovery.pause()
        result = await read(recovery.order_preflight.current_quote, db, uid, row, 'live', SYMBOL)
        return result['price']


async def orders(uid, request_id):
    key = manual.request_key(uid, request_id)
    async with pg.get_session_factory()() as db:
        parent = await db.scalar(select(LiveOrder).where(LiveOrder.user_id == uid,
            LiveOrder.client_order_id == 'intent:' + key[:57]))
        child = await db.scalar(select(LiveOrder).where(LiveOrder.retry_of == parent.id)) if parent else None
        return parent, child


async def refresh(uid, order_id):
    async with pg.get_session_factory()() as db:
        order = await recovery.parent_for(db, uid, order_id)
        row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
        recovery.verify_account(order, row)
        await recovery.pause()
        latest = await read(recovery.kis_execution.direct_status, order, row)
        was_filled = order.status == 'FILLED'
        recovery.apply_status(order, latest)
        await db.commit()
        if order.status == 'FILLED' and not was_filled:
            await recovery.auto_trade.notification.notify_order_filled(symbol=order.symbol,
                side=order.side.lower(), quantity=order.filled_quantity, price=order.avg_filled_price,
                environment='paper', user_id=str(uid), order_ref=order.client_order_id)
        return {'id': str(order.id), 'status': order.status, 'filled': order.filled_quantity,
                'created_at': order.created_at.isoformat(), 'price': order.price, 'order_no': order.order_no,
                'cancelled': latest.get('cancelled'), 'remaining': latest.get('remainingQuantity'),
                'cancelled_quantity': latest.get('cancelledQuantity')}


async def confirmed(uid, order_id, expected, deadline):
    while now() < deadline:
        result = await refresh(uid, order_id)
        if result['status'] == 'FILLED' or result['status'] == expected:
            return result
        await asyncio.sleep(5)
    raise TimeoutError('증권사 확정 상태 조회 기한을 넘었습니다.')


async def cleanup(uid, request_id):
    results = []
    parent, child = await orders(uid, request_id)
    for order in (parent, child):
        if order is None:
            continue
        try:
            current = await refresh(uid, order.id)
            if current['status'] not in ('FILLED', 'CANCELLED'):
                await recovery.cancel(uid, order.id)
                current = await confirmed(uid, order.id, 'CANCELLED', now() + timedelta(seconds=45))
            results.append(current)
        except Exception as exc:
            results.append({'id': str(order.id), 'status': 'needs_review', 'error_type': type(exc).__name__})
    return results


def start_window(config, *, start_now=False):
    day = date.fromisoformat(config['day'])
    current = now()
    if start_now:
        # 예약의 지연 실행과 달리 사용자가 명시적으로 시작하는 당일 1회 시험이다.
        # 장 마감 전 정리 시간을 확보하고, 같은 날짜의 요청 키·저널을 그대로 쓴다.
        deadline = current + timedelta(minutes=50)
        if (current.date() != day or current.time() < time(9)
                or deadline > datetime.combine(day, time(15, 20), recovery.control.KST)):
            raise ValueError('수동 시험은 지정된 거래일 09:00~14:30에만 시작합니다.')
        recovery.check_window(day)
        return deadline
    start = datetime.combine(day, time(9, 10), recovery.control.KST)
    if not start <= current < start + timedelta(minutes=2):
        raise ValueError('지정된 날짜 09:10~09:12에만 새 시험을 시작합니다.')
    recovery.check_window(day)
    return datetime.combine(day, time(10), recovery.control.KST)


async def run(config, directory, *, start_now=False, additional_attempt=False):
    uid = uuid.UUID(config['user_id'])
    directory = Path(directory)
    base = directory / f"session-{uid}-{config['day']}.json"
    suffix = ':additional' if additional_attempt else ''
    request_id = uuid.uuid5(uuid.NAMESPACE_URL, f"qurious:c5-session:{uid}:{config['day']}{suffix}")
    path = base.with_stem(base.stem + '-additional') if additional_attempt else base
    with trial.locked(base):
        if path.exists():
            return {'status': 'already_started', 'previous': json.loads(path.read_text())['status']}
        if additional_attempt:
            if not start_now or not base.exists() or json.loads(base.read_text())['status'] != 'parent_filled_without_retry':
                raise ValueError('첫 시험이 선체결로 끝난 뒤 사용자가 승인한 수동 추가 시험 1회만 가능합니다.')
        deadline = start_window(config, start_now=start_now)
        await account(uid, config)
        record = {'status': 'started', 'day': config['day'], 'request_id': str(request_id),
                  'started_at': now().isoformat(), 'start_mode': 'manual' if start_now else 'scheduled',
                  'additional_attempt': additional_attempt}
        trial.write(path, record, exclusive=True)
        try:
            current = await quote(uid, config)
            ticks = 2 if additional_attempt else 1
            price = recovery.gateway.align_price_to_tick(current + ticks * recovery.gateway.tick_size(int(current)), 'sell')
            record.update(status='parent_sending', parent_price=price)
            trial.write(path, record)
            await recovery.pause()  # 마지막 시세 조회와 주문 준비의 잔고 조회를 띄운다.
            result = await manual.submit(uid, request_id=request_id, symbol=SYMBOL, side='sell', quantity=1, price=price)
            record['parent_result'] = {k: result.get(k) for k in ('status', 'code', 'intent_id')}
            parent, _ = await orders(uid, request_id)
            if parent is None or not parent.order_no or result.get('status') not in ('submitted', 'filled'):
                raise ValueError('원 매도 접수 번호를 확인하지 못했습니다.')
            record.update(status='parent_cancelling', parent_id=str(parent.id))
            trial.write(path, record)
            await recovery.pause()
            await recovery.cancel(uid, parent.id)
            state = await confirmed(uid, parent.id, 'CANCELLED', now() + timedelta(seconds=90))
            if state['status'] == 'FILLED':
                record['final_account'] = await account(uid, config, trial_quantity=0)
                record['status'] = 'parent_filled_without_retry'
                return record
            if state['filled'] != 0 or state['cancelled_quantity'] != 1 or state['remaining'] != 0 or not state['cancelled']:
                raise ValueError('시험 1주의 전량 취소가 확정되지 않았습니다.')
            started = datetime.fromisoformat(state['created_at'])
            retry_at = started + timedelta(minutes=30, seconds=2)
            until = min(started + timedelta(minutes=42), deadline - timedelta(minutes=5))
            record.update(status='waiting_for_retry', retry_after=retry_at.isoformat(), retry_before=until.isoformat())
            trial.write(path, record)
            while now() < retry_at:
                await asyncio.sleep(min(30, (retry_at-now()).total_seconds()))
            while now() < until:
                current = await quote(uid, config)
                # 현재가가 원 지정가 이상이며 기존 1% 이내일 때 한 번만 시험한다. 체결은 별도 확인한다.
                if current >= price and within_retry_price_limit(price, current, 1):
                    break
                await asyncio.sleep(10)
            else:
                record.update(status='not_executed', code='PRICE_CONDITION_NOT_MET')
                return record
            await account(uid, config)
            record['status'] = 'retry_sending'
            trial.write(path, record)
            await recovery.pause()
            result = await trial.run(uid, parent.id, directory / 'restoration', execute=True)
            record['retry_result'] = {k: result.get(k) for k in ('status', 'code', 'intent_id', 'policy_restored')}
            _, child = await orders(uid, request_id)
            if result.get('status') != 'submitted' or child is None or not child.order_no:
                raise ValueError('재주문 접수 번호를 확인하지 못했습니다.')
            record.update(status='confirming_fill', child_id=str(child.id))
            trial.write(path, record)
            state = await confirmed(uid, child.id, 'FILLED', min(now()+timedelta(minutes=3), deadline-timedelta(minutes=2)))
            if state['status'] != 'FILLED' or state['filled'] != 1:
                raise ValueError('재주문 1주 체결을 확인하지 못했습니다.')
            record['final_account'] = await account(uid, config, trial_quantity=0)
            record.update(status='passed', child_order_no=state['order_no'], filled_quantity=1)
            return record
        except Exception as exc:
            record.update(status='needs_review', error_type=type(exc).__name__)
            return record
        finally:
            record['orders'] = await cleanup(uid, request_id)
            if any(row['status'] == 'needs_review' for row in record['orders']):
                record['status'] = 'needs_review'
            record['finished_at'] = now().isoformat()
            trial.write(path, record)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--start-now', action='store_true',
                        help='사용자가 지금 시작하도록 요청한 경우만 사용. 예약에는 넣지 않는다.')
    parser.add_argument('--additional-attempt', action='store_true',
                        help='첫 시험의 선체결 이후 사용자가 별도로 승인한 추가 시험 1회. 매수는 하지 않는다.')
    args = parser.parse_args()
    if args.start_now and not args.execute:
        parser.error('--start-now는 --execute와 함께 사용합니다.')
    if args.additional_attempt and not args.start_now:
        parser.error('--additional-attempt는 --start-now와 함께 사용합니다.')
    config = json.loads(args.config.read_text())
    await pg.connect_postgres()
    await connect_redis()
    try:
        result = (await run(config, args.config.parent, start_now=args.start_now,
                            additional_attempt=args.additional_attempt) if args.execute
                  else await account(uuid.UUID(config['user_id']), config))
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await close_redis()
        await pg.close_postgres()


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({'status': 'needs_review', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
