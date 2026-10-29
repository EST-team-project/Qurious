"""판 2를 QUANT 장부·공통 위험 관문에 연결한다. KIS 전송은 하지 않는다.

수집 자료가 늦게 도착해도 모델 체결은 다음 거래일 09:00이다. Order.created_at은
실제 기록 시각, filled_at은 모델 체결 시각이다. 일손실/주문수 관문은 실행일에
적용하고, 신호와 모델 체결일은 price_basis에 별도로 보존한다.
"""
from datetime import date, datetime, time, timezone
import math

from sqlalchemy import select

from app.database.postgres import get_session_factory
from app.models import BrokerSettings, Order, OrderIntent, Portfolio, QuantVirtualAccount, StrategyRuntime
from app.services import (strategy_v2 as v2, execution_control as control, live_ownership,
                          rebalance_daily, collector_db, hf_snapshot, trading_cost)

SYMBOL = '005930.KS'


def inputs():
    ready = rebalance_daily.readiness()
    if not ready['ready']:
        raise control.Rejected('DATA_NOT_READY', ready['message'])
    path = collector_db.db_path()
    if path is None:
        raise control.Rejected('DATA_NOT_READY', '수집 DB를 확인하지 못했습니다.')
    path = path.resolve()
    if ready.get('source_commit'):
        proof = hf_snapshot.read_ready_proof(path.parent)
        if proof['snapshot_commit'] != ready['source_commit']:
            raise control.Rejected('DATA_CHANGED', '확인 중 수집 자료 세대가 바뀌었습니다.')
    bars = v2.load_bars(SYMBOL, date.fromisoformat(ready['data_as_of']), path=path)
    v2.judgment(v2.CONTRACT, bars)
    return bars, {k: ready.get(k) for k in ('data_as_of', 'data_ready_at', 'source_commit')}


def context(uid):
    return dict(user_id=uid, account_ref=control.digest([str(uid), 'QUANT']),
                book='V2_VIRTUAL', symbol=SYMBOL, spec=v2.CONTRACT)


def runtime_id(ctx):
    return control.digest([str(ctx['user_id']), ctx['account_ref'], ctx['book'], 'ma_cross_20_60', 2, SYMBOL])


async def configuration(db, uid, *, require_enabled):
    row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid).execution_options(populate_existing=True))
    if row is None or row.quant_mode != 'paper':
        raise control.Rejected('V2_PAPER_ONLY', '판 2 다음 시가 실행은 앱 QUANT 가상 장부만 지원합니다.')
    if row.risk_kill_switch or require_enabled and not row.quant_auto_enabled:
        raise control.Rejected('DISABLED', '자동 실행 중지 또는 비상 정지 상태입니다.')
    if require_enabled and (row.quant_strategy_id, row.quant_strategy_version) != ('ma_cross_20_60', 2):
        raise control.Rejected('SETTINGS_CHANGED', '선택한 전략이 판 2가 아닙니다.')
    return row


async def record(db, ctx, key, event):
    return await v2.apply_event(db, **ctx, event_key=key, event=event)


