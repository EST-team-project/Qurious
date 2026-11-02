"""#183: 설정 변경·재시작·부분 매도에도 진입 기준 보존, 확정 ATR 단위."""
import asyncio
import os
import sqlite3
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.models import User, Portfolio, OrderIntent
from app.services import risk_stops as stops
from app.services.execution_policy import ExecutionPolicy, policy_for, risk_quantity


def test_new_policy_atr_and_saved_legacy_pct():
    assert ExecutionPolicy(size_kind="risk_pct").stop_kind == "atr"
    assert policy_for(SimpleNamespace(quant_execution_policy={"size_kind": "risk_pct"})).stop_kind == "pct"


def test_atr_uses_confirmed_bars_and_converts_adjusted_units(tmp_path, monkeypatch):
    path = tmp_path / "prices.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE price_daily (bas_dt TEXT,srtn_cd TEXT,hipr REAL,lopr REAL,clpr REAL)")
        db.execute("CREATE TABLE price_adjusted (bas_dt TEXT,srtn_cd TEXT,adj_hipr REAL,adj_lopr REAL,adj_clpr REAL,cum_factor REAL)")
        for d in range(1, 21):
            day = f"202610{d:02}"
            high = 110 if d < 20 else 9999  # 장중 봉은 ATR에 영향을 주지 않는다.
            db.execute("INSERT INTO price_daily VALUES (?,?,?,?,?)", (day, "005930", high, 90, 100))
            db.execute("INSERT INTO price_adjusted VALUES (?,?,?,?,?,?)", (day, "005930", high * .5, 45, 50, .5))
    monkeypatch.setattr(stops.collector_db, "db_path", lambda: path)
    monkeypatch.setattr(stops.market_calendar, "trading_days", lambda start, end: {"days": [{"date": end.isoformat(), "is_trading_day": True}]})
    result = stops.atr_distance("005930.KS", ExecutionPolicy(), now=datetime(2026, 10, 20, 12, tzinfo=stops.KST))
    assert result["atr_as_of"] == "2026-10-19" and result["distance"] == 40 and result["atr_adjusted"] == 10
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM price_daily WHERE bas_dt='20261019'")
    with pytest.raises(ValueError, match="확정 일봉"):
        stops.atr_distance("005930.KS", ExecutionPolicy(), now=datetime(2026, 10, 20, 12, tzinfo=stops.KST))


def test_quantity_identifies_budget_and_risk_limits():
    from datetime import date
    args = dict(equity=10_000_000, cash=10_000_000, price=275900, stop_price=250918,
                budget=1_000_000, existing_value=0, position_cap_pct=30, risk_pct=1,
                slippage_bps=10, when=date(2026, 10, 15))
    assert "budget" in risk_quantity(**args)["binding_limits"]
    args["budget"] = 10_000_000
    assert "risk" in risk_quantity(**args)["binding_limits"]


