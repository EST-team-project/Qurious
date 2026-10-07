"""실제 수집기 SQLite + PostgreSQL: 종가 판단, 예약, 시가 정산, 재시작/중복 방지."""
import asyncio
import sqlite3
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select, func

from app.models import Order, RebalanceRun
from app.services import rebalance as rb, rebalance_prices as prices, rebalance_settlement as st
from tests.test_rebalance_policy import scenario, needs_db, target
from tests.test_rebalance_daily import clock, ready_data  # noqa: F401

pytestmark = pytest.mark.usefixtures("rebalance_db_schema")

SYMBOLS = ('005930.KS', '000660.KS')


def insert_open(path, day='20261007', price=900, volume=1000):
    with sqlite3.connect(path) as conn:
        conn.executemany('INSERT OR REPLACE INTO price_daily (bas_dt,srtn_cd,itms_nm,mrkt_ctg,mkp,clpr,trqu) '
                         "VALUES (?,?,'시험','KOSPI',?,1200,?)",
                         [(day, s.split('.')[0], price, volume) for s in SYMBOLS])


def ready(clock, day=8):
    clock.current = datetime(2026, 10, day, 13, 30, tzinfo=rb.KST)
    return dict(ready=True, data_as_of=f'2026-10-{day-1:02}')


async def queue(db, uid, automatic=True):
    plan = await rb.get_plan(db, uid)
    rb.apply_plan_update(plan, dict(targets=[target(SYMBOLS[0], 40), target(SYMBOLS[1], 40)],
                                    drift_enabled=True, auto_execute=automatic))
    await db.flush()
    result = await rb.check_daily(db, uid, plan)
    run = await db.get(RebalanceRun, uuid.UUID(result['run_id']))
    return plan, run


def test_raw_price_exact_date_and_no_flat_open(clock, ready_data):
    assert prices.read_prices(SYMBOLS, date(2026, 10, 2))[SYMBOLS[0]]['price'] == 1000
    with pytest.raises(prices.PriceUnavailable):
        prices.read_prices(SYMBOLS, date(2026, 10, 6))
    insert_open(ready_data[0], price=0)
    with pytest.raises(prices.PriceUnavailable):
        prices.read_prices(SYMBOLS, date(2026, 10, 7), 'open')
    insert_open(ready_data[0], volume=0)
    with pytest.raises(prices.PriceUnavailable):
        prices.read_prices(SYMBOLS, date(2026, 10, 7), 'open')
    assert prices.next_trading_day(date(2026, 10, 8)) == date(2026, 10, 12)  # 한글날 + 주말


def test_etf_raw_price_and_missing_calendar(clock, ready_data, monkeypatch):
    with sqlite3.connect(ready_data[0]) as c:
        c.execute("INSERT INTO etf_daily (bas_dt,srtn_cd,clpr,mkp,trqu) VALUES ('20261002','0000D0',1234,1200,50)")
    quote = prices.read_prices(['0000D0.KS'], date(2026, 10, 2))['0000D0.KS']
    assert quote['is_etf'] and quote['price'] == 1234
    with pytest.raises(prices.PriceUnavailable):
        prices.next_trading_day(date(2027, 12, 31))


