"""PAPER 계좌와 분리된 백테스트 전용 원장."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    BacktestAccount,
    BacktestSnapshot,
    Order,
    Portfolio,
    PORTFOLIO_BOOK_BACKTEST,
)
from app.services import trading_cost


KST = ZoneInfo("Asia/Seoul")
INITIAL_CASH = 100_000_000
SOURCE = "BACKTEST"


class BacktestTradeError(ValueError):
    """백테스트 주문 실패."""


def _price_unit(price: float) -> float:
    return float(int(price)) if price >= 1000 else round(price, 2)


async def get_account(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    lock: bool = True,
) -> BacktestAccount:
    """백테스트 계좌 생성 또는 조회."""

    stmt = (
        pg_insert(BacktestAccount)
        .values(
            user_id=user_id,
            initial_cash=INITIAL_CASH,
            cash=INITIAL_CASH,
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    await db.execute(stmt)

    query = select(BacktestAccount).where(
        BacktestAccount.user_id == user_id
    )
    if lock:
        query = query.with_for_update()

    account = (await db.execute(query)).scalar_one()
    return account


async def get_position(
    db: AsyncSession,
    user_id: uuid.UUID,
    symbol: str,
) -> Portfolio | None:
    return (
        await db.execute(
            select(Portfolio).where(
                Portfolio.user_id == user_id,
                Portfolio.symbol == symbol,
                Portfolio.book == PORTFOLIO_BOOK_BACKTEST,
            )
        )
    ).scalar_one_or_none()


async def reset_backtest(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> None:
    """백테스트 자료만 삭제하고 백테스트 현금만 초기화."""

    await db.execute(
        delete(Order).where(
            Order.user_id == user_id,
            Order.source == SOURCE,
        )
    )

    await db.execute(
        delete(Portfolio).where(
            Portfolio.user_id == user_id,
            Portfolio.book == PORTFOLIO_BOOK_BACKTEST,
        )
    )

    await db.execute(
        delete(BacktestSnapshot).where(
            BacktestSnapshot.user_id == user_id,
        )
    )

    account = await get_account(db, user_id)
    account.initial_cash = INITIAL_CASH
    account.cash = INITIAL_CASH

    await db.flush()


async def fill_stock_order(
    db: AsyncSession,
    user_id: uuid.UUID,
    info: dict,
    side: str,
    quantity: int,
    *,
    filled_at: datetime,
) -> dict:
    """PAPER 계좌를 거치지 않는 백테스트 전용 주식 체결."""

    side = (side or "").upper()
    if side not in ("BUY", "SELL"):
        raise BacktestTradeError("주문 방향은 BUY 또는 SELL이어야 합니다.")

    quantity = int(quantity)
    if quantity <= 0:
        raise BacktestTradeError("주문 수량은 1 이상이어야 합니다.")

    symbol = str(info["symbol"])
    name = str(info.get("name") or symbol)
    raw_price = float(info["price"])

    if raw_price <= 0:
        raise BacktestTradeError("체결 가격이 올바르지 않습니다.")

    price = _price_unit(raw_price)
    market = info.get("market") or trading_cost.market_of(symbol)

    try:
        costs = trading_cost.order_costs(
            side=side.lower(),
            price=price,
            quantity=quantity,
            when=filled_at.date(),
            market=market,
            is_etf=info.get(
                "is_etf",
                trading_cost.is_etf_name(name),
            ),
        )
    except trading_cost.UnsupportedMarketError as exc:
        raise BacktestTradeError(str(exc)) from exc

    account = await get_account(db, user_id)
    position = await get_position(db, user_id, symbol)

    if side == "BUY":
        if costs.net_amount > account.cash:
            raise BacktestTradeError(
                f"백테스트 현금 부족: 필요 {costs.net_amount:,.0f}원 / "
                f"보유 {account.cash:,.0f}원"
            )

        account.cash -= costs.net_amount

        if position is None:
            position = Portfolio(
                user_id=user_id,
                symbol=symbol,
                book=PORTFOLIO_BOOK_BACKTEST,
                name=name,
                quantity=quantity,
                avg_price=price,
            )
            db.add(position)
        else:
            old_qty = position.quantity
            new_qty = old_qty + quantity
            position.avg_price = (
                position.avg_price * old_qty + price * quantity
            ) / new_qty
            position.quantity = new_qty

    else:
        if position is None or position.quantity < quantity:
            raise BacktestTradeError("매도할 백테스트 보유 수량이 부족합니다.")

        position.quantity -= quantity
        account.cash += costs.net_amount

        if position.quantity == 0:
            await db.delete(position)

    order = Order(
        user_id=user_id,
        symbol=symbol,
        name=name,
        order_type=side.lower(),
        quantity=quantity,
        price=price,
        status="filled",
        broker="virtual",
        source=SOURCE,
        order_price=price,
        **trading_cost.order_fields(
            costs,
            price,
            quantity,
            filled_at=filled_at,
        ),
    )
    db.add(order)

    await db.flush()

    return {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "net_amount": costs.net_amount,
        "cash": account.cash,
    }


async def save_snapshot(
    db: AsyncSession,
    user_id: uuid.UUID,
    snap_date: date,
    prices: dict[str, float],
) -> dict:
    """해당 날짜의 종가로 백테스트 장부만 평가."""

    account = await get_account(db, user_id)

    positions = (
        await db.execute(
            select(Portfolio).where(
                Portfolio.user_id == user_id,
                Portfolio.book == PORTFOLIO_BOOK_BACKTEST,
            )
        )
    ).scalars().all()

    stock_value = 0.0
    for position in positions:
        price = prices.get(position.symbol)

        # 해당 날짜 봉이 없으면 마지막으로 확보한 종가를 사용한다.
        if price is None or price <= 0:
            price = position.avg_price

        stock_value += position.quantity * price

    cash = float(account.cash)
    equity = cash + stock_value

    previous = (
        await db.execute(
            select(BacktestSnapshot)
            .where(
                BacktestSnapshot.user_id == user_id,
                BacktestSnapshot.snap_date < snap_date,
            )
            .order_by(BacktestSnapshot.snap_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    previous_equity = (
        float(previous.total_equity)
        if previous is not None
        else None
    )

    daily_return = (
        equity / previous_equity - 1
        if previous_equity and previous_equity > 0
        else 0.0
    )

    values = {
        "user_id": user_id,
        "snap_date": snap_date,
        "cash": cash,
        "position_value": stock_value,
        "total_equity": equity,
        "daily_return": daily_return,
        "position_count": len(positions),
        "stock_value": stock_value,
    }

    stmt = (
        pg_insert(BacktestSnapshot)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["user_id", "snap_date"],
            set_={
                key: value
                for key, value in values.items()
                if key not in ("user_id", "snap_date")
            },
        )
    )

    await db.execute(stmt)

    return values