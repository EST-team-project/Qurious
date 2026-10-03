"""레거시 직접 호출 경로(게이트웨이 미설정) — KIS 도 사용자 DB 키로, 승인 없이는 모의 서버로 (TC-KC · Qurious 2026-10-03).

강사님 9478811 의 같은 이름 시험은 「KIS 는 DB 키가 아니라 Secrets Manager 자격증명을 쓴다 · 서버 자격증명이 없으면
DB 에 키가 있어도 주문하지 않는다」 를 쟀다. Qurious 는 사용자마다 자기 키를 쓰므로 반대로 잰다 —
DB 키로 주문하고, 서버 .env 의 KIS 키는 무시하며, 실거래 승인이 없으면 팩토리에 모의(paper=True)를 요청한다.
"""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.services import auto_trade
from app.services import kis_credentials as kc

UID = uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "")
    for k in ("KIS_SECRETS_NAME", "KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO"):
        monkeypatch.setattr(settings, k, "")
    monkeypatch.setattr(settings, "KIS_ENVIRONMENT", "paper")
    kc.invalidate()
    yield
    kc.invalidate()


def _row(**over):
    base = dict(quant_mode="live", broker="kis", app_key="dbkey", app_secret="dbsec", account_no="dbacct")
    base.update(over)
    return SimpleNamespace(**base)


def _place(row):
    captured: dict = {}

    class FakeClient:
        async def place_order(self, account_no, symbol, side, quantity, price):
            captured["account_no"] = account_no
            return {"rt_cd": "0"}

    def fake_factory(broker, app_key, app_secret, paper):
        captured.update(broker=broker, app_key=app_key, app_secret=app_secret, paper=paper)
        return FakeClient()

    with patch.object(auto_trade, "get_broker_client", side_effect=fake_factory), \
         patch.object(auto_trade.notification, "notify_order_placed", AsyncMock()):
        out = asyncio.run(auto_trade._place_live_order(row, "005930.KS", "삼성전자", "buy", 1, 70_000.0, str(UID)))
    return out, captured


def test_KIS_는_사용자_DB_키로_주문하고_승인_없이는_모의를_요청한다():
    out, captured = _place(_row())
    assert out["status"] == "submitted"
    assert captured == {"broker": "kis", "app_key": "dbkey", "app_secret": "dbsec", "paper": True, "account_no": "dbacct"}


def test_서버_env_의_KIS_키는_주문에_쓰지_않는다(monkeypatch):
    monkeypatch.setattr(settings, "KIS_APP_KEY", "server-key")
    monkeypatch.setattr(settings, "KIS_APP_SECRET", "server-secret")
    monkeypatch.setattr(settings, "KIS_ACCOUNT_NO", "5012345601")
    _out, captured = _place(_row())
    assert captured["app_key"] == "dbkey" and captured["account_no"] == "dbacct"


def test_사용자_키가_없으면_주문하지_않는다():
    out, captured = _place(_row(app_key="", app_secret=""))
    assert out is None and captured == {}
