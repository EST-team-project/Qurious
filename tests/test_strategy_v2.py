"""판 2 첫 진입·체결가 손절·전량 청산·재진입·자료 단위. 외부 주문 없음."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import strategy_v2 as v2

SPEC = deepcopy(v2.CONTRACT)


def bar(day, close, factor=1, spread=2):
    row = {"date": str(day), "open": close, "high": close + spread, "low": close - spread,
           "close": close, "factor": factor, "halted": False}
    row.update({"adjusted_" + k: row[k] * factor for k in ("open", "high", "low", "close")})
    return row


def bars():
    start = date(2026, 7, 1)
    return [bar(start + timedelta(days=i), 100 + i) for i in range(60)]


@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    monkeypatch.setattr(v2.market_calendar, 'trading_days', lambda start, end: {
        'partial': False, 'days': [{'date': str(start + timedelta(days=i)), 'is_trading_day': True}
                                 for i in range((end - start).days + 1)]})


def plan():
    state, out = v2.observe(v2.initial_state(), SPEC, bars())
    assert out['action'] == 'BUY'
    return state


def reserved(state=None, qty=10, key='order-1', mode='kis_intraday_probe'):
    state = state or plan()
    target = date.fromisoformat(state['pending']['signal_date']) + timedelta(days=1)
    return v2.reserve(state, order_key=key, quantity=qty, mode=mode, target_date=str(target))[0]


def filled(state=None, qty=10, avg=160, status='FILLED'):
    state = state or reserved(qty=qty)
    return v2.fill(state, order_key=state['pending']['order_key'], cumulative_quantity=qty,
        average_price=avg, status=status, filled_at=state['pending']['target_date']+'T09:00:00+09:00')[0]


def test_first_true_signal_allowed_with_warmup_and_atr():
    state = plan()
    assert state['quantity'] == 0 and state['reentry_armed']
    assert state['pending']['distance_raw'] == pytest.approx(8)
    with pytest.raises(ValueError, match='60'):
        v2.observe(v2.initial_state(), SPEC, bars()[:-1])


@pytest.mark.parametrize('field,value', [('version', True), ('entry_mode', 'close'), ('reentry', 'always'), ('warmup_bars', 59)])
def test_unknown_contract_never_silently_falls_back(field, value):
    spec = deepcopy(SPEC); spec[field] = value
    with pytest.raises(ValueError): v2.validate_card(spec)


@pytest.mark.parametrize('bad', [None, 0, -1, float('nan'), float('inf'), True])
def test_invalid_factor_rejected(bad):
    rows = bars(); rows[-1]['factor'] = bad
    with pytest.raises(ValueError): v2.judgment(SPEC, rows)


def test_adjusted_atr_uses_judgment_factor_not_latest_or_multiplication():
    rows = [bar(date(2026,7,1)+timedelta(days=i), 100+i, factor=.5) for i in range(60)]
    result = v2.judgment(SPEC, rows)
    assert result['atr_adjusted'] == 2 and result['distance_raw'] == 8
    rows[-1]['adjusted_close'] = 999
    with pytest.raises(ValueError, match='단위'): v2.judgment(SPEC, rows)


def test_close_only_stop_and_locked_actual_fill_price():
    state = filled(avg=170)
    assert state['stop_price'] == 162 and state['take_price'] == 186
    rows = bars() + [bar(date(2026,8,30), 180, spread=50)]
    unchanged, result = v2.observe(state, SPEC, rows)
    assert result['action'] == 'HOLD'  # low crosses stop; only close may trigger
    assert unchanged['stop_price'] == 162 and unchanged['take_price'] == 186
    rows += [bar(date(2026,8,31), 161)]
    stopped, result = v2.observe(unchanged, SPEC, rows)
    assert result['action'] == 'SELL' and result['reason'] == 'STOP_CLOSE'
    assert stopped['pending']['base_quantity'] == 10
    with pytest.raises(ValueError, match='전량'): reserved(stopped, qty=5)


def test_partial_fills_never_allow_pyramiding_and_final_fill_locks_vwap():
    state = reserved()
    partial = filled(state, qty=4, avg=160, status='PARTIALLY_FILLED')
    assert partial['quantity'] == 4 and partial['stop_price'] == 152
    rows = bars() + [bar(date(2026,8,30), 165)]
    pending, result = v2.observe(partial, SPEC, rows)
    assert result['action'] == 'HOLD'
    with pytest.raises(ValueError): reserved(pending)
    done = filled(pending, qty=10, avg=164)
    assert done['quantity'] == 10 and done['avg_price'] == 164 and done['stop_price'] == 156
    assert done['pending'] is None


@pytest.mark.parametrize('status', ['ACCEPTED', 'UNKNOWN'])
def test_receipt_and_unknown_do_not_imply_fill_or_allow_resubmit(status):
    state, _ = v2.fill(reserved(), order_key='order-1', cumulative_quantity=0,
                       average_price=None, status=status)
    assert state['quantity'] == 0 and state['pending']['phase'] == status
    with pytest.raises(ValueError): reserved(state)
    with pytest.raises(ValueError): v2.reduce_event(state, SPEC, {'kind':'cancel_plan','reason':'retry'})
    with pytest.raises(ValueError): v2.fill(state, order_key='order-1', cumulative_quantity=1,
        average_price=160, status=status, filled_at='2026-08-30T09:00:00+09:00')


def test_terminal_partial_cancel_preserves_only_confirmed_quantity():
    state = filled(reserved(), qty=4, avg=160, status='PARTIALLY_FILLED')
    state = filled(state, qty=4, avg=160, status='CANCELLED')
    assert state['quantity'] == 4 and state['pending'] is None and state['stop_price'] == 152


def test_exit_then_true_cannot_reenter_until_false_then_true():
    state = filled()
    rows = bars() + [bar(date(2026,8,30), 180)]  # take at close, entry still true
    state, result = v2.observe(state, SPEC, rows)
    assert result['reason'] == 'TAKE_CLOSE'
    state = filled(reserved(state, key='sell'), avg=180)
    assert not state['reentry_armed'] and state['quantity'] == 0
    rows += [bar(date(2026,8,31), 181)]
    state, out = v2.observe(state, SPEC, rows)
    assert out['action'] == 'HOLD' and not state['reentry_armed']
    for i in range(25):
        rows += [bar(date(2026,9,1)+timedelta(days=i), 50)]
        state, out = v2.observe(state, SPEC, rows)
    assert state['reentry_armed']
    for i in range(25):
        rows += [bar(date(2026,9,26)+timedelta(days=i), 200)]
        state, out = v2.observe(state, SPEC, rows)
        if out['action'] == 'BUY': break
    assert out['action'] == 'BUY'


def test_corporate_action_blocks_holding_persistently_and_skips_first_entry():
    rows = bars(); rows[-1] = bar(date(2026,8,29), 159, factor=2)
    flat, out = v2.observe(v2.initial_state(), SPEC, rows)
    assert out['action'] == 'HOLD'
    state = filled()
    rows = bars() + [bar(date(2026,8,30), 320, factor=.5)]
    state, out = v2.observe(state, SPEC, rows)
    assert state['blocked'] == 'CORPORATE_ACTION_RECONCILIATION'
    rows += [bar(date(2026,8,31), 320, factor=.5)]
    state, out = v2.observe(state, SPEC, rows)
    assert out['action'] == 'HOLD' and state['quantity'] == 10


def test_risk_size_includes_budget_cash_position_and_zero():
    state = plan()
    kwargs = dict(equity=100000, cash=100000, price=160, budget=100000,
                  existing_value=0, position_cap_pct=30, slippage_bps=10, when=date(2026,8,30))
    result = v2.size_entry(state, **kwargs)
    assert result['estimated_loss'] <= 1000 and result['estimated_cash'] <= 30000
    assert v2.size_entry(state, **{**kwargs,'cash':100})['quantity'] == 0
    state, out = v2.reduce_event(state, SPEC, {'kind':'cancel_plan','reason':'ZERO_QUANTITY'})
    assert state['pending'] is None and out['status'] == 'blocked'


def test_virtual_next_open_cannot_be_intraday_price_or_later_trading_day():
    state = reserved(mode='virtual_next_open')
    with pytest.raises(ValueError, match='장중'):
        v2.fill(state, order_key='order-1', cumulative_quantity=10, average_price=160,
                status='FILLED', filled_at='2026-08-30T14:00:00+09:00')
    with pytest.raises(ValueError, match='바로 다음'):
        v2.reserve(plan(), order_key='next', quantity=10, mode='virtual_next_open', target_date='2026-08-31')
    assert filled(state)['quantity'] == 10


@pytest.mark.parametrize('qty,avg,status', [(3,160,'PARTIALLY_FILLED'), (11,160,'FILLED'), (4,161,'CANCELLED'), (4,160,'REJECTED')])
def test_invalid_or_changed_confirmed_fill_rejected(qty, avg, status):
    state = filled(reserved(), qty=4, avg=160, status='PARTIALLY_FILLED')
    with pytest.raises(ValueError): filled(state, qty=qty, avg=avg, status=status)


def test_history_is_not_mutated_and_old_bar_cannot_rewind():
    old = v2.initial_state(); saved=deepcopy(old)
    state, _ = v2.observe(old, SPEC, bars())
    assert old == saved
    with pytest.raises(ValueError, match='되돌릴'): v2.observe(state, SPEC, bars())


def test_virtual_replay_fills_next_open_full_exit_and_records_gap():
    from app.services.strategy_v2_replay import replay
    rows = bars()
    up = bar(date(2026,8,30), 180); up.update(open=160, low=158, adjusted_open=160, adjusted_low=158)
    gap = bar(date(2026,8,31), 181); gap.update(open=140, low=138, adjusted_open=140, adjusted_low=138)
    rows += [up, gap, bar(date(2026,9,1), 182)]
    report = replay(SPEC, rows, start=date(2026,8,29), initial_cash=100000, budget=100000,
        slippage_bps=0, risk_row=SimpleNamespace(risk_kill_switch=False,risk_daily_loss_limit_pct=0))
    assert len(report['fills']) == 2
    buy, sell = report['fills']
    assert buy['signal_date']=='2026-08-29' and buy['filled_at'].startswith('2026-08-30T09:00')
    assert buy['price']==160 and sell['price']==140
    assert sell['reason']=='TAKE_CLOSE' and sell['quantity']==buy['quantity']
    assert report['state']['quantity']==0 and not report['state']['reentry_armed']
    expected = 100000 - buy['cost']['net_amount'] + sell['cost']['net_amount']
    assert report['cash']==pytest.approx(expected,abs=.01)
    assert report['cash'] < 100000  # 익절 조건이어도 다음 시가 갭으로 손실 가능


def test_virtual_replay_cannot_move_missing_next_open_to_later_day():
    from app.services.strategy_v2_replay import replay
    rows = bars() + [bar(date(2026,8,31), 160)]
    report = replay(SPEC, rows, start=date(2026,8,29), initial_cash=100000, budget=100000,slippage_bps=0)
    assert report['fills']==[]
    assert '바로 다음' in report['rows'][-1]['skipped']['reason']


def test_virtual_replay_never_forces_one_share_and_keeps_kill_switch():
    from app.services.strategy_v2_replay import replay
    rows=bars()+[bar(date(2026,8,30),160)]
    for capital, row in [(100,None),(100000,SimpleNamespace(risk_kill_switch=True))]:
        report=replay(SPEC,rows,start=date(2026,8,29),initial_cash=capital,budget=capital,risk_row=row)
        assert report['fills']==[] and report['state']['quantity']==0


def test_future_or_flat_atr_cannot_supply_entry():
    rows=[bar(date(2026,7,1)+timedelta(days=i),100,spread=0) for i in range(60)]
    with pytest.raises(ValueError):v2.judgment(SPEC,rows)
    rows=bars();rows[-1]['date']='2099-01-01'
    with pytest.raises(ValueError,match='마감'):v2.judgment(SPEC,rows)


def test_runtime_contract_matches_published_v2_card():
    import json
    from pathlib import Path
    card=Path(__file__).resolve().parents[1]/'docs/phase-3/02-design/system/예시/strategy-card-ma-cross-v2.json'
    assert v2.validate_card(json.loads(card.read_text())) == v2.validate_card(SPEC)


def test_halted_bar_does_not_plan_entry():
    rows=bars();rows[-1]['halted']=True
    state,out=v2.observe(v2.initial_state(),SPEC,rows)
    assert state['pending'] is None and out['action']=='HOLD'


def test_partial_sell_then_cancel_keeps_remaining_strategy_position():
    state=filled()
    state,_=v2.observe(state,SPEC,bars()+[bar(date(2026,8,30),180)])
    state=reserved(state,key='sell')
    state=filled(state,qty=4,avg=180,status='PARTIALLY_FILLED')
    assert state['quantity']==6 and state['avg_price']==160
    state=filled(state,qty=4,avg=180,status='CANCELLED')
    assert state['quantity']==6 and state['pending'] is None
    state,out=v2.observe(state,SPEC,bars()+[bar(date(2026,8,30),180),bar(date(2026,8,31),181)])
    assert out['action']=='SELL'
    state=filled(reserved(state,qty=6,key='sell-rest'),qty=6,avg=181)
    assert state['quantity']==0 and not state['reentry_armed']


def test_delayed_fill_does_not_consume_the_close_stop_judgment():
    state=filled(reserved(),qty=4,avg=160,status='PARTIALLY_FILLED')
    rows=bars()+[bar(date(2026,8,30),140)]
    state,out=v2.observe(state,SPEC,rows)
    assert out['deferred'] and state['last_bar']=='2026-08-29'
    state=filled(state,qty=10,avg=160)
    state,out=v2.observe(state,SPEC,rows)
    assert out['action']=='SELL' and out['reason']=='STOP_CLOSE'
