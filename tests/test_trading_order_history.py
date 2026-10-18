"""TC-TOH · 직접매매 › 주문/매매 「최근 주문 내역」(GET /api/orders) — 자동매매 · Open API · 예약 주문은 빼고,
그 규칙이 모의주문 내역(`paper_trading.stock_order_history` · #219)과 같다.

10-17 모의투자 점검 셋째 바퀴에서 #219 고침 뒤에도 이 화면(이동원 몫 · 10-07 결정)에만 자동매매 주문 5건이 섞였다.
거름을 두 곳에 적을 수밖에 없어(팀원 서비스 함수는 응답 꼴이 다르다) 두 결과를 시험이 맞댄다.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest

from app.models import Base, User
from app.models.trading import Order
from app.services import paper_trading as pt

ROOT = Path(__file__).resolve().parents[1]
DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB_URL, reason="일회용 시험 DB 없음")
SOURCES = ("WEB", "PAPER", "PINE", "QUANT", "OPENAPI", "RESERVED")


@pytest.fixture
def anyio_backend():
  return "asyncio"


@pytest.fixture
async def db():
  from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

  engine = create_async_engine(DB_URL)
  async with engine.begin() as conn:
    # 공유 시험 DB — 지우지 않고 없는 표만 만든다(다른 시험의 표가 orders 에 기댈 수 있다) · 결과는 사용자로 거른다
    await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[User.__table__, Order.__table__], checkfirst=True))
  factory = async_sessionmaker(engine, expire_on_commit=False)
  async with factory() as session:
    uid = uuid.uuid4()
    session.add(User(id=uid, name="t", email=f"{uid.hex}@t.local", password_hash="x", client_id=uid.hex))
    await session.flush()   # User 먼저(FK)
    for i, src in enumerate(SOURCES):
      session.add(Order(user_id=uid, symbol=f"00000{i}.KS", name=f"출처 {src}", order_type="buy", quantity=1,
                        price=1000, status="filled", broker="virtual" if src in ("WEB", "PAPER") else src.lower(),
                        source=src))
    await session.commit()
    yield session, uid
  await engine.dispose()


@needs_db
@pytest.mark.anyio
async def test_직접매매_주문_내역은_모의주문_내역과_같은_출처만_보인다(db):
  from app.routes import stocks

  session, uid = db
  mine = (await stocks.order_history(user={"id": str(uid)}, db=session))["orders"]
  theirs = await pt.stock_order_history(session, uid, limit=50)
  assert {o["name"] for o in mine} == {"출처 WEB", "출처 PAPER", "출처 PINE"}
  assert {o["name"] for o in mine} == {o["name"] for o in theirs}, "두 화면의 주문 내역 규칙이 갈라졌다"
  # 화면이 읽는 칸은 그대로
  assert set(mine[0]) >= {"symbol", "name", "order_type", "quantity", "price", "broker", "created_at"}


def test_화면은_빠진_주문을_어디서_보는지_알린다():
  src = (ROOT / "public" / "js" / "trading.js").read_text(encoding="utf-8")
  body = src[src.index("async function loadOrderHistory("): src.index("async function loadBrokerStatus(")]
  assert re.search(r'^\s+el\.insertAdjacentHTML\("beforeend", `[^`]*자동매매 현황', body, re.M)
  assert 'href="#quant-auto"' in body
