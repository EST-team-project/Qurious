"""#200: 실제 인증 의존성 + HTTP 조회/취소/발행. 외부 작업은 실행하지 않는다."""
import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database.postgres import get_pg_session
from app.lib import jwt_auth, session
from app.models.task import TaskOwnership
from app.routes import tasks
from app.services import task_access

A = {"id": str(uuid.uuid4()), "roles": ["user"]}
B = {"id": str(uuid.uuid4()), "roles": ["user"]}
ADMIN = {"id": str(uuid.uuid4()), "roles": ["admin"]}
TASK_ID = str(uuid.uuid4())


class OwnershipDB:
    def __init__(self):
        self.rows = {}
        self.pending = []
        self.commit_error = None
        self.read_error = None

    def add(self, row):
        self.pending.append(row)

    async def commit(self):
        if self.commit_error:
            raise self.commit_error
        for row in self.pending:
            self.rows[row.task_id] = row
        self.pending.clear()

    async def rollback(self):
        self.pending.clear()

    async def get(self, model, task_id):
        assert model is TaskOwnership
        if self.read_error:
            raise self.read_error
        return self.rows.get(task_id)


@pytest.fixture
def env(monkeypatch):
    db = OwnershipDB()
    db.rows[TASK_ID] = TaskOwnership(task_id=TASK_ID, user_id=uuid.UUID(A["id"]))
    app = FastAPI()
    app.include_router(tasks.router)

    async def database():
        yield db

    app.dependency_overrides[get_pg_session] = database
    monkeypatch.setattr(settings, "JWT_SECRET", "issue200-test-secret-never-for-production")
    monkeypatch.setattr(jwt_auth, "is_revoked", AsyncMock(return_value=False))
    monkeypatch.setattr(session, "get_session", AsyncMock(side_effect=lambda sid: {"a": A, "b": B, "admin": ADMIN}.get(sid)))
    monkeypatch.setattr(session, "touch_session", AsyncMock())
    backend = Mock()
    backend.get_task_meta.return_value = {"status": "SUCCESS", "result": {"answer": "A의 답변"}}
    result = Mock(return_value=SimpleNamespace(backend=backend))
    revoke = Mock()
    monkeypatch.setattr(tasks, "AsyncResult", result)
    monkeypatch.setattr(tasks.celery_app.control, "revoke", revoke)
    with TestClient(app) as client:
        yield SimpleNamespace(app=app, client=client, db=db, result=result, backend=backend, revoke=revoke)


def auth(user=A, kind="jwt"):
    if kind == "jwt":
        return {"Authorization": "Bearer " + jwt_auth.create_access_token(user)}
    sid = "a" if user == A else "b" if user == B else "admin"
    return {"Cookie": f"{session.COOKIE_NAME}={sid}"}


@pytest.mark.parametrize("method", ["get", "delete"])
def test_unauthenticated_requests_never_reach_celery(env, method):
    response = getattr(env.client, method)(f"/api/tasks/{TASK_ID}")
    assert response.status_code == 401
    env.result.assert_not_called()
    env.revoke.assert_not_called()


