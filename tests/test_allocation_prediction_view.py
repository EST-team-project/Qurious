"""#249: 극단 환산값·내부 점수·분류 확률을 구분하고 과거 저장본도 안전하게 읽는다."""
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import ml
from app.services.allocation_prediction_view import allocation_view, prediction_view
from tests.conftest import make_candles


def prediction(annual=300, reliable=True):
    return {"pred_ann_return_pct": annual, "confidence": .31, "signal": 1,
            "quality": {"reliable": reliable, "cls_val_accuracy": .60 if reliable else .30, "baseline_accuracy": .36},
            "explanation": {"signal": 1, "signal_label": "매수", "probability_pct": 48.2, "summary": "모델 판단"}}


@pytest.mark.parametrize("value", [300, 500, -90, -99])
def test_limits_are_not_displayed_as_predictions(value):
    source = prediction(value)
    before = copy.deepcopy(source)
    view = prediction_view(source)
    assert view["pred_ann_return_pct"] is None and view["pred_ann_return_status"] == "out_of_range"
    assert "모델 범위 밖" in view["display"]["return_text"]
    assert source == before  # 순위 계산용 입력을 수정하지 않는다.
    assert prediction_view(view) == view  # 저장 → 재조회에도 같은 문장


@pytest.mark.parametrize("value", [299.99, -89.99, 0, 12.34])
def test_in_range_values_are_described_as_annualized_five_day_prediction(value):
    view = prediction_view(prediction(value))
    assert view["pred_ann_return_pct"] == value and view["pred_ann_return_status"] == "available"
    assert "5거래일 예측" in view["display"]["return_text"]


@pytest.mark.parametrize("value", [None, float('nan'), float('inf'), '300', True])
def test_missing_or_invalid_value_is_not_zero(value):
    view = prediction_view(prediction(value))
    assert view["pred_ann_return_pct"] is None and view["pred_ann_return_status"] == "unavailable"
    assert "확인할 수 없습니다" in view["display"]["return_text"]


def test_probability_uses_classifier_not_composite_score():
    display = prediction_view(prediction())["display"]
    assert "모델 매수 확률 48.2%" in display["signal_text"]
    assert "50% 미만" in display["probability_note"] and "실제 수익" in display["probability_note"]
    assert "0.31" not in str(display) and "31.0%" not in str(display)


def test_quality_warning_survives_missing_xai_and_uses_raw_probability():
    ai = prediction(reliable=False)
    ai.update(explanation=None, model_signal=1, model_signal_probability_pct=48.2, signal_confidence=.34)
    view = prediction_view(ai)
    assert view["signal"] == 0
    assert "최종 판단 관망 · 모델 매수 확률 48.2%" == view["display"]["signal_text"]
    assert "검증 성능 기준을 충족하지 못해" in view["display"]["quality_warning"]
    assert "30.0%" in view["display"]["quality_warning"]


def test_old_unreliable_xai_is_consistent_with_final_signal():
    ai = prediction(reliable=False)
    view = prediction_view(ai)
    assert view["explanation"]["signal_label"] == "관망"
    assert view["explanation"]["model_signal_label"] == "매수"
    assert "관망" in view["display"]["signal_text"]
    assert ai["explanation"]["signal_label"] == "매수"


def test_unverified_classifier_does_not_claim_probability_or_quality():
    view = prediction_view({"pred_ann_return_pct": 5, "confidence": .5, "signal_confidence": .5, "signal": 1})
    assert "분류 확률 미확인" in view["display"]["signal_text"]
    assert "검증 성능을 확인할 수 없습니다" in view["display"]["quality_warning"]


def stored_result():
    return {"risk_profile": "moderate", "horizon_years": 3, "amount_manwon": 5000,
            "allocations": {"국내주식": 30, "해외주식": 25, "국내채권": 30, "대체자산": 10, "현금": 5},
            "stock_picks": [{"code": "005930.KS", "name": "삼성전자", "weight": 30,
                             "reason": "연환산 수익률 38.76%, 변동성 36.71%, AI 예측 수익률 300.0% (매수, 신뢰도 0.31)",
                             "ai_prediction": prediction(reliable=False)}],
            "optimization": {"weights": {"005930.KS": 100}}, "projections": []}


def test_old_reason_is_replaced_without_changing_weights_or_original():
    original = stored_result()
    before = copy.deepcopy(original)
    view = allocation_view(original)
    assert "300.0%" not in view["stock_picks"][0]["reason"]
    assert "신뢰도 0.31" not in view["stock_picks"][0]["reason"]
    assert "모델 범위 밖" in view["stock_picks"][0]["reason"]
    assert original == before and view["optimization"] == original["optimization"]
    assert view["stock_picks"][0]["weight"] == 30
    assert allocation_view(view) == view


@pytest.fixture
def client(monkeypatch):
    app = FastAPI(); app.include_router(ml.router)
    db = SimpleNamespace(commit=AsyncMock())
    app.dependency_overrides[ml.get_current_user] = lambda: {"id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"}
    app.dependency_overrides[ml.get_pg_session] = lambda: db
    with TestClient(app) as c:
        yield c, db


def test_latest_http_normalizes_old_saved_data_without_writing(client, monkeypatch):
    c, db = client
    stored = stored_result(); before = copy.deepcopy(stored)
    async def load(*args): return {"id": "old-result", "saved_at": "2026-10-16T00:00:00+00:00", "result": stored}
    monkeypatch.setattr(ml, "load_result", load)
    response = c.get('/api/ml/robo/allocation/latest')
    assert response.status_code == 200, response.text
    data = response.json()
    assert "300.0%" not in data["result"]["stock_picks"][0]["reason"]
    assert data["id"] == "old-result" and data["handoff"]["targets"][0]["weight_pct"] == 30
    db.commit.assert_not_awaited(); assert stored == before


def test_new_http_saves_same_safe_result_and_uses_current_xai_cache(client, monkeypatch):
    c, db = client
    raw_ai = prediction(); before = copy.deepcopy(raw_ai)
    cache = AsyncMock(return_value=raw_ai)
    monkeypatch.setattr(ml, "QUANT_STOCKS", [{"symbol": "005930.KS", "name": "삼성전자"}])
    monkeypatch.setattr(ml, "get_candles", AsyncMock(return_value={"candles": make_candles(100)}))
    monkeypatch.setattr(ml, "cache_get", cache)
    monkeypatch.setattr(ml, "optimize_portfolio", lambda *_: {"weights": {"005930.KS": 100}, "expected_return_pct": 10, "expected_volatility_pct": 20})
    save = AsyncMock(return_value={"id": "new", "saved_at": "2026-10-19T00:00:00+00:00"})
    monkeypatch.setattr(ml, "save_result", save)
    response = c.post('/api/ml/robo/allocation', json={})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["stock_picks"][0]["ai_prediction"]["pred_ann_return_pct"] is None
    assert data["stock_picks"][0]["weight"] == 30
    assert save.await_args.args[2] == {k: v for k, v in data.items() if k != "saved"}
    assert cache.await_args.args[0] == "ai_predict:v4:005930.KS"
    assert raw_ai == before
    db.commit.assert_awaited_once()
