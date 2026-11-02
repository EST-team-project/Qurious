"""#217/#364: 실제 ETF 수집 스키마, 후보 배분, 시간 경계 및 호가 계약."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import sqlite3
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.services import etf_allocation as allocation, etf_execution, product_etfs
from app.services.brokers import stock_coin_trade_gateway as gateway
from tests.test_asset_allocation import allocation_fixture
from tests.test_product_etfs import _make_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "market.sqlite3"
    _make_db(path)  # 실제 collector 스키마/20일 이상 ETF 고정물 재사용
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(path))
    product_etfs.clear_cache()
    yield path
    product_etfs.clear_cache()


def test_catalog_to_draft_preserves_every_asset_budget_and_inputs(db):
    source = allocation_fixture()
    before = deepcopy(source)
    catalog = product_etfs.selection_catalog()
    draft = allocation.build_draft(source, catalog, "2026-10-07")
    assert draft["status"] == "complete" and draft["cash_weight_pct"] == 4
    assert draft["unapplied_allocations"] == {}
    assert {t["symbol"]: t["weight_pct"] for t in draft["selected_etfs"]} == {
        "360750.KS": 26, "273130.KS": 29, "411060.KS": 10}
    assert sum(Decimal(str(t["weight_pct"])) for t in draft["targets"]) + Decimal(str(draft["cash_weight_pct"])) == 100
    assert source == before
    assert "상품명·기초지수" in draft["message"]


@pytest.mark.parametrize("invalid", [dict(halted=True), dict(halted=None), dict(trade_days_20d=19),
    dict(multiple=2), dict(single_stock=True), dict(derivative_group="single_stock"),
    dict(flags=["inverse"]), dict(flags=["futures"]), dict(flags=["synthetic"]),
    dict(flags=["option_income"]), dict(close=0), dict(aum=float("nan")), dict(trade_value_20d=0)])
def test_ineligible_candidates_leave_budget_in_cash_and_never_hide_products(db, invalid):
    catalog = product_etfs.selection_catalog()
    for item in catalog["items"]:
        if item["asset_class"] == "해외주식":
            item.update(invalid)
    draft = allocation.build_draft(allocation_fixture(), catalog, "2026-10-07")
    assert draft["status"] == "partial"
    assert draft["unapplied_allocations"] == {"해외주식": 26}
    assert draft["cash_weight_pct"] == 30
    assert not any(x["asset_class"] == "해외주식" for x in draft["selected_etfs"])
    assert any(x["asset_class"] == "해외주식" for x in catalog["items"])


def test_selection_ties_are_deterministic_and_old_catalog_is_rejected(db):
    catalog = product_etfs.selection_catalog()
    item = next(x for x in catalog["items"] if x["code"] == "360750")
    catalog["items"].append({**item, "code": "111111"})
    for items in (catalog["items"], list(reversed(catalog["items"]))):
        draft = allocation.build_draft(allocation_fixture(), {**catalog, "items": items}, "2026-10-07")
        assert next(x for x in draft["selected_etfs"] if x["asset_class"] == "해외주식")["symbol"] == "111111.KS"
    with pytest.raises(ValueError, match="확정 거래일"):
        allocation.build_draft(allocation_fixture(), catalog, "2026-10-08")


@pytest.mark.parametrize("hour,minute,expected", [(15, 29, "2026-10-30"), (15, 30, "2026-11-02")])
def test_confirmed_day_excludes_intraday_and_weekend(monkeypatch, hour, minute, expected):
    def days(start, end):
        return [x for x in [{"date": "2026-10-30", "is_trading_day": True},
                           {"date": "2026-10-31", "is_trading_day": False},
                           {"date": "2026-11-01", "is_trading_day": False},
                           {"date": "2026-11-02", "is_trading_day": True}] if x["date"] <= end.isoformat()]
    monkeypatch.setattr(allocation.rebalance_schedule, "days", days)
    assert allocation.confirmed_day(datetime(2026, 11, 2, hour, minute, tzinfo=allocation.KST)) == expected


def test_optional_latest_preview_is_read_only_and_preserves_saved_result(db, monkeypatch):
    from app.routes import ml
    source = allocation_fixture() | {"risk_profile": "moderate", "horizon_years": 4}
    saved = {"id": "saved-id", "saved_at": "2026-10-07T20:00:00+09:00", "result": source}
    loader = AsyncMock(side_effect=lambda *a: deepcopy(saved))
    monkeypatch.setattr(ml, "load_result", loader)
    def forbidden(*a, **kw):
        pytest.fail("미리보기는 저장·재계산하지 않는다")
    for name in ("save_result", "asset_allocation", "get_candles"):
        monkeypatch.setattr(ml, name, forbidden)
    monkeypatch.setattr(allocation, "confirmed_day", lambda: "2026-10-07")
    app = FastAPI()
    app.include_router(ml.router)
    app.dependency_overrides[ml.get_current_user] = lambda: {"id": "only-this-user"}
    app.dependency_overrides[ml.get_pg_session] = lambda: "session"
    with TestClient(app) as client:
        original = client.get("/api/ml/robo/allocation/latest").json()
        response = client.get("/api/ml/robo/allocation/latest?include_etfs=true")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["result"] == source and body["id"] == saved["id"]
        assert original["handoff"]["cash_weight_pct"] == 69
        assert body["handoff"]["cash_weight_pct"] == 4
        loader.assert_awaited_with("session", "only-this-user")
        monkeypatch.setattr(allocation, "confirmed_day", lambda: "2026-10-08")
        assert client.get("/api/ml/robo/allocation/latest?include_etfs=true").status_code == 409
        assert client.get("/api/ml/robo/allocation/latest").json() == original


@pytest.mark.parametrize("price,tick,buy,sell", [(1999.5, 1, 2000, 1999), (2000, 5, 2000, 2000),
    (2001, 5, 2005, 2000), (50001, 5, 50005, 50000), (500001, 5, 500005, 500000)])
def test_etf_tick_boundaries_and_equity_is_unchanged(price, tick, buy, sell):
    assert gateway.tick_size(int(price), is_etf=True) == tick
    assert gateway.align_price_to_tick(price, "buy", is_etf=True) == buy
    assert gateway.align_price_to_tick(price, "sell", is_etf=True) == sell
    assert gateway.align_price_to_tick(50001, "buy") == 50100


@pytest.mark.parametrize("hour,minute,warn", [(8, 59, False), (9, 0, True), (9, 4, True),
    (9, 5, False), (15, 19, False), (15, 20, True), (15, 29, True), (15, 30, False)])
def test_lp_boundaries_and_dated_close_nav_never_claim_live_inav(db, hour, minute, warn):
    result = etf_execution.describe("360750.KS", now=datetime(2026, 11, 2, hour, minute, tzinfo=allocation.KST))
    assert result["is_etf"] and bool(result["warnings"]) == warn
    assert result["premium_as_of"] == result["as_of"] == "2026-10-07"
    assert result["close_nav_premium_pct"] == pytest.approx(.05)
    assert etf_execution.describe("005930.KS")["classification"] == "unverified"


def test_missing_nav_does_not_fabricate_zero_premium_or_create_missing_db(db, monkeypatch, tmp_path):
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE etf_daily SET nav=NULL WHERE srtn_cd='360750'")
    assert "close_nav_premium_pct" not in etf_execution.describe("360750.KS")
    missing = tmp_path / "absent.sqlite3"
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(missing))
    assert not etf_execution.describe("360750.KS")["is_etf"]
    assert not missing.exists()
