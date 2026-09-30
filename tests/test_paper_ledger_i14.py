"""I14 회귀 시험 — 자동매매가 모의투자 화면에 「없는 수익」 을 만들지 않는가.

무엇이 틀렸었나 —
자동매매는 현금을 `quant_virtual_accounts`(1천만 원)에서 빼고 보유는 공용 `portfolio` 에
넣었다. 모의투자 화면은 `paper_accounts`(1억 원) 현금 + `portfolio` 보유로 총자산을 세므로
**산 주식 값이 그대로 없는 수익**이 됐다(IA v0.2: 3건 뒤 +3,194,750원 · +3.19%).

어떻게 고쳤나 — 두 번 고쳤다 —
2026-09-28 Qurious 는 현금을 `paper_accounts` 하나로 합쳤다. 2026-09-30 강사님 원본(2026-09-29)을
기초 코드로 받으며 **장부를 둘로 나누는 방식**으로 바꿨다: 자동매매 = `quant_virtual_accounts` 현금 +
`portfolio.book = QUANT` / 모의투자 · 직접매매 = `paper_accounts` 현금 + `book = PAPER`.

그래서 여기서 지키는 불변식 —
1. **자동매매는 PAPER 장부를 건드리지 않는다** — 체결가로 평가한 모의투자 총자산 = 초기 현금 − (PAPER 주문 비용).
2. **QUANT 장부도 제 식이 맞는다** — 체결가로 평가한 자동매매 총자산 = 1천만 원 − (QUANT 주문 비용).
3. 한 장부의 보유를 다른 장부의 주문으로 팔 수 없다(직접매매로 자동매매 보유를 팔면 없는 돈이 생긴다).
화면이 쓰는 식(`account_snapshot`: 현금 + 보유 평가)을 장부별로 그대로 따라 센다.

왜 진짜 Postgres 인가 —
자동매매 체결은 계좌 행을 `FOR UPDATE` 로 잠그고, 모델이 `PG_UUID` · `ARRAY` 를 쓴다.
SQLite 는 `FOR UPDATE` 를 무시한다 — 가짜 세션으로는 잠금과 장부 구분을 확인할 수 없다.

돌리는 법 (DB 주소가 없으면 DB 시험은 **건너뛴다** — 정적 가드 둘만 돈다)::

    docker run -d --name qurious-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 pgvector/pgvector:pg16
    QURIOUS_TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:55432/postgres \\
        python -m pytest tests/test_paper_ledger_i14.py
    docker stop qurious-test-pg && docker rm qurious-test-pg

⚠️ 시험은 그 DB 에 `users` · `paper_accounts` · `portfolio` · `orders` · `quant_virtual_accounts`
   와 코인 · 대체자산 표 넷, 모두 아홉 표를 **지우고 다시 만든다.** 개발 DB 주소를 넣지 않는다.
"""
from __future__ import annotations

import inspect
import os
import pathlib
import re
import uuid

import pytest
from sqlalchemy import func, select, update

