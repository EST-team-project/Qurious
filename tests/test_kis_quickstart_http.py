"""HTTP 레벨: GET /api/quant/settings 가 가린 키만 내려보내는지, 원클릭 라우트 2개가 동작하는지 (TC-KQ).

강사님 9478811 판은 서버 관리 KIS(Secrets Manager)를 전제로 「사용자 키를 무시한다」 를 쟀다. Qurious 는 사용자마다
자기 키를 쓰므로(2026-10-03 결정 · app/services/kis_credentials.py) — 저장은 사용자 키를 남기고, 화면에는 가린 키만,
서버 관리 증권사 목록은 비어 있다. 원클릭 · 실전 차단 시험은 그대로 두되, 실전 차단은 실거래 승인이 있을 때만
성립한다(승인이 없으면 우리 관문이 real 을 paper 로 내린다 — tests/test_live_trading_guard.py 5절).
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.routes import stocks as sr
from app.services import kis_credentials as kc
from app.services import kis_quickstart as qs

UID = uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")


class Result:
    def __init__(self, one=None): self._one = one
    def scalar_one_or_none(self): return self._one


class FakeDb:
    def __init__(self, row=None): self.row, self.commits = row, 0
    def add(self, obj): self.row = obj
    async def flush(self): pass
    async def commit(self): self.commits += 1
    async def execute(self, stmt, *_a, **_k): return Result(one=self.row)


def kis_row():
    return SimpleNamespace(
        user_id=UID, broker="kis", quant_mode="paper", paper=True, app_key="USER-KEY-1234", app_secret="USER-SECRET",
        account_no="5012345601", quant_symbol_source="ai", quant_selected_symbols=[], quant_ai_top_n=3,
        quant_per_trade_budget=1_000_000.0, quant_buy_ratio=1.0, quant_sell_ratio=0.5,
        risk_daily_loss_limit_pct=3.0, risk_max_position_pct=30.0, risk_max_orders_per_day=20, risk_cooldown_min=30,
        risk_kill_switch=False, risk_halt_reason="", quant_auto_enabled=False, quant_strategy_id="", quant_strategy_version=0,
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "https://sct.test")
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_API_KEY", "key")
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_KIS_ENVIRONMENT", "paper")
    for k in ("KIS_SECRETS_NAME", "KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO"):
        monkeypatch.setattr(settings, k, "")
    kc.invalidate()
    db = FakeDb(kis_row())
    app = FastAPI()
    app.include_router(sr.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": str(UID), "email": "t@t"}
    app.dependency_overrides[get_pg_session] = lambda: db
    with patch.object(sr.strategy_loader, "is_configured", return_value=False), \
         patch.object(sr.strategy_loader, "list_strategies", AsyncMock(return_value=[])):
        yield TestClient(app), db
    kc.invalidate()


def test_get_quant_settings_가린_사용자_키만_내려간다(client):
    c, _db = client
    r = c.get("/api/quant/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["broker"] == "kis" and body["connected"] is True and body["app_key"] == "USER****"
    assert body["kis_managed"] is None and body["managed_brokers"] == []
    for secret in ("USER-KEY-1234", "USER-SECRET"):
        assert secret not in r.text


def test_post_quant_settings_KIS_도_사용자_키를_저장한다(client):
    c, db = client
    r = c.post("/api/quant/settings", json={"mode": "paper", "broker": "kis", "app_key": "NEW-KEY", "app_secret": "NEW-SECRET",
                                             "account_no": "999", "symbol_source": "ai"})
    assert r.status_code == 200, r.text
    assert (db.row.app_key, db.row.app_secret, db.row.account_no) == ("NEW-KEY", "NEW-SECRET", "999")
    assert db.commits == 1


def test_quickstart_readiness_and_start(client):
    c, db = client
    r = c.get("/api/quant/kis/quickstart")
    assert r.status_code == 200 and r.json()["ready"] is True and r.json()["route"] == "stock-coin-trade"
    with patch.object(qs.auto_trade, "start_auto_trade", AsyncMock(return_value=True)) as start, patch.object(qs, "audit", AsyncMock()):
        r = c.post("/api/quant/kis/quickstart")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["started"] and body["environment"] == "paper" and body["settings"]["symbol_source"] == "ai"
    assert db.row.quant_mode == "live" and db.row.broker == "kis" and db.row.quant_symbol_source == "ai"
    assert db.row.quant_per_trade_budget == 300_000.0 and db.row.risk_max_position_pct == 20.0
    assert db.row.app_key == "USER-KEY-1234"   # 우리 판은 원클릭이 사용자 키를 지우지 않는다
    start.assert_awaited_once()
    r = c.get("/api/quant/kis/quickstart")
    assert r.json()["already_started"] is False   # DB 플래그는 start_auto_trade(모킹)가 켜므로 여기선 False


def test_quickstart_409_when_real(client, monkeypatch, allow_live_trading):
    c, db = client
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_KIS_ENVIRONMENT", "real")
    r = c.post("/api/quant/kis/quickstart")
    assert r.status_code == 409 and "실전" in r.json()["detail"]
    assert db.row.quant_mode == "paper" and db.commits == 0


def test_quickstart_승인_없으면_real_설정도_모의로_시작한다(client, monkeypatch):
    c, _db = client
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_KIS_ENVIRONMENT", "real")
    r = c.get("/api/quant/kis/quickstart")
    assert r.json()["environment"] == "paper" and r.json()["ready"] is True