@pytest.mark.parametrize("kind", ["jwt", "cookie"])
def test_owner_can_read_and_request_normal_cancel(env, kind):
    headers = auth(kind=kind)
    response = env.client.get(f"/api/tasks/{TASK_ID}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"task_id": TASK_ID, "state": "success", "result": {"answer": "A의 답변"}}
    response = env.client.delete(f"/api/tasks/{TASK_ID}", headers=headers)
    assert response.status_code == 200 and response.json()["terminate"] is False
    env.revoke.assert_called_once_with(TASK_ID, terminate=False)


@pytest.mark.parametrize("method", ["get", "delete"])
@pytest.mark.parametrize("kind", ["jwt", "cookie"])
def test_other_owner_unknown_and_legacy_tasks_are_indistinguishable(env, method, kind):
    call = getattr(env.client, method)
    denied = call(f"/api/tasks/{TASK_ID}", headers=auth(B, kind))
    unknown = call("/api/tasks/old-system-task-without-owner", headers=auth(B, kind))
    assert denied.status_code == unknown.status_code == 404
    assert denied.json() == unknown.json()
    env.result.assert_not_called()
    env.revoke.assert_not_called()


def test_owner_cannot_terminate_worker(env):
    response = env.client.delete(f"/api/tasks/{TASK_ID}?terminate=true", headers=auth())
    assert response.status_code == 403
    env.revoke.assert_not_called()


@pytest.mark.parametrize("task_id", [TASK_ID, "legacy-system-job"])
def test_admin_can_read_and_terminate_registered_or_legacy_tasks(env, task_id):
    assert env.client.get(f"/api/tasks/{task_id}", headers=auth(ADMIN)).status_code == 200
    assert env.client.delete(f"/api/tasks/{task_id}?terminate=true", headers=auth(ADMIN)).status_code == 200
    env.revoke.assert_called_once_with(task_id, terminate=True)


@pytest.mark.parametrize("user", [A, ADMIN])
@pytest.mark.parametrize("method", ["get", "delete"])
def test_ownership_storage_failure_fails_closed_even_for_admin(env, user, method):
    env.db.read_error = SQLAlchemyError("postgres://private-password@internal")
    response = getattr(env.client, method)(f"/api/tasks/{TASK_ID}", headers=auth(user))
    assert response.status_code == 503
    assert "private-password" not in response.text
    env.result.assert_not_called()
    env.revoke.assert_not_called()


@pytest.mark.parametrize("state, expected", [("PENDING", "pending"), ("STARTED", "running"), ("RETRY", "running"), ("REVOKED", "error"), ("FAILURE", "error")])
def test_task_state_snapshot_does_not_expose_internal_errors(env, state, expected):
    env.backend.get_task_meta.return_value = {"status": state, "result": RuntimeError("secret-key /internal/path")}
    response = env.client.get(f"/api/tasks/{TASK_ID}", headers=auth())
    assert response.status_code == 200
    assert response.json()["state"] == expected and response.json()["result"] is None
    assert "secret-key" not in response.text and "/internal/path" not in response.text
    env.backend.get_task_meta.assert_called_once_with(TASK_ID)


@pytest.mark.parametrize("method", ["get", "delete"])
def test_celery_backend_failure_returns_safe_error(env, method):
    env.backend.get_task_meta.side_effect = RuntimeError("redis://private-password")
    env.revoke.side_effect = RuntimeError("redis://private-password")
    response = getattr(env.client, method)(f"/api/tasks/{TASK_ID}", headers=auth())
    assert response.status_code == 503 and "private-password" not in response.text


def test_registration_failure_prevents_publish(env):
    env.db.commit_error = SQLAlchemyError("private-password")
    task = Mock()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(task_access.enqueue_owned_task(env.db, A, task))
    assert exc.value.status_code == 503 and "private-password" not in exc.value.detail
    task.apply_async.assert_not_called()
    assert not env.db.pending


def test_uncertain_publish_keeps_owner_and_does_not_retry(env):
    task = Mock()
    task.apply_async.side_effect = RuntimeError("broker may have received this")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(task_access.enqueue_owned_task(env.db, A, task, question="private question"))
    assert exc.value.status_code == 503
    task.apply_async.assert_called_once()
    sent = task.apply_async.call_args.kwargs
    assert sent["retry"] is False
    assert str(env.db.rows[sent["task_id"]].user_id) == A["id"]


@pytest.mark.parametrize("path, body, task_name", [
    ("/api/chat/async", {"question": "질문", "use_rag": False, "history": [{"role": "user", "content": "앞 질문"}]}, "run_agent_task"),
    ("/api/ingest/financial/async", None, "financial_ingest_task"),
    ("/api/ingest/crawl/auto/async", None, "auto_crawl_task"),
    ("/api/ingest/crawl/url/async", {"url": "https://example.com"}, "url_crawl_task"),
    ("/api/ingest/translation-data/async", {"data_type": "labeled", "categories": ["news"], "languages": ["en"], "max_docs": 2}, "translation_ingest_task"),
])
def test_all_http_producers_save_owner_before_publish_and_return_pollable_task(env, monkeypatch, path, body, task_name):
    from app.routes import chat, ingest
    from app.tasks import agent_tasks, ingest_tasks

    env.app.include_router(chat.router)
    env.app.include_router(ingest.router)
    monkeypatch.setattr(chat, "_get_or_create_conversation", AsyncMock(return_value=str(uuid.uuid4())))
    monkeypatch.setattr(ingest.url_guard, "ensure_allowed", AsyncMock())
    task = getattr(agent_tasks if task_name == "run_agent_task" else ingest_tasks, task_name)
    captured = []

    def publish(*, task_id, kwargs, retry):
        # 발행 함수가 불리는 순간 이미 커밋된 행이어야 한다.
        assert str(env.db.rows[task_id].user_id) == A["id"]
        assert retry is False and not env.db.pending
        captured.append((task_id, kwargs))
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(task, "apply_async", publish)
    response = env.client.post(path, json=body, headers=auth(kind="cookie"))
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(captured) == 1 and captured[0][0] == result["task_id"]
    assert env.client.get(result["poll_url"], headers=auth()).status_code == 200
    assert env.client.get(result["poll_url"], headers=auth(B)).status_code == 404
    if task_name == "run_agent_task":
        assert captured[0][1]["user_id"] == A["id"]
        assert captured[0][1]["question"] == body["question"]
    elif task_name == "url_crawl_task":
        assert captured[0][1] == {"url": body["url"]}
    elif task_name == "translation_ingest_task":
        assert captured[0][1] == body


def test_two_users_receive_distinct_owned_ids(env):
    task = Mock()

    async def run():
        return await task_access.enqueue_owned_task(env.db, A, task), await task_access.enqueue_owned_task(env.db, B, task)

    a, b = asyncio.run(run())
    assert a != b
    assert str(env.db.rows[a].user_id) == A["id"]
    assert str(env.db.rows[b].user_id) == B["id"]


@pytest.mark.skipif(not os.environ.get("QURIOUS_TEST_DATABASE_URL"), reason="격리 PostgreSQL 필요")
def test_real_database_commit_survives_new_sessions_and_user_deletion(env, rebalance_db_schema):
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.models import User

    engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with sessions() as db:
            for user in (A, B):
                db.add(User(id=uuid.UUID(user["id"]), name="시험", email=f"{user['id']}@test.invalid",
                            password_hash="not-a-real-hash", client_id=user["id"].replace("-", "")))
            await db.commit()

    # 발행하는 스레드의 별도 연결에서 소유자가 이미 보이는지 확인한다.
    def publish(*, task_id, **kwargs):
        async def check():
            async with sessions() as db:
                row = await db.get(TaskOwnership, task_id)
                assert row is not None and str(row.user_id) == A["id"]
        asyncio.run(check())

    async def enqueue():
        async with sessions() as db:
            return await task_access.enqueue_owned_task(db, A, SimpleNamespace(apply_async=publish))

    async def database():
        async with sessions() as db:
            yield db

    async def cleanup_user():
        async with sessions() as db:
            await db.execute(delete(User).where(User.id == uuid.UUID(A["id"])))
            await db.commit()

    asyncio.run(setup())
    task_id = asyncio.run(enqueue())
    env.app.dependency_overrides[get_pg_session] = database
    assert env.client.get(f"/api/tasks/{task_id}", headers=auth()).status_code == 200
    assert env.client.get(f"/api/tasks/{task_id}", headers=auth(B)).status_code == 404
    asyncio.run(cleanup_user())
    assert env.client.get(f"/api/tasks/{task_id}", headers=auth()).status_code == 404
    asyncio.run(engine.dispose())
