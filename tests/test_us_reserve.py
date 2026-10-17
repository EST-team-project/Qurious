"""미국주식 예약 주문 · 미국 정규장 상태 시험 (TC-USR · `P01-④-3` · 2026-10-17 · 모의투자 점검 L10 · #256 미국 쪽).

결정: Figma 「Qurious · 미국주식 주문 화면」 C — 장이 닫힌 때 미국주식 매수는 예약으로 받아 **다음 정규장 시작가**로 체결한다.
규칙 한 곳은 `app/services/us_reserve.py`, 라우트는 `app/routes/us_reserve.py`.

여기서 지키는 것 —
1. 장 시간: 뉴욕 09:30 ~ 16:00 · 주말 · NYSE 휴장일 · 조기 마감 · 서머타임(2026-11-01 끝)을 시간대가 맞춘다 ·
   휴장일 표 밖의 해는 None(「연다」 고 짐작하지 않는다).
2. 예약은 장이 닫힌 때 · 해외 종목 · 매수만 — 열려 있으면 MarketOpenError(라우트 409 · 바로 주문하면 된다) ·
   국내 종목 · 표 밖 · 잘못된 수량은 ReserveError(라우트 400) + 까닭.
3. 체결: 예약한 뒤 처음 열린 정규장의 시가 × 그때 환율 · 체결 시각 = 그 정규장 시작 · 시가를 못 받으면 기다림(다른 날
   값으로 메우지 않음) · 두 번 읽어도 한 번만 체결(멱등) · 현금이 모자라면 건너뜀 + 까닭.
4. 예약 줄은 모의투자 주문 내역에 섞이지 않고(source RESERVED) 체결 줄은 내역에 남는다(PAPER).
5. 라우트 넷이 라우터 · 앱에 붙어 있고 오류를 바른 상태 코드로 돌려준다.
DB 시험은 QURIOUS_TEST_DATABASE_URL(일회용 DB · scripts/personal/test.ps1)이 있을 때만 돈다 — 나머지는 네트워크 · DB 없이 돈다.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Order, PaperAccount, Portfolio, User
from app.routes import us_reserve as routes
from app.services import paper_trading, stock, us_reserve as ur

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
KST = timezone(timedelta(hours=9))
SAT_KST = datetime(2026, 10, 17, 17, 0, tzinfo=KST)          # 토요일 저녁 — 미국 장 닫힘
MON_OPEN_UTC = datetime(2026, 10, 19, 13, 30, tzinfo=UTC)    # 10-19(월) 09:30 EDT


# ── 1. 장 시간 ─────────────────────────────────────────────────────────────────
def test_saturday_is_closed_and_next_open_is_monday_2230_kst():
    s = ur.market_state(SAT_KST)
    assert s["open"] is False
    assert s["next_open_kst"] == "10-19(월) 22:30"
    assert s["label"] == "미국 정규장 닫힘 · 다음 정규장 10-19(월) 22:30(KST)"


def test_after_dst_ends_the_open_is_2330_kst():
    s = ur.market_state(datetime(2026, 11, 7, 12, 0, tzinfo=KST))   # 11-01 서머타임 끝 뒤 토요일
    assert s["open"] is False and s["next_open_kst"] == "11-09(월) 23:30"


def test_open_during_the_regular_session():
    s = ur.market_state(datetime(2026, 10, 19, 23, 0, tzinfo=KST))   # 월 10:00 EDT
    assert s["open"] is True
    assert s["close_kst"] == "10-20(화) 05:00" and "마감" in s["label"]
    assert ur.market_state(MON_OPEN_UTC)["open"] is True              # 시작 시각 그 순간은 열림
    assert ur.market_state(MON_OPEN_UTC - timedelta(seconds=1))["open"] is False


def test_holidays_and_early_close_follow_the_nyse_notice():
    assert ur.trading_day(date(2026, 11, 26)) is False                # 추수감사절
    assert ur.trading_day(date(2027, 3, 26)) is False                 # 성금요일
    assert ur.trading_day(date(2027, 12, 24)) is False                # 크리스마스 대체
    assert ur.trading_day(date(2026, 10, 19)) is True
    _s, end = ur.session_bounds(date(2026, 11, 27))
    assert (end.hour, end.minute) == (13, 0)                          # 다음 날 조기 마감
    after = datetime(2026, 11, 27, 19, 0, tzinfo=UTC)                 # 14:00 EST — 이미 닫힘
    s = ur.market_state(after)
    assert s["open"] is False and s["next_open_kst"] == "11-30(월) 23:30"
    # NYSE 공지 표의 줄 수 — 2028 새해는 토요일이라 쉬는 날이 없다(「—」)
    by_year = {y: sum(1 for d in ur.NYSE_HOLIDAYS if d.year == y) for y in (2026, 2027, 2028)}
    assert by_year == {2026: 10, 2027: 10, 2028: 9}


def test_years_outside_the_table_are_unknown_not_open():
    assert ur.trading_day(date(2029, 1, 2)) is None
    assert ur.market_state(datetime(2029, 1, 2, 15, 0, tzinfo=UTC))["open"] is None
    # 2028-12-29(금) 마감 뒤 → 다음 정규장은 2029 년이라 모름
    assert ur.next_open_after(datetime(2028, 12, 29, 22, 0, tzinfo=UTC)) is None


def test_naive_times_are_read_as_utc():
    assert ur.next_open_after(datetime(2026, 10, 17, 8, 0)) == ur.next_open_after(datetime(2026, 10, 17, 8, 0, tzinfo=UTC))


# ── 2. 예약을 받지 않는 때 (DB 없이) ─────────────────────────────────────────────
class _NoDb:
    async def execute(self, *a, **k):
        raise AssertionError("까닭이 앞에서 정해지면 DB 를 부르지 않는다")


@pytest.mark.anyio
async def test_reserve_is_refused_while_the_market_is_open(monkeypatch):
    monkeypatch.setattr(ur, "market_state", lambda now=None: {"open": True, "label": "열림"})
    with pytest.raises(ur.MarketOpenError):
        await ur.place(_NoDb(), uuid.uuid4(), "PLUG", 1)


@pytest.mark.anyio
@pytest.mark.parametrize("symbol, qty", [("005930", 1), ("005930.KS", 1), ("PLUG", 0), ("PLUG", True)])
async def test_reserve_refuses_domestic_and_bad_quantity(symbol, qty):
    with pytest.raises(ur.ReserveError):
        await ur.place(_NoDb(), uuid.uuid4(), symbol, qty, now=SAT_KST)


@pytest.mark.anyio
async def test_reserve_is_refused_when_the_calendar_does_not_know(monkeypatch):
    monkeypatch.setattr(ur, "market_state", lambda now=None: {"open": None, "label": "휴장일 표에 없는 해"})
    with pytest.raises(ur.ReserveError, match="휴장일 표"):
        await ur.place(_NoDb(), uuid.uuid4(), "PLUG", 1)


# ── 3. 그 정규장의 시가 고르기 ───────────────────────────────────────────────────
@pytest.fixture
def anyio_backend():
    return "asyncio"


def _bars(*days_open, normalized=False):
    out = []
    for d, op in days_open:
        t = datetime(d.year, d.month, d.day, 0 if normalized else 13, 0 if normalized else 30, tzinfo=UTC)
        out.append({"time": int(t.timestamp()), "open": op, "close": op, "high": op, "low": op})
    return {"candles": out}


@pytest.mark.anyio
@pytest.mark.parametrize("normalized", [False, True])
async def test_session_open_price_matches_the_day_by_utc_date(monkeypatch, normalized):
    calls = []

    async def fake(symbol, period="1y", interval="1d", max_age_hours=6):
        calls.append((symbol, period, interval, max_age_hours))
        return _bars((date(2026, 10, 16), 1.38), (date(2026, 10, 19), 1.50), normalized=normalized)

    monkeypatch.setattr(stock, "get_candles", fake)
    got = await ur.session_open_price("PLUG", date(2026, 10, 19), MON_OPEN_UTC + timedelta(hours=2))
    assert got == 1.50
    assert calls == [("PLUG", "5d", "1d", 0)]          # 새로 받는다(옛 저장본엔 그날 봉이 없을 수 있다)
    assert await ur.session_open_price("PLUG", date(2026, 10, 20), MON_OPEN_UTC) is None


# ── 4. 라우트 ─────────────────────────────────────────────────────────────────
def test_routes_are_on_the_router_and_mounted_in_the_app():
    have = {(r.path, m) for r in routes.router.routes for m in r.methods}
    assert {("/api/paper/stocks/us-market", "GET"), ("/api/paper/stocks/reservations", "GET"),
            ("/api/paper/stocks/reservations", "POST"),
            ("/api/paper/stocks/reservations/{order_id}", "DELETE")} <= have
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "app.include_router(us_reserve_routes.router)" in main


class _FakeDb:
    def __init__(self):
        self.calls = []

    async def commit(self):
        self.calls.append("commit")

    async def rollback(self):
        self.calls.append("rollback")


USER = {"id": str(uuid.uuid4()), "client_id": "t"}


@pytest.mark.anyio
async def test_post_maps_market_open_to_409_and_reasons_to_400(monkeypatch):
    async def opened(*a, **k):
        raise ur.MarketOpenError("지금은 미국 정규장이 열려 있습니다")

    async def refused(*a, **k):
        raise ur.ReserveError("국내 종목은 예약을 받지 않습니다")

    body = routes.ReserveBody(symbol="PLUG", quantity=1)
    monkeypatch.setattr(ur, "place", opened)
    with pytest.raises(HTTPException) as e1:
        await routes.reserve(body, USER, _FakeDb())
    assert e1.value.status_code == 409
    db = _FakeDb()
    monkeypatch.setattr(ur, "place", refused)
    with pytest.raises(HTTPException) as e2:
        await routes.reserve(body, USER, db)
    assert e2.value.status_code == 400 and "국내" in e2.value.detail and db.calls == ["rollback"]


@pytest.mark.anyio
async def test_get_fills_due_reservations_commits_then_lists(monkeypatch):
    seen = []

    async def fill(db, uid, now=None):
        seen.append("fill")
        return [{"status": "filled"}]

    async def lst(db, uid, limit=20):
        seen.append("list:" + ",".join(db.calls))
        return []

    monkeypatch.setattr(ur, "fill_due", fill)
    monkeypatch.setattr(ur, "list_reservations", lst)
    out = await routes.reservations(USER, _FakeDb())
    assert seen == ["fill", "list:commit"]                 # 체결을 먼저 저장한 뒤 목록을 읽는다
    assert out["fired"] == [{"status": "filled"}] and "open" in out["market"] and out["note"] == ur.NOTE


# ── 5. DB — 예약 → 체결 · 멱등 · 기다림 · 건너뜀 · 취소 ────────────────────────────
DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB_URL, reason="QURIOUS_TEST_DATABASE_URL 이 없다 — scripts/personal/test.ps1 로 돌린다")
TABLES = [User.__table__, PaperAccount.__table__, Portfolio.__table__, Order.__table__]
FIXED_CREATED = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)     # 토 17:00 KST 에 예약했다고 둔다(시험이 실제 시계를 따르지 않게)
QUOTE = {"symbol": "PLUG", "code": "PLUG", "name": "Plug Power Inc.", "market": "NCM", "price": 1834.848,
         "price_local": 1.38, "currency": "USD", "fx_rate": 1329.6, "fx_source": "live",
         "fx_note": "받은 환율 1 USD = 1,329.60원 · 10-17 17:35 기준"}


@pytest.fixture
async def db(monkeypatch):
    from app.models import Base
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def quote(symbol):
        return dict(QUOTE)

    monkeypatch.setattr(paper_trading, "resolve_stock", quote)
    engine = create_async_engine(DB_URL)
    async with engine.begin() as conn:
        # 지우지 않고 없는 표만 만든다 — 전체 실행에서는 다른 시험이 만든 표(order_fills → orders)가 남아 있어
        # drop_all 이 「다른 객체가 기대고 있다」 로 멈췄다(65차). 시험마다 새 사용자라 그 사용자로만 거르면 섞이지 않는다.
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        uid = uuid.uuid4()
        session.add(User(id=uid, name="usr", email=f"{uid.hex}@test.local", password_hash="x", client_id=uid.hex))
        await session.commit()
        yield session, uid
    await engine.dispose()


async def _reserve(session, uid, qty=1):
    r = await ur.place(session, uid, "PLUG", qty, now=SAT_KST)
    o = (await session.execute(select(Order).where(Order.id == uuid.UUID(r["order_id"])))).scalar_one()
    o.created_at = FIXED_CREATED
    await session.commit()
    return r, o


def _candles(monkeypatch, bars):
    async def fake(symbol, period="1y", interval="1d", max_age_hours=6):
        return bars
    monkeypatch.setattr(stock, "get_candles", fake)


@needs_db
@pytest.mark.anyio
async def test_reserve_then_fill_at_the_first_session_open(db, monkeypatch):
    session, uid = db
    r, _o = await _reserve(session, uid)
    assert r["status"] == "pending" and r["next_open_kst"] == "10-19(월) 22:30" and r["note"] == ur.NOTE
    cash0 = float((await paper_trading.get_account(session, uid)).cash)
    _candles(monkeypatch, _bars((date(2026, 10, 16), 1.38), (date(2026, 10, 19), 1.50)))
    fired = await ur.fill_due(session, uid, now=MON_OPEN_UTC + timedelta(hours=2))
    await session.commit()
    assert [f["status"] for f in fired] == ["filled"]
    f = fired[0]
    assert f["open_local"] == 1.50 and f["fill_price"] == 1994.0      # 1.50 × 1,329.60 = 1,994.4 → 원화 단가
    assert f["filled_at_kst"] == "10-19(월) 22:30"
    session.expire_all()
    row = (await session.execute(select(Order).where(Order.id == uuid.UUID(r["order_id"])))).scalar_one()
    assert row.status == "filled" and row.filled_at == MON_OPEN_UTC and row.avg_fill_price == 1994.0
    assert (await session.execute(select(Portfolio.quantity).where(Portfolio.user_id == uid))).scalar_one() == 1
    cash1 = float((await paper_trading.get_account(session, uid)).cash)
    assert cash0 - cash1 == pytest.approx(row.net_amount)
    # 두 번 읽어도 한 번만 체결(멱등) — 새 내역 줄이 생기지 않는다
    assert await ur.fill_due(session, uid, now=MON_OPEN_UTC + timedelta(days=3)) == []
    hist = await paper_trading.stock_order_history(session, uid, limit=50)
    assert len(hist) == 1                                             # 예약 줄(RESERVED)은 내역에 없고 체결 줄(PAPER)만
    sources = (await session.execute(select(Order.source).where(Order.user_id == uid))).scalars().all()
    assert sorted(sources) == ["PAPER", "RESERVED"]


@needs_db
@pytest.mark.anyio
async def test_fill_waits_when_the_open_price_is_missing_and_before_the_open(db, monkeypatch):
    session, uid = db
    r, _o = await _reserve(session, uid)
    _candles(monkeypatch, _bars((date(2026, 10, 16), 1.38)))          # 10-19 봉이 아직 없다
    assert await ur.fill_due(session, uid, now=MON_OPEN_UTC - timedelta(minutes=1)) == []   # 정규장 전
    fired = await ur.fill_due(session, uid, now=MON_OPEN_UTC + timedelta(minutes=5))
    assert [f["status"] for f in fired] == ["waiting"] and "시가" in fired[0]["reason"]
    row = (await session.execute(select(Order).where(Order.id == uuid.UUID(r["order_id"])))).scalar_one()
    assert row.status == "pending"                                    # 다른 날 값으로 메우지 않는다
    assert (await session.execute(select(Order).where(Order.user_id == uid, Order.source == "PAPER"))).first() is None


@needs_db
@pytest.mark.anyio
async def test_fill_is_skipped_with_a_reason_when_cash_is_short(db, monkeypatch):
    session, uid = db
    r, _o = await _reserve(session, uid, qty=1000)
    acc = await paper_trading.get_account(session, uid)
    acc.cash = 1000.0
    await session.commit()
    _candles(monkeypatch, _bars((date(2026, 10, 19), 1.50)))
    fired = await ur.fill_due(session, uid, now=MON_OPEN_UTC + timedelta(hours=1))
    assert [f["status"] for f in fired] == ["skipped"] and "현금" in fired[0]["reason"]


@needs_db
@pytest.mark.anyio
async def test_cancel_only_own_pending_and_list_shows_next_open(db, monkeypatch):
    session, uid = db
    r, _o = await _reserve(session, uid)
    rows = await ur.list_reservations(session, uid)
    assert rows[0]["status"] == "pending" and rows[0]["next_open_kst"] == "10-19(월) 22:30"
    with pytest.raises(ur.ReserveError):
        await ur.cancel(session, uuid.uuid4(), r["order_id"])        # 남의 예약은 못 지운다
    assert (await ur.cancel(session, uid, r["order_id"]))["status"] == "cancelled"
    with pytest.raises(ur.ReserveError):
        await ur.cancel(session, uid, r["order_id"])                  # 이미 취소됨
    monkeypatch.setattr(ur, "MAX_PENDING", 1)
    await ur.place(session, uid, "PLUG", 1, now=SAT_KST)
    with pytest.raises(ur.ReserveError, match="대기 중인 예약"):
        await ur.place(session, uid, "PLUG", 1, now=SAT_KST)
