"""#79: 수동/일별 판단 통일, 현금 이연, 목표 비중 예약과 시간 순서 보호."""
import asyncio
import sqlite3
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, update

from app.models import RebalanceRun, PaperAccount, Portfolio, CashflowEvent, Order
from app.routes import rebalance as routes
from app.services import rebalance as rb, rebalance_settlement as st
from tests.test_rebalance_policy import scenario, needs_db, target
from tests.test_rebalance_daily import clock, ready_data  # noqa: F401
from tests.test_rebalance_settlement import SYMBOLS, insert_open, ready, queue

pytestmark = [needs_db, pytest.mark.usefixtures('rebalance_db_schema')]


async def no_audit(*args, **kwargs):
    pass


async def stamp_account_history(db, uid, day):
    """시험 DB의 실제 벽시계 대신 시나리오 거래 시각을 명시한다."""
    stamp = datetime(2026, 10, day, 16, tzinfo=rb.KST)
    await db.flush()
    for model, field in [(PaperAccount, 'updated_at'), (Portfolio, 'updated_at'),
                         (Order, 'created_at'), (CashflowEvent, 'created_at')]:
        await db.execute(update(model).where(model.user_id == uid).values(**{field: stamp}))
    await db.flush()


def forbid_quotes(monkeypatch):
    async def fail(*args, **kwargs):
        raise AssertionError('리밸런싱은 외부 현재가를 조회하지 않음')
    monkeypatch.setattr(rb.pt, 'resolve_stock', fail)


def test_manual_preview_execution_use_close_and_only_reserve(monkeypatch, clock, ready_data):
    monkeypatch.setattr(routes, 'audit', no_audit)
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            forbid_quotes(monkeypatch)
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                plan.targets = [target(SYMBOLS[0], 40), target(SYMBOLS[1], 40)]
                await db.commit()
                user = {'id': str(uid)}
                preview = await routes.preview(user, db)
                assert preview['snapshot']['valuation_date'] == '2026-10-02'
                assert preview['snapshot']['price_basis'] == 'previous_close'
                assert all(o['price'] == 1000 for o in preview['orders'])
                result = await routes.execute(routes.ExecuteBody(), user, db)
                assert result['status'] == 'scheduled'
                assert result['context']['scheduled_for'] == '2026-10-07'
                assert result['context']['reservation_policy'] == 'target_weights_v1'
                assert (await rb.pt.get_account(db, uid)).cash == 200000
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
                with pytest.raises(HTTPException) as error:
                    await routes.execute(routes.ExecuteBody(), user, db)
                assert error.value.status_code == 400
    asyncio.run(go())


@pytest.mark.parametrize('condition', ['before_update', 'closed', 'failed', 'missing_close'])
def test_manual_routes_wait_without_fallback(monkeypatch, clock, ready_data, condition):
    if condition == 'before_update':
        clock.current = datetime(2026, 10, 6, 12, tzinfo=rb.KST)
    elif condition == 'closed':
        clock.current = datetime(2026, 10, 9, 14, tzinfo=rb.KST)
    elif condition == 'failed':
        ready_data[2](ok=False)
    else:
        with sqlite3.connect(ready_data[0]) as conn:
            conn.execute("DELETE FROM price_daily WHERE srtn_cd='005930'")
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            forbid_quotes(monkeypatch)
            async with factory() as db:
                user = {'id': str(uid)}
                status = await routes.status(user, db)
                assert status['snapshot'] is None and status['valuation_error']
                for call in [lambda: routes.preview(user, db),
                             lambda: routes.execute(routes.ExecuteBody(), user, db)]:
                    with pytest.raises(HTTPException):
                        await call()
                result = await rb.record_cashflow(db, uid, 'DIVIDEND', 200000)
                assert result['check_deferred'] and result['run'] is None
                await db.commit()
                assert (await rb.pt.get_account(db, uid)).cash == 400000
                assert await db.scalar(select(func.count(RebalanceRun.id)).where(RebalanceRun.user_id == uid)) == 0
    asyncio.run(go())


