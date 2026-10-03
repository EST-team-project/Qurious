"""통합 대시보드 「KIS 모의투자 시작」 원클릭: 경로 판정, 차단 조건, 설정 저장 + 자동매매 ON. (TC-KQ)

Qurious(2026-10-03 반영): 강사님 판은 서버 관리 KIS(Secrets Manager)로 시작하고 사용자 키를 지운다. 우리 판은 그
사용자의 KIS 키로 시작하고 키를 남긴다(kis_credentials 머리말) — 그 둘을 재는 시험만 바꿨다. 「실전이면 막는다」 는
실거래 승인이 있을 때만 성립한다(승인이 없으면 관문이 real 을 paper 로 내린다)."""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.models import BrokerSettings
from app.services import kis_credentials as kc
from app.services import kis_quickstart as qs

UID = uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")


class Result:
    def __init__(self, one=None): self._one = one
    def scalar_one_or_none(self): return self._one


class FakeDb:
    def __init__(self, row=None):
        self.row, self.added, self.commits = row, [], 0
    def add(self, obj): self.added.append(obj); self.row = obj
    async def commit(self): self.commits += 1
    async def execute(self, stmt, *_a, **_k):
        return Result(one=self.row)


def row(**over):
    base = dict(user_id=UID, broker="mock", quant_mode="paper", paper=True, app_key="k", app_secret="s", account_no="a",
                quant_symbol_source="manual", quant_selected_symbols=["005930.KS"], quant_ai_top_n=1,
                quant_per_trade_budget=1_000_000.0, quant_buy_ratio=1.0, quant_sell_ratio=0.5,
                risk_daily_loss_limit_pct=3.0, risk_max_position_pct=30.0, risk_max_orders_per_day=20, risk_cooldown_min=30,
                risk_kill_switch=False, risk_halt_reason="", quant_auto_enabled=False)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "https://sct.test")
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_API_KEY", "key")
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_KIS_ENVIRONMENT", "paper")
    for k in ("KIS_SECRETS_NAME", "KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO"):
        monkeypatch.setattr(settings, k, "")
    kc.invalidate()
    yield
    kc.invalidate()


def _patches(started=True):
    return (patch.object(qs.auto_trade, "start_auto_trade", AsyncMock(return_value=started)),
            patch.object(qs, "audit", AsyncMock()))


def test_readiness_ready_via_gateway_paper():
    st = asyncio.run(qs.readiness(FakeDb(None), UID))
    assert st["ready"] and st["route"] == "stock-coin-trade" and st["environment"] == "paper"
    assert st["running"] is False and st["already_started"] is False
    assert st["defaults"]["quant_per_trade_budget"] == 300_000.0 and st["defaults"]["risk_max_position_pct"] == 20.0


def test_readiness_blocked_when_nothing_connected(monkeypatch):
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "")
    st = asyncio.run(qs.readiness(FakeDb(None), UID))
    assert st["ready"] is False and st["reason"] == "not_connected" and st["connected"] is False


def test_readiness_blocked_when_gateway_is_real(monkeypatch, allow_live_trading):
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_KIS_ENVIRONMENT", "real")
    st = asyncio.run(qs.readiness(FakeDb(None), UID))
    assert st["ready"] is False and st["reason"] == "real_environment"


def test_readiness_승인_없으면_게이트웨이_real_도_모의다(monkeypatch):
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_KIS_ENVIRONMENT", "real")
    st = asyncio.run(qs.readiness(FakeDb(None), UID))
    assert st["ready"] is True and st["environment"] == "paper"


