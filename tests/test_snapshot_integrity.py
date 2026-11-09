"""#371: 시세 근거, GET 부작용, 불완전 경계의 실제 DB 회귀 시험."""
import asyncio
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.models import User, PaperAccount, PaperAccountSnapshot, PaperSnapshotPriceAudit, CashflowEvent, Order
from app.services import paper_trading as pt, paper_snapshot_service as snapshots, snapshot_pricing as pricing


def test_daily_stock_requires_close_time_and_crypto_requires_exchange_time():
    now = datetime(2026, 11, 2, 15, 40, tzinfo=pricing.KST)
    for source, stamp, expected in [("kis_gateway", None, False),
            ("delayed", "2026-11-02T12:00:00+09:00", False),
            ("delayed", "2026-11-02T15:30:00+09:00", True),
            ("delayed", "2026-11-02T15:31:00+09:00", False),
            ("kis_gateway", "2026-11-02T15:40:00+09:00", False),
            ("collector_close", "2026-11-02", True)]:
        item = pricing.evidence("stock", "005930", 100, source, stamp, now=now)
        assert pricing.daily_complete(item, now.date(), at=now) is expected
    for age, expected in [(0, True), (300, True), (301, False), (-1, False)]:
        item = pricing.evidence("crypto", "KRW-BTC", 100, "upbit", (now - timedelta(seconds=age)).isoformat(), now=now)
        assert item["complete"] is expected
    assert not pricing.evidence("crypto", "KRW-BTC", float("nan"), "upbit", now.isoformat(), now=now)["complete"]
    assert pricing.stock_quote_time("2026-11-02 15:30", "delayed") == "2026-11-02T15:30:00+09:00"
    assert pricing.stock_quote_time(None, "kis_gateway") is None


def test_expired_upbit_cache_is_not_returned_when_refresh_fails(monkeypatch):
    now = time.time()
    monkeypatch.setattr(pt, "_UPBIT_TICKER_CACHE", {
        "KRW-BTC": {"ts": now - 400, "data": {"market": "KRW-BTC", "price": 100,
                    "as_of": datetime.fromtimestamp(now - 400, timezone.utc).isoformat()}}})
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.side_effect = RuntimeError("offline")
    monkeypatch.setattr(pt.httpx, "AsyncClient", lambda **kwargs: client)
    assert asyncio.run(pt.upbit_tickers(["KRW-BTC"])) == []


@pytest.mark.parametrize("as_of,collector_available,source,complete", [
    ("2026-11-02 15:30", False, "delayed", True),
    ("2026-11-02 12:00", True, "collector_close", True),
    ("2026-11-02 12:00", False, "delayed", False),
])
@pytest.mark.parametrize('include_audits', [False, True])
def test_stock_snapshot_uses_close_evidence_or_stays_incomplete(monkeypatch, as_of, collector_available, source, complete, include_audits):
    from app.services import price_basis
    position = SimpleNamespace(symbol="005930.KS", name="삼성", quantity=2, avg_price=90)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [position]))))
    monkeypatch.setattr(pt, "resolve_stock", AsyncMock(return_value={
        "price": 110, "currency": "KRW", "quote_source": "delayed", "quote_as_of": as_of}))
    def close(symbol, day):
        assert day == date(2026, 11, 2)
        if not collector_available:
            raise ValueError("no daily bar")
        return {"raw_close": 120, "as_of": day.isoformat()}
    monkeypatch.setattr(price_basis, "load_day", close)
    rows = asyncio.run(pt.stock_positions(db, uuid.uuid4(), include_price_metadata=True,
                                         valuation_date=date(2026, 11, 2), include_price_audits=include_audits))
    assert rows[0]["_price_complete"] is complete
    assert rows[0]["_price_metadata"]["source"] == source
    assert rows[0]["_price_metadata"]["price"] == (120 if collector_available else 110)
    pt.resolve_stock.assert_awaited_once()
    if include_audits:
        audit = rows[0]['_price_audits'][0]
        assert audit['source'] == source and audit['used_price'] == rows[0]['_price_metadata']['price']


def test_account_get_does_not_write_daily_snapshot(monkeypatch):
    from app.routes import paper
    monkeypatch.setattr(paper.pt, "account_snapshot", AsyncMock(return_value={"cash": 1}))
    writer = AsyncMock()
    monkeypatch.setattr(paper, "record_daily_snapshot", writer)
    assert asyncio.run(paper.account({"id": str(uuid.uuid4())}, SimpleNamespace(commit=AsyncMock()))) == {"cash": 1}
    writer.assert_not_awaited()


