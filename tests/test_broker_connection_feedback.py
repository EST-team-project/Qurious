"""#232: 실제 KIS 응답 → HTTP 안내, 현재가 확인 범위와 인증 정보 비노출."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.routes import stocks
from app.services.brokers import kis
from app.services.brokers.kis_token import KISTokenError

PATHS = ["/api/broker/price?symbol=005930.KS", "/api/broker/test"]
SECRET = "SECRET-MUST-NOT-LEAK"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(stocks.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"}
    app.dependency_overrides[get_pg_session] = lambda: None
    with TestClient(app) as client:
        yield client


def upstream(monkeypatch, phase, status, body):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        assert request.method in ("GET", "POST")
        is_token = request.url.path == "/oauth2/tokenP"
        if (phase == "token") == is_token:
            if body == "timeout": raise httpx.ReadTimeout(SECRET, request=request)
            if body == "html": return httpx.Response(status, text=SECRET)
            return httpx.Response(status, json=body)
        assert is_token, "A failed token must not be followed by a quote"
        return httpx.Response(200, json={"access_token": "TEST-TOKEN", "expires_in": 86400})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(kis.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    async def token(_key, issue): return await issue()
    monkeypatch.setattr(kis, "shared_token", token)
    monkeypatch.setattr(stocks, "_get_broker_client", AsyncMock(return_value=kis.KISClient("TEST-KEY", SECRET)))
    return calls


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("phase,status,body,code", [
    ("token", 403, {"error_code": "EGW00133"}, "TOKEN_RATE_LIMIT"),
    ("token", 403, {"error_code": "EGW00103"}, "INVALID_CREDENTIALS"),
    ("token", 403, {"error_code": "EGW00105"}, "INVALID_CREDENTIALS"),
    ("token", 401, {}, "BROKER_AUTH_REJECTED"),
    ("token", 403, {"error_description": SECRET}, "BROKER_AUTH_REJECTED"),
    ("token", 403, "html", "BROKER_AUTH_REJECTED"),
    ("token", 429, {}, "QUOTE_RATE_LIMIT"),
    ("token", 503, "html", "TOKEN_UNAVAILABLE"),
    ("token", 200, [], "TOKEN_UNAVAILABLE"),
    ("token", 200, "timeout", "QUOTE_TIMEOUT"),
    ("quote", 200, {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": SECRET}, "QUOTE_RATE_LIMIT"),
    ("quote", 401, {}, "BROKER_AUTH_REJECTED"),
    ("quote", 403, {}, "BROKER_AUTH_REJECTED"),
    ("quote", 429, {}, "QUOTE_RATE_LIMIT"),
    ("quote", 503, {"error": SECRET}, "QUOTE_UNAVAILABLE"),
    ("quote", 200, "timeout", "QUOTE_TIMEOUT"),
    ("quote", 200, {"rt_cd": "0", "output": {"stck_prpr": "0"}}, "QUOTE_UNAVAILABLE"),
    ("quote", 200, {"rt_cd": "0", "output": {"stck_prpr": "NaN"}}, "QUOTE_UNAVAILABLE"),
])
def test_upstream_failures_are_actionable_without_leaking(client, monkeypatch, caplog, path, phase, status, body, code):
    calls = upstream(monkeypatch, phase, status, body)
    result = client.get(path)
    # Upstream 401 must not become the user's session-expired 401.
    assert result.status_code == 502
    detail = result.json()["detail"]
    assert detail["code"] == code
    assert detail["scope"] == "quote" and detail["account_verified"] is False
    assert detail["message"] and detail["hint"]
    if code == "TOKEN_RATE_LIMIT":
        assert detail["retry_after_seconds"] == 60 and "1분 뒤" in detail["hint"]
    else:
        assert detail["retry_after_seconds"] is None and "1분 뒤" not in detail["hint"]
    for raw in (SECRET, "TEST-KEY", "TEST-TOKEN", "https://", "Forbidden", "developer.mozilla.org"):
        assert raw not in result.text and raw not in caplog.text
    assert len(calls) == (1 if phase == "token" else 2)
    assert all(p in ("/oauth2/tokenP", "/uapi/domestic-stock/v1/quotations/inquire-price") for p in calls)


@pytest.mark.parametrize("path", PATHS)
def test_success_only_verifies_quote(client, monkeypatch, path):
    upstream(monkeypatch, "quote", 200, {"rt_cd": "0", "output": {"stck_prpr": "72000", "hts_kor_isnm": "삼성전자"}})
    result = client.get(path)
    assert result.status_code == 200
    body = result.json()
    assert body["source"] == "broker" and body["account_verified"] is False and body["scope"] == "quote"
    assert (body.get("broker_price") or body)["current"] == 72000


@pytest.mark.parametrize("path", PATHS)
def test_missing_credentials_are_marked_as_mock(client, monkeypatch, path):
    row = SimpleNamespace(broker="kis", app_key="", app_secret="", account_no="", paper=True)
    monkeypatch.setattr(stocks, "_get_broker_settings_row", AsyncMock(return_value=row))
    result = client.get(path)
    assert result.status_code == 200
    assert result.json()["source"] == "mock" and result.json()["account_verified"] is False
    if path.endswith("test"):
        assert "증권사 연결을 확인한 결과가 아닙니다" in result.json()["message"]


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("error,code", [
    (KISTokenError("KIS_TOKEN_RATE_LIMIT", SECRET), "TOKEN_RATE_LIMIT"),
    (KISTokenError("KIS_TOKEN_UNAVAILABLE", SECRET), "TOKEN_UNAVAILABLE"),
    (RuntimeError(SECRET), "QUOTE_UNAVAILABLE"),
])
def test_local_setup_or_token_store_failure_is_also_safe(client, monkeypatch, caplog, path, error, code):
    monkeypatch.setattr(stocks, "_get_broker_client", AsyncMock(side_effect=error))
    result = client.get(path)
    assert result.status_code == 502 and result.json()["detail"]["code"] == code
    assert SECRET not in result.text and SECRET not in caplog.text


@pytest.mark.parametrize("path", PATHS)
def test_login_required_before_calling_broker(client, monkeypatch, path):
    client.app.dependency_overrides.pop(get_current_user)
    get_client = AsyncMock()
    monkeypatch.setattr(stocks, "_get_broker_client", get_client)
    assert client.get(path).status_code == 401
    get_client.assert_not_awaited()
