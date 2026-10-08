"""주소 검사 시험 (TC-UG) — 자료를 직접 받기 전에 「받아도 되는 주소인가」(크롤링 세 화면 · 설계 2 · 2026-10-07).

지키는 것 — 네트워크 없이 돈다(이름 풀기 · robots 받기를 바꿔 끼운다).
1. 형식: http · https · 기본 포트만 · 주소 안의 계정 정보 금지
2. 내부망: 가리키는 IP 가 하나라도 공인 주소가 아니면 막는다(루프백 · 사설 · 링크 로컬 · 공유 주소 · IPv4 를 품은 IPv6)
3. 허용 목록: 목록 밖은 막고 robots.txt 를 받으러 가지도 않는다 · 네이버 금융은 「막음」 까닭과 함께(결정 ①)
4. robots: 금지하면 막고, 받지 못하면 허용 목록을 따른다
5. 실제로 받는 길(수동 크롤링 둘 · 네이버)은 막히면 400 이고 받기 함수를 부르지 않는다
6. 화면 API(규칙 · 검사)는 관리자만
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.routes import data as data_routes
from app.routes import ingest as ingest_routes
from app.services import url_guard as ug

GLOBAL = ["211.43.20.5"]           # 공인 주소(이름 풀기를 바꿔 끼울 때 쓴다)


def _no_net(host):
    raise AssertionError(f"이름 풀기를 부르면 안 된다: {host}")


def _no_robots(origin):
    raise AssertionError(f"robots.txt 를 받으러 가면 안 된다: {origin}")


@pytest.mark.parametrize("url", ["ftp://opendart.fss.or.kr/x", "javascript:alert(1)", "", "http://",
                                 "http://user:pw@opendart.fss.or.kr/", "https://opendart.fss.or.kr:8443/api"])
def test_format_rejects(url):
    """TC-UG-01 · 형식 — http · https · 기본 포트만 · 계정 정보 금지. 이름 풀기 전에 멈춘다."""
    v = ug.check(url, resolve=_no_net, fetch_robots=_no_robots)
    assert (v["ok"], v["verdict"], v["checks"][-1]["name"]) == (False, "막음", "형식")


@pytest.mark.parametrize("url", ["http://127.0.0.1:80/", "http://10.0.0.5/", "http://192.168.1.1/x",
                                 "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
                                 "http://100.64.0.1/", "http://0.0.0.0/"])
def test_internal_ip_literals_blocked(url):
    """TC-UG-02 · 내부망 — IP 를 바로 적은 내부 주소(클라우드 메타데이터 169.254.169.254 · 공유 주소 100.64/10 포함)는 막는다."""
    v = ug.check(url, resolve=_no_net, fetch_robots=_no_robots)
    assert (v["ok"], v["checks"][-1]["name"]) == (False, "내부망"), v["reason"]


def test_names_resolving_inside_or_unresolvable_are_blocked():
    """TC-UG-02b · 이름이 가리키는 IP 를 **모두** 본다 — 하나라도 내부면 막고, 이름을 풀지 못해도 막는다."""
    assert ug.check("http://localhost/", resolve=lambda h: ["127.0.0.1"], fetch_robots=_no_robots)["checks"][-1]["name"] == "내부망"
    mixed = ug.check("https://opendart.fss.or.kr/", resolve=lambda h: GLOBAL + ["10.0.0.1"], fetch_robots=_no_robots)
    assert mixed["ok"] is False and "사설" in mixed["reason"]

    def boom(h):
        raise OSError("nodename nor servname provided")
    assert "이름 풀이 실패" in ug.check("https://nowhere.invalid/", resolve=boom, fetch_robots=_no_robots)["reason"]


def test_allowlist_blocks_others_without_fetching_robots():
    """TC-UG-03 · 허용 목록 밖은 막고 robots.txt 를 받으러 가지도 않는다 · 네이버 금융은 까닭을 함께(결정 ①)."""
    v = ug.check("https://example.com/a", resolve=lambda h: GLOBAL, fetch_robots=_no_robots)
    assert (v["ok"], v["checks"][-1]["name"], v["reason"]) == (False, "허용 목록", "허용 목록 밖")
    n = ug.check("https://finance.naver.com/item/main.naver?code=005930", resolve=lambda h: GLOBAL, fetch_robots=_no_robots)
    assert n["reason"] == "허용 목록 밖 — robots.txt 전면 금지"


def test_robots_decides_for_allowed_hosts():
    """TC-UG-04 · robots — 금지하면 막고, 그 경로만 금지면 다른 경로는 허용 · 받지 못하면 허용 목록을 따른다."""
    url = "https://opendart.fss.or.kr/api/list.json"
    deny = ug.check(url, resolve=lambda h: GLOBAL, fetch_robots=lambda o: "User-agent: *\nDisallow: /\n")
    assert (deny["ok"], deny["checks"][-1]["name"]) == (False, "robots")
    part = ug.check(url, resolve=lambda h: GLOBAL, fetch_robots=lambda o: "User-agent: *\nDisallow: /private\n")
    assert (part["ok"], part["verdict"], part["source"]) == (True, "허용", "전자공시 OpenAPI")
    none = ug.check(url, resolve=lambda h: GLOBAL, fetch_robots=lambda o: None)
    assert none["ok"] is True and [c["name"] for c in none["checks"]] == ["형식", "내부망", "허용 목록", "robots"]


@pytest.fixture
def ingest_client(monkeypatch):
    calls = []

    async def fake_crawl(url, db, ollama, log):
        calls.append(url)
        return 3

    monkeypatch.setattr(ingest_routes, "crawl_url", fake_crawl)
    monkeypatch.setattr(ingest_routes, "crawl_naver_stock", lambda *a, **k: (_ for _ in ()).throw(AssertionError("네이버를 불렀다")))
    monkeypatch.setattr(ingest_routes, "get_llm_client", lambda: None)
    monkeypatch.setattr(ug, "_resolve", lambda h: ["127.0.0.1"] if h == "localhost" else GLOBAL)
    monkeypatch.setattr(ug, "_fetch_robots", lambda origin: None)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "name": "시험", "email": "t@example.com", "roles": ["user"]}

    async def no_db():
        yield None
    app.dependency_overrides[get_pg_session] = no_db
    return TestClient(app), calls


def test_crawl_routes_block_before_fetching(ingest_client):
    """TC-UG-05 · 실제로 받는 길은 막히면 400(까닭 · 허용 목록) 이고 받기 함수를 부르지 않는다 — 허용 주소만 받는다."""
    c, calls = ingest_client
    for path in ("/api/ingest/crawl/url", "/api/ingest/crawl/url/async"):
        r = c.post(path, json={"url": "http://localhost/admin"})
        assert r.status_code == 400 and "내부망" in r.json()["detail"]["message"], path
        r = c.post(path, json={"url": "https://example.com/"})
        assert r.status_code == 400 and "허용 목록 밖" in r.json()["detail"]["message"], path
    r = c.post("/api/ingest/crawl/naver", json={"code": "005930"})
    assert r.status_code == 400 and "robots.txt 전면 금지" in r.json()["detail"]["message"]
    assert calls == []
    r = c.post("/api/ingest/crawl/url", json={"url": "https://opendart.fss.or.kr/api/list.json"})
    assert r.status_code == 200 and calls == ["https://opendart.fss.or.kr/api/list.json"]


def test_data_url_api_is_admin_only(monkeypatch):
    """TC-UG-06 · 화면 API — 규칙 · 검사는 관리자만(일반 사용자 403) · 막혀도 200 으로 까닭을 돌려준다."""
    monkeypatch.setattr(ug, "_resolve", lambda h: GLOBAL)
    monkeypatch.setattr(ug, "_fetch_robots", lambda origin: None)
    app = FastAPI()
    app.include_router(data_routes.router)
    c = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": ["user"]}
    assert c.get("/api/data/url-rules").status_code == 403
    assert c.post("/api/data/url-check", json={"url": "https://example.com"}).status_code == 403
    app.dependency_overrides[get_current_user] = lambda: {"id": "a1", "roles": ["admin"]}
    rules = c.get("/api/data/url-rules").json()
    assert {r["host"] for r in rules["allowed"]} >= {"opendart.fss.or.kr", "www.korea.kr", "apis.data.go.kr", "ecos.bok.or.kr"}
    assert any(r["host"] == "finance.naver.com" and r["verdict"] == "막음" for r in rules["blocked"])
    j = c.post("/api/data/url-check", json={"url": "https://example.com"}).json()
    assert (j["ok"], j["reason"]) == (False, "허용 목록 밖")
    assert c.post("/api/data/url-check", json={"url": "https://ecos.bok.or.kr/api/"}).json()["ok"] is True


# ── 리다이렉트 (2026-10-08) — 허용된 곳이 돌려보낸 주소도 보내기 전에 검사한다 ─────────────────────────
def _redirecting_transport(seen: list[str], to: str):
    """처음 주소(opendart)는 `to` 로 돌려보내고, 그 밖은 본문 200 — 실제로 「보낸」 주소를 seen 에 적는다."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "opendart.fss.or.kr":
            return httpx.Response(302, headers={"Location": to})
        return httpx.Response(200, text="<html><title>t</title><body>" + "본문 " * 80 + "</body></html>")
    return httpx.MockTransport(handler)