@needs_db
def test_close_decision_reserves_then_uses_open_once(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async def forbidden(*args, **kw):
                raise AssertionError('자동 경로에서 현재가를 조회하면 안 됨')
            monkeypatch.setattr(rb.pt, 'resolve_stock', forbidden)
            async with factory() as db:
                plan, run = await queue(db, uid)
                rid = run.id
                assert run.status == 'scheduled' and run.context['valuation_date'] == '2026-10-02'
                assert run.context['scheduled_for'] == '2026-10-07'
                assert run.before_weights[SYMBOLS[0]] == 60
                assert all(o['price'] == 1000 for o in run.orders)
                quantities = [o['quantity'] for o in run.orders]
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
                assert (await rb.pt.get_account(db, uid)).cash == 200000
                await db.commit()
            # Even if a future row is present, it cannot fill on decision/execution day.
            insert_open(ready_data[0])
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                assert (await st.settle(db, uid, plan, {'ready':True, 'data_as_of':'2026-10-07'})).status == 'scheduled'
                await db.commit()
            state = ready(clock)
            async def settle():
                async with factory() as db:
                    plan = await rb.get_plan(db, uid)
                    run = await st.settle(db, uid, plan, state)
                    await db.commit()
                    return run.status if run else None
            results = await asyncio.gather(*(settle() for _ in range(4)))
            assert results.count('executed') == 1
            async with factory() as db:
                run = await db.get(RebalanceRun, rid)
                assert [o['quantity'] for o in run.orders] != quantities
                assert [o['quantity'] for o in run.context['indicative_orders']] == quantities
                assert all(o['price'] == 900 and o['decision_price'] == 1000 for o in run.orders)
                assert run.context['fill_date'] == '2026-10-07'
                assert run.context['confirmed_at'].startswith('2026-10-08')
                orders = (await db.execute(select(Order).where(Order.user_id == uid))).scalars().all()
                assert len(orders) == len(quantities)
                assert all(o.filled_at.astimezone(rb.KST).date() == date(2026,10,7) for o in orders)
                assert run.context['actual_cost'] > 0
    asyncio.run(go())


@needs_db
@pytest.mark.parametrize('change', ['cash', 'settings', 'none', 'missing', 'halted'])
def test_missing_data_or_unresolved_changes_wait(monkeypatch, clock, ready_data, change):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan, run = await queue(db, uid)
                rid = run.id
                await db.commit()
            if change != 'missing':
                insert_open(ready_data[0], volume=0 if change == 'halted' else 1000)
            state = ready(clock)
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                if change == 'cash':
                    (await rb.pt.get_account(db, uid)).cash += 100
                elif change == 'settings':
                    plan.min_order_amount = 2000
                elif change == 'none':
                    state['ready'] = False
                result = await st.settle(db, uid, plan, state)
                assert result.status == 'scheduled' and result.context['waiting_reason']
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
                await db.commit()
            async with factory() as db:
                assert (await db.get(RebalanceRun, rid)).status == 'scheduled'
    asyncio.run(go())


@needs_db
def test_approval_keeps_close_orders_and_manual_check_cannot_replace(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan, run = await queue(db, uid, automatic=False)
                assert run.status == 'proposed'
                orders = run.orders
                assert (await rb.check_daily(db, uid, plan))['reason'] == 'already_checked'
                assert run.context['price_basis'] == 'previous_close'
                await db.commit()
                run = await rb.execute_proposal(db, uid, run.id)
                assert run.status == 'scheduled'
                assert [o['quantity'] for o in orders] == [o['quantity'] for o in run.orders]
                await db.commit()
                with pytest.raises(rb.RebalanceError):
                    await rb.execute_proposal(db, uid, run.id)
    asyncio.run(go())


@needs_db
def test_price_gap_resizes_orders_without_negative_cash(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                rb.apply_plan_update(plan, dict(targets=[target(SYMBOLS[0],100)], auto_execute=True, drift_enabled=True))
                await db.flush()
                await rb.execute(db, uid, plan, 'MANUAL')
                await db.commit()
            insert_open(ready_data[0], price=100000)
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                run = await st.settle(db, uid, plan, ready(clock))
                assert run.status == 'executed'
                assert all(o['status'] == 'filled' for o in run.orders)
                assert run.orders[0]['quantity'] < run.context['indicative_orders'][0]['quantity']
                assert (await rb.pt.get_account(db, uid)).cash >= 0
                await db.commit()
                assert await st.settle(db, uid, plan, ready(clock)) is None
    asyncio.run(go())


@needs_db
def test_settlement_survives_new_decision_failure(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                _, run = await queue(db, uid)
                rid = run.id
                await db.commit()
            insert_open(ready_data[0])
            state = ready(clock)
            state.update(decision_date='2026-10-08', update_finished_at='2026-10-08T13:00:00+09:00')
            monkeypatch.setattr(rb.daily, 'readiness', lambda: state)
            async def unavailable(*args, **kwargs):
                raise prices.PriceUnavailable('새 판정 가격 누락')
            monkeypatch.setattr(st, 'close_snapshot', unavailable)
            result = await rb.check_all_due(factory)
            assert result['errors'] == 1
            async with factory() as db:
                assert (await db.get(RebalanceRun, rid)).status == 'executed'
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 2
                assert (await rb.get_plan(db, uid)).last_auto_check_date == date(2026,10,6)
            # Retry the failing evaluation: it must never repeat yesterday's settlement.
            await rb.check_all_due(factory)
            async with factory() as db:
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 2
    asyncio.run(go())


@needs_db
def test_partial_fill_keeps_costs_and_does_not_retry(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                _, run = await queue(db, uid)
                qty = [o['quantity'] for o in run.orders]
                await db.commit()
            insert_open(ready_data[0])
            original = rb.pt._fill_stock_order
            async def fail_buy(db, uid, quote, side, quantity, **kwargs):
                if side == 'BUY':
                    raise rb.pt.PaperTradeError('시험용 주문 실패')
                return await original(db, uid, quote, side, quantity, **kwargs)
            monkeypatch.setattr(rb.pt, '_fill_stock_order', fail_buy)
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                run = await st.settle(db, uid, plan, ready(clock))
                assert run.status == 'partial'
                assert [o['quantity'] for o in run.orders] != qty
                assert [o['status'] for o in run.orders] == ['filled', 'failed']
                sell = run.orders[0]
                assert (await rb.pt.get_account(db, uid)).cash == 200000 + sell['net_amount']
                assert sell['cost']['total_cost'] > 0
                await db.commit()
                assert await st.settle(db, uid, plan, ready(clock)) is None
    asyncio.run(go())


@needs_db
def test_cashflow_waits_until_daily_check_and_reserves(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                plan.auto_execute = True
                result = await rb.record_cashflow(db, uid, 'DEPOSIT', 200000)
                assert result['run'] is None and result['check_deferred']
                await db.commit()
                result = await rb.check_daily(db, uid, plan)
                assert result['status'] == 'scheduled'
                assert plan.last_auto_check_result['price_basis'] == 'previous_close'
                await db.commit()
    asyncio.run(go())


@needs_db
def test_batch_pipeline_waits_for_update_and_open_across_holidays(monkeypatch, clock, ready_data):
    """SQLite 일봉·완료 기록 → 실제 readiness → 배치 → PG 정산을 이어 검증한다.

    자료는 시험용이다. 실제 수집 성공으로 간주하지 않으며 판단/체결 함수를 대체하지 않는다.
    """
    path, _, write = ready_data

    def update(day, price_day, **changes):
        clock.current = datetime(2026, 10, day, 13, 30, tzinfo=rb.KST)
        write(started_at=f'2026-10-{day:02}T12:30:01+09:00',
              finished_at=f'2026-10-{day:02}T13:00:00+09:00',
              after={'price_max': f'202610{price_day:02}'}, **changes)

    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async def forbidden(*args, **kwargs):
                raise AssertionError('자동 배치에서 현재가를 조회하면 안 됨')
            monkeypatch.setattr(rb.pt, 'resolve_stock', forbidden)
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                rb.apply_plan_update(plan, dict(targets=[target(SYMBOLS[0], 40), target(SYMBOLS[1], 40)],
                                               drift_enabled=True, auto_execute=True))
                await db.commit()

            # 목요일 판단 → 한글날과 주말을 건너 월요일 시가 예약.
            insert_open(path, day='20261007')
            with sqlite3.connect(path) as conn:
                conn.execute("UPDATE price_daily SET clpr=1000 WHERE bas_dt='20261007'")
            update(8, 7)
            first = await rb.check_all_due(factory)
            assert first['readiness']['ready'] and first['checked'] == 1 and first['errors'] == 0
            async with factory() as db:
                run = (await db.execute(select(RebalanceRun).where(RebalanceRun.user_id == uid))).scalar_one()
                rid = run.id
                assert run.status == 'scheduled' and run.context['valuation_date'] == '2026-10-07'
                assert run.context['scheduled_for'] == '2026-10-12'
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
            repeat = await rb.check_all_due(factory)
            assert repeat['checked'] == repeat['executed'] == repeat['errors'] == 0

            # 체결 예정일 당일에는 시가가 확정되지 않아 정산하지 않는다.
            insert_open(path, day='20261008')
            update(12, 8)
            assert (await rb.check_all_due(factory))['executed'] == 0

            # 화요일 자료가 들어와도 러너가 실패했으면 기존 예약을 그대로 기다린다.
            insert_open(path, day='20261012')
            update(13, 12, ok=False, stopped='price failed')
            failed_update = await rb.check_all_due(factory)
            assert not failed_update['readiness']['ready'] and failed_update['executed'] == 0

            # 갱신 성공 기록이 있어도 주문 종목 하나의 시가가 없으면 전 주문 대기.
            write(ok=True, stopped=None)
            with sqlite3.connect(path) as conn:
                conn.execute("UPDATE price_daily SET mkp=0 WHERE bas_dt='20261012' AND srtn_cd='000660'")
            missing = await rb.check_all_due(factory)
            assert missing['readiness']['ready'] and missing['executed'] == missing['checked'] == missing['errors'] == 0
            async with factory() as db:
                assert (await db.get(RebalanceRun, rid)).status == 'scheduled'
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
                assert (await rb.get_plan(db, uid)).last_auto_check_date == date(2026, 10, 8)

            # 빠진 시가 보완 뒤 같은 날 재시도: 12일 시가로 체결, 13일 확정.
            with sqlite3.connect(path) as conn:
                conn.execute("UPDATE price_daily SET mkp=900 WHERE bas_dt='20261012' AND srtn_cd='000660'")
            complete = await rb.check_all_due(factory)
            assert complete['executed'] == complete['checked'] == 1 and complete['errors'] == 0
            async with factory() as db:
                run = await db.get(RebalanceRun, rid)
                assert run.status == 'executed' and run.context['fill_date'] == '2026-10-12'
                assert run.context['confirmed_at'].startswith('2026-10-13')
                assert all(order['price'] == 900 for order in run.orders)
                count = await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid))
                assert count == 2
            again = await rb.check_all_due(factory)
            assert again['checked'] == again['executed'] == again['errors'] == 0
            async with factory() as db:
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == count
    asyncio.run(go())