def test_manual_check_shares_daily_gate_and_defers_later_events(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            forbid_quotes(monkeypatch)
            async with factory() as db:
                first = await routes.check({'id':str(uid)}, db)
                assert first['checked'] and first['run_id'] is None
                await rb.record_cashflow(db, uid, 'DEPOSIT', 100000)
                await rb.record_cashflow(db, uid, 'DIVIDEND', 100000)
                await db.commit()
                again = await routes.check({'id':str(uid)}, db)
                assert again['already_processed']
                plan = await rb.get_plan(db, uid)
                assert not (await rb.check_daily(db, uid, plan))['checked']
                assert await db.scalar(select(func.count(RebalanceRun.id)).where(RebalanceRun.user_id == uid)) == 0
            # 다음 거래일의 갱신이 끝나야 누적 이벤트를 판단한다.
            insert_open(ready_data[0], day='20261006')
            clock.current = datetime(2026, 10, 7, 13, 30, tzinfo=rb.KST)
            ready_data[2](started_at='2026-10-07T12:30:01+09:00', finished_at='2026-10-07T13:00:00+09:00',
                          after={'price_max':'20261006'})
            async with factory() as db:
                result = await routes.check({'id':str(uid)}, db)
                assert result['checked'] and result['triggers'] == ['CASHFLOW']
                run = await db.get(RebalanceRun, uuid.UUID(result['run_id']))
                assert run.plan_kind == 'buy_only' and run.context['valuation_date'] == '2026-10-06'
    asyncio.run(go())


@pytest.mark.parametrize('change', ['deposit', 'withdraw', 'trade_resolves'])
def test_pre_execution_changes_recalculate_or_cancel(monkeypatch, clock, ready_data, change):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                await stamp_account_history(db, uid, 6)
                plan, run = await queue(db, uid)
                original_orders = list(run.orders)
                if change == 'trade_resolves':
                    await rb.pt.stock_order(db, uid, SYMBOLS[0], 'SELL', 200)
                    await rb.pt.stock_order(db, uid, SYMBOLS[1], 'BUY', 200)
                else:
                    await rb.record_cashflow(db, uid, 'DEPOSIT' if change == 'deposit' else 'WITHDRAW', 100000)
                await stamp_account_history(db, uid, 6)
                await db.commit()
                before = await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid))
                insert_open(ready_data[0], price=1000)
                forbid_quotes(monkeypatch)
                result = await st.settle(db, uid, plan, ready(clock))
                if change == 'trade_resolves':
                    assert result.status == 'cancelled'
                    assert result.context['cancel_reason'] == 'condition_resolved'
                    assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == before
                else:
                    assert result.status == 'executed'
                    assert result.context['indicative_orders'] == original_orders
                    assert [o['quantity'] for o in result.orders] != [o['quantity'] for o in original_orders]
                    assert (await rb.pt.get_account(db, uid)).cash >= 0
                await db.commit()
                assert await st.settle(db, uid, plan, ready(clock)) is None
    asyncio.run(go())


@pytest.mark.parametrize('change_day', [7, 8])
def test_execution_day_or_later_event_never_enters_historical_fill(monkeypatch, clock, ready_data, change_day):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                await stamp_account_history(db, uid, 6)
                plan, run = await queue(db, uid)
                await rb.record_cashflow(db, uid, 'DEPOSIT', 100000)
                await stamp_account_history(db, uid, change_day)
                await db.commit()
                insert_open(ready_data[0])
                result = await st.settle(db, uid, plan, ready(clock))
                assert result.status == 'scheduled' and result.context['review_required']
                assert (await rb.pt.get_account(db, uid)).cash == 300000
                assert sum(e.remaining_budget for e in await rb.pending_cashflows(db, uid)) == 80000
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
    asyncio.run(go())


def test_old_reservation_keeps_approved_quantities(monkeypatch, clock, ready_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan, run = await queue(db, uid)
                run.context = {k:v for k,v in run.context.items() if k != 'reservation_policy'}
                quantities = [o['quantity'] for o in run.orders]
                await db.commit()
                insert_open(ready_data[0])
                result = await st.settle(db, uid, plan, ready(clock))
                assert result.status == 'executed'
                assert [o['quantity'] for o in result.orders] == quantities
    asyncio.run(go())


@pytest.mark.parametrize('missing', [False, True])
def test_protected_holdings_display_uses_close_without_blocking_managed_plan(monkeypatch, clock, ready_data, missing):
    if missing:
        with sqlite3.connect(ready_data[0]) as conn:
            conn.execute("DELETE FROM price_daily WHERE srtn_cd='000660'")
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            forbid_quotes(monkeypatch)
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                plan.targets = [target(SYMBOLS[0], 75)]
                await db.commit()
                result = await routes.status({'id':str(uid)}, db)
                snap = result['snapshot']
                assert snap['total_asset'] == 800000
                assert snap['excluded_prices_unavailable'] == ([SYMBOLS[1]] if missing else [])
                if not missing:
                    assert snap['excluded_asset'] == 200000
                    assert snap['rows'][0]['current_amount'] == 200000
                assert result['valuation_error'] is None
    asyncio.run(go())