@pytest.mark.parametrize("to, why", [("http://127.0.0.1/admin", "내부망"), ("http://169.254.169.254/latest/meta-data/", "내부망"),
                                     ("https://example.com/x", "허용 목록 밖")])
def test_redirect_hop_blocked_before_sending(monkeypatch, to, why):
    """TC-UG-07 · 리다이렉트 홉 — 허용된 곳이 내부망 · 목록 밖으로 돌려보내면 그 주소로는 **보내지 않고** 막는다(요청 훅)."""
    import asyncio

    import httpx

    monkeypatch.setattr(ug, "_resolve", lambda h: GLOBAL)
    monkeypatch.setattr(ug, "_fetch_robots", lambda origin: None)
    seen: list[str] = []

    async def go():
        async with httpx.AsyncClient(transport=_redirecting_transport(seen, to), follow_redirects=True,
                                     event_hooks={"request": [ug.guard_request]}) as client:
            await client.get("https://opendart.fss.or.kr/api/list.json")

    with pytest.raises(ug.BlockedHop) as e:
        asyncio.run(go())
    assert seen == ["https://opendart.fss.or.kr/api/list.json"], "막힌 홉이 실제로 나갔다"
    assert e.value.status_code == 400 and why in e.value.detail["message"] and e.value.detail["url"] == to


