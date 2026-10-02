"""리밸런싱 순수 계산. 시세/DB 접근 없이 입력·비중·주문 비용을 검증한다."""
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite

from app.services import trading_cost as tc


def number(value, name, minimum=0, maximum=None):
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f'{name}: 유효한 숫자를 입력하세요.') from None
    if not isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f'{name}: 허용 범위의 유한한 숫자를 입력하세요.')
    return value


def bp(percent):
    return int((Decimal(str(percent)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def weights(cash, positions, targets, threshold, enabled, exclude_unplanned):
    target_map = {t['symbol']: float(t['weight_pct']) for t in targets}
    pos_map = {p['symbol']: p for p in positions}
    excluded = sum(p['evalAmount'] for p in positions if exclude_unplanned and p['symbol'] not in target_map)
    stock_eval = sum(p['evalAmount'] for p in positions) - excluded
    total = cash + stock_eval
    rows, drifts = [], []
    for sym in sorted(set(target_map) | set(pos_map)):
        p = pos_map.get(sym, {})
        managed = not exclude_unplanned or sym in target_map
        amount = float(p.get('evalAmount', 0))
        cur = amount / total * 100 if total > 0 and managed else 0
        tgt = target_map.get(sym, 0)
        delta = bp(cur) - bp(tgt)
        if managed:
            drifts.append(abs(delta))
        rows.append(dict(symbol=sym, name=p.get('name') or next((t.get('name', sym) for t in targets if t['symbol'] == sym), sym),
                         quantity=p.get('quantity', 0), price=p.get('currentPrice'), current_amount=amount,
                         current_weight_pct=bp(cur)/100, target_weight_pct=tgt, drift_pct=delta/100,
                         in_plan=sym in target_map, managed=managed))
    cash_target = 100 - sum(target_map.values())
    cash_weight = cash / total * 100 if total > 0 else 100
    cash_drift = bp(cash_weight) - bp(cash_target)
    maximum = max(drifts + [abs(cash_drift)])
    return dict(total_asset=round(total, 2), excluded_asset=round(excluded, 2), cash=cash,
                cash_weight_pct=bp(cash_weight)/100, cash_target_pct=cash_target, cash_drift_pct=cash_drift/100,
                cash_excess=round(cash-total*cash_target/100, 2), stock_eval=stock_eval, rows=rows,
                max_drift_pct=maximum/100, max_drift_bp=maximum,
                drift_exceeded=bool(enabled and target_map and maximum >= bp(threshold)))


def cashflow_signal(excess, budget, threshold):
    # Same-sign restriction prevents a withdrawal from generating buys and vice versa.
    eligible = min(abs(excess), abs(budget)) if excess * budget > 0 else 0
    due = eligible > 0 and eligible >= threshold
    return dict(cashflow_due=due, cashflow_available=round(eligible, 2), pending_budget=round(budget, 2),
                plan_kind='buy_only' if budget > 0 else 'sell_only')


def choose_triggers(time_due, drift_due, mode, cashflow_due, drift_enabled=True):
    # In scheduled mode the date AND threshold must match; TIME alone must not bypass it.
    triggers = []
    if mode == 'scheduled':
        if time_due and drift_enabled and drift_due:
            triggers += ['TIME', 'DRIFT']
    else:
        if time_due:
            triggers.append('TIME')
        if drift_enabled and drift_due:
            triggers.append('DRIFT')
    if cashflow_due:
        triggers.append('CASHFLOW')
    return triggers


def order_cost(row, price, qty, side, when):
    return tc.order_costs(side.lower(), price, qty, when, market=tc.market_of(row['symbol']),
                          is_etf=tc.is_etf_name(row['name']))


def orders(snap, prices, minimum, kind='full', budget=None, when=None):
    """Cost-aware integer sizing. Cashflow sales stop at the deficit; full sells may rotate assets."""
    if kind not in ('full', 'buy_only', 'sell_only'):
        raise ValueError('알 수 없는 계획 종류입니다.')
    when = when or tc.today_kst()
    total = snap['total_asset']
    reserve = total * snap['cash_target_pct']/100
    buy_limit = max(0, snap['cash']-reserve)
    sell_limit = max(0, reserve-snap['cash'])
    if budget is not None:
        buy_limit, sell_limit = min(buy_limit, abs(budget)), min(sell_limit, abs(budget))
    candidates, skipped = [], []
    for row in snap['rows']:
        if not row.get('managed', True):
            continue
        price = prices.get(row['symbol'])
        if not price or not isfinite(price) or price <= 0:
            skipped.append({'symbol': row['symbol'], 'reason': '시세 조회 실패'})
            continue
        diff = total * row['target_weight_pct']/100 - row['current_amount']
        side = 'BUY' if diff > 0 else 'SELL'
        if (kind == 'buy_only' and side == 'SELL') or (kind == 'sell_only' and side == 'BUY'):
            continue
        qty = int(abs(diff)//price)
        if side == 'SELL':
            qty = min(qty, int(row['quantity']))
        if qty > 0 and qty * price >= minimum:
            candidates.append((side, -abs(diff), row['symbol'], row, price, qty))
    # Biggest deficits/surpluses first; stable symbol tie-break.
    candidates.sort(key=lambda x: (0 if x[0] == 'SELL' else 1, x[1], x[2]))
    result, cash, cashflow_spent = [], float(snap['cash']), 0.0
    for side, _, _, row, price, qty in candidates:
        unit = order_cost(row, price, 1, side, when)
        if side == 'BUY':
            available = max(0, cash-reserve)
            if kind == 'buy_only':
                available = min(available, max(0, buy_limit-cashflow_spent))
            qty = min(qty, int(available // unit.net_amount))
        elif kind == 'sell_only':
            available = max(0, sell_limit-cashflow_spent)
            qty = min(qty, int(available // unit.net_amount))
        if qty <= 0 or price*qty < minimum:
            continue
        cost = order_cost(row, price, qty, side, when)
        cash += cost.net_amount if side == 'SELL' else -cost.net_amount
        cashflow_spent += cost.net_amount
        result.append(dict(symbol=row['symbol'], name=row['name'], side=side, quantity=qty, price=price,
                           amount=round(price*qty, 2), net_amount=cost.net_amount, cost=cost.as_dict(), status='proposed'))
    return dict(orders=result, skipped=skipped, estimated_cash_after=round(cash, 2),
                estimated_cost=round(sum(o['cost']['total_cost'] for o in result), 2),
                estimated_turnover=round(sum(o['amount'] for o in result), 2), snapshot=snap, plan_kind=kind)
