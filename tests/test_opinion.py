"""P01-④-2 — 의견 변환 진리표 (TC-OP)."""
import os
import uuid
from datetime import date, datetime, timezone

import pytest

from app.models import PORTFOLIO_BOOK_PAPER, Base, BrokerSettings, Portfolio, User
from app.models.signal import SignalSnapshot
from app.services.opinion import BUY, SELL, HOLD, SKIP, CONFIDENCE_MIN, decide
from app.services.ta_utils import DEFINITION

DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB_URL, reason="일회용 시험 DB 없음")

TABLES = [User.__table__, Portfolio.__table__, SignalSnapshot.__table__, BrokerSettings.__table__]


# ── 진리표 (순수 함수) ──────────────────────────────────────────

def test_buy_when_not_held_and_buy_signal_with_conf():
    assert decide("매수", CONFIDENCE_MIN, held=False) == (BUY, "buy_new")
    assert decide("매수", 1.0, held=False) == (BUY, "buy_new")


def test_skip_when_low_conf():
    assert decide("매수", CONFIDENCE_MIN - 0.01, held=False) == (SKIP, "skip_low_conf")


def test_sell_when_held_and_sell_signal_with_conf():
    assert decide("매도", CONFIDENCE_MIN, held=True) == (SELL, "sell_held")


def test_hold_when_held_and_low_conf_sell():
    assert decide("매도", CONFIDENCE_MIN - 0.01, held=True) == (HOLD, "hold_low_conf")


def test_hold_when_held_any_signal():
    assert decide("매수", 0.9, held=True) == (HOLD, "hold_held")
    assert decide("관망", 0.5, held=True) == (HOLD, "hold_held")


def test_skip_when_not_held_and_sell_or_neutral():
    assert decide("매도", 0.9, held=False) == (SKIP, "skip_neutral")
    assert decide("관망", 0.5, held=False) == (SKIP, "skip_neutral")


def test_risk_gate_forces_sell_when_held():
    assert decide("매수", 0.9, held=True, risk_gate=True) == (SELL, "sell_risk_gate")
    assert decide("관망", 0.5, held=True, risk_gate=True) == (SELL, "sell_risk_gate")


def test_risk_gate_no_effect_when_not_held():
    assert decide("매수", 0.9, held=False, risk_gate=True) == (BUY, "buy_new")
    assert decide("관망", 0.5, held=False, risk_gate=True) == (SKIP, "skip_neutral")


# ── API 라우트 (T2 + 보유 여부 → opinion) — 라우트 함수 직접 호출 ────

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from sqlalchemy import text

    engine = create_async_engine(DB_URL)
    async with engine.begin() as conn:
        # FK 얽힘 때문에 drop_all 대신 raw CASCADE
        for t in reversed(TABLES):
            await conn.execute(text(f'DROP TABLE IF EXISTS "{t.name}" CASCADE'))
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=TABLES))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        uid = uuid.uuid4()
        session.add(User(id=uid, name="op", email=f"{uid.hex}@t.local",
                         password_hash="x", client_id=uid.hex))
        await session.commit()
        yield session, uid
    await engine.dispose()


def _t2(symbol, signal, confidence):
    return SignalSnapshot(
        as_of=date(2026, 10, 14), symbol=symbol, definition=DEFINITION,
        signal=signal, strength="보통", confidence=confidence,
        composite=2.0, agreement=0.5,
        timeframes=[], reasons=[], computed_at=datetime.now(timezone.utc),
    )


@needs_db
@pytest.mark.anyio
async def test_mtf_signal_opinion_buy_new_when_not_held(db):
    from app.routes.stocks import stock_mtf_signal

    session, uid = db
    session.add(_t2("035420", "매수", 0.7))
    await session.commit()

    j = await stock_mtf_signal(symbol="035420.KS", db=session, user={"id": str(uid)})
    assert j["held"] is False
    assert j["opinion"] == "매수"
    assert j["opinion_rule"] == "buy_new"


@needs_db
@pytest.mark.anyio
async def test_mtf_signal_opinion_sell_held_when_held(db):
    from app.routes.stocks import stock_mtf_signal

    session, uid = db
    session.add(_t2("035420", "매도", 0.7))
    session.add(Portfolio(user_id=uid, symbol="035420.KS",
                          book=PORTFOLIO_BOOK_PAPER, name="NAVER",
                          quantity=5, avg_price=100000))
    await session.commit()

    j = await stock_mtf_signal(symbol="035420.KS", db=session, user={"id": str(uid)})
    assert j["held"] is True
    assert j["opinion"] == "매도"
    assert j["opinion_rule"] == "sell_held"


@needs_db
@pytest.mark.anyio
async def test_mtf_signal_opinion_skip_neutral_when_not_held_sell(db):
    from app.routes.stocks import stock_mtf_signal

    session, uid = db
    session.add(_t2("035420", "매도", 0.7))
    await session.commit()

    j = await stock_mtf_signal(symbol="035420.KS", db=session, user={"id": str(uid)})
    assert j["held"] is False
    assert j["opinion"] == "관망"
    assert j["opinion_rule"] == "skip_neutral"


@needs_db
@pytest.mark.anyio
async def test_mtf_signal_risk_gate_forces_sell(db, monkeypatch):
    """A — 킬 스위치가 켜지면 opinion 이 매도 강제."""
    from app.routes.stocks import stock_mtf_signal
    from app.models import BrokerSettings

    session, uid = db
    session.add(_t2("035420", "관망", 0.5))   # 신호가 관망이어도
    session.add(Portfolio(user_id=uid, symbol="035420.KS",
                          book=PORTFOLIO_BOOK_PAPER, name="NAVER",
                          quantity=5, avg_price=100000))
    session.add(BrokerSettings(user_id=uid, risk_kill_switch=True))
    await session.commit()

    j = await stock_mtf_signal(symbol="035420.KS", db=session, user={"id": str(uid)})
    assert j["held"] is True
    assert j["risk_gate"] is True
    assert j["opinion"] == "매도"
    assert j["opinion_rule"] == "sell_risk_gate"


@needs_db
@pytest.mark.anyio
async def test_mtf_signal_no_risk_gate_normal(db):
    """A — 킬 스위치 꺼져 있고 손실 없으면 risk_gate=False."""
    from app.routes.stocks import stock_mtf_signal

    session, uid = db
    session.add(_t2("035420", "매수", 0.7))
    await session.commit()

    j = await stock_mtf_signal(symbol="035420.KS", db=session, user={"id": str(uid)})
    assert j["risk_gate"] is False


@needs_db
@pytest.mark.anyio
async def test_mtf_signal_held_lookup_fails_gracefully(db, monkeypatch):
    """#194 결함 1 — 보유 조회가 실패해도 신호·의견은 나온다."""
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.routes.stocks import stock_mtf_signal

    session, uid = db
    session.add(_t2("035420", "매수", 0.7))
    await session.commit()

    original_execute = AsyncSession.execute

    async def _broken(self, *args, **kw):
        stmt = str(args[0]) if args else ""
        if "portfolio" in stmt.lower():
            raise OperationalError("connection lost", None, None)
        return await original_execute(self, *args, **kw)

    monkeypatch.setattr(AsyncSession, "execute", _broken)

    j = await stock_mtf_signal(symbol="035420.KS", db=session, user={"id": str(uid)})
    assert j["held"] is False           # DB 못 닿으면 미보유 가정
    assert j["opinion"] == "매수"        # 신호·의견은 정상