async def recover(db, ctx, runtime):
    """가상 장부 commit 뒤 프로세스가 죽어도 Order가 유일한 체결 근거다."""
    pending = runtime.state['pending']
    if not pending or pending['phase'] == 'planned':
        return None
    intent = await db.get(OrderIntent, pending['order_key'])
    if intent is None:
        raise control.Rejected('EXECUTION_UNCONFIRMED', '예약에 대응하는 주문 의도를 확인하지 못했습니다.')
    if (intent.user_id != ctx['user_id'] or intent.account_ref != ctx['account_ref'] or intent.book != 'QUANT'
            or (intent.strategy_id, intent.strategy_version, intent.symbol) != ('ma_cross_20_60', 2, SYMBOL)
            or intent.side != pending['side']):
        raise control.Rejected('OWNERSHIP_UNCONFIRMED', '예약과 주문 의도의 귀속이 다릅니다.')
    order = await db.scalar(select(Order).where(Order.execution_intent_id == intent.intent_id))
    if order is None:
        if intent.status not in ('skipped', 'error'):
            raise control.Rejected('EXECUTION_UNCONFIRMED', '장부 체결 미확인 상태이며 재전송하지 않습니다.')
        event = dict(kind='fill', order_key=intent.intent_id, cumulative_quantity=0, average_price=None, status='REJECTED')
    else:
        at = datetime.combine(date.fromisoformat(pending['target_date']), time(9), v2.KST)
        if (order.user_id != ctx['user_id'] or order.source != 'QUANT' or order.symbol != SYMBOL
                or order.order_type.upper() != pending['side'] or order.status != 'filled'
                or order.quantity != pending['quantity'] or order.filled_quantity != pending['quantity']
                or order.filled_at != at or not math.isclose(float(order.avg_fill_price or 0), pending['execution_price'], rel_tol=1e-10)):
            raise control.Rejected('FILL_CONFLICT', '확정 가상 체결과 예약의 수량·가격·시각이 다릅니다.')
        event = dict(kind='fill', order_key=intent.intent_id, cumulative_quantity=order.filled_quantity,
                     average_price=order.avg_fill_price, status='FILLED', filled_at=at.isoformat())
        # 외부 전송이 없는 원자적 가상 장부에 한해서만 PENDING을 확정할 수 있다.
        intent.status = 'filled'
        intent.result = {**intent.result, 'status': 'filled', 'quantity': order.quantity, 'price': order.price,
                         'reconciled_from_order': str(order.id)}
    result = await record(db, ctx, 'fill:' + intent.intent_id, event)
    await db.commit()
    return result


async def prepare(db, ctx, intent, bars, evidence, expected_pending, *, require_enabled):
    current_bars, current_evidence = inputs()
    if control.digest(current_bars) != control.digest(bars) or current_evidence != evidence:
        raise control.Rejected('DATA_CHANGED', '준비 중 확정 자료가 바뀌었습니다.')
    row = await configuration(db, ctx['user_id'], require_enabled=require_enabled)
    runtime = await db.get(StrategyRuntime, runtime_id(ctx), populate_existing=True)
    if not runtime or runtime.state['pending'] != expected_pending or runtime.state['blocked']:
        raise control.Rejected('STATE_CHANGED', '실행 준비 중 판 2 상태가 바뀌었습니다.')
    day = date.fromisoformat(bars[-1]['date'])
    if runtime.state['last_bar'] >= day.isoformat():
        raise control.Rejected('STALE_SIGNAL', '이미 처리한 봉으로 주문하지 않습니다.')
    if bars[-1].get('halted') or v2.adjustment_changed(expected_pending['factor'], bars[-1]['factor']):
        raise control.Rejected('CORPORATE_ACTION_OR_HALT', '실행일 거래정지 또는 가격 조정 사건으로 보류합니다.')
    positions = (await db.scalars(select(Portfolio).where(Portfolio.user_id == ctx['user_id'], Portfolio.book == 'QUANT', Portfolio.quantity > 0))).all()
    if any(p.symbol != SYMBOL for p in positions):
        raise control.Rejected('VALUATION_UNAVAILABLE', '다른 종목의 동일 시각 평가가 필요해 판 2 실행을 보류합니다.')
    account = await db.scalar(select(QuantVirtualAccount).where(QuantVirtualAccount.user_id == ctx['user_id']))
    if account is None:
        raise control.Rejected('ACCOUNT_UNAVAILABLE', 'QUANT 가상 계좌가 없습니다.')
    actual = sum(p.quantity for p in positions)
    owned = await live_ownership.virtual_quantity(db, intent, actual)
    if owned != runtime.state['quantity']:
        raise control.Rejected('OWNERSHIP_UNCONFIRMED', '전략 상태와 확정 장부 보유가 다릅니다.')
    raw_open = v2.positive(bars[-1]['open'], '다음 거래일 원주가 시가')
    # 카드의 가상 재현과 같은 편도 10bp 가정. 실제 KIS 시세로 표시하지 않는다.
    slip = trading_cost.DEFAULT_SLIPPAGE_BPS
    price = raw_open * (1 + (1 if intent.side == 'BUY' else -1) * slip / 10000)
    cash, equity = float(account.cash_balance), float(account.cash_balance) + actual * raw_open
    limits = control.risk_guard.RiskLimits.from_row(row)
    sizing = None
    quantity = owned
    if intent.side == 'BUY':
        sizing = v2.size_entry(runtime.state, equity=equity, cash=cash, price=price,
            budget=float(row.quant_per_trade_budget) * float(row.quant_buy_ratio), existing_value=actual * price,
            position_cap_pct=limits.max_position_pct, slippage_bps=0, when=day)
        quantity = sizing['quantity']
    if quantity <= 0:
        raise control.Rejected('ZERO_QUANTITY', '위험·예산·현금 상한으로 주문할 수량이 없습니다.')
    # 예약 단계에서 실제 거래일 달력도 검증한다. 여기서는 상태를 저장하지 않는다.
    v2.reserve(runtime.state, order_key=intent.key, quantity=quantity, mode='virtual_next_open', target_date=day.isoformat(), execution_price=price)
    at = datetime.combine(day, time(9), v2.KST)
    return dict(db=db, quantity=quantity, price=price, cash=cash, equity=equity,
        position_value=actual * price, owned_quantity=owned, settings=control.settings_signature(row),
        checked_at=datetime.now(timezone.utc), filled_at=at,
        price_basis={'mode': 'virtual_next_open', 'signal_as_of': expected_pending['signal_date'],
            'model_filled_at': at.isoformat(), 'raw_open': raw_open, 'price': price,
            'slippage_bps': slip, 'sizing': sizing, **evidence})


