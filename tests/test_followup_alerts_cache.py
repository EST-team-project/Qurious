"""#424 실제 삭제 경계, #468 확정 체결 알림 데이터·발송 실패 격리."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.models import DataCache
from app.services import auto_trade, data_cache, execution_alerts, notification


@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요")
@pytest.mark.usefixtures("rebalance_db_schema")
def test_prune_preserves_execution_state_and_recent_quotes_in_postgres(monkeypatch):
    async def run():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(data_cache, "get_session_factory", lambda: factory)
        old = datetime.now(timezone.utc) - timedelta(days=8)
        obsolete = {"candles:005930:1y:1d", "macro_indicators"}
        protected = {"quant:cycle_log:u", "quant:reconcile:baseline:u", "quant:last_beat_run",
                     "ai_predict:v4:x", "model_compare:abc", "candles_state:x", "unknown:state"}
        async with factory() as db:
            db.add_all([DataCache(key=k, data={"sentinel": k}, updated_at=old) for k in obsolete | protected])
            db.add(DataCache(key="candles:fresh", data={"sentinel": "fresh"}))
            await db.commit()
        dry = await data_cache.prune_external(dry_run=True)
        assert dry["would_delete"] == 2 and dry["deleted"] == 0
        async with factory() as db:
            assert len((await db.scalars(select(DataCache))).all()) == len(obsolete | protected) + 1
        assert (await data_cache.prune_external())["deleted"] == 2
        async with factory() as db:
            rows = (await db.scalars(select(DataCache))).all()
            assert {r.key for r in rows} == protected | {"candles:fresh"}
            assert all(r.data["sentinel"] == ("fresh" if r.key == "candles:fresh" else r.key) for r in rows)
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("failed", [False, True])
def test_committed_paper_fill_reports_costs_and_survives_alert_failure(monkeypatch, failed):
    send = AsyncMock(side_effect=RuntimeError("synthetic alert failure") if failed else None)
    monkeypatch.setattr(notification, "notify_auto_trade_executed", send)
    trade = {"status": "filled", "symbol": "005930.KS", "name": "삼성", "action": "buy", "quantity": 1,
             "price": 10000, "cash_balance": 89985, "cost": {"commission": 10, "fee_clearing": 5,
             "tax_transfer": 0, "tax_rural": 0, "net_amount": 10015, "cost_basis": "estimated"}}
    asyncio.run(auto_trade._report_execution(None, None, trade, "user", mode="paper"))
    details = dict(send.call_args.kwargs["details"])
    assert details["체결 후 가상 현금"] == "89,985.00원"
    assert details["거래세"] == "0.00원" and details["정산금액"] == "10,015.00원"
    assert trade["status"] == "filled"


def test_missing_alert_values_are_not_invented_and_optional_details_reach_event(monkeypatch):
    assert execution_alerts.fill_details({"cash_balance": float("nan")}) == []
    assert execution_alerts.risk_details({"orders_today": 1}, SimpleNamespace(max_orders_per_day=0)) == [
        ("당일 주문 수 / 상한", "1 / 제한 없음")]
    send = AsyncMock()
    monkeypatch.setattr(notification, "dispatch_event", send)
    asyncio.run(notification.notify_order_placed("005930", "buy", 1, 100, details=[("주문번호", "test-1")]))
    assert ("주문번호", "test-1") in send.call_args.args[0].fields
    asyncio.run(notification.notify_risk_skip("005930", "삼성", "buy", "limit", details=[("당일 손익", "-1%")]))
    assert ("당일 손익", "-1%") in send.call_args.args[0].fields
