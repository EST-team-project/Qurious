"""DF-145: 화면에서 설정을 다시 저장해도 사용자 자격증명이 보존된다."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.routes import stocks

KEY, SECRET, ACCOUNT = "TEST-ORIGINAL-KEY", "TEST-ORIGINAL-SECRET", "12345678-01"
PATHS = ["/api/broker/settings", "/api/quant/settings"]


@pytest.fixture
def settings_client(monkeypatch):
    row = SimpleNamespace(broker="kis", app_key=KEY, app_secret=SECRET,
                          account_no=ACCOUNT, paper=True)
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(stocks, "_get_broker_settings_row", AsyncMock(return_value=row))
    monkeypatch.setattr(stocks, "_get_or_create_broker_settings_row", AsyncMock(return_value=row))
    monkeypatch.setattr(stocks, "audit", AsyncMock())
    app = FastAPI()
    app.include_router(stocks.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"}
    app.dependency_overrides[get_pg_session] = lambda: db
    with TestClient(app) as client:
        yield client, row, db


@pytest.mark.parametrize("path", PATHS)
def test_reload_then_save_keeps_real_credentials(settings_client, path):
    client, row, db = settings_client
    view = client.get("/api/broker/settings").json()
    assert view["app_key"] == KEY[:4] + "****"
    assert SECRET not in str(view) and KEY not in str(view)
    response = client.post(path, json={"broker": "kis", "app_key": view["app_key"],
                                      "app_secret": "", "account_no": view["account_no"]})
    assert response.status_code == 200
    assert (row.app_key, row.app_secret, row.account_no) == (KEY, SECRET, ACCOUNT)
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("credentials", [{}, {"app_key": "", "app_secret": "", "account_no": ""}])
def test_noncredential_settings_keep_same_broker_credentials(settings_client, path, credentials):
    client, row, _ = settings_client
    assert client.post(path, json={"broker": "kis", **credentials}).status_code == 200
    assert (row.app_key, row.app_secret, row.account_no) == (KEY, SECRET, ACCOUNT)


@pytest.mark.parametrize("path", PATHS)
def test_explicit_replacement_uses_new_key_pair(settings_client, path):
    client, row, _ = settings_client
    assert client.post(path, json={"broker": "kis", "app_key": "NEW-KEY",
                                  "app_secret": "NEW-SECRET", "account_no": "87654321-01"}).status_code == 200
    assert (row.app_key, row.app_secret, row.account_no) == ("NEW-KEY", "NEW-SECRET", "87654321-01")


@pytest.mark.parametrize("payload", [
    {"broker": "kis", "app_key": "WRNG****"},
    {"broker": "kis", "app_key": "NEW-KEY"},
    {"broker": "kb", "app_key": KEY[:4] + "****", "app_secret": ""},
])
@pytest.mark.parametrize("path", PATHS)
def test_invalid_or_foreign_mask_does_not_mutate_settings(settings_client, path, payload):
    client, row, db = settings_client
    before = vars(row).copy()
    response = client.post(path, json=payload)
    assert response.status_code == 422
    assert vars(row) == before
    db.commit.assert_not_awaited()
    assert KEY not in response.text and SECRET not in response.text


@pytest.mark.parametrize("broker", ["mock", "kb"])
@pytest.mark.parametrize("path", PATHS)
def test_switch_without_credentials_does_not_reuse_old_broker(settings_client, path, broker):
    client, row, _ = settings_client
    assert client.post(path, json={"broker": broker}).status_code == 200
    assert row.broker == broker
    assert (row.app_key, row.app_secret, row.account_no) == ("", "", "")


@pytest.mark.parametrize("path", PATHS)
def test_unauthenticated_save_never_loads_settings(settings_client, monkeypatch, path):
    client, _, db = settings_client
    client.app.dependency_overrides.pop(get_current_user)
    load = AsyncMock()
    monkeypatch.setattr(stocks, "_get_or_create_broker_settings_row", load)
    assert client.post(path, json={"broker": "kis"}).status_code == 401
    load.assert_not_awaited()
    db.commit.assert_not_awaited()
