"""국면 목표 갱신: 실제 SQLite·PostgreSQL, 주문 승인·잠금·롤백·계정 격리."""
import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta
import sqlite3
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import Order, RebalanceRun, RebalanceTargetChange
from app.routes import rebalance as routes
from app.services import allocation_store, asset_allocation, rebalance as rb, rebalance_regime as regime
from tests.test_rebalance_daily import clock, ready_data  # noqa: F401
from tests.test_rebalance_policy import scenario, needs_db

pytestmark = pytest.mark.usefixtures("rebalance_db_schema")
SYMBOLS = ("005930.KS", "000660.KS")
BASE = asset_allocation.asset_allocation("moderate", 3)


def source_result():
    return {
        "allocation_model": "regime",
        "allocations": {"국내주식": 33, "해외주식": 27.5, "국내채권": 25.3, "대체자산": 10, "현금": 4.2},
        "optimization": {"weights": {SYMBOLS[0]: 75, SYMBOLS[1]: 25}},
        "stock_picks": [{"code": s, "name": s} for s in SYMBOLS],
        "asset_model": {"model": "regime", "reference_allocations": BASE,
                        "regime": {"key": "up_low"}, "as_of": "2026-10-01"}}


@pytest.fixture
def proxy_data(ready_data):
    path = ready_data[0]
    end = date(2026, 10, 2)
    days = [end - timedelta(days=i) for i in range(240) if (end - timedelta(days=i)).weekday() < 5]
    with sqlite3.connect(path) as db:
        for asset, proxy in regime.models.ASSET_PROXIES.items():
            for i, day in enumerate(reversed(days)):
                # 국내주식 하락·저변동, 나머지는 양의 비상수 수익률.
                close = 20000 * (.999 ** i if asset == "국내주식" else 1.0003 ** i)
                db.execute("INSERT INTO etf_daily (bas_dt,srtn_cd,clpr,mkp,hipr,lopr,trqu) VALUES (?,?,?,?,?,?,?)",
                           (day.strftime("%Y%m%d"), proxy["symbol"][:6], close, close, close, close, 1000))
    return path


async def enable(db, uid, *, auto=False, result=None):
    result = result or source_result()
    saved = await allocation_store.save_result(db, uid, result)
    plan = await rb.get_plan(db, uid)
    await db.commit()
    await db.refresh(plan)
    body = routes.PlanBody(
        expected_updated_at=plan.updated_at, targets=asset_allocation.rebalance_draft(result)["targets"],
        drift_enabled=True, auto_execute=auto,
        regime_auto=routes.RegimeAutoBody(enabled=True, allocation_id=saved["id"]))
    await routes.update_plan(body, {"id": str(uid)}, db)
    return await rb.get_plan(db, uid)


def test_collector_regime_is_fresh_and_future_bars_do_not_change_it(clock, proxy_data):
    config = {"baseline": BASE}
    before = proxy_data.read_bytes()
    first = regime.calculate(config, date(2026, 10, 2))
    assert first["regime"]["key"] == "down_low"
    assert first["allocations"]["국내주식"] == 22.5
    assert proxy_data.read_bytes() == before
    with sqlite3.connect(proxy_data) as db:
        db.executemany("INSERT INTO etf_daily (bas_dt,srtn_cd,clpr) VALUES ('20261006',?,999999)",
                       [(p["symbol"][:6],) for p in regime.models.ASSET_PROXIES.values()])
    assert regime.calculate(config, date(2026, 10, 2)) == first


@needs_db
@pytest.mark.parametrize("auto", [False, True])
def test_changed_regime_updates_targets_and_existing_approval_policy(monkeypatch, clock, proxy_data, auto):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await enable(db, uid, auto=auto)
                before = deepcopy(plan.targets)
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
                result = await rb.check_daily(db, uid, plan)
                await db.commit()
                assert result["checked"] and result["regime_auto"]["status"] == "changed"
                assert sum(t["weight_pct"] for t in plan.targets) == 22.5
                # 같은 나머지 0.005%p는 종목코드 오름차순으로 배정한다.
                weights = {t["symbol"]: t["weight_pct"] for t in plan.targets}
                assert weights == {SYMBOLS[0]: 16.87, SYMBOLS[1]: 5.63}
                assert set(t["symbol"] for t in before) == set(t["symbol"] for t in plan.targets)
                assert result["status"] == ("scheduled" if auto else "proposed")
                assert (await rb.pt.get_account(db, uid)).cash == 200000
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
                history = await regime.history(db, uid)
                assert len(history) == 1 and history[0]["before_targets"] == before
                assert history[0]["evidence"]["to_regime"] == "down_low"
                run = await db.get(RebalanceRun, uuid.UUID(result["run_id"]))
                assert run.context["regime_change_id"] == history[0]["id"]
                assert (await rb.check_daily(db, uid, plan))["reason"] == "already_checked"
                assert len(await regime.history(db, uid)) == 1
                assert await regime.history(db, uuid.uuid4()) == []
    asyncio.run(go())


