"""번역 자료 API 시험 (TC-TA) — app/routes/ingest.py 의 번역 적재 · 검색 세 길(결정 T2 · T6 · 2026-10-23).

무엇을 지키나
1. **기본은 꺼짐** — 설정 TRANSLATION_API_ENABLED 기본값은 False 이고, 꺼져 있으면 셋 모두 403(서비스를 부르지 않는다).
   모음 조각에 AI허브 원문 · 번역이 그대로 있어, 로그인만 보면 승인받지 않은 사람이 원문을 본다(이용정책 5항 「열람」).
2. **켜도 관리자만** — 일반 사용자는 403.
3. **응답 코드로 가른다**(DF-149) — 모음 없음 = 404 · Qdrant · 임베딩 장애 = 503 · 0건 = 200 빈 목록 · 원자료 폴더 없음 = 404.
   예전엔 셋이 모두 200 「hits: []」 라 사용자가 「적재 전」 · 「장애」 · 「결과 없음」 을 가를 수 없었다.

돌리는 법 — 호스트에서 돈다(서비스 함수를 바꿔 끼워 Qdrant · 임베딩 없이). 서비스 자체는 TC-TR(컨테이너)이 본다.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.lib import vector_db
from app.lib.session import get_current_user
from app.routes import ingest as ingest_routes
from app.services.translation_ingest import EmbeddingUnavailable, TranslationDataMissing

ADMIN = {"id": "a1", "client_id": "c1", "roles": ["user", "admin"]}
USER = {"id": "u1", "client_id": "c1", "roles": ["user"]}
SEARCH = ("/api/ingest/translation-search", {"query": "배당"})
INGEST = ("/api/ingest/translation-data", {"data_type": "labeled"})
ASYNC = ("/api/ingest/translation-data/async", {"data_type": "labeled"})


@pytest.fixture
def api(monkeypatch):
    from app.database.postgres import get_pg_session

    calls: list[str] = []
    behaviour: dict = {"search": [], "ingest": {"total_docs": 0}}

    async def fake_search(query, ollama, top_k=5, category=None, target_language=None):
        calls.append("search")
        b = behaviour["search"]
        if isinstance(b, Exception):
            raise b
        return b

    async def fake_ingest(ollama, log, **kw):
        calls.append("ingest")
        b = behaviour["ingest"]
        if isinstance(b, Exception):
            raise b
        return b

    async def fake_enqueue(db, user, task, **kw):
        calls.append("enqueue")
        return "t1"

    async def no_db():
        yield None

    monkeypatch.setattr(ingest_routes, "translation_search", fake_search)
    monkeypatch.setattr(ingest_routes, "run_translation_ingest", fake_ingest)
    monkeypatch.setattr(ingest_routes, "enqueue_owned_task", fake_enqueue)
    monkeypatch.setattr(ingest_routes, "get_llm_client", lambda: None)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    app.dependency_overrides[get_pg_session] = no_db
    c = TestClient(app)
    c.calls, c.behaviour, c.app_ref = calls, behaviour, app
    return c


def _post(api, route):
    path, body = route
    return api.post(path, json=body)


def test_default_is_off():
    """TC-TA-01 · 설정 기본값은 꺼짐 — 누가 기본값을 켜 두면 여기서 깨진다(.env 로만 켠다)."""
    assert Settings.model_fields["TRANSLATION_API_ENABLED"].default is False


def test_off_means_403_for_all_three(api, monkeypatch):
    """TC-TA-02 · 꺼져 있으면 관리자라도 셋 모두 403(「꺼져 있습니다」) · 서비스도 큐도 부르지 않는다."""
    monkeypatch.setattr(settings, "TRANSLATION_API_ENABLED", False)
    for route in (SEARCH, INGEST, ASYNC):
        r = _post(api, route)
        assert r.status_code == 403 and "꺼져 있습니다" in r.json()["detail"], route[0]
    assert api.calls == []


def test_on_but_not_admin_is_403(api, monkeypatch):
    """TC-TA-03 · 켜도 관리자만 — 일반 사용자는 셋 모두 403(「관리자 권한」)."""
    monkeypatch.setattr(settings, "TRANSLATION_API_ENABLED", True)
    api.app_ref.dependency_overrides[get_current_user] = lambda: USER
    for route in (SEARCH, INGEST, ASYNC):
        r = _post(api, route)
        assert r.status_code == 403 and "관리자" in r.json()["detail"], route[0]
    assert api.calls == []


def test_search_status_codes(api, monkeypatch):
    """TC-TA-04 · 검색 — 결과 = 200(건수 그대로) · 0건 = 200 빈 목록 · 모음 없음 = 404 · Qdrant 장애 = 503 · 임베딩 장애 = 503."""
    monkeypatch.setattr(settings, "TRANSLATION_API_ENABLED", True)
    hit = {"score": 0.9, "text": "가", "translation": "a", "doc_no": "SYN-1", "category": "news",
           "target_language": "en", "domain": "금융"}
    api.behaviour["search"] = [hit]
    r = _post(api, SEARCH)
    assert r.status_code == 200 and r.json()["hits"] == [hit] and r.json()["collection"] == "translation_docs"
    api.behaviour["search"] = []
    r = _post(api, SEARCH)
    assert r.status_code == 200 and r.json()["hits"] == []
    api.behaviour["search"] = vector_db.CollectionMissing("translation_docs")
    r = _post(api, SEARCH)
    assert r.status_code == 404 and "적재되지 않았습니다" in r.json()["detail"]
    api.behaviour["search"] = vector_db.VectorDBUnavailable("Qdrant 검색 실패 — ResponseHandlingException")
    r = _post(api, SEARCH)
    assert r.status_code == 503 and "ResponseHandlingException" in r.json()["detail"]
    api.behaviour["search"] = EmbeddingUnavailable("임베딩 모델(nomic-embed-text) 호출 실패")
    r = _post(api, SEARCH)
    assert r.status_code == 503 and "임베딩" in r.json()["detail"]


def test_ingest_status_codes(api, monkeypatch):
    """TC-TA-05 · 적재 — 성공 = 200(요약) · 원자료 폴더 없음 = 404(받는 법 안내) · Qdrant · 임베딩 장애 = 503 · 비동기 길은 큐에 넣는다."""
    monkeypatch.setattr(settings, "TRANSLATION_API_ENABLED", True)
    api.behaviour["ingest"] = {"total_docs": 12, "zips": ["TL_5. 공시정보_1. 영어.zip"]}
    r = _post(api, INGEST)
    assert r.status_code == 200 and r.json()["result"]["total_docs"] == 12
    api.behaviour["ingest"] = TranslationDataMissing("/app/data/1.데이터")
    r = _post(api, INGEST)
    assert r.status_code == 404 and "받은 파일 이름 그대로" in r.json()["detail"]
    for exc in (vector_db.VectorDBUnavailable("Qdrant 넣기 실패"), EmbeddingUnavailable("임베딩 모델 응답이 비었다")):
        api.behaviour["ingest"] = exc
        r = _post(api, INGEST)
        assert r.status_code == 503 and "적재하지 못했습니다" in r.json()["detail"]
    r = _post(api, ASYNC)
    assert r.status_code == 200 and r.json()["task_id"] == "t1" and api.calls[-1] == "enqueue"


def test_all_translation_routes_use_the_gate():
    """TC-TA-06 · 번역 길은 모두 문지기를 지난다 — 새 번역 라우트가 로그인만 걸고 생기면 여기서 깨진다."""
    gated = []
    for r in ingest_routes.router.routes:
        if "translation" in getattr(r, "path", ""):
            deps = [d.call for d in r.dependant.dependencies]
            gated.append((r.path, ingest_routes._translation_gate in deps))
    assert len(gated) == 3 and all(ok for _, ok in gated), gated