async def run(uid, *, execute=False, require_enabled=False):
    """수동 호출은 자동 설정을 바꾸지 않는다. 정기 실행은 require_enabled=True."""
    ctx = context(uid)
    try:
        bars, evidence = inputs()
        day = bars[-1]['date']
        async with get_session_factory()() as db:
            async with control.account_lock(db, ctx['account_ref']) as acquired:
                if not acquired:
                    return control.blocked('ACCOUNT_BUSY', '같은 계좌의 실행이 진행 중입니다.')
                await configuration(db, uid, require_enabled=require_enabled)
                runtime = await db.get(StrategyRuntime, runtime_id(ctx))
                if not execute:
                    state = runtime.state if runtime else v2.initial_state()
                    if state['pending']:
                        return dict(status='DRY_RUN', pending=state['pending'], evidence=evidence)
                    if state['last_bar'] == day:
                        return dict(status='DRY_RUN', reason='이미 판단한 봉', evidence=evidence)
                    _, result = v2.observe(state, v2.CONTRACT, bars)
                    return dict(status='DRY_RUN', decision=result, evidence=evidence)
                if runtime:
                    await recover(db, ctx, runtime)
                    await db.refresh(runtime)
                else:
                    account = await db.scalar(select(QuantVirtualAccount).where(QuantVirtualAccount.user_id == uid))
                    if account is None:
                        from app.services.auto_trade import _INITIAL_CAPITAL
                        db.add(QuantVirtualAccount(user_id=uid, initial_capital=float(_INITIAL_CAPITAL), cash_balance=float(_INITIAL_CAPITAL)))
                    result = await record(db, ctx, 'bar:' + day, dict(kind='bar', bars=bars))
                    await db.commit()
                    return dict(status='initialized', decision=result['outcome'], evidence=evidence)
                if runtime.state['last_bar'] == day:
                    return dict(status='duplicate', reason='이미 판단한 봉', evidence=evidence)
                if runtime.state['last_bar'] > day:
                    raise control.Rejected('STALE_DATA', '이전 자료 세대로 상태를 되돌릴 수 없습니다.')
                pending = runtime.state['pending']
                if not pending:
                    result = await record(db, ctx, 'bar:' + day, dict(kind='bar', bars=bars))
                    await db.commit()
                    return dict(status='observed', decision=result['outcome'], evidence=evidence)
                if runtime.state['blocked']:
                    raise control.Rejected('CORPORATE_ACTION_RECONCILIATION', '조정 사건 보유 대조가 필요합니다.')
                if bars[-1].get('halted') or v2.adjustment_changed(pending['factor'], bars[-1]['factor']):
                    await record(db, ctx, 'cancel:' + day, dict(kind='cancel_plan', reason='CORPORATE_ACTION_OR_HALT'))
                    result = await record(db, ctx, 'bar:' + day, dict(kind='bar', bars=bars))
                    await db.commit()
                    return dict(status='skipped', code='CORPORATE_ACTION_OR_HALT', decision=result['outcome'])
                # 계좌 잠금을 풀고 공통 관문이 같은 잠금을 얻는다. prepare에서 상태를 재검사한다.
                await db.commit()
        intent = control.Intent(uid, ctx['account_ref'], 'QUANT', 'ma_cross_20_60', 2, SYMBOL,
            pending['side'], pending['signal_date'] + ':next_open', 'v2_next_open',
            control.digest({'pending': pending, 'bar': bars[-1], 'spec': v2.validate_card(v2.CONTRACT)}))
        async def prepare_order(db):
            try:
                return await prepare(db, ctx, intent, bars, evidence, pending, require_enabled=require_enabled)
            except control.Rejected:
                raise
            except ValueError as exc:
                raise control.Rejected('V2_INPUT_INVALID', str(exc)) from exc
        async def send(order_id, quantity, basis):
            db = basis['db']
            await record(db, ctx, 'reserve:' + intent.key, dict(kind='reserve', order_key=intent.key,
                quantity=quantity, mode='virtual_next_open', target_date=day, execution_price=basis['price']))
            await db.commit()
            from app.services.auto_trade import _execute_virtual_trade
            result = await _execute_virtual_trade(db, uid, SYMBOL, '삼성전자', intent.side.lower(),
                basis['price'], quantity, pending['reason'], filled_at=basis['filled_at'], strict_quantity=True)
            return {**result, 'price_basis': basis['price_basis']}
        outcome = await control.execute(intent, 0, prepare_order, send, require_enabled=require_enabled)
        async with get_session_factory()() as db:
            async with control.account_lock(db, ctx['account_ref']) as acquired:
                if not acquired:
                    return {**outcome, 'reconciliation': 'pending'}
                runtime = await db.get(StrategyRuntime, runtime_id(ctx))
                if runtime.state['pending'] and runtime.state['pending']['phase'] != 'planned':
                    recovered = await recover(db, ctx, runtime)
                    await db.refresh(runtime)
                    if recovered and recovered['outcome']['status'] == 'FILLED':
                        saved = await db.get(OrderIntent, intent.key, populate_existing=True)
                        outcome = {**outcome, **saved.result, 'intent_id': intent.key}
                if outcome.get('status') == 'filled' and not runtime.state['pending']:
                    observed = await record(db, ctx, 'bar:' + day, dict(kind='bar', bars=bars))
                    await db.commit()
                    return {**outcome, 'decision': observed['outcome'], 'evidence': evidence}
        if outcome.get('duplicate'):
            return {**outcome, 'original_status': outcome.get('status'), 'status': 'duplicate'}
        return outcome
    except control.Rejected as exc:
        result = control.blocked(exc.code, str(exc))
        if exc.code in ('EXECUTION_UNCONFIRMED', 'FILL_CONFLICT'):
            result['status'] = 'unknown'
        return result
    except ValueError as exc:
        return control.blocked('V2_INPUT_INVALID', str(exc))
