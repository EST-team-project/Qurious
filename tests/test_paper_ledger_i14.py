"""I14 회귀 시험 — 자동매매 매수가 모의계좌(`paper_accounts`) 현금을 줄이는가.

무엇이 틀렸었나 —
자동매매는 현금을 `quant_virtual_accounts`(1천만 원)에서 빼고 보유는 공용 `portfolio` 에
넣었다. 모의투자 화면은 `paper_accounts`(1억 원) 현금 + `portfolio` 보유로 총자산을 세므로
**산 주식 값이 그대로 없는 수익**이 됐다(IA v0.2: 3건 뒤 +3,194,750원 · +3.19%).

그래서 여기서 지키는 불변식은 하나다 —
**체결가로 평가하면 총자산 = 초기 현금 − 거래비용.** 매수만으로 총자산이 늘면 안 된다.
화면이 쓰는 식(`account_snapshot`: 현금 + 보유 평가)을 그대로 따라 센다.

왜 진짜 Postgres 인가 —
장부 합치기의 핵심은 수동 주문과 자동매매가 **같은 행을 `FOR UPDATE` 로 잠그는** 것이다.
SQLite 는 `FOR UPDATE` 를 무시하고, 모델이 `PG_UUID`·`ARRAY` 를 쓴다. 가짜 세션으로는
"같은 행을 본다" 를 확인할 수 없다.

돌리는 법 (DB 주소가 없으면 DB 시험은 **건너뛴다** — 정적 가드 하나만 돈다)::

    docker run -d --name qurious-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 pgvector/pgvector:pg16
    QURIOUS_TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:55432/postgres \\
        python -m pytest tests/test_paper_ledger_i14.py
    docker stop qurious-test-pg && docker rm qurious-test-pg

⚠️ 시험은 그 DB 에 `users`·`paper_accounts`·`portfolio`·`orders`·`quant_virtual_accounts`
   와 코인·대체자산 표 넷, 모두 아홉 표를 **지우고 다시 만든다.** 개발 DB 주소를 넣지 않는다.
"""
from __future__ import annotations

import inspect
import os
import uuid

import pytest
from sqlalchemy import func, select

from app.models import (
    AlternativeOrder,
    AlternativePosition,
    Base,
    CryptoHolding,
    CryptoOrder,
    Order,
    PAPER_INITIAL_CASH,
    PaperAccount,
    Portfolio,
    QuantVirtualAccount,
    User,
)
from app.services import auto_trade, paper_trading

DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(
    not DB_URL, reason="QURIOUS_TEST_DATABASE_URL 이 없다 — 파일 머리말의 docker 명령으로 띄운다")

# `reset_account` 가 코인·대체자산 표까지 지우므로 그 넷도 만든다.
TABLES = [User.__table__, PaperAccount.__table__, Portfolio.__table__, Order.__table__,
          QuantVirtualAccount.__table__, CryptoHolding.__table__, CryptoOrder.__table__,
          AlternativePosition.__table__, AlternativeOrder.__table__]

SYMBOL, NAME, PRICE = "005930.KS", "삼성전자", 70_000.0


# ── 0. 정적 가드 (DB 없이 돈다) ──────────────────────────────────────────
def test_auto_trade_no_longer_uses_the_second_cash_ledger():
    """자동매매 코드가 옛 현금 장부를 다시 읽거나 쓰면 I14 가 되살아난다."""
    src = inspect.getsource(auto_trade)
    code = src.split('"""', 2)[2]                 # 모듈 머리말(설명)은 빼고 코드만 본다
    assert "QuantVirtualAccount" not in code
    assert "paper_trading.get_account(db, user_id, lock=True)" in code


# ── DB 준비 ──────────────────────────────────────────────────────────────
@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=TABLES))
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=TABLES))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        uid = uuid.uuid4()
        session.add(User(id=uid, name="i14", email=f"{uid.hex}@test.local",
                         password_hash="x", client_id=uid.hex))
        await session.commit()
        yield session, uid
    await engine.dispose()


async def _cash(session, uid) -> float:
    session.expire_all()
    return float((await paper_trading.get_account(session, uid)).cash)


async def _equity_at_cost(session, uid) -> float:
    """화면 식(`account_snapshot`) 그대로 — 현금 + 보유 평가. 평가가는 체결가로 둔다."""
    cash = await _cash(session, uid)
    rows = (await session.execute(select(Portfolio).where(Portfolio.user_id == uid))).scalars()
    return cash + sum(p.quantity * PRICE for p in rows)


async def _total_cost(session, uid) -> float:
    q = select(func.coalesce(func.sum(Order.commission + Order.tax_transfer
                                      + Order.tax_rural + Order.fee_clearing), 0.0)
               ).where(Order.user_id == uid)
    return float((await session.execute(q)).scalar_one())


