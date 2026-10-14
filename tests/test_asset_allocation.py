"""배분 공통 비중·국내주식 전달·계정별 실제 PG 저장 계약."""
import asyncio
from copy import deepcopy
from decimal import Decimal
import os
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.asset_allocation import PROFILES, asset_allocation, rebalance_draft


@pytest.mark.parametrize("risk", PROFILES)
@pytest.mark.parametrize("years", range(1, 11))
def test_weights_are_nonnegative_complete_and_preserve_safe_previous_results(risk, years):
    got = asset_allocation(risk, years)
    assert set(got) == {"국내주식", "해외주식", "국내채권", "대체자산", "현금"}
    assert sum(got.values()) == 100 and min(got.values()) >= 0
    old = PROFILES[risk].copy()
    boost = min(6, max(0, years - 3))
    old["국내주식"] += boost
    old["해외주식"] += boost
    old["국내채권"] -= boost
    old["현금"] -= boost
    if min(old.values()) >= 0:
        assert got == old
    got["현금"] = -999
    assert asset_allocation(risk, years)["현금"] >= 0


@pytest.mark.parametrize("risk,years", [("invalid", 3), ("moderate", 0), ("moderate", 11), ("moderate", True)])
def test_invalid_inputs(risk, years):
    with pytest.raises(ValueError):
        asset_allocation(risk, years)


def allocation_fixture():
    return {"allocations": asset_allocation("moderate", 4),
            "optimization": {"weights": {"005930.KS": 33.3, "000660.KS": 33.3, "035420.KS": 33.3}},
            "stock_picks": [{"code": "005930.KS", "name": "삼성전자"}]}


def test_draft_preserves_domestic_budget_and_names_without_mutating_result():
    source = allocation_fixture()
    before = deepcopy(source)
    draft = rebalance_draft(source)
    assert sum(Decimal(str(t["weight_pct"])) for t in draft["targets"]) == Decimal(31)
    assert draft["cash_weight_pct"] == 69
    assert draft["unapplied_allocations"] == {"해외주식": 26, "국내채권": 29, "대체자산": 10}
    assert draft["original_cash_weight_pct"] == 4
    assert next(t for t in draft["targets"] if t["symbol"] == "005930.KS")["name"] == "삼성전자"
    assert source == before


@pytest.mark.parametrize("weights", [{}, {"AAPL": 100}, {"005930.KS": -1}, {"005930.KS": 0},
                                     {"005930.KS": float("nan")}, {"005930.KS": float("inf")}])
def test_unsupported_or_invalid_optimizer_cannot_be_imported(weights):
    source = allocation_fixture()
    source["optimization"]["weights"] = weights
    with pytest.raises(ValueError):
        rebalance_draft(source)


def test_light_api_auth_validation_and_no_market_or_database_calls(monkeypatch):
    from app.routes import ml
    app = FastAPI()
    app.include_router(ml.router)
    def forbidden(*args, **kwargs):
        pytest.fail("비중 조회는 시장/DB를 호출하지 않는다")
    monkeypatch.setattr(ml, "get_candles", forbidden)
    monkeypatch.setattr(ml, "cache_get", forbidden)
    app.dependency_overrides[ml.get_pg_session] = forbidden
    with TestClient(app) as client:
        assert client.get("/api/ml/robo/weights").status_code == 401
        app.dependency_overrides[ml.get_current_user] = lambda: {"id": str(uuid.uuid4())}
        response = client.get("/api/ml/robo/weights?risk_profile=aggressive&horizon_years=10")
        assert response.status_code == 200
        assert response.json()["allocations"] == asset_allocation("aggressive", 10)
        for query in ("risk_profile=unknown", "horizon_years=11", "horizon_years=0"):
            assert client.get("/api/ml/robo/weights?" + query).status_code == 422


@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요")
@pytest.mark.usefixtures("rebalance_db_schema")
def test_calculate_save_reload_isolation_failure_and_no_plan_or_order_mutation(monkeypatch):
    from app.routes import ml
    from app.models import User, AllocationResult, RebalancePlan, RebalanceRun, Order
    from app.services.allocation_store import save_result
    from app.services.account import delete_user_data
    from tests.conftest import make_candles

    async def go():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        uids = [uuid.uuid4(), uuid.uuid4()]
        user = {"id": str(uids[0])}
        async def session():
            async with factory() as db:
                yield db
        async def candles(*args, **kwargs):
            return {"candles": make_candles(100)}
        async def cached(*args, **kwargs):
            return {"pred_ann_return_pct": 5, "confidence": .6}
        monkeypatch.setattr(ml, "QUANT_STOCKS", [{"symbol": "005930.KS", "name": "삼성전자"}])
        monkeypatch.setattr(ml, "get_candles", candles)
        monkeypatch.setattr(ml, "cache_get", cached)
        monkeypatch.setattr(ml, "optimize_portfolio", lambda *a: {
            "weights": {"005930.KS": 100}, "expected_return_pct": 5, "expected_volatility_pct": 15})
        app = FastAPI()
        app.include_router(ml.router)
        app.dependency_overrides[ml.get_current_user] = lambda: user
        app.dependency_overrides[ml.get_pg_session] = session
        async with factory() as db:
            db.add_all([User(id=u, name="배분 시험", email=f"{u}@example.com", password_hash="test", client_id=u.hex) for u in uids])
            await db.commit()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.get("/api/ml/robo/allocation/latest")).status_code == 404
                response = await client.post("/api/ml/robo/allocation", json={"risk_profile": "aggressive", "horizon_years": 10})
                assert response.status_code == 200, response.text
                result = response.json()
                assert result["stock_picks"][0]["weight"] == 47
                saved = (await client.get("/api/ml/robo/allocation/latest")).json()
                assert saved["id"] == result["saved"]["id"]
                assert saved["result"] == {k: v for k, v in result.items() if k != "saved"}
                assert saved["handoff"]["targets"][0]["weight_pct"] == 47
                user["id"] = str(uids[1])
                assert (await client.get("/api/ml/robo/allocation/latest")).status_code == 404
                user["id"] = str(uids[0])
                second = (await client.post("/api/ml/robo/allocation", json={"risk_profile": "moderate"})).json()
                assert second["saved"]["id"] != saved["id"]
                async def empty(*args, **kwargs):
                    return {"candles": []}
                monkeypatch.setattr(ml, "get_candles", empty)
                assert (await client.post("/api/ml/robo/allocation", json={})).status_code == 422
                assert (await client.get("/api/ml/robo/allocation/latest")).json()["id"] == second["saved"]["id"]
                # 실패한 트랜잭션 및 비정상 숫자가 이전 결과를 덮어쓰지 않는다.
                async with factory() as db:
                    await save_result(db, uids[0], allocation_fixture())
                    await db.rollback()
                    with pytest.raises(ValueError):
                        await save_result(db, uids[0], {"bad": float("nan")})
                assert (await client.get("/api/ml/robo/allocation/latest")).json()["id"] == second["saved"]["id"]
            async with factory() as db:
                assert await db.scalar(select(func.count()).select_from(AllocationResult)) == 1
                for model in (RebalancePlan, RebalanceRun, Order):
                    assert await db.scalar(select(func.count()).select_from(model).where(model.user_id.in_(uids))) == 0
                await delete_user_data(db, uids[0])
                await db.commit()
                assert await db.get(AllocationResult, uids[0]) is None
        finally:
            async with factory() as db:
                for uid in uids:
                    await delete_user_data(db, uid)
                await db.commit()
            await engine.dispose()
    asyncio.run(go())