@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PostgreSQL 필요")
@pytest.mark.usefixtures("rebalance_db_schema")
def test_daily_boundaries_provenance_and_manual_cannot_overwrite(monkeypatch):
    async def scenario():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        uid = uuid.uuid4()
        async with factory() as db:
            db.add(User(id=uid, email=f"{uid}@test.local", name="snapshot", password_hash="x", client_id=uid.hex))
            await db.flush()
            db.add(PaperAccount(user_id=uid, cash=100, initial_cash=100))
            await db.commit()
            calls = []
            async def snapshot(db, uid, *, valuation_date, include_price_audits):
                assert include_price_audits
                calls.append(valuation_date)
                value = {19: 100, 20: 110, 21: 500, 22: 120, 23: 132}[valuation_date.day]
                if calls.count(date(2026, 10, 23)) > 1:
                    value = 999  # manual 요청이 daily 본문과 감사 행을 덮지 않아야 한다.
                meta = pricing.evidence("stock", "005930", value, "collector_close", valuation_date.isoformat())
                if valuation_date.day == 21:
                    meta["fallback"] = ["average_cost"]
                return {"cash": 0, "stockEval": value, "cryptoEval": 0, "alternativeEval": 0,
                        "totalAsset": value, "counts": {"stocks": 1}, "price_complete": True, "price_metadata": [meta],
                        "_price_audits": [{'asset_type':'stock','symbol':'005930','price_role':'valuation',
                            'used_price':value,'currency':'KRW','source':'collector_close','status':'delayed','fallback_used':False}]}
            monkeypatch.setattr(snapshots, "account_snapshot", snapshot)
            for d in range(19, 24):
                await snapshots.record_daily_snapshot(db, uid, snap_date=date(2026, 10, d))
                if d == 19:
                    from app.services import performance_service
                    insufficient = await performance_service.get_robo_metrics(db, uid)
                    assert insufficient["status"] == "insufficient_data"
                    assert await snapshots.snapshot_count(db, uid) == 1
            days, values, _ = await snapshots.get_daily_returns(db, uid, with_dates=True)
            assert days == ["2026-10-20", "2026-10-23"] and list(values) == pytest.approx([.1, .1])
            bad = await db.scalar(select(PaperAccountSnapshot).where(PaperAccountSnapshot.user_id == uid,
                                      PaperAccountSnapshot.snap_date == date(2026, 10, 21)))
            assert bad.completeness == "incomplete" and bad.price_metadata[0]["fallback"] == ["average_cost"]
            assert "price" not in bad.price_metadata[0]
            daily = await snapshots.record_daily_snapshot(db, uid, snap_date=date(2026, 10, 23), origin="manual")
            assert daily.origin == "daily" and daily.total_equity == 132
            assert len(calls) == 6  # 평가와 감사가 한 번의 조회를 공유한다.
            audit = await db.scalar(select(PaperSnapshotPriceAudit).where(PaperSnapshotPriceAudit.snapshot_id == daily.id))
            assert audit.used_price == 132
            first = await db.scalar(select(PaperAccountSnapshot).where(PaperAccountSnapshot.user_id == uid,
                                        PaperAccountSnapshot.snap_date == date(2026, 10, 19)))
            assert not first.return_valid
            from app.services import performance_service
            before = await snapshots.snapshot_count(db, uid)
            metrics = await performance_service.get_robo_metrics(db, uid)
            assert metrics["snap_dates"] == ["2026-10-19", "2026-10-20", "2026-10-22", "2026-10-23"]
            assert await snapshots.snapshot_count(db, uid) == before
            # 과거 complete 표지만 있고 종목별 근거가 없는 줄과 다른 회차는
            # 자산 배분·벤치마크에도 섞이지 않는다.
            db.add_all([
                PaperAccountSnapshot(user_id=uid, snap_date=date(2026, 10, 16), total_equity=999,
                    cash=999, position_count=0, epoch=2, origin="daily", completeness="complete"),
                PaperAccountSnapshot(user_id=uid, snap_date=date(2026, 10, 17), total_equity=999,
                    cash=0, position_count=1, epoch=1, origin="daily", completeness="complete"),
            ])
            await db.commit()
            allocation = await performance_service.get_allocation_history(db, uid)
            assert [r["date"] for r in allocation["series"]] == metrics["snap_dates"]
            monkeypatch.setattr("app.services.stock.get_candles", AsyncMock(return_value={"candles": [
                {"date": f"2026-10-{d}", "close": 100} for d in range(16, 24)]}))
            benchmark = await performance_service.get_benchmark_series(db, uid)
            # 성과 시계열은 실제 수익률이 계산된 날만 갖는다(첫 스냅샷은 기준점).
            assert benchmark["dates"] == ["2026-10-20", "2026-10-23"]
        await engine.dispose()
    asyncio.run(scenario())