# ── 1. 핵심 — 매수가 모의계좌 현금을 줄인다 ──────────────────────────────
@needs_db
@pytest.mark.anyio
async def test_auto_buy_debits_paper_cash_and_creates_no_phantom_profit(db):
    session, uid = db
    trade = await auto_trade._execute_virtual_trade(
        session, uid, SYMBOL, NAME, "buy", PRICE, 3, "I14 시험")
    assert trade["status"] == "filled" and trade["quantity"] == 3

    cash = await _cash(session, uid)
    assert cash == pytest.approx(PAPER_INITIAL_CASH - trade["cost"]["net_amount"])
    assert cash < PAPER_INITIAL_CASH - 3 * PRICE + 1          # 체결대금 이상 빠졌다
    assert trade["cash_balance"] == pytest.approx(cash)        # 로그와 장부가 같은 값

    # 총자산(체결가 평가) = 초기 현금 − 비용. 옛 코드는 여기서 +210,000(+0.21%)이 났다.
    equity = await _equity_at_cost(session, uid)
    assert equity == pytest.approx(PAPER_INITIAL_CASH - await _total_cost(session, uid))
    assert equity <= PAPER_INITIAL_CASH

    # 두 번째 현금 장부에는 아무것도 생기지 않는다
    n = (await session.execute(select(func.count()).select_from(QuantVirtualAccount))).scalar_one()
    assert n == 0


@needs_db
@pytest.mark.anyio
async def test_auto_sell_credits_the_same_ledger(db):
    session, uid = db
    await auto_trade._execute_virtual_trade(session, uid, SYMBOL, NAME, "buy", PRICE, 3, "매수")
    before = await _cash(session, uid)
    trade = await auto_trade._execute_virtual_trade(session, uid, SYMBOL, NAME, "sell", PRICE, 1, "매도")
    assert trade["status"] == "filled"
    assert await _cash(session, uid) == pytest.approx(before + trade["cost"]["net_amount"])
    pos = (await session.execute(select(Portfolio).where(Portfolio.user_id == uid))).scalar_one()
    assert pos.quantity == 2
    equity = await _equity_at_cost(session, uid)
    assert equity == pytest.approx(PAPER_INITIAL_CASH - await _total_cost(session, uid))


# ── 2. 수동 주문과 자동매매가 **같은 현금**을 본다 ─────────────────────
@needs_db
@pytest.mark.anyio
async def test_auto_trade_sees_cash_spent_by_manual_orders(db):
    """수동으로 현금을 거의 다 쓴 뒤 자동매매가 3주를 사려 하면 1주만 체결돼야 한다.

    옛 코드는 1천만 원짜리 다른 장부를 봐서 3주를 다 샀다.
    """
    session, uid = db
    await paper_trading.apply_cash(session, uid, -(PAPER_INITIAL_CASH - 100_000))
    await session.commit()
    trade = await auto_trade._execute_virtual_trade(
        session, uid, SYMBOL, NAME, "buy", PRICE, 3, "잔고 부족 시험")
    assert trade["status"] == "filled" and trade["quantity"] == 1
    assert await _cash(session, uid) == pytest.approx(100_000 - trade["cost"]["net_amount"])
    assert await _cash(session, uid) >= 0


@needs_db
@pytest.mark.anyio
async def test_auto_buy_skips_when_paper_cash_is_empty(db):
    session, uid = db
    await paper_trading.apply_cash(session, uid, -PAPER_INITIAL_CASH)
    await session.commit()
    trade = await auto_trade._execute_virtual_trade(session, uid, SYMBOL, NAME, "buy", PRICE, 1, "빈 계좌")
    assert trade["status"] == "skipped" and trade["quantity"] == 0
    assert await _cash(session, uid) == 0
    n = (await session.execute(select(func.count()).select_from(Portfolio))).scalar_one()
    assert n == 0


# ── 3. 직접매매(/api/orders) — 보유 없이 팔면 없는 돈이 생기던 구멍 ──────
@needs_db
@pytest.mark.anyio
async def test_manual_virtual_sell_beyond_holdings_is_rejected(db):
    """옛 코드는 보유 0주에서 1주를 팔아도 현금이 늘었다(`_apply_portfolio` 는 보유가 없으면
    아무것도 안 하는데 현금은 먼저 더했다). 같은 불변식(현금 ↔ 보유)의 구멍이다."""
    from fastapi import HTTPException
    from app.routes import stocks

    session, uid = db
    user = {"id": str(uid)}
    body = lambda side, q: stocks.OrderBody(                              # noqa: E731
        symbol=SYMBOL, name=NAME, order_type=side, quantity=q, price=PRICE)

    with pytest.raises(HTTPException) as e:
        await stocks.place_order(body("sell", 1), user=user, db=session)
    assert e.value.status_code == 400
    await session.rollback()
    assert await _cash(session, uid) == PAPER_INITIAL_CASH                # 한 푼도 안 늘었다

    await stocks.place_order(body("buy", 2), user=user, db=session)
    with pytest.raises(HTTPException):
        await stocks.place_order(body("sell", 3), user=user, db=session)  # 보유보다 많이
    await session.rollback()
    await stocks.place_order(body("sell", 2), user=user, db=session)      # 보유만큼은 된다
    equity = await _equity_at_cost(session, uid)
    assert equity == pytest.approx(PAPER_INITIAL_CASH - await _total_cost(session, uid))


# ── 4. 초기화는 두 경로를 함께 되돌린다 ─────────────────────────────────
@needs_db
@pytest.mark.anyio
async def test_reset_restores_a_consistent_ledger_after_auto_trades(db):
    session, uid = db
    await auto_trade._execute_virtual_trade(session, uid, SYMBOL, NAME, "buy", PRICE, 3, "매수")
    await paper_trading.reset_account(session, uid)
    await session.commit()
    assert await _cash(session, uid) == PAPER_INITIAL_CASH
    assert await _equity_at_cost(session, uid) == PAPER_INITIAL_CASH
