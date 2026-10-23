"""탈퇴 때 올린 문서 조각 지우기 시험 (TC-DIA) — `DELETE /api/me`(app/routes/auth.py · DF-146 · 2026-10-23).

무엇을 지키나 — 사용자 결정(2026-10-23): 탈퇴할 때 벡터 조각을 못 지우면 **탈퇴를 멈추고 503**.
1. 조각 지우기가 실패하면 DB 를 하나도 지우지 않는다(계정 · 기록 그대로 · 다시 시도할 수 있다).
2. 올린 문서가 없으면 벡터 DB 를 부르지 않는다 — 벡터 DB 가 꺼져 있어도 탈퇴한다.
3. 올린 문서가 있으면 그 사람 ID · 그 사람 출처 키로 조각부터 지우고, 지운 수를 응답에 싣는다.

DB · 벡터 DB 없이 돈다 — 세션 · 사용자 행 · 계정 함수는 가짜로, 문지기 모듈(app/services/user_docs.py)은 가짜 모듈로
바꿔 끼운다(라우트가 올린 문서가 있을 때만 안에서 가져오므로, 호스트 파이썬에 LangChain 이 없어도 이 시험은 돈다).
"""
from __future__ import annotations

import sys
import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services as services_pkg
from app.lib.jwt_auth import get_current_user_any
from app.routes import auth as auth_mod

UID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
BODY = {"password": "pw-for-test", "confirm": "탈퇴"}


class _Session:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def commit(self):
        self.log.append("commit")

    async def rollback(self):
        self.log.append("rollback")


class _VectorStoreError(RuntimeError):
    pass


@pytest.fixture
def harness(monkeypatch):
    log: list = []
    state = {"keys": [], "fail": False}

    async def keys(db, uid):
        log.append(("keys", uid))
        return list(state["keys"])

    async def delete_user_data(db, uid):
        log.append(("delete_user_data", uid))
        return {"users": 1}

    async def delete_owner(owner_id, source_keys=()):
        log.append(("delete_owner", owner_id, list(source_keys)))
        if state["fail"]:
            raise _VectorStoreError("Qdrant 에 닿지 못함")
        return len(list(source_keys)) + 1

    async def load_user(db, user):
        return types.SimpleNamespace(id=UID, password_hash="x")

    async def noop(*a, **k):
        return None

    fake_ud = types.ModuleType("app.services.user_docs")
    fake_ud.delete_owner = delete_owner
    fake_rp = types.ModuleType("app.services.rag_pipeline")
    fake_rp.VectorStoreError = _VectorStoreError
    monkeypatch.setitem(sys.modules, "app.services.user_docs", fake_ud)
    monkeypatch.setitem(sys.modules, "app.services.rag_pipeline", fake_rp)
    monkeypatch.setattr(services_pkg, "user_docs", fake_ud, raising=False)   # 진짜를 먼저 가져온 프로세스(컨테이너)에서도 가짜로

    monkeypatch.setattr(auth_mod, "get_session_factory", lambda: (lambda: _Session(log)))
    monkeypatch.setattr(auth_mod, "_load_user", load_user)
    monkeypatch.setattr(auth_mod.account, "verify_password", lambda pw, h: True)
    monkeypatch.setattr(auth_mod.account, "uploaded_source_keys", keys)
    monkeypatch.setattr(auth_mod.account, "delete_user_data", delete_user_data)
    for name in ("delete_all_user_sessions", "clear_user_state", "revoke_all_tokens_for", "audit"):
        monkeypatch.setattr(auth_mod, name, noop)

    app = FastAPI()
    app.include_router(auth_mod.router)
    app.dependency_overrides[get_current_user_any] = lambda: {"id": str(UID), "email": "d@example.com", "roles": ["user"]}
    return TestClient(app), log, state


def test_purge_failure_stops_account_deletion_with_503(harness):
    """TC-DIA-01 · 조각 지우기 실패 → 503 · DB 는 지우지도 커밋하지도 않는다(계정 · 기록 그대로)."""
    client, log, state = harness
    state.update(keys=[f"upload:{UID}:memo.txt"], fail=True)
    res = client.request("DELETE", "/api/me", json=BODY)
    assert res.status_code == 503, res.text
    assert "탈퇴를 멈췄습니다" in res.json()["detail"]
    assert ("delete_owner", str(UID), [f"upload:{UID}:memo.txt"]) in log
    assert not any(e[0] == "delete_user_data" for e in log if isinstance(e, tuple)) and "commit" not in log


def test_no_uploads_never_touches_the_vector_store(harness):
    """TC-DIA-02 · 올린 문서가 없으면 벡터 DB 를 부르지 않고 탈퇴한다(꺼져 있어도 된다)."""
    client, log, state = harness
    state.update(keys=[], fail=True)
    res = client.request("DELETE", "/api/me", json=BODY)
    assert res.status_code == 200, res.text
    assert not any(isinstance(e, tuple) and e[0] == "delete_owner" for e in log)
    assert ("delete_user_data", UID) in log and "commit" in log


def test_uploads_are_purged_first_and_counted(harness):
    """TC-DIA-03 · 올린 문서가 있으면 조각부터(그 사람 ID · 출처 키) 지우고 DB 를 지운다 · 지운 수가 응답에 실린다."""
    client, log, state = harness
    state.update(keys=[f"upload:{UID}:a.txt", f"upload:{UID}:b.txt"], fail=False)
    res = client.request("DELETE", "/api/me", json=BODY)
    assert res.status_code == 200, res.text
    order = [e[0] for e in log if isinstance(e, tuple)]
    assert order.index("delete_owner") < order.index("delete_user_data"), "조각보다 DB 를 먼저 지웠다"
    assert res.json()["deleted"]["user_docs(벡터 조각)"] == 3
