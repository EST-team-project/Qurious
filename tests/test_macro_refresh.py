"""TC-MR — 거시 · 미국 시세 라우트의 새로고침 인자 (`?refresh=true` · app/routes/macro.py · 2026-11-05)

배경: 해외 · 원자재 시세(`/indicators`) · 미국 섹터 ETF(`/industry`) · 미국 종목 카드(`/us-stocks`)는 저장본(data_cache)을 최대 2시간까지
그대로 보인다. 화면에 새로고침 단추를 달아도 같은 저장본이 되돌아오므로, 서버가 새로고침 요청이면 저장본의 한도를 줄여 다시 받게 한다.
연타로 야후를 연달아 두드리지 않게 「60초 안에 받은 저장본」 은 새로고침이어도 그대로 돌려준다.

1. 평소 요청은 옛 동작 그대로 — 저장본 한도 2시간 · 응답에 `refresh` 칸 없음. (TC-MR-01)
2. 새로고침 요청이면 저장본 한도가 60초이고, 한도를 넘었으면(저장본 없음으로 읽힘) 다시 받아 저장한다. (TC-MR-02)
3. 60초 안의 저장본이 있으면 다시 받지 않고 그것을 돌려주되 `refresh.reused_cache` 로 밝힌다. (TC-MR-03)
4. HTTP 로 `?refresh=true` 가 실제로 쿼리 인자로 읽힌다. (TC-MR-04)
5. 새로고침으로 받았는데 값이 전부 비면(야후 막힘) 저장본을 덮어쓰지 않고 이전 저장본을 돌려준다. (TC-MR-05)
6. 화면 연결 — 세 화면이 새로고침 때만 `?refresh=true` 를 붙이고, 메뉴로 들어올 때는 평소 저장본이다. (TC-MR-06)

네트워크 · PostgreSQL 은 쓰지 않는다 — 캐시 함수 · 야후 호출은 대역이다.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import macro

ROUTES = [
    ("macro_indicators", macro.KEY_MACRO_INDICATORS, "indicators"),
    ("macro_industry", macro.KEY_SECTOR_ETFS, "sectors"),
    ("macro_us_stocks", macro.KEY_US_STOCKS, "stocks"),
]
STORED = [{"symbol": "X", "price": 1.0, "name": "저장본"}]


class Probe:
    """cache_get · cache_set · 야후 호출 대역 — 몇 번 불렸고 어떤 한도로 읽었는지 적어 둔다."""

    def __init__(self, cached):
        self.cached, self.max_ages, self.sets, self.fetches = cached, [], [], 0

    async def cache_get(self, key, max_age_hours=24):
        self.max_ages.append(max_age_hours)
        return self.cached

    async def cache_set(self, key, data):
        self.sets.append(key)

    async def latest(self, symbol, unit):
        self.fetches += 1
        return {"price": 2.0, "change_p": 0.5, "name": "새로 받음"}


@pytest.fixture
def probe(monkeypatch):
    def make(cached):
        p = Probe(cached)
        monkeypatch.setattr(macro, "cache_get", p.cache_get)
        monkeypatch.setattr(macro, "cache_set", p.cache_set)
        monkeypatch.setattr(macro, "_get_latest", p.latest)
        return p
    return make


def _call(name, **kw):
    return asyncio.run(getattr(macro, name)(_user={"id": 1}, **kw))


@pytest.mark.parametrize("name,key,field", ROUTES)
def test_default_request_keeps_the_two_hour_cache_and_has_no_refresh_field(probe, name, key, field):
    """TC-MR-01 · 평소 요청 — 저장본 한도 2시간 · 저장본이 있으면 그대로 · 응답에 refresh 칸 없음."""
    p = probe(STORED)
    out = _call(name)
    assert p.max_ages == [2] and out["from_cache"] is True and out[field] == STORED and "refresh" not in out
    assert p.fetches == 0 and p.sets == []


@pytest.mark.parametrize("name,key,field", ROUTES)
def test_refresh_request_shrinks_cache_limit_and_refetches_when_stale(probe, name, key, field):
    """TC-MR-02 · 새로고침 — 한도 60초 · 그보다 오래된 저장본은 없는 것으로 읽혀(cache_get 이 None) 다시 받고 저장한다."""
    p = probe(None)
    out = _call(name, refresh=True)
    assert p.max_ages == [pytest.approx(60 / 3600)] and out["from_cache"] is False
    assert p.fetches > 0 and p.sets == [key] and out[field], "다시 받아 저장본을 갱신한다"
    assert out["refresh"] == {"requested": True, "reused_cache": False, "min_age_seconds": 60}


@pytest.mark.parametrize("name,key,field", ROUTES)
def test_refresh_within_a_minute_reuses_cache_and_says_so(probe, name, key, field):
    """TC-MR-03 · 60초 안에 받은 저장본이 있으면 야후를 다시 부르지 않고 돌려주되 reused_cache=true 로 밝힌다(연타 방지)."""
    p = probe(STORED)
    out = _call(name, refresh=True)
    assert p.fetches == 0 and p.sets == [] and out["from_cache"] is True and out[field] == STORED
    assert out["refresh"] == {"requested": True, "reused_cache": True, "min_age_seconds": 60}


def test_query_param_is_really_read_over_http(probe):
    """TC-MR-04 · HTTP — `?refresh=true` 가 쿼리 인자로 읽혀 한도가 60초가 되고, 없으면 2시간이다(함수 직접 호출만으론 못 본다)."""
    p = probe(STORED)
    app = FastAPI()
    app.include_router(macro.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": 1}
    client = TestClient(app)
    assert client.get("/api/macro/us-stocks").json()["from_cache"] is True
    r = client.get("/api/macro/us-stocks?refresh=true")
    assert r.status_code == 200 and r.json()["refresh"]["requested"] is True
    assert p.max_ages[0] == 2 and p.max_ages[1] == pytest.approx(60 / 3600)


class BlankProbe(Probe):
    """야후가 막혀 값이 전부 비는 상황 — 새로고침이 아닌 읽기(2시간 한도)에는 이전 저장본이 있다."""

    def __init__(self, old):
        super().__init__(None)
        self.old = old

    async def cache_get(self, key, max_age_hours=24):
        self.max_ages.append(max_age_hours)
        return self.old if max_age_hours >= 2 else None      # 60초 한도로는 없고 2시간 한도로는 이전 저장본이 보인다

    async def latest(self, symbol, unit):
        self.fetches += 1
        return {"price": None, "change_p": None}


@pytest.mark.parametrize("name,key,field", ROUTES)
def test_refresh_that_got_nothing_keeps_the_old_cache(monkeypatch, name, key, field):
    """TC-MR-05 · 새로고침인데 받은 값이 전부 비었으면 저장본을 덮어쓰지 않고(cache_set 없음) 이전 저장본을 돌려주며 refresh.failed 로 밝힌다 ·
    이전 저장본도 없으면 평소처럼 그대로 낸다(빈 화면을 지어 감추지 않는다)."""
    p = BlankProbe(STORED)
    for attr, fn in (("cache_get", p.cache_get), ("cache_set", p.cache_set), ("_get_latest", p.latest)):
        monkeypatch.setattr(macro, attr, fn)
    out = _call(name, refresh=True)
    assert out["from_cache"] is True and out[field] == STORED and p.sets == [], "이전 저장본을 지키고 덮어쓰지 않는다"
    assert out["refresh"] == {"requested": True, "reused_cache": True, "min_age_seconds": 60, "failed": True}
    q = BlankProbe(None)
    for attr, fn in (("cache_get", q.cache_get), ("cache_set", q.cache_set), ("_get_latest", q.latest)):
        monkeypatch.setattr(macro, attr, fn)
    out2 = _call(name, refresh=True)
    assert out2["from_cache"] is False and q.sets == [key] and "failed" not in out2["refresh"], "이전 저장본이 없으면 평소처럼"


def test_three_screens_add_refresh_only_from_the_button():
    """TC-MR-06 · 구조 — ml.js(거시 · 산업)와 us.js 는 새로고침 단추에서만 `?refresh=true` 를 붙이고(메뉴 진입은 평소 저장본) ·
    app.html 에 두 단추가 있으며 · 미국 단추는 이벤트 객체를 옵션으로 넘기지 않는다."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    ml = (root / "public/js/ml.js").read_text(encoding="utf-8")
    us = (root / "public/js/us.js").read_text(encoding="utf-8")
    html = (root / "public/app.html").read_text(encoding="utf-8")
    assert '"/api/macro/indicators" + (refresh ? "?refresh=true" : "")' in ml and '"/api/macro/industry" + (refresh ? "?refresh=true" : "")' in ml
    assert 'getElementById("macro-refresh")?.addEventListener("click", () => loadMacroDashboard({ refresh: true }))' in ml
    assert 'getElementById("industry-refresh")?.addEventListener("click", () => loadMacroIndustry({ refresh: true }))' in ml
    assert '"/api/macro/us-stocks" + (refresh ? "?refresh=true" : "")' in us and "() => loadUsDashboard({ refresh: true })" in us
    assert 'addEventListener("click",    loadUsDashboard)' not in us, "이벤트 객체가 옵션 자리로 들어가면 안 된다"
    assert 'id="macro-refresh"' in html and 'id="industry-refresh"' in html
    main = (root / "public/js/main.js").read_text(encoding="utf-8")
    assert "loadMacroDashboard();" in main and "loadMacroIndustry();" in main and "loadUsDashboard();" in main, "메뉴 진입은 인자 없이"