def test_redirect_within_allowlist_follows(monkeypatch):
    """TC-UG-07b · 허용 목록 안에서의 리다이렉트는 따라간다 · robots 가 그 경로를 금지하면 그 홉에서 막는다."""
    import asyncio

    import httpx

    monkeypatch.setattr(ug, "_resolve", lambda h: GLOBAL)
    seen: list[str] = []

    async def go():
        async with httpx.AsyncClient(transport=_redirecting_transport(seen, "https://www.korea.kr/news/1"),
                                     follow_redirects=True, event_hooks={"request": [ug.guard_request]}) as client:
            return await client.get("https://opendart.fss.or.kr/api/list.json")

    monkeypatch.setattr(ug, "_fetch_robots", lambda origin: None)
    assert asyncio.run(go()).status_code == 200 and seen[-1] == "https://www.korea.kr/news/1"
    seen.clear()
    monkeypatch.setattr(ug, "_fetch_robots", lambda o: "User-agent: *\nDisallow: /news\n" if "korea.kr" in o else None)
    with pytest.raises(ug.BlockedHop):
        asyncio.run(go())
    assert seen == ["https://opendart.fss.or.kr/api/list.json"]


def test_crawl_url_reraises_blocked_hop_as_400(monkeypatch):
    """TC-UG-08 · 받는 길이 훅을 건다 — 막힌 홉은 크롤러가 삼켜 「0청크 · 성공」 이 되지 않고 라우트가 400 을 돌려준다."""
    import httpx

    from app.services import crawl

    monkeypatch.setattr(ug, "_resolve", lambda h: GLOBAL)
    monkeypatch.setattr(ug, "_fetch_robots", lambda origin: None)
    seen: list[str] = []
    real_client = httpx.AsyncClient

    def client_with_mock(*a, **kw):
        assert ug.guard_request in kw.get("event_hooks", {}).get("request", []), "crawl_url 이 요청 훅을 걸지 않았다"
        kw["transport"] = _redirecting_transport(seen, "http://10.0.0.7/secret")
        return real_client(*a, **kw)

    monkeypatch.setattr(crawl.httpx, "AsyncClient", client_with_mock)
    monkeypatch.setattr(ingest_routes, "get_llm_client", lambda: None)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": ["user"]}

    async def no_db():
        yield None
    app.dependency_overrides[get_pg_session] = no_db
    r = TestClient(app).post("/api/ingest/crawl/url", json={"url": "https://opendart.fss.or.kr/api/list.json"})
    assert r.status_code == 400 and "리다이렉트" in r.json()["detail"]["message"] and "사설" in r.json()["detail"]["message"]
    assert seen == ["https://opendart.fss.or.kr/api/list.json"]
