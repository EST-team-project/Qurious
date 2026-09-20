"""`fill_sync.sync_daily_fills` 를 실제 Postgres 로 검증한다.

가짜 증권사가 정해 둔 체결을 돌려주고, 그것이 `orders` · `order_fills` 에 제대로
들어가는지 본다. 확인하는 것은 네 가지다.

  1. 취소·미체결은 건너뛴다
  2. 증권사 제비용과 우리 요율표가 **맞으면** `cost_basis="broker"`,
     **어긋나면** `estimated` 로 두고 차액을 보고한다
  3. 같은 체결을 두 번 동기화해도 행이 늘지 않는다 (증권사 주문번호로 갱신)
  4. `net_amount = 체결금액 ± 세목합` 이라는 불변식이 항상 성립한다

쓰는 법 (임시 Postgres 를 띄워 두고)
    docker run -d --name qurious-fillsync-test -e POSTGRES_PASSWORD=test         -e POSTGRES_DB=qurious -p 55433:5432 pgvector/pgvector:pg16
    PYTHONPATH=. python scripts/verify_fill_sync.py
    docker stop qurious-fillsync-test && docker rm qurious-fillsync-test

DSN 은 환경변수 `FILL_SYNC_TEST_DSN` 으로 바꿀 수 있다.
"""
import asyncio, os, sys, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, text

from app.models.base import Base
from app.models.trading import Order, OrderFill
from app.models.user import User
from app.services.brokers.base import BrokerClient, FillInfo
from app.services import fill_sync

DSN = os.getenv("FILL_SYNC_TEST_DSN",
                "postgresql+asyncpg://postgres:test@localhost:55433/qurious")


class FakeBroker(BrokerClient):
    """정해 둔 체결만 돌려주는 가짜 증권사."""
    def __init__(self, fills): self.fills = fills
    async def get_token(self): ...
    async def get_price(self, symbol): ...
    async def get_balance(self, account_no): ...
    async def place_order(self, *a, **k): ...
    async def get_daily_ohlcv(self, *a, **k): ...
    async def get_daily_fills(self, account_no, start, end, symbol=None):
        return self.fills


def mk(odno, side, qty, price, fees, *, symbol="005930", name="삼성전자",
       date="20260918", cancelled=False, filled=None):
    filled = qty if filled is None else filled
    return FillInfo(
        broker_order_id=odno, symbol=symbol, name=name, side=side,
        order_date=date, order_time="091530", order_quantity=qty, order_price=price,
        filled_quantity=filled, avg_fill_price=price, gross_amount=price * filled,
        total_fees=fees, cancelled=cancelled, exchange="KRX", raw={"odno": odno},
    )


async def main():
    engine = create_async_engine(DSN, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    uid = uuid.uuid4()
    async with Session() as db:
        # 여러 번 돌려도 부딪히지 않게 계정 식별자를 매번 새로 만든다
        tag = uid.hex[:12]
        db.add(User(id=uid, email=f"verify-{tag}@example.invalid", password_hash="x",
                    name="fill_sync 검증", client_id=f"verify-{tag}"))
        await db.commit()

    from app.services import trading_cost
    # 우리 요율표가 계산하는 값을 그대로 fees 로 주면 "일치" 여야 한다
    est_buy = trading_cost.order_costs("buy", 70000, 10, "20260918", "KOSPI")
    est_sell = trading_cost.order_costs("sell", 71000, 10, "20260918", "KOSPI")
    print(f"  요율표 추정 — 매수 {est_buy.total_cost:.2f}원 · 매도 {est_sell.total_cost:.2f}원")

    fills = [
        mk("0001", "buy", 10, 70000, est_buy.total_cost),          # 일치
        mk("0002", "sell", 10, 71000, est_sell.total_cost + 500),  # 불일치(500원 차이)
        mk("0003", "buy", 5, 50000, None),                         # 제비용 미제공
        mk("0004", "buy", 3, 60000, 100.0, cancelled=True),        # 취소
        mk("0005", "buy", 3, 60000, 100.0, filled=0),              # 미체결
    ]

    print("\n[1회차] 동기화")
    async with Session() as db:
        r = await fill_sync.sync_daily_fills(
            db, uid, FakeBroker(fills), "5020182001", "20260918", "20260918")
    for k in ("fetched", "created", "updated", "verified", "no_fee_info",
              "skipped_cancelled", "skipped_unfilled", "mismatch_count"):
        print(f"    {k:18s} {r[k]}")
    for m in r["mismatched"]:
        print(f"    불일치: {m['broker_order_id']} {m['side']} 증권사 {m['broker_fees']:.2f} "
              f"vs 우리 {m['our_fees']:.2f} (차 {m['diff']:+.2f}원 · {m['diff_bps']:+.2f}bp)")

    print("\n[2회차] 같은 체결을 다시 동기화 — 행이 늘면 안 된다")
    async with Session() as db:
        r2 = await fill_sync.sync_daily_fills(
            db, uid, FakeBroker(fills), "5020182001", "20260918", "20260918")
        print(f"    created={r2['created']} updated={r2['updated']}")
        orders = (await db.execute(select(Order).where(Order.user_id == uid))).scalars().all()
        # 이 검증이 만든 주문에 달린 체결만 센다 — 전체를 세면 지난 실행분이 섞인다
        ids = [o.id for o in orders]
        n_fills = len((await db.execute(
            select(OrderFill).where(OrderFill.order_id.in_(ids)))).scalars().all())
        print(f"    orders {len(orders)}행 · order_fills {n_fills}행")
        print()
        print(f"    {'주문번호':>8s} {'구분':>5s} {'수량':>4s} {'체결가':>8s} {'정산금액':>12s} "
              f"{'수수료':>8s} {'거래세':>8s} {'농특세':>7s} {'유관':>7s} {'근거':>10s}")
        for o in sorted(orders, key=lambda x: x.broker_order_id):
            print(f"    {o.broker_order_id:>8s} {o.order_type:>5s} {o.filled_quantity:>4d} "
                  f"{o.avg_fill_price:>8,.0f} {o.net_amount:>12,.2f} {o.commission:>8.2f} "
                  f"{o.tax_transfer:>8.2f} {o.tax_rural:>7.2f} {o.fee_clearing:>7.2f} {o.cost_basis:>10s}")

        # 정산금액이 실제로 현금 증감과 맞는지
        print()
        for o in sorted(orders, key=lambda x: x.broker_order_id):
            gross = o.avg_fill_price * o.filled_quantity
            fees = o.commission + o.tax_transfer + o.tax_rural + o.fee_clearing
            want = gross + fees if o.order_type == "buy" else gross - fees
            gap = o.net_amount - want
            mark = "OK " if abs(gap) < 0.01 else f"차이 {gap:+.2f}"
            print(f"    {o.broker_order_id} 세목합 검산: gross {gross:,.0f} {'+' if o.order_type=='buy' else '-'} "
                  f"{fees:.2f} = {want:,.2f} vs net {o.net_amount:,.2f} → {mark}")

    await engine.dispose()
    print("\n검증 끝")

if __name__ == "__main__":
    asyncio.run(main())