@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PostgreSQL 필요")
@pytest.mark.usefixtures("rebalance_db_schema")
@pytest.mark.parametrize("from_entry", [False, True])
def test_stop_is_immutable_across_restart_partial_sell_and_policy_change(from_entry):
    async def scenario():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        uid, pid = uuid.uuid4(), uuid.uuid4()
        row = SimpleNamespace(quant_execution_policy={"size_kind": "risk_pct", "stop_kind": "pct", "stop_loss_pct": 1},
                              quant_strategy_id="s", quant_strategy_version=1)
        async with factory() as db:
            db.add(User(id=uid, name="stop", email=f"{uid}@test.local", password_hash="x", client_id=uid.hex))
            await db.flush()
            entry_id = uuid.uuid4().hex if from_entry else None
            if entry_id:
                basis = await stops.entry_basis("005930.KS", 10000, ExecutionPolicy(stop_kind="pct", stop_loss_pct=5))
                db.add(OrderIntent(intent_id=entry_id, user_id=uid, account_ref="ref", book="QUANT", strategy_id="s",
                    strategy_version=1, symbol="005930.KS", side="BUY", source="quant", input_hash="x", status="filled",
                    result={"price_basis": {"stop": basis}}))
            p = Portfolio(id=pid, user_id=uid, symbol="005930.KS", name="삼성", book="QUANT", quantity=10,
                          avg_price=10000, risk_entry_intent_id=entry_id)
            db.add(p)
            await db.commit()
            first = await stops.for_position(db, uid, row, "paper", p)
            assert first["origin"] == ("entry" if from_entry else "transition")
            assert first["stop_price"] == (9500 if from_entry else 9900)
            p.quantity = 5
            await db.commit()
        row.quant_execution_policy = {"size_kind": "fixed_budget", "stop_kind": "pct", "stop_loss_pct": 20}
        async with factory() as db:
            p = await db.get(Portfolio, pid)
            assert await stops.for_position(db, uid, row, "paper", p) == first
            row.quant_strategy_id = "another_strategy"
            assert await stops.for_position(db, uid, row, "paper", p) == first
            p.avg_price = 11000
            await db.commit()
            with pytest.raises(ValueError, match="평균가"):
                await stops.for_position(db, uid, row, "paper", p)
            await db.delete(p)
            await db.commit()
            row.quant_execution_policy["size_kind"] = "risk_pct"
            p2 = Portfolio(user_id=uid, symbol="005930.KS", name="삼성", book="QUANT", quantity=1, avg_price=10000)
            db.add(p2)
            await db.commit()
            assert (await stops.for_position(db, uid, row, "paper", p2))["stop_price"] == 8000
        await engine.dispose()
    asyncio.run(scenario())


@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PostgreSQL 필요")
@pytest.mark.usefixtures("rebalance_db_schema")
def test_live_partial_fill_then_partial_sale_preserves_stop(monkeypatch):
    from datetime import timedelta
    from app.models import LiveOrder
    monkeypatch.setattr(stops.live_ownership, "account_ref", lambda *args: "account")
    async def scenario():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        uid = uuid.uuid4()
        row = SimpleNamespace(quant_execution_policy={"size_kind": "risk_pct", "stop_kind": "pct", "stop_loss_pct": 5},
                              quant_strategy_id="s", quant_strategy_version=1)
        at = datetime.now(stops.KST)
        async with factory() as db:
            db.add(User(id=uid, name="partial", email=f"{uid}@test.local", password_hash="x", client_id=uid.hex))
            await db.flush()
            # 10주 주문 중 6주 확정 체결, 잔량 취소. 손절은 주문량이 아닌 확정 보유를 따른다.
            db.add(LiveOrder(user_id=uid, account_ref="account", strategy_id="s", strategy_version=1,
                client_order_id=uid.hex, symbol="005930.KS", side="BUY", quantity=10,
                filled_quantity=6, avg_filled_price=10000, status="CANCELLED", created_at=at))
            await db.commit()
            pos = SimpleNamespace(symbol="005930.KS", quantity=6, avg_price=10000)
            first = await stops.for_position(db, uid, row, "live", pos)
            db.add(LiveOrder(user_id=uid, account_ref="account", strategy_id="s", strategy_version=1,
                client_order_id=uid.hex+"sell", symbol="005930.KS", side="SELL", quantity=2,
                filled_quantity=2, avg_filled_price=11000, status="FILLED", created_at=at+timedelta(seconds=1)))
            await db.commit()
        async with factory() as db:
            row.quant_execution_policy["stop_loss_pct"] = 20
            # reconcile은 과거 매도가 있으면 단순 평단을 주지 않는다. 확정 체결로 남은 원가를 재구성한다.
            pos = SimpleNamespace(symbol="005930.KS", quantity=4, avg_price=None)
            assert await stops.for_position(db, uid, row, "live", pos) == first
        await engine.dispose()
    asyncio.run(scenario())
