"""KIS 모의 취소의 공식 요청 형태와 응답 유실 경계. 실제 HTTP 없음."""
import asyncio
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from app.services.brokers import kis


@pytest.mark.parametrize("kind", ["ok", "timeout", "bad_json", "missing_id", "rejected"])
def test_cancel_is_paper_only_and_one_post(monkeypatch, kind):
    calls = []
    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert request.url.host == "openapivts.koreainvestment.com"
        assert request.headers["tr_id"] == "VTTC0013U"
        assert body["ORGN_ODNO"] == "000123" and body["KRX_FWDG_ORD_ORGNO"] == "00950"
        assert body["ORD_QTY"] == "2" and body["QTY_ALL_ORD_YN"] == "Y" and body["RVSE_CNCL_DVSN_CD"] == "02"
        if kind == "timeout": raise httpx.ReadTimeout("synthetic")
        if kind == "bad_json": return httpx.Response(200, content=b"invalid")
        if kind == "rejected": return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "TEST"})
        return httpx.Response(200, json={"rt_cd": "0", "output": {} if kind == "missing_id" else {"ODNO": "000124"}})
    original = httpx.AsyncClient
    monkeypatch.setattr(kis.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    client = kis.KISClient("synthetic", "synthetic")
    monkeypatch.setattr(client, "_ensure_token", AsyncMock())
    if kind == "ok":
        assert asyncio.run(client.cancel_order("1234567801", "000123", "00950", 2))["status"] == "ACCEPTED"
    else:
        with pytest.raises(RuntimeError if kind == "rejected" else kis.OrderSubmissionUnknown):
            asyncio.run(client.cancel_order("1234567801", "000123", "00950", 2))
    assert len(calls) == 1
    client.paper = False
    with pytest.raises(ValueError): asyncio.run(client.cancel_order("1234567801", "000123", "00950", 2))
    assert len(calls) == 1