def test_readiness_uses_user_kis_keys_when_no_gateway(monkeypatch):
    """게이트웨이가 없으면 그 사용자의 KIS 키(종목 선정 화면에 넣은 것)로 직접 — 서버 계좌는 없다."""
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "")
    monkeypatch.setattr(settings, "KIS_APP_KEY", "server-key")      # 서버 .env 키는 무시된다
    monkeypatch.setattr(settings, "KIS_APP_SECRET", "server-secret")
    st = asyncio.run(qs.readiness(FakeDb(row(broker="kis")), UID))
    assert st["ready"] and st["route"] == "kis-direct" and st["environment"] == "paper"
    st2 = asyncio.run(qs.readiness(FakeDb(row(broker="kis", app_key="", app_secret="")), UID))
    assert st2["ready"] is False and st2["reason"] == "not_connected"


def test_readiness_already_started_and_kill_switch():
    st = asyncio.run(qs.readiness(FakeDb(row(broker="kis", quant_mode="live", quant_auto_enabled=True)), UID))
    assert st["already_started"] is True and st["running"] is True
    st2 = asyncio.run(qs.readiness(FakeDb(row(risk_kill_switch=True, risk_halt_reason="일손실")), UID))
    assert st2["ready"] is False and st2["reason"] == "kill_switch" and st2["kill_reason"] == "일손실"


def test_start_creates_row_applies_testbed_defaults_and_enables():
    db = FakeDb(None)
    p1, p2 = _patches(started=True)
    with p1 as start, p2 as audit:
        out = asyncio.run(qs.start(db, str(UID)))
    r = db.row
    assert isinstance(r, BrokerSettings) and db.commits == 1
    assert (r.broker, r.quant_mode, r.paper, r.quant_symbol_source, r.quant_ai_top_n) == ("kis", "live", False, "ai", 3)
    assert r.quant_per_trade_budget == 300_000.0 and r.risk_max_position_pct == 20.0 and r.risk_max_orders_per_day == 10
    assert not (r.app_key or r.app_secret or r.account_no)   # 새 행(게이트웨이 길) — 키를 만들지 않는다
    start.assert_awaited_once_with(db, str(UID))
    audit.assert_awaited_once()
    assert out["ok"] and out["started"] and out["route"] == "stock-coin-trade" and out["settings"]["symbol_source"] == "ai"


def test_start_on_existing_row_keeps_user_keys_and_reports_already_running():
    db = FakeDb(row(quant_auto_enabled=True))
    p1, p2 = _patches(started=False)
    with p1, p2:
        out = asyncio.run(qs.start(db, str(UID)))
    assert db.added == [] and db.row.broker == "kis" and db.row.quant_mode == "live"
    assert (db.row.app_key, db.row.app_secret, db.row.account_no) == ("k", "s", "a")   # 우리 판: 사용자 키를 남긴다
    assert db.row.quant_selected_symbols == []
    assert out["started"] is False and out["already_running"] is True


def test_start_blocked_not_connected(monkeypatch):
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "")
    db = FakeDb(None)
    with pytest.raises(qs.QuickstartBlocked) as ei:
        asyncio.run(qs.start(db, str(UID)))
    assert ei.value.reason == "not_connected" and db.commits == 0


def test_start_blocked_real_environment(monkeypatch, allow_live_trading):
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_KIS_ENVIRONMENT", "real")
    db = FakeDb(row())
    with pytest.raises(qs.QuickstartBlocked) as ei:
        asyncio.run(qs.start(db, str(UID)))
    assert ei.value.reason == "real_environment" and db.commits == 0 and db.row.broker == "mock"


def test_start_blocked_kill_switch():
    db = FakeDb(row(risk_kill_switch=True, risk_halt_reason="수동"))
    with pytest.raises(qs.QuickstartBlocked) as ei:
        asyncio.run(qs.start(db, str(UID)))
    assert ei.value.reason == "kill_switch" and db.commits == 0


def test_route_returns_409_on_block(monkeypatch):
    from fastapi import HTTPException
    from app.routes import stocks as sr
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(sr.kis_quickstart_start(user={"id": str(UID)}, db=FakeDb(None)))
    assert ei.value.status_code == 409 and "KIS 키가 없습니다" in ei.value.detail
