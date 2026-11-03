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
            return httpx.Response(200, json={"strategy_id": "ma_cross", "version": 2, "universe": ["005930"],
                                             "acceptance": {"passed": True}})
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


@pytest.mark.parametrize("acceptance", [None, {}, {"passed": False}, {"passed": "true"}, {"passed": 1}, []])
def test_remote_unaccepted_version_cannot_be_used_for_trading(acceptance):
    # 원격의 특정 버전 API는 불합격 이력도 반환한다. 목록의 합격 필터에 의존하면 안 된다.
    card = {"strategy_id": "x", "version": 1, "acceptance": acceptance}
    sl.set_transport(httpx.MockTransport(lambda request: httpx.Response(200, json=card)))
    assert asyncio.run(sl.get_strategy("x", 1)) is None


def test_remote_accepted_pinned_version_is_available():
    card = {"strategy_id": "x", "version": 1, "acceptance": {"passed": True}}
    sl.set_transport(httpx.MockTransport(lambda request: httpx.Response(200, json=card)))
    assert asyncio.run(sl.get_strategy("x", 1)) == card


@pytest.mark.parametrize("body", [[], "invalid", 1, {"strategies": "invalid"}, {"strategies": [None, [], "x"]}])
def test_malformed_remote_list_is_unavailable(body):
    sl.set_transport(httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
    assert asyncio.run(sl.list_strategies()) == []


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
    assert sl.is_configured() and [card['version'] for card in listed] == [1, 2]
    assert all(card['test_only'] and card['source'] == 'fixed_test' for card in listed)
    assert all('acceptance' not in card and 'backtest_result' not in card for card in listed)
    card = asyncio.run(sl.get_strategy("ma_cross_20_60", 1))
    assert card["version"] == 1 and card["universe"] == ["005930"]
    card["universe"].append("000660")
    assert asyncio.run(sl.get_strategy("ma_cross_20_60"))["universe"] == ["005930"]
    card_v2 = asyncio.run(sl.get_strategy('ma_cross_20_60', 2))
    from app.services import strategy_v2
    strategy_v2.validate_card(card_v2)
    assert {k: v for k, v in card_v2.items() if k != 'name'} == strategy_v2.CONTRACT
    card_v2['stops']['atr_mult'] = 5
    assert asyncio.run(sl.get_strategy('ma_cross_20_60', 2))['stops']['atr_mult'] == 2
    assert asyncio.run(sl.get_strategy('ma_cross_20_60'))['version'] == 1


@pytest.mark.parametrize("strategy_id,version", [("other", 1), ("ma_cross_20_60", 3),
    ("ma_cross_20_60", True), ("ma_cross_20_60", "1"), ("../ma_cross_20_60", 1)])
def test_fixed_test_rejects_other_cards_and_versions(monkeypatch, strategy_id, version):
    monkeypatch.setattr(settings, "STRATEGY_SPEC_SOURCE", "fixed_test")
    assert asyncio.run(sl.get_strategy(strategy_id, version)) is None


@pytest.mark.parametrize("tampered", [False, True])
@pytest.mark.parametrize('version', [1, 2])
def test_missing_or_changed_fixed_input_does_not_fall_back_to_remote(monkeypatch, tmp_path, tampered, version):
    monkeypatch.setattr(settings, "STRATEGY_SPEC_SOURCE", "fixed_test")
    path = tmp_path / "card.json"
    if tampered:
        path.write_text('{"strategy_id":"ma_cross_20_60","version":1}')
    monkeypatch.setattr(sl, '_FIXED_CARD' if version == 1 else '_FIXED_CARD_V2', path)
    sl.set_transport(httpx.MockTransport(lambda request: pytest.fail("No fallback allowed")))
    assert sl.is_configured()  # 다른 판의 온전한 카드는 그대로 제공한다.
    assert [card['version'] for card in asyncio.run(sl.list_strategies())] == [3 - version]
    assert asyncio.run(sl.get_strategy('ma_cross_20_60', version)) is None


def test_all_fixed_cards_missing_is_unconfigured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'STRATEGY_SPEC_SOURCE', 'fixed_test')
    monkeypatch.setattr(sl, '_FIXED_CARD', tmp_path / 'missing-v1.json')
    monkeypatch.setattr(sl, '_FIXED_CARD_V2', tmp_path / 'missing-v2.json')
    assert not sl.is_configured()
    assert asyncio.run(sl.list_strategies()) == []


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
@pytest.mark.parametrize("tamper", [False, True])
@pytest.mark.parametrize('version', [1, 2])
def test_fixed_card_line_endings_preserve_content_guard(monkeypatch, tmp_path, newline, tamper, version):
    attribute = '_FIXED_CARD' if version == 1 else '_FIXED_CARD_V2'
    raw = getattr(sl, attribute).read_bytes().replace(b"\r\n", b"\n")
    if tamper:
        raw = raw.replace(b"005930", b"000660")
    path = tmp_path / "card.json"
    path.write_bytes(raw.replace(b"\n", newline))
    monkeypatch.setattr(sl, attribute, path)
    monkeypatch.setattr(settings, "STRATEGY_SPEC_SOURCE", "fixed_test")
    sl.set_transport(httpx.MockTransport(lambda request: pytest.fail("No fallback allowed")))
    assert sl.is_configured()
    assert bool(asyncio.run(sl.get_strategy('ma_cross_20_60', version))) is (not tamper)
    assert (version in [card['version'] for card in asyncio.run(sl.list_strategies())]) is (not tamper)
