"""잔고 누락을 0원 계좌로 처리하지 않고, 조회 오류의 인증 정보는 숨긴다."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.routes import stocks
from app.services.brokers import kis

SECRET = "PRIVATE-ACCOUNT-KEY-MUST-NOT-LEAK"
PATH = "/api/broker/balance"


def balance_body():
    return {"rt_cd": "0", "output1": [], "output2": [{
        "tot_evlu_amt": "0", "dnca_tot_amt": "0",
        "pchs_amt_smtl_amt": "0", "evlu_pfls_smtl_amt": "0",
    }]}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(stocks.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"}
    app.dependency_overrides[get_pg_session] = lambda: None
    with TestClient(app) as client:
        yield client


def upstream(monkeypatch, body, status=200, headers=None):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.host == "openapivts.koreainvestment.com"
        assert request.url.path.endswith("/inquire-balance")
        if body == "timeout":
            raise httpx.ReadTimeout(SECRET, request=request)
        return httpx.Response(status, json=body, headers=headers)

    real = httpx.AsyncClient
    monkeypatch.setattr(kis.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    broker = kis.KISClient("TEST-KEY", SECRET, paper=True)
    monkeypatch.setattr(broker, "_ensure_token", AsyncMock())
    monkeypatch.setattr(stocks, "_get_broker_client_and_account", AsyncMock(return_value=(broker, "kis", "12345678-01")))
    return broker, calls


def test_explicit_zero_balance_is_valid(client, monkeypatch):
    broker, calls = upstream(monkeypatch, balance_body())
    result = client.get(PATH)
    assert result.status_code == 200
    assert result.json()["total_eval"] == 0 and result.json()["holdings"] == []
    assert len(calls) == 1


@pytest.mark.parametrize("broken", [
    {}, {"rt_cd": "0"}, {"rt_cd": "0", "output1": [], "output2": [{}]},
    {"rt_cd": "0", "output1": [], "output2": []},
    {"rt_cd": "0", "output1": {}, "output2": [{}]},
])
def test_missing_balance_is_not_a_zero_account(client, monkeypatch, broken):
    upstream(monkeypatch, broken)
    result = client.get(PATH)
    assert result.status_code == 502
    assert result.json()["detail"]["scope"] == "balance"
    assert result.json()["detail"]["account_verified"] is False


@pytest.mark.parametrize("field,value", [
    ("tot_evlu_amt", "NaN"), ("dnca_tot_amt", "Infinity"),
    ("tot_evlu_amt", ""), ("dnca_tot_amt", None),
    ("tot_evlu_amt", True), ("dnca_tot_amt", "-1"),
])
def test_invalid_account_amount_never_reaches_trading(monkeypatch, field, value):
    body = balance_body()
    body["output2"][0][field] = value
    broker, _ = upstream(monkeypatch, body)
    with pytest.raises(RuntimeError, match="잔고"):
        asyncio.run(broker.get_balance("12345678-01"))


def test_held_position_missing_value_is_not_silently_zeroed(monkeypatch):
    body = balance_body()
    body["output1"] = [{"pdno": "005930", "hldg_qty": "2"}]
    broker, _ = upstream(monkeypatch, body)
    with pytest.raises(RuntimeError, match="잔고"):
        asyncio.run(broker.get_balance("12345678-01"))


def test_valid_holding_and_negative_profit_are_preserved(monkeypatch):
    body = balance_body()
    body["output1"] = [{"pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "2",
                        "pchs_avg_pric": "70000", "prpr": "69000", "evlu_amt": "138000",
                        "evlu_pfls_amt": "-2000", "evlu_pfls_rt": "-1.43"}]
    body["output2"][0].update(tot_evlu_amt="148000", dnca_tot_amt="10000",
                               pchs_amt_smtl_amt="140000", evlu_pfls_smtl_amt="-2000")
    broker, _ = upstream(monkeypatch, body)
    result = asyncio.run(broker.get_balance("12345678-01"))
    assert result.cash == 10000 and result.total_gain == -2000
    assert result.holdings[0].quantity == 2 and result.holdings[0].gain_loss == -2000


@pytest.mark.parametrize("body,status,code", [
    ({"rt_cd": "1", "msg_cd": "EGW00103", "msg1": SECRET}, 200, "INVALID_CREDENTIALS"),
    ({"error": SECRET}, 403, "BROKER_AUTH_REJECTED"),
    ({"rt_cd": "1", "msg_cd": "EGW00201", "msg1": SECRET}, 200, "BALANCE_RATE_LIMIT"),
    ("timeout", 200, "BALANCE_TIMEOUT"),
])
def test_balance_failure_is_safe_and_actionable(client, monkeypatch, caplog, body, status, code):
    upstream(monkeypatch, body, status)
    result = client.get(PATH)
    assert result.status_code == 502
    detail = result.json()["detail"]
    assert detail["code"] == code and detail["scope"] == "balance"
    assert detail["message"] and detail["hint"] and detail["account_verified"] is False
    assert SECRET not in result.text and SECRET not in caplog.text
    assert "12345678" not in result.text and "https://" not in result.text


def test_client_setup_failure_is_also_sanitized(client, monkeypatch):
    monkeypatch.setattr(stocks, "_get_broker_client_and_account", AsyncMock(side_effect=RuntimeError(SECRET)))
    result = client.get(PATH)
    assert result.status_code == 502 and SECRET not in result.text


def test_login_checked_before_balance_lookup(client, monkeypatch):
    client.app.dependency_overrides.pop(get_current_user)
    get_client = AsyncMock()
    monkeypatch.setattr(stocks, "_get_broker_client_and_account", get_client)
    assert client.get(PATH).status_code == 401
    get_client.assert_not_awaited()