@needs_db
def test_disabled_or_same_regime_preserves_targets(monkeypatch, clock, proxy_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                before = deepcopy(plan.targets)
                r = await rb.check_daily(db, uid, plan)
                assert r["regime_auto"]["status"] == "disabled" and plan.targets == before
                await db.rollback()
                source = source_result()
                calculated = regime.calculate({"baseline": BASE}, date(2026, 10, 2))
                source["allocations"] = calculated["allocations"]
                source["asset_model"]["regime"] = calculated["regime"]
                plan = await enable(db, uid, result=source)
                before = deepcopy(plan.targets)
                r = await rb.check_daily(db, uid, plan)
                await db.commit()
                assert r["regime_auto"]["status"] == "unchanged" and plan.targets == before
                assert not await regime.history(db, uid)
    asyncio.run(go())


@needs_db
@pytest.mark.parametrize("bad", ["missing", "stale", "invalid", "short"])
def test_unusable_data_keeps_targets_orders_and_daily_gate(monkeypatch, clock, proxy_data, bad):
    with sqlite3.connect(proxy_data) as db:
        if bad == "missing":
            db.execute("DELETE FROM etf_daily WHERE srtn_cd='069500'")
        elif bad == "stale":
            db.execute("DELETE FROM etf_daily WHERE srtn_cd='069500' AND bas_dt='20261002'")
        elif bad == "invalid":
            db.execute("UPDATE etf_daily SET clpr=0 WHERE srtn_cd='069500' AND bas_dt='20261002'")
        else:
            db.execute("DELETE FROM etf_daily WHERE bas_dt<'20260901'")
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await enable(db, uid, auto=True)
                before = deepcopy(plan.targets)
                result = await routes.check({"id": str(uid)}, db)
                assert result["reason"] == "regime_waiting"
                plan = await rb.get_plan(db, uid)
                assert plan.targets == before and plan.last_auto_check_date is None
                assert plan.regime_state["status"] == "waiting"
                assert not await regime.history(db, uid)
                assert await db.scalar(select(func.count(RebalanceRun.id)).where(RebalanceRun.user_id == uid)) == 0
                assert await db.scalar(select(func.count(Order.id)).where(Order.user_id == uid)) == 0
    asyncio.run(go())


@needs_db
def test_pending_reservation_keeps_its_targets(monkeypatch, clock, proxy_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await enable(db, uid)
                run = await rb.execute(db, uid, plan, "MANUAL")
                before = deepcopy(plan.targets)
                await db.commit()
                result = await rb.check_daily(db, uid, plan)
                assert result["reason"] == "settlement_waiting"
                assert plan.targets == before and run.status == "scheduled"
                assert not await regime.history(db, uid)
    asyncio.run(go())


@needs_db
def test_failure_after_target_change_rolls_back_history_and_plan(monkeypatch, clock, proxy_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await enable(db, uid)
                before = deepcopy(plan.targets)
                async def fail(*args, **kwargs):
                    raise rb.RebalanceError("제안 계산 실패")
                monkeypatch.setattr(rb, "propose", fail)
                with pytest.raises(HTTPException):
                    await routes.check({"id": str(uid)}, db)
                plan = await rb.get_plan(db, uid)
                assert plan.targets == before and plan.regime_state["regime"] == "up_low"
                assert not await regime.history(db, uid)
    asyncio.run(go())


@needs_db
def test_concurrent_daily_checks_make_one_change_and_proposal(monkeypatch, clock, proxy_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                await enable(db, uid)
                await db.commit()
            async def check():
                async with factory() as db:
                    plan = await rb.get_plan(db, uid)
                    r = await rb.check_daily(db, uid, plan)
                    await db.commit()
                    return r
            results = await asyncio.gather(check(), check())
            assert sum(bool(r["checked"]) for r in results) == 1
            async with factory() as db:
                assert len(await regime.history(db, uid)) == 1
                assert await db.scalar(select(func.count(RebalanceRun.id)).where(RebalanceRun.user_id == uid)) == 1
    asyncio.run(go())


@needs_db
def test_stale_editor_cannot_overwrite_automatic_change_and_manual_edit_requires_disable(monkeypatch, clock, proxy_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await enable(db, uid)
                old_version, old_targets = plan.updated_at, deepcopy(plan.targets)
                await db.commit()
            async with factory() as db:
                await rb.check_daily(db, uid, await rb.get_plan(db, uid))
                await db.commit()
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await routes.update_plan(routes.PlanBody(expected_updated_at=old_version, targets=old_targets,
                        regime_auto=routes.RegimeAutoBody(enabled=False)), {"id": str(uid)}, db)
                assert exc.value.status_code == 409
                plan = await rb.get_plan(db, uid)
                version = plan.updated_at
                with pytest.raises(HTTPException) as exc:
                    await routes.update_plan(routes.PlanBody(expected_updated_at=version, targets=old_targets),
                                             {"id": str(uid)}, db)
                assert exc.value.status_code == 409
                result = await routes.update_plan(routes.PlanBody(expected_updated_at=version, targets=old_targets,
                    regime_auto=routes.RegimeAutoBody(enabled=False)), {"id": str(uid)}, db)
                assert not result["regime_auto"]["enabled"]
                assert result["targets"] == old_targets
                assert len(await regime.history(db, uid)) == 1
    asyncio.run(go())


@needs_db
def test_binding_rejects_other_user_old_or_nonregime_results(monkeypatch, clock, proxy_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await rb.get_plan(db, uid)
                await db.commit()
                await db.refresh(plan)
                version = plan.updated_at
                with pytest.raises(HTTPException) as exc:
                    await routes.update_plan(routes.PlanBody(expected_updated_at=version,
                        regime_auto=routes.RegimeAutoBody(enabled=True, allocation_id=uuid.uuid4())),
                        {"id": str(uid)}, db)
                assert exc.value.status_code == 409
                source = source_result()
                source["allocation_model"] = "risk_parity"
                with pytest.raises(HTTPException) as exc:
                    await enable(db, uid, result=source)
                assert exc.value.status_code == 400
                assert not (await rb.get_plan(db, uid)).regime_config
    asyncio.run(go())


def test_confirmed_etf_mapping_and_unapplied_cash_stay_fixed(clock, proxy_data):
    config = {"baseline": BASE, "stock_weights": {SYMBOLS[0]: 75, SYMBOLS[1]: 25},
              "stock_picks": source_result()["stock_picks"],
              "etfs": [{"asset_class": "해외주식", "symbol": "360750.KS", "name": "확인한 ETF"}]}
    result = regime.calculate(config, date(2026, 10, 2))
    targets = regime.mapped_targets(config, result["allocations"])
    weights = {t["symbol"]: t["weight_pct"] for t in targets}
    assert weights["360750.KS"] == result["allocations"]["해외주식"]
    assert set(weights) == {*SYMBOLS, "360750.KS"}
    assert round(100 - sum(weights.values()), 2) == round(sum(
        result["allocations"][k] for k in ("국내채권", "대체자산", "현금")), 2)


@needs_db
def test_source_generation_change_waits_and_retry_can_succeed(monkeypatch, clock, proxy_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await enable(db, uid)
                before = deepcopy(plan.targets)
                original = regime.calculate
                original_readiness = rb.daily.readiness
                def replaced(*args):
                    result = original(*args)
                    monkeypatch.setattr(rb.daily, "readiness", lambda: {
                        **original_readiness(), "source_commit": "changed_generation"})
                    return result
                monkeypatch.setattr(regime, "calculate", replaced)
                r = await rb.check_daily(db, uid, plan)
                await db.commit()
                assert r["reason"] == "regime_waiting" and plan.targets == before
                assert not await regime.history(db, uid)
                assert plan.last_auto_check_date is None
                monkeypatch.setattr(regime, "calculate", original)
                r = await rb.check_daily(db, uid, plan)
                await db.commit()
                assert r["checked"] and len(await regime.history(db, uid)) == 1
    asyncio.run(go())


@needs_db
def test_saved_result_replacement_does_not_rebind_enabled_plan(monkeypatch, clock, proxy_data):
    async def go():
        async with scenario(monkeypatch, symbols=SYMBOLS) as (factory, uid):
            async with factory() as db:
                plan = await enable(db, uid)
                original_source = plan.regime_config["source_id"]
                replacement = source_result()
                replacement["asset_model"]["reference_allocations"] = asset_allocation.asset_allocation("aggressive", 3)
                replacement["optimization"]["weights"] = {SYMBOLS[0]: 20, SYMBOLS[1]: 80}
                await allocation_store.save_result(db, uid, replacement)
                await db.commit()
                r = await rb.check_daily(db, uid, plan)
                await db.commit()
                assert r["checked"]
                assert sum(t["weight_pct"] for t in plan.targets) == 22.5
                assert plan.regime_config["source_id"] == original_source
                assert (await allocation_store.load_result(db, uid))["result"] == replacement
    asyncio.run(go())