@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PostgreSQL 필요")
@pytest.mark.usefixtures("rebalance_db_schema")
def test_deposit_is_excluded_from_snapshot_and_performance_returns(monkeypatch):
    """#612 — 같은 날 입금만으로 PAPER 일간·누적 수익률이 상승하지 않는다."""
    async def scenario():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        uid = uuid.uuid4()
        now = datetime.now(pricing.KST)
        today = now.date()
        previous_at = now - timedelta(days=1)
        async with factory() as db:
            db.add(User(id=uid, email=f"{uid}@test.local", name="cashflow",
                        password_hash="x", client_id=uid.hex))
            await db.flush()
            db.add(PaperAccount(user_id=uid, cash=109, initial_cash=100, epoch=1))
            db.add(PaperAccountSnapshot(
                user_id=uid, snap_date=today - timedelta(days=1), cash=100,
                position_value=0, total_equity=100, daily_return=0, position_count=0,
                stock_value=0, crypto_value=0, alt_value=0, epoch=1,
                snapshot_at=previous_at, completeness="complete", origin="daily",
                price_metadata=[], return_valid=False,
            ))
            db.add(CashflowEvent(
                user_id=uid, epoch=1, kind="DEPOSIT", amount=9,
                created_at=now - timedelta(hours=12), remaining_budget=0,
                cash_after=109, symbol="", memo="test deposit",
            ))
            await db.commit()

            async def snapshot(_db, _uid, **kwargs):
                return {"cash": 109.0, "stockEval": 0.0, "cryptoEval": 0.0,
                        "alternativeEval": 0.0, "totalAsset": 109.0,
                        "counts": {"stocks": 0, "crypto": 0, "alternatives": 0},
                        "price_complete": True, "price_metadata": [], "_price_audits": []}

            monkeypatch.setattr(snapshots, "account_snapshot", snapshot)
            monkeypatch.setattr(snapshots, "consecutive", lambda a, b: b == a + timedelta(days=1))
            current = await snapshots.record_daily_snapshot(db, uid, snap_date=today)
            assert current.daily_return == pytest.approx(0.0)
            assert current.return_valid
            await snapshots.record_daily_snapshot(db, uid, snap_date=today + timedelta(days=1))
            await snapshots.record_daily_snapshot(db, uid, snap_date=today + timedelta(days=2))

            dates, returns, equity = await snapshots.get_daily_returns(db, uid, with_dates=True)
            assert dates == [(today + timedelta(days=i)).isoformat() for i in (0, 1, 2)]
            assert returns.tolist() == pytest.approx([0.0, 0.0, 0.0])
            assert equity.tolist() == pytest.approx([100.0, 109.0, 109.0, 109.0])

            from app.services import performance_service
            table = await performance_service.get_returns_table(db, uid)
            assert table["return_cumulative"] == pytest.approx(0.0)
            assert table["return_basis"] == "modified_dietz_external_cashflows_excluded"
            metrics = await performance_service.get_robo_metrics(db, uid)
            assert metrics["total_return"] == pytest.approx(0.0)
        await engine.dispose()

    asyncio.run(scenario())


def test_missing_weekday_does_not_become_one_day_return(monkeypatch):
    monkeypatch.setattr(pricing.market_calendar, "trading_days", lambda *args: {"days": [
        {"date": f"2026-11-0{d}", "is_trading_day": True} for d in (2, 3, 4)]})
    assert not pricing.consecutive(date(2026, 11, 2), date(2026, 11, 4))


def test_educational_alternative_audit_does_not_require_live_feed():
    quote = asyncio.run(pt.alt_quote('RE-SEOUL', include_price_audit=True))
    assert quote['_price_audit']['fallback_used'] and quote['_price_audit']['status'] == 'demo'


@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PostgreSQL 필요")
@pytest.mark.usefixtures("rebalance_db_schema")
def test_turnover_uses_only_current_paper_epoch_orders():
    """#612 — 매매회전율에 과거 회차 및 회차 미확인 주문을 포함하지 않는다."""
    async def scenario():
        engine = create_async_engine(
            os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        uid = uuid.uuid4()
        async with factory() as db:
            db.add(User(
                id=uid, email=f"{uid}@test.local", name="turnover",
                password_hash="x", client_id=uid.hex,
            ))
            await db.flush()
            db.add(PaperAccount(user_id=uid, cash=1000, initial_cash=1000, epoch=2))
            db.add_all([
                Order(user_id=uid, symbol="AAA", name="current-buy",
                      order_type="buy", quantity=2, price=200, epoch=2, source="WEB"),
                Order(user_id=uid, symbol="BBB", name="current-sell",
                      order_type="sell", quantity=2, price=150, epoch=2, source="PINE"),
                Order(user_id=uid, symbol="CCC", name="old-buy",
                      order_type="buy", quantity=1, price=100, epoch=1, source="PAPER"),
                Order(user_id=uid, symbol="DDD", name="old-sell",
                      order_type="sell", quantity=1, price=100, epoch=1, source="REBALANCE"),
                Order(user_id=uid, symbol="EEE", name="legacy-buy",
                      order_type="buy", quantity=3, price=300, epoch=None, source="WEB"),
            ])
            await db.commit()

            from app.services.performance_service import get_turnover
            result = await get_turnover(db, uid)
            assert result["total_buy"] == 400.0
            assert result["total_sell"] == 300.0

        await engine.dispose()

    asyncio.run(scenario())
