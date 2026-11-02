"""#478/#476 실제 PostgreSQL 경합·커밋 경계·알림 재시작 회수·PAPER 수량 검증."""
import asyncio
import os
import uuid
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import postgres
from app.models import NotificationLog, Order, PaperAccount, Portfolio, User
from app.services import market_calendar, notification, paper_fill_notifications as notices
from app.services import paper_risk_preview as risk, paper_trading as pt

pytestmark = pytest.mark.usefixtures("rebalance_db_schema")
DB_URL = os.getenv("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB_URL, reason="격리 PostgreSQL 필요")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def setup(monkeypatch):
    engine = create_async_engine(DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(postgres, "get_session_factory", lambda: factory)
    monkeypatch.setattr(notices, "get_session_factory", lambda: factory)
    monkeypatch.setattr(pt, "stop_market_open", lambda: True)
    async def confirm(db, uid, info, **kwargs):
        return info
    monkeypatch.setattr(pt, "_confirm_quote", confirm)
    quote = {"symbol": "005930.KS", "name": "시험", "market": "KOSPI", "price": 10000, "is_etf": False}
    async def resolve(symbol):
        return dict(quote)
    monkeypatch.setattr(pt, "resolve_stock", resolve)
    monkeypatch.setattr(notification, "_load_user_settings", AsyncMock(return_value={"channels": ["discord"]}))
    delivered = []
    async def deliver(ev, cfg, channels, **kwargs):
        delivered.append(ev)
        return ["discord"], [True], [1]
    monkeypatch.setattr(notification, "_deliver", deliver)
    uid = uuid.uuid4()
    async with factory() as db:
        db.add(User(id=uid, name="flow", email=f"{uid}@test.local", client_id=uid.hex, password_hash="x"))
        await db.flush()
        db.add(PaperAccount(user_id=uid, cash=1_000_000, initial_cash=1_000_000))
        await db.commit()
    yield factory, uid, quote, delivered
    await engine.dispose()


@pytest.mark.parametrize("stamp,open_", [
    ("2026-11-02T08:59:59", False), ("2026-11-02T09:00:00", True),
    ("2026-11-02T15:29:59", True), ("2026-11-02T15:30:00", False),
    ("2026-11-01T10:00:00", False), ("2026-10-09T10:00:00", False),
])
def test_stop_regular_session(monkeypatch, stamp, open_):
    now = datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo("Asia/Seoul"))
    monkeypatch.setattr(market_calendar, "trading_days", lambda a, b: {
        "days": [{"date": a.isoformat(), "is_trading_day": True}]})
    assert pt.stop_market_open(now) is open_


@pytest.mark.parametrize("calendar", [{"partial": True, "days": []}, {"days": []},
                                       {"days": [{"date": "2026-11-02", "is_trading_day": False}]}])
def test_unconfirmed_or_closed_calendar(monkeypatch, calendar):
    monkeypatch.setattr(market_calendar, "trading_days", lambda a, b: calendar)
    assert not pt.stop_market_open(datetime(2026, 11, 2, 10, tzinfo=ZoneInfo("Asia/Seoul")))


def test_missing_calendar(monkeypatch):
    def missing(*args):
        raise market_calendar.CalendarUnavailable("missing")
    monkeypatch.setattr(market_calendar, "trading_days", missing)
    assert not pt.stop_market_open(datetime(2026, 11, 2, 10, tzinfo=ZoneInfo("Asia/Seoul")))


@needs_db
@pytest.mark.anyio
@pytest.mark.parametrize("side,price", [("BUY", 10000), ("BUY", 9000), ("SELL", 10000), ("SELL", 11000)])
async def test_stop_direction(setup, side, price):
    factory, uid, _, _ = setup
    async with factory() as db:
        with pytest.raises(pt.StopOrderError, match="기준 시세"):
            await pt.place_stop_order(db, uid, "005930", side, 1, price)
        assert not (await db.execute(select(Order).where(Order.user_id == uid))).scalars().all()


@needs_db
@pytest.mark.anyio
async def test_closed_scan_and_close_during_quote_keep_pending(setup, monkeypatch):
    factory, uid, quote, _ = setup
    async with factory() as db:
        placed = await pt.place_stop_order(db, uid, "005930", "BUY", 1, 11000)
        await db.commit()
        quote["price"] = 12000
        for sequence in ([False], [True, False], [True, True, False]):
            states = iter(sequence)
            monkeypatch.setattr(pt, "stop_market_open", lambda: next(states))
            assert await pt.check_stop_orders(db, uid) == []
            await db.commit()
            row = await db.get(Order, uuid.UUID(placed["order_id"]))
            assert row.status == "pending" and not row.fill_notice_pending


@needs_db
@pytest.mark.anyio
async def test_parallel_scans_fill_once_and_preserve_stop(setup, monkeypatch):
    factory, uid, quote, delivered = setup
    async with factory() as db:
        placed = await pt.place_stop_order(db, uid, "005930", "BUY", 2, 11000)
        await db.commit()
    quote["price"] = 12000
    entered, release = asyncio.Event(), asyncio.Event()
    async def paused(db, user, info, **kwargs):
        entered.set()
        await release.wait()
        return info
    monkeypatch.setattr(pt, "_confirm_quote", paused)
    async def scan():
        async with factory() as db:
            out = await pt.check_stop_orders(db, uid)
            await db.commit()
            return out
    first = asyncio.create_task(scan())
    await asyncio.wait_for(entered.wait(), 3)
    assert await asyncio.wait_for(scan(), 3) == []
    release.set()
    assert len(await first) == 1
    assert await scan() == []
    async with factory() as db:
        rows = (await db.execute(select(Order).where(Order.user_id == uid))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert str(row.id) == placed["order_id"]
        assert row.price == row.avg_fill_price == 12000 and row.order_price == row.stop_price == 11000
        assert row.commission > 0 and row.filled_quantity == 2 and row.fill_notice_pending
        history = await pt.stock_order_history(db, uid)
        assert len(history) == 1 and history[0]["order_id"] == placed["order_id"]
        with pytest.raises(pt.StopOrderError):
            await pt.cancel_stop_order(db, uid, placed["order_id"])
    await asyncio.gather(notices.drain(user_id=uid), notices.drain(user_id=uid))
    assert len(delivered) == 1


@needs_db
@pytest.mark.anyio
async def test_notification_commit_rollback_recovery_and_dedupe(setup, monkeypatch):
    factory, uid, _, delivered = setup
    async with factory() as db:
        await pt.stock_order(db, uid, "005930", "BUY", 1)
        await db.flush()
        await notices.drain(user_id=uid)
        assert not delivered  # 커밋 전 체결은 알림 없음
        await db.rollback()
        await notices.drain(user_id=uid)
        assert not delivered
        result = await pt.stock_order(db, uid, "005930", "BUY", 1)
        await db.commit()
    real = notification.notify_paper_order_filled
    monkeypatch.setattr(notification, "notify_paper_order_filled", AsyncMock(side_effect=RuntimeError("offline")))
    await notices.drain(user_id=uid)  # API의 체결 성공을 실패로 바꾸지 않는다.
    async with factory() as db:
        row = await db.get(Order, uuid.UUID(result["order_id"]))
        assert row.status == "filled" and row.fill_notice_pending
    monkeypatch.setattr(notification, "notify_paper_order_filled", real)
    await notices.drain(user_id=uid)  # 새 세션에서 재시작 후 회수
    assert len(delivered) == 1
    async with factory() as db:
        row = await db.get(Order, uuid.UUID(result["order_id"]))
        assert not row.fill_notice_pending
        row.fill_notice_pending = True  # 발송 이후 flag 커밋 전에 죽은 상황
        await db.commit()
    await notices.drain(user_id=uid)
    assert len(delivered) == 1
    async with factory() as db:
        logs = (await db.execute(select(NotificationLog).where(NotificationLog.user_id == uid))).scalars().all()
        assert len(logs) == 1 and logs[0].ref == result["order_id"] and logs[0].delivery_status == "delivered"
        assert "PAPER" in logs[0].subject and "KIS" not in logs[0].message


@needs_db
@pytest.mark.anyio
async def test_paper_sizing_ignores_quant_and_rejects_existing_position(setup):
    factory, uid, _, _ = setup
    async with factory() as db:
        db.add(Portfolio(user_id=uid, symbol="005930.KS", name="QUANT", book="QUANT", quantity=999, avg_price=999999))
        await db.commit()
        body = risk.RiskPreviewBody(symbol="005930", stop_kind="pct", budget=200_000, risk_pct=1)
        out = await risk.preview(db, uid, body)
        assert out["book"] == "PAPER" and out["equity"] == out["cash"] == 1_000_000
        assert out["quantity"] == 19 and out["estimated_cash"] <= 200_000 and out["estimated_loss"] <= 10_000
        assert not (await db.execute(select(Order).where(Order.user_id == uid))).scalars().all()
        await pt.stock_order(db, uid, "005930", "BUY", 1)
        await db.commit()
        with pytest.raises(pt.PaperTradeError, match="이미 보유"):
            await risk.preview(db, uid, body)


@needs_db
@pytest.mark.anyio
async def test_incomplete_valuation_and_missing_atr_do_not_fallback(setup, monkeypatch):
    factory, uid, _, _ = setup
    async with factory() as db:
        monkeypatch.setattr(pt, "account_snapshot", AsyncMock(return_value={"price_complete": False}))
        with pytest.raises(pt.PaperTradeError, match="불완전"):
            await risk.preview(db, uid, risk.RiskPreviewBody(symbol="005930"))
        monkeypatch.setattr(pt, "account_snapshot", AsyncMock(return_value={"price_complete": True, "totalAsset": 1e6, "cash": 1e6}))
        monkeypatch.setattr(risk.risk_stops, "entry_basis", AsyncMock(side_effect=ValueError("확정 일봉 없음")))
        with pytest.raises(pt.PaperTradeError, match="확정 일봉"):
            await risk.preview(db, uid, risk.RiskPreviewBody(symbol="005930"))


@needs_db
@pytest.mark.anyio
async def test_cancel_lock_wins_over_scan(setup):
    factory, uid, quote, delivered = setup
    async with factory() as db:
        placed = await pt.place_stop_order(db, uid, "005930", "BUY", 1, 11000)
        await db.commit()
        quote["price"] = 12000
        await pt.cancel_stop_order(db, uid, placed["order_id"])
        async with factory() as scanner:
            assert await asyncio.wait_for(pt.check_stop_orders(scanner, uid), 3) == []
            await scanner.commit()
        await db.commit()
        assert await pt.check_stop_orders(db, uid) == []
        assert await pt.stock_order_history(db, uid) == []
    await notices.drain(user_id=uid)
    assert not delivered


@needs_db
@pytest.mark.anyio
async def test_disabled_fill_event_never_sends(setup, monkeypatch):
    factory, uid, _, delivered = setup
    monkeypatch.setattr(notification, "_load_user_settings", AsyncMock(return_value={
        "channels": ["discord"], "preferences": {"events": {"order_fill": "off"}}}))
    async with factory() as db:
        result = await pt.stock_order(db, uid, "005930", "BUY", 1)
        await db.commit()
    await notices.drain(user_id=uid)
    assert not delivered
    async with factory() as db:
        row = await db.get(Order, uuid.UUID(result["order_id"]))
        assert row.status == "filled" and not row.fill_notice_pending