from app.models import (
    AlternativeOrder,
    AlternativePosition,
    Base,
    CryptoHolding,
    CryptoOrder,
    Order,
    PAPER_INITIAL_CASH,
    PORTFOLIO_BOOK_PAPER,
    PORTFOLIO_BOOK_QUANT,
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
QUANT_INITIAL = float(auto_trade._INITIAL_CAPITAL)
ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── 0. 정적 가드 (DB 없이 돈다) ──────────────────────────────────────────
def test_auto_trade_touches_only_the_quant_ledger():
    """자동매매 코드가 모의투자 장부(PaperAccount · book=PAPER)를 읽거나 쓰면 I14 가 되살아난다."""
    src = inspect.getsource(auto_trade)
    code = src.split('"""', 2)[2]                 # 모듈 머리말(설명)은 빼고 코드만 본다
    assert "paper_trading" not in code and "PaperAccount" not in code
    assert "PORTFOLIO_BOOK_PAPER" not in code
    assert "book=PORTFOLIO_BOOK_QUANT" in code    # 새 보유는 QUANT 장부로 들어간다
    assert ".with_for_update()" in code          # 현금 행을 잠그고 쓴다


def test_every_portfolio_query_names_a_book():
    """보유를 읽거나 지우는 곳마다 장부(book)를 적는다 — 빠지면 두 장부가 섞인다.

    같은 종목이 PAPER · QUANT 두 줄일 수 있어, 장부 없이 읽으면 한쪽 보유를 다른 쪽 주문으로
    팔거나(없는 돈) 두 줄이 걸려 오류가 난다. 2026-09-30 병합에서 직접매매 매도 검사가 그랬다.
    """
    빠짐 = []
    for p in (ROOT / "app").rglob("*.py"):
        lines = p.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if re.search(r"(select|delete)\(Portfolio\b", line) and "book" not in " ".join(lines[i:i + 4]):
                빠짐.append(f"{p.relative_to(ROOT).as_posix()}:{i + 1}")
    assert not 빠짐, "장부(book) 조건 없는 보유 조회: " + ", ".join(빠짐)


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


async def _paper_cash(session, uid) -> float:
    session.expire_all()
    return float((await paper_trading.get_account(session, uid)).cash)


async def _quant_cash(session, uid) -> float:
    session.expire_all()
    acc = (await session.execute(select(QuantVirtualAccount).where(QuantVirtualAccount.user_id == uid))).scalar_one_or_none()
    return float(acc.cash_balance) if acc else QUANT_INITIAL


async def _holdings(session, uid, book: str) -> dict[str, int]:
    rows = (await session.execute(
        select(Portfolio).where(Portfolio.user_id == uid, Portfolio.book == book))).scalars()
    return {p.symbol: p.quantity for p in rows}


async def _equity_at_cost(session, uid, book: str) -> float:
    """화면 식(`account_snapshot`) 그대로 — 장부별 현금 + 보유 평가. 평가가는 체결가로 둔다."""
    cash = await (_paper_cash if book == PORTFOLIO_BOOK_PAPER else _quant_cash)(session, uid)
    return cash + sum(q * PRICE for q in (await _holdings(session, uid, book)).values())


async def _total_cost(session, uid, source: str) -> float:
    q = select(func.coalesce(func.sum(Order.commission + Order.tax_transfer
                                      + Order.tax_rural + Order.fee_clearing), 0.0)
               ).where(Order.user_id == uid, Order.source == source)
    return float((await session.execute(q)).scalar_one())


# ── 1. 핵심 — 자동매매 매수가 모의투자 총자산을 바꾸지 않는다 ────────────
@needs_db
@pytest.mark.anyio
async def test_auto_buy_leaves_paper_equity_and_debits_quant_cash(db):
    session, uid = db
    trade = await auto_trade._execute_virtual_trade(
        session, uid, SYMBOL, NAME, "buy", PRICE, 3, "I14 시험")
    assert trade["status"] == "filled" and trade["quantity"] == 3

    # 모의투자 장부: 현금도 보유도 그대로 — 옛 코드는 여기서 +210,000(+0.21%)이 났다.
    assert await _paper_cash(session, uid) == PAPER_INITIAL_CASH
    assert await _holdings(session, uid, PORTFOLIO_BOOK_PAPER) == {}
    assert await _equity_at_cost(session, uid, PORTFOLIO_BOOK_PAPER) == PAPER_INITIAL_CASH

    # 자동매매 장부: 정산금액(체결대금 + 비용)만큼 현금이 빠지고, 체결가 평가 총자산 = 초기 − 비용
    cash = await _quant_cash(session, uid)
    assert cash == pytest.approx(QUANT_INITIAL - trade["cost"]["net_amount"])
    assert cash < QUANT_INITIAL - 3 * PRICE + 1               # 체결대금 이상 빠졌다
    assert trade["cash_balance"] == pytest.approx(cash)        # 로그와 장부가 같은 값
    assert await _holdings(session, uid, PORTFOLIO_BOOK_QUANT) == {SYMBOL: 3}
    equity = await _equity_at_cost(session, uid, PORTFOLIO_BOOK_QUANT)
    assert equity == pytest.approx(QUANT_INITIAL - await _total_cost(session, uid, "QUANT"))
    assert equity <= QUANT_INITIAL


@needs_db
@pytest.mark.anyio
async def test_auto_sell_credits_the_quant_ledger(db):
    session, uid = db
    await auto_trade._execute_virtual_trade(session, uid, SYMBOL, NAME, "buy", PRICE, 3, "매수")
    before = await _quant_cash(session, uid)
    trade = await auto_trade._execute_virtual_trade(session, uid, SYMBOL, NAME, "sell", PRICE, 1, "매도")
    assert trade["status"] == "filled"
    assert await _quant_cash(session, uid) == pytest.approx(before + trade["cost"]["net_amount"])
    assert await _holdings(session, uid, PORTFOLIO_BOOK_QUANT) == {SYMBOL: 2}
    equity = await _equity_at_cost(session, uid, PORTFOLIO_BOOK_QUANT)
    assert equity == pytest.approx(QUANT_INITIAL - await _total_cost(session, uid, "QUANT"))
    assert await _paper_cash(session, uid) == PAPER_INITIAL_CASH


# ── 2. 두 장부의 현금은 서로 기대지 않는다 ──────────────────────────────
@needs_db
@pytest.mark.anyio
async def test_auto_trade_uses_its_own_cash_not_paper_cash(db):
    """수동으로 모의투자 현금을 거의 다 써도 자동매매는 자기 현금(1천만 원)으로 3주를 산다.

    (2026-09-28 판은 반대였다 — 현금을 합쳐서 1주만 체결됐다. 장부를 나눈 지금은 이것이 맞는 동작이다.)
    """
    session, uid = db
    await paper_trading.apply_cash(session, uid, -(PAPER_INITIAL_CASH - 100_000))
    await session.commit()
    trade = await auto_trade._execute_virtual_trade(
        session, uid, SYMBOL, NAME, "buy", PRICE, 3, "장부 분리 시험")
    assert trade["status"] == "filled" and trade["quantity"] == 3
    assert await _paper_cash(session, uid) == pytest.approx(100_000)   # 모의투자 현금은 그대로
    assert await _quant_cash(session, uid) == pytest.approx(QUANT_INITIAL - trade["cost"]["net_amount"])


@needs_db
@pytest.mark.anyio
async def test_auto_buy_skips_when_quant_cash_is_empty(db):
    session, uid = db
    await auto_trade._execute_virtual_trade(session, uid, SYMBOL, NAME, "buy", PRICE, 1, "계좌 만들기")
    await session.execute(update(QuantVirtualAccount).where(QuantVirtualAccount.user_id == uid)
                          .values(cash_balance=0.0))
    await session.commit()
    trade = await auto_trade._execute_virtual_trade(session, uid, "000660.KS", "SK하이닉스", "buy", PRICE, 1, "빈 계좌")
    assert trade["status"] == "skipped" and trade["quantity"] == 0
    assert await _quant_cash(session, uid) == 0
    assert "000660.KS" not in await _holdings(session, uid, PORTFOLIO_BOOK_QUANT)


# ── 3. 직접매매(/api/orders) — 보유 없이 팔면 없는 돈이 생기던 구멍 ──────
def _order(stocks, side, q):
    return stocks.OrderBody(symbol=SYMBOL, name=NAME, order_type=side, quantity=q, price=PRICE)


@needs_db
@pytest.mark.anyio
async def test_manual_virtual_sell_beyond_holdings_is_rejected(db):
    """옛 코드는 보유 0주에서 1주를 팔아도 현금이 늘었다(`_apply_portfolio` 는 보유가 없으면
    아무것도 안 하는데 현금은 먼저 더했다). 같은 불변식(현금 ↔ 보유)의 구멍이다."""
    from fastapi import HTTPException
    from app.routes import stocks

    session, uid = db
    user = {"id": str(uid)}

    with pytest.raises(HTTPException) as e:
        await stocks.place_order(_order(stocks, "sell", 1), user=user, db=session)
    assert e.value.status_code == 400
    await session.rollback()
    assert await _paper_cash(session, uid) == PAPER_INITIAL_CASH          # 한 푼도 안 늘었다

    await stocks.place_order(_order(stocks, "buy", 2), user=user, db=session)
    with pytest.raises(HTTPException):
        await stocks.place_order(_order(stocks, "sell", 3), user=user, db=session)  # 보유보다 많이
    await session.rollback()
    await stocks.place_order(_order(stocks, "sell", 2), user=user, db=session)      # 보유만큼은 된다
    equity = await _equity_at_cost(session, uid, PORTFOLIO_BOOK_PAPER)
    assert equity == pytest.approx(PAPER_INITIAL_CASH - await _total_cost(session, uid, "WEB"))


@needs_db
@pytest.mark.anyio
async def test_manual_sell_cannot_sell_quant_holdings(db):
    """자동매매가 산 3주(QUANT)를 직접매매 가상 매도(PAPER)로 팔 수 없다 — 팔리면 없는 돈이 생긴다."""
    from fastapi import HTTPException
    from app.routes import stocks

    session, uid = db
    await auto_trade._execute_virtual_trade(session, uid, SYMBOL, NAME, "buy", PRICE, 3, "자동 매수")
    with pytest.raises(HTTPException) as e:
        await stocks.place_order(_order(stocks, "sell", 1), user={"id": str(uid)}, db=session)
    assert e.value.status_code == 400
    await session.rollback()
    assert await _paper_cash(session, uid) == PAPER_INITIAL_CASH
    assert await _holdings(session, uid, PORTFOLIO_BOOK_QUANT) == {SYMBOL: 3}


# ── 4. 모의투자 초기화는 모의투자 장부만 되돌린다 ───────────────────────
@needs_db
@pytest.mark.anyio
async def test_reset_restores_paper_and_leaves_the_quant_book(db):
    from app.routes import stocks

    session, uid = db
    await stocks.place_order(_order(stocks, "buy", 2), user={"id": str(uid)}, db=session)
    await auto_trade._execute_virtual_trade(session, uid, SYMBOL, NAME, "buy", PRICE, 3, "자동 매수")
    await paper_trading.reset_account(session, uid)
    await session.commit()
    assert await _paper_cash(session, uid) == PAPER_INITIAL_CASH
    assert await _equity_at_cost(session, uid, PORTFOLIO_BOOK_PAPER) == PAPER_INITIAL_CASH
    assert await _holdings(session, uid, PORTFOLIO_BOOK_QUANT) == {SYMBOL: 3}   # 자동매매 장부는 그대로
