"""#213: 실제 회차·판단 출처와 점수를 표시하며 계산 실패를 0점 관망으로 만들지 않는다."""
import asyncio
import copy
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import auto_trade
from app.services.decision_signal_view import signal_view, cycle_timestamp
from app.routes import stocks

UID = UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")


@pytest.mark.parametrize("settings,kind,words", [
    ({"aggressive": False}, "basic", "기본 일봉"),
    ({"aggressive": True}, "aggressive", "공격 모드 · 분봉"),
    ({"aggressive": False, "strategy": {"applied": True,"id": "s1","version": 3}}, "strategy", "사용자 전략 s1 v3"),
    ({"aggressive": False, "strategy": {"applied": False,"id": "s1","error": "missing"}}, "basic", "기본 일봉"),
    ({}, "unknown", "판단 방식 미확인"),
])
def test_method_matches_recorded_settings_without_changing_signal(settings, kind, words):
    raw = {"symbol": "005930.KS", "action": "매도", "score": 2,
           "basis": {"as_of": "2026-10-16", "interval": "1d", "normalized_score": .7}}
    before = copy.deepcopy(raw)
    view = signal_view(raw, settings, "2026-10-19T02:00:00Z")
    assert view["decision"]["kind"] == kind and words in view["decision"]["method"]
    assert view["cycle_at"] == "2026-10-19T02:00:00Z"
    assert view["decision"]["as_of"] == "2026-10-16"
    assert raw == before and view["action"] == "매도" and view["score"] == 2
    assert ("정규화 점수 +0.70" in view["decision"]["score_text"]) == (kind == "strategy")


@pytest.mark.parametrize("score", [None, "2", float("nan"), float("inf"), True])
def test_missing_or_bad_scores_are_not_zero(score):
    assert signal_view({"score": score}, {})["decision"]["score_text"] == "점수 미확인"


def test_failure_does_not_display_a_numeric_score():
    view = signal_view({"error": "지표 계산 실패", "score": 0}, {"aggressive": True})
    assert view["decision"]["kind"] == "unavailable"
    assert "판단 불가" in view["decision"]["method"] and "0.0" not in view["decision"]["score_text"]


def test_time_order_uses_instant_not_text_or_unknown_time():
    assert cycle_timestamp("2026-10-19T10:00:00+09:00") < cycle_timestamp("2026-10-19T02:00:00Z")
    assert cycle_timestamp(None) < cycle_timestamp("2026-10-19T02:00:00")


def test_status_projection_does_not_rewrite_cached_cycles(monkeypatch):
    cycles = [{"time": "2026-10-19T02:00:00Z", "settings": {"aggressive": True},
               "signals": [{"symbol": "005930.KS", "action": "관망", "score": 5}]}]
    before = copy.deepcopy(cycles)
    monkeypatch.setattr(auto_trade, "is_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(auto_trade, "cache_get", AsyncMock(return_value={"cycles": cycles}))
    result = asyncio.run(auto_trade.get_status(None, UID))
    assert result["log"][0]["signals"][0]["decision"]["kind"] == "aggressive"
    assert cycles == before and result["log"][0]["signals"][0]["action"] == "관망"


def test_http_sorts_combined_sources_and_preserves_errors(monkeypatch):
    from app.services import kis_batch, reconciliation
    own = [{"time": "2026-10-19T02:00:00Z", "signals": [{"symbol": "A", "action": "매수", "score": 2}]}]
    # 배치는 소스 순서상 뒤에 붙지만 실제 회차는 더 오래됐다. 잘못된 시각도 최신을 밀어내지 않는다.
    batch = [{"time": "2026-10-19T10:00:00+09:00", "signals": [{"symbol": "B", "action": "매도"}]},
             {"time": None, "signals": [{"symbol": "E", "error": "지표 계산 실패"}]}]
    monkeypatch.setattr(auto_trade, "is_enabled", AsyncMock(return_value=False))
    async def cache(key, **kwargs): return {"cycles": own if str(UID) in key else batch}
    monkeypatch.setattr(auto_trade, "cache_get", cache)
    monkeypatch.setattr(kis_batch, "system_status", AsyncMock(return_value={"running": True}))
    monkeypatch.setattr(reconciliation, "latest", AsyncMock(return_value=None))
    app = FastAPI(); app.include_router(stocks.router)
    app.dependency_overrides[stocks.get_current_user] = lambda: {"id": str(UID)}
    app.dependency_overrides[stocks.get_pg_session] = lambda: None
    with TestClient(app) as client:
        response = client.get("/api/quant/auto/status")
    assert response.status_code == 200, response.text
    sigs = response.json()["signals"]
    assert [s["symbol"] for s in sigs] == ["E", "B", "A"]
    assert sigs[0]["signal"] == "UNAVAILABLE" and sigs[0]["decision"]["kind"] == "unavailable"
    assert sigs[-1]["cycle_at"] == own[0]["time"] and sigs[-1]["source"] == "me"
