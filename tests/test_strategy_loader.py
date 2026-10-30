"""domain-rag-lab 전략 스펙 로더: 미설정 폴백, TTL 캐시, 404 → None."""
import asyncio

import httpx
import pytest

from app.config import settings
from app.services import strategy_loader as sl


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    sl.clear_cache()
    monkeypatch.setattr(settings, "STRATEGY_SPEC_SOURCE", "remote")
    monkeypatch.setattr(settings, "DOMAIN_RAG_LAB_BASE_URL", "https://rag.test")
    monkeypatch.setattr(settings, "DOMAIN_RAG_LAB_API_KEY", "k")
    yield
    sl.set_transport(None)
    sl.clear_cache()


def test_unconfigured_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "DOMAIN_RAG_LAB_BASE_URL", "")
    assert asyncio.run(sl.list_strategies()) == []
    assert asyncio.run(sl.get_strategy("x")) is None


def test_list_and_get_with_cache():
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        assert request.headers["X-API-Key"] == "k"
        if request.url.path == "/backtests/strategies":
            return httpx.Response(200, json={"strategies": [{"strategy_id": "ma_cross", "version": 2}]})
        if request.url.path == "/backtests/strategies/ma_cross":
            return httpx.Response(200, json={"strategy_id": "ma_cross", "version": 2, "universe": ["005930"]})
        return httpx.Response(404, json={"detail": "not found"})

    sl.set_transport(httpx.MockTransport(handler))
    assert asyncio.run(sl.list_strategies())[0]["strategy_id"] == "ma_cross"
    assert asyncio.run(sl.list_strategies())[0]["version"] == 2
    assert hits["n"] == 1  # 캐시 적중
    assert asyncio.run(sl.get_strategy("ma_cross"))["universe"] == ["005930"]
    assert asyncio.run(sl.get_strategy("missing")) is None


def test_expired_cache_is_not_used_on_upstream_failure(monkeypatch):
    sl._cache["/backtests/strategies/x"] = (0, {"strategy_id": "x", "version": 1})
    sl.set_transport(httpx.MockTransport(lambda request: httpx.Response(503)))
    assert asyncio.run(sl.get_strategy("x")) is None


@pytest.mark.parametrize("body", [[], {"strategy_id": "other", "version": 1},
    {"strategy_id": "x", "version": 2}, {"strategy_id": "x", "version": True}])
def test_wrong_card_or_version_is_rejected(body):
    sl.set_transport(httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
    assert asyncio.run(sl.get_strategy("x", 1)) is None


def test_explicit_fixed_test_card_is_available_without_remote_and_has_no_fake_performance(monkeypatch):
    monkeypatch.setattr(settings, "STRATEGY_SPEC_SOURCE", "fixed_test")
    monkeypatch.setattr(settings, "DOMAIN_RAG_LAB_BASE_URL", "")
    sl.set_transport(httpx.MockTransport(lambda request: pytest.fail("Fixed mode must not call remote")))
    listed = asyncio.run(sl.list_strategies())
    assert sl.is_configured() and len(listed) == 1 and listed[0]["test_only"]
    assert listed[0]["source"] == "fixed_test"
    assert "acceptance" not in listed[0] and "backtest_result" not in listed[0]
    card = asyncio.run(sl.get_strategy("ma_cross_20_60", 1))
    assert card["version"] == 1 and card["universe"] == ["005930"]
    card["universe"].append("000660")
    assert asyncio.run(sl.get_strategy("ma_cross_20_60"))["universe"] == ["005930"]


@pytest.mark.parametrize("strategy_id,version", [("other", 1), ("ma_cross_20_60", 2),
    ("ma_cross_20_60", True), ("ma_cross_20_60", "1"), ("../ma_cross_20_60", 1)])
def test_fixed_test_rejects_other_cards_and_versions(monkeypatch, strategy_id, version):
    monkeypatch.setattr(settings, "STRATEGY_SPEC_SOURCE", "fixed_test")
    assert asyncio.run(sl.get_strategy(strategy_id, version)) is None


@pytest.mark.parametrize("tampered", [False, True])
def test_missing_or_changed_fixed_input_does_not_fall_back_to_remote(monkeypatch, tmp_path, tampered):
    monkeypatch.setattr(settings, "STRATEGY_SPEC_SOURCE", "fixed_test")
    path = tmp_path / "card.json"
    if tampered:
        path.write_text('{"strategy_id":"ma_cross_20_60","version":1}')
    monkeypatch.setattr(sl, "_FIXED_CARD", path)
    sl.set_transport(httpx.MockTransport(lambda request: pytest.fail("No fallback allowed")))
    assert not sl.is_configured()
    assert asyncio.run(sl.list_strategies()) == []
    assert asyncio.run(sl.get_strategy("ma_cross_20_60", 1)) is None
