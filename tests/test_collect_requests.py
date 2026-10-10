"""TC-CQ — 화면 수집 요청 표 · API (목표 기능 ① 수집 단추 · 2026-10-10).

화면(관리자)은 요청 줄만 남기고 이 PC 의 작업자(`scripts/collect_worker.py`)가 가져가 러너를 돌린다(조사서
`docs/조사/러너단계결과-화면실행통로-조사.md` 안 1). 여기서 지키는 것:

- 받는 값은 고르기 목록뿐 — 종류(step · all) · 러너 단계 이름(러너가 쓴 단계 목록에 있는 이름). 명령 글자는 받지 않는다.
- 같은 요청 한 번만(멱등) — 대기 · 도는 중인 같은 단계(또는 전체) 요청이 있으면 새 줄 없이 그 줄을 돌려준다.
  DB 의 부분 고유 색인이 정본이라 두 관리자가 동시에 눌러도 한 줄이다.
- 요청 줄과 감사 줄은 한 트랜잭션 — 실패를 삼키는 `audit()` 도우미를 이 길에서 쓰지 않는다.
- 상태를 바꾸는 요청은 관리자 + 화면 머리글(`X-Qurious-Action: collect`) + 다른 사이트 요청 거절.
- 작업자가 꺼져 있어도 요청은 받고 「대기 — PC 작업자 꺼짐」 으로 보인다 · 3시간 안에 시작하지 못한 요청은 만료.

DB 시험은 일회용 시험 DB(`QURIOUS_TEST_DATABASE_URL` · `scripts/personal/test.ps1`)가 있을 때만 돈다.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import collect_requests as cq

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 12, 14, 0, tzinfo=KST)          # 월요일 14:00 — 12:30 회차 뒤 · 막는 때 밖

CATALOG_STEPS = [
    {"name": "price", "label": "시세", "group": "받기", "fatal": True, "upload": False, "timeout_min": 30},
    {"name": "news", "label": "정책뉴스", "group": "받기", "fatal": False, "upload": False, "timeout_min": 10},
    {"name": "ohlcv", "label": "일봉", "group": "계산", "fatal": False, "upload": False, "timeout_min": 40},
    {"name": "upload", "label": "올리기", "group": "백업", "fatal": True, "upload": True, "timeout_min": 60},
]
# 막는 때는 러너가 막는 데 쓰는 함수로 셈해 단계 목록 파일에 쓴 값(scripts/daily_update.py guard_windows · TC-DU 가 맞댄다)
GUARDS = {"schedule": "12:30", "full": {"from": "11:00", "to": "13:30"},
          "steps": {"price": {"from": "12:00", "to": "13:30"}, "news": {"from": "12:20", "to": "13:30"},
                    "ohlcv": {"from": "11:50", "to": "13:30"}, "upload": {"from": "11:30", "to": "13:30"}}}
CATALOG = {"groups": [], "steps": CATALOG_STEPS, "by_name": {s["name"]: s for s in CATALOG_STEPS},
           "written_at": "2026-10-12T12:30:01+09:00", "guards": GUARDS}
EMPTY_CATALOG = {"groups": [], "steps": [], "by_name": {}, "written_at": None}


# ── 순수 — 받는 값 ────────────────────────────────────────────────────────
def test_validate_accepts_only_known_kinds_and_steps():
    """TC-CQ-01 · 받는 값 — 종류는 step · all 둘 · step 은 러너 단계 목록의 이름만 · all 에는 단계 이름을 주지 않는다 · 목록 밖은 422."""
    assert cq.validate("step", "price", CATALOG) == ("step", "price")
    assert cq.validate("all", None, CATALOG) == ("all", "")
    assert cq.validate("all", "", CATALOG) == ("all", "")
    for kind, step, word in (("bogus", "price", "종류"), ("step", None, "단계 이름"), ("step", "", "단계 이름"),
                             ("step", "rm -rf", "단계"), ("step", "PRICE", "단계"), ("all", "price", "전체 수집")):
        with pytest.raises(cq.RequestError) as e:
            cq.validate(kind, step, CATALOG)
        assert e.value.status == 422 and word in e.value.message, (kind, step, e.value.message)
    with pytest.raises(cq.RequestError) as e:                # 러너가 단계 목록을 아직 쓰지 않은 PC
        cq.validate("step", "price", EMPTY_CATALOG)
    assert e.value.status == 422 and "단계 목록" in e.value.message


# ── 순수 — 작업자 꺼짐 · 대기 까닭 · 막는 때 ──────────────────────────────
class _W:
    """작업자 줄 흉내(ORM 줄과 같은 칸)."""

    def __init__(self, seen_at, state="idle", note="", request_id=None, allow_upload=True):
        self.name, self.pid, self.started_at, self.seen_at = "PC-1", 4321, seen_at, seen_at
        self.state, self.note, self.request_id, self.allow_upload = state, note, request_id, allow_upload


def test_worker_view_marks_off_after_stale_window():
    """TC-CQ-02 · 작업자는 매 분 뜬다 — 마지막 신호가 3분 안이면 살아 있고, 넘으면 「꺼짐」 · 줄이 없으면 「없음」(등록 안내)."""
    alive = cq.worker_view(_W(NOW - timedelta(seconds=170)), now=NOW)
    assert alive["alive"] is True and alive["status"] == "idle" and alive["status_label"] == "쉬는 중"
    off = cq.worker_view(_W(NOW - timedelta(seconds=190), state="running"), now=NOW)
    assert off["alive"] is False and off["status"] == "off" and off["last_state"] == "running"
    assert "13:56" in off["note"], off["note"]                # 마지막 신호 시각(KST)을 보인다
    missing = cq.worker_view(None, now=NOW)
    assert missing["alive"] is False and missing["status"] == "missing" and "collect_worker.py install" in missing["note"]
    assert cq.WORKER_STALE_AFTER == timedelta(minutes=3)


def test_wait_reason_follows_worker():
    """TC-CQ-03 · 대기 줄의 까닭 — 작업자 꺼짐 · 다른 요청이 도는 중 · 작업자가 기다림(그 까닭 그대로) · 곧 시작."""
    rid = uuid.uuid4()
    off = cq.worker_view(None, now=NOW)
    assert "PC 작업자 꺼짐" in cq.wait_reason(rid, off)
    busy = cq.worker_view(_W(NOW, state="running", request_id=uuid.uuid4()), now=NOW)
    assert "앞 요청" in cq.wait_reason(rid, busy)
    waiting = cq.worker_view(_W(NOW, state="waiting", note="12:30 회차와 겹쳐 13:30 뒤에 돈다"), now=NOW)
    assert cq.wait_reason(rid, waiting) == "12:30 회차와 겹쳐 13:30 뒤에 돈다"
    idle = cq.worker_view(_W(NOW), now=NOW)
    assert "1분" in cq.wait_reason(rid, idle)


def test_rules_come_from_runner_catalog():
    """TC-CQ-04 · 막는 때는 러너가 막는 데 쓰는 함수로 셈해 단계 목록에 쓴 값 그대로 — 앱은 다시 셈하지 않는다(앱 이미지에는
    scripts/ 가 없고, 셈을 두 곳에 두면 한쪽만 고쳐 어긋난다) · 옛 목록(값 없음)은 None 과 까닭 · 만료 · 꺼짐 기준을 함께."""
    r = cq.rules(CATALOG)
    assert r["schedule"] == "12:30" and r["full"] == {"from": "11:00", "to": "13:30"}
    assert r["steps"] == GUARDS["steps"] and r["steps"] is not GUARDS["steps"]
    assert r["expire_hours"] == 3 and r["worker_stale_s"] == 180 and "note" not in r
    old = cq.rules(EMPTY_CATALOG)
    assert old["full"] is None and old["steps"] == {} and "단계 목록" in old["note"]


def test_rules_blocked_now_from_runner_windows_and_server_clock():
    """TC-CQ-16 · 「지금 막힘」 은 서버가 정한다 — 단계 목록의 창(러너가 쓴 값)을 서버 시각(KST)으로 견주고 끝나는 시각을 함께 준다.
    러너의 rerun_blocked · full_run_blocked 와 같은 비교(양끝 포함). 화면은 시계를 다시 세지 않는다(화면 PC 시계가 틀려도 같은 답).
    창이 없는 옛 목록은 「모름」(None) — 짐작으로 막거나 열지 않는다."""
    def at(h, m):
        return datetime(2026, 10, 12, h, m, tzinfo=KST)

    b = cq.rules(CATALOG, now=at(12, 10))["blocked_now"]
    assert b["full"] == {"blocked": True, "until": "13:30"}
    assert b["steps"]["price"] == {"blocked": True, "until": "13:30"}       # 12:00 ~ 13:30 안
    assert b["steps"]["news"] == {"blocked": False, "until": None}         # 12:20 ~ 13:30 — 아직 앞
    assert set(b["steps"]) == set(GUARDS["steps"])
    assert cq.rules(CATALOG, now=at(11, 0))["blocked_now"]["full"]["blocked"] is True     # 시작 시각 포함
    assert cq.rules(CATALOG, now=at(13, 30))["blocked_now"]["full"]["blocked"] is True    # 끝 시각 포함
    after = cq.rules(CATALOG, now=at(13, 31))["blocked_now"]
    assert after["full"] == {"blocked": False, "until": None}
    assert not any(v["blocked"] for v in after["steps"].values())
    assert cq.rules(CATALOG, now=at(10, 59))["blocked_now"]["full"]["blocked"] is False
    # 서버 시계가 UTC 여도 KST 로 바꿔 견준다(03:10Z = 12:10 KST)
    assert cq.rules(CATALOG, now=datetime(2026, 10, 12, 3, 10, tzinfo=timezone.utc))["blocked_now"]["full"]["blocked"] is True
    assert cq.rules(EMPTY_CATALOG, now=at(12, 10))["blocked_now"] is None
    # 목록 응답도 같은 시각으로 — listing 이 now 를 rules 에 넘긴다(두 시각이 어긋나지 않게)
    import inspect
    assert "rules(catalog, now=now)" in inspect.getsource(cq.listing)


def test_blocked_now_agrees_with_runner_judgement():
    """TC-CQ-17 · 앱의 「지금 막힘」 이 러너의 막힘 판정과 하루 내내 같다 — 10:00 ~ 14:00 를 5분마다, 러너가 그 시각에 쓴 창으로.
    (러너가 막는 데 쓰는 함수가 정본 — 둘이 어긋나면 화면은 열렸는데 러너가 75 로 돌려보내거나, 그 반대가 된다)"""
    from scripts import daily_update as du

    for minute in range(10 * 60, 14 * 60 + 1, 5):
        now = datetime(2026, 10, 12, minute // 60, minute % 60, tzinfo=KST)
        cat = {**CATALOG, "guards": du.guards(now)}
        b = cq.rules(cat, now=now)["blocked_now"]
        assert b["full"]["blocked"] == (du.full_run_blocked(now) is not None), now
        for s in du.STEPS:
            assert b["steps"][s.name]["blocked"] == (du.rerun_blocked(s, now) is not None), (now, s.name)


# ── 라우트 — 관리자 · 화면 머리글 · 응답 코드 ─────────────────────────────
@pytest.fixture
def client(monkeypatch):
    from app.database.postgres import get_pg_session
    from app.lib.session import get_current_user
    from app.routes import data as data_routes

    async def fake_session():
        yield object()

    calls: list = []

    async def fake_create(db, *, kind, step, user, catalog, now=None):
        calls.append(("create", kind, step, user["id"]))
        cq.validate(kind, step, catalog)
        return {"id": "r1", "kind": kind, "step": step or None, "status": "queued"}, step != "news"

    async def fake_cancel(db, *, request_id, user, catalog, now=None):
        calls.append(("cancel", request_id))
        if request_id == "00000000-0000-0000-0000-000000000404":
            raise cq.RequestError(404, "그런 요청이 없다")
        if request_id == "00000000-0000-0000-0000-000000000409":
            raise cq.RequestError(409, "대기 중인 요청만 취소한다 — 지금 「도는 중」")
        return {"id": request_id, "status": "cancelled"}

    async def fake_listing(db, *, catalog, now=None, limit=20):
        calls.append(("list", limit))
        return {"requests": [], "worker": cq.worker_view(None, now=NOW), "rules": cq.rules(catalog)}

    async def fake_worker(db, *, now=None):
        return cq.worker_view(None, now=NOW)

    monkeypatch.setattr(cq, "create", fake_create)
    monkeypatch.setattr(cq, "cancel", fake_cancel)
    monkeypatch.setattr(cq, "listing", fake_listing)
    monkeypatch.setattr(cq, "worker_status", fake_worker)
    monkeypatch.setattr(cq, "current_catalog", lambda: CATALOG)
    app = FastAPI()
    app.include_router(data_routes.router)
    app.dependency_overrides[get_pg_session] = fake_session
    app.dependency_overrides[get_current_user] = lambda: {"id": "a1", "client_id": "c1", "roles": ["user", "admin"]}
    c = TestClient(app)
    c.calls = calls
    c.app_ref = app
    return c


H = {cq.ACTION_HEADER: cq.ACTION_VALUE}


def test_routes_admin_only(client):
    """TC-CQ-05 · 넷 모두 관리자만 — 일반 사용자는 403(화면에서 숨기는 것만 믿지 않는다)."""
    from app.lib.session import get_current_user
    client.app_ref.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": ["user"]}
    rid = str(uuid.uuid4())
    assert client.post("/api/data/runner/requests", json={"kind": "all"}, headers=H).status_code == 403
    assert client.get("/api/data/runner/requests").status_code == 403
    assert client.post(f"/api/data/runner/requests/{rid}/cancel", headers=H).status_code == 403
    assert client.get("/api/data/runner/worker").status_code == 403
    assert client.calls == []


def test_state_changing_routes_need_screen_header(client):
    """TC-CQ-06 · 상태를 바꾸는 둘(만들기 · 취소)은 화면 머리글이 있어야 하고, 다른 사이트에서 온 요청은 거절한다(CSRF —
    SameSite 쿠키 위에 한 겹 더 · Jenkins 빌드 시작의 crumb 과 같은 생각) · 읽기 둘은 머리글이 없어도 된다."""
    rid = str(uuid.uuid4())
    assert client.post("/api/data/runner/requests", json={"kind": "all"}).status_code == 403
    assert client.post("/api/data/runner/requests", json={"kind": "all"},
                       headers={cq.ACTION_HEADER: "yes"}).status_code == 403
    assert client.post(f"/api/data/runner/requests/{rid}/cancel").status_code == 403
    cross = {**H, "Sec-Fetch-Site": "cross-site"}
    assert client.post("/api/data/runner/requests", json={"kind": "all"}, headers=cross).status_code == 403
    assert client.calls == []
    same = {**H, "Sec-Fetch-Site": "same-origin"}
    assert client.post("/api/data/runner/requests", json={"kind": "all"}, headers=same).status_code == 202
    assert client.get("/api/data/runner/requests").status_code == 200
    assert client.get("/api/data/runner/worker").status_code == 200


def test_create_codes(client):
    """TC-CQ-07 · 만들기 — 새 줄 202 · 이미 있는 같은 요청 200(같은 줄) · 종류 · 단계가 목록 밖이면 422(명령 글자 거절)."""
    r = client.post("/api/data/runner/requests", json={"kind": "step", "step": "price"}, headers=H)
    assert r.status_code == 202 and r.json()["created"] is True and r.json()["request"]["step"] == "price"
    r = client.post("/api/data/runner/requests", json={"kind": "step", "step": "news"}, headers=H)
    assert r.status_code == 200 and r.json()["created"] is False
    for body in ({"kind": "shell"}, {"kind": "step", "step": "price; del *"}, {"kind": "step", "step": "x" * 40},
                 {"kind": "step", "step": "nosuch"}, {"kind": "all", "step": "price"}, {"kind": "step"}):
        assert client.post("/api/data/runner/requests", json=body, headers=H).status_code == 422, body


def test_cancel_and_list_codes(client):
    """TC-CQ-08 · 취소 — 없으면 404 · 대기가 아니면 409 · 요청 ID 는 UUID 만(아니면 422) / 목록 개수 한도 1 ~ 100."""
    ok = str(uuid.uuid4())
    assert client.post(f"/api/data/runner/requests/{ok}/cancel", headers=H).json()["request"]["status"] == "cancelled"
    assert client.post("/api/data/runner/requests/00000000-0000-0000-0000-000000000404/cancel",
                       headers=H).status_code == 404
    assert client.post("/api/data/runner/requests/00000000-0000-0000-0000-000000000409/cancel",
                       headers=H).status_code == 409
    assert client.post("/api/data/runner/requests/not-a-uuid/cancel", headers=H).status_code == 422
    assert client.get("/api/data/runner/requests?limit=0").status_code == 422
    assert client.get("/api/data/runner/requests?limit=101").status_code == 422
    j = client.get("/api/data/runner/requests?limit=5").json()
    assert ("list", 5) in client.calls and j["rules"]["full"] == {"from": "11:00", "to": "13:30"}


# ── 일회용 시험 DB ────────────────────────────────────────────────────────
DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB_URL, reason="일회용 시험 DB 없음 — scripts/personal/test.ps1 로 돈다")


@pytest.fixture
def db_schema(rebalance_db_schema):
    """모든 표를 만들고 모듈 끝에 지우는 공용 픽스처(DF-73) — 새 표가 users 를 가리켜 다른 시험의 표 지우기와 엉키지 않게."""
    return rebalance_db_schema


def _db(scenario):
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    url = make_url(DB_URL)
    assert "test" in DB_URL and url.database != "fin_ai" and url.port != 15432, "일회용 시험 DB만 사용"

    async def go():
        engine = create_async_engine(DB_URL, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE collect_workers, collect_requests, audit_events, users CASCADE"))
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                return await scenario(db, async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(go())


async def _admin(db) -> dict:
    from app.models import User
    u = User(name="관리자", email=f"admin-{uuid.uuid4().hex[:8]}@test.local", password_hash="x",
             client_id=uuid.uuid4().hex[:16], roles=["user", "admin"])
    db.add(u)
    await db.commit()
    return {"id": str(u.id), "client_id": u.client_id, "name": u.name, "roles": ["user", "admin"]}


async def _audits(db, kind: str) -> list:
    from sqlalchemy import select
    from app.models import AuditEvent
    return list((await db.execute(select(AuditEvent).where(AuditEvent.event_type == kind))).scalars())


@needs_db
def test_create_is_idempotent_and_audited_together(db_schema):
    """TC-CQ-09 · 같은 요청 한 번만 — 두 번째는 같은 줄(created False) · 감사 줄은 새 줄을 만든 때 한 번(같은 트랜잭션) ·
    다른 단계 · 전체 수집은 따로 줄이 생긴다 · 작업자 줄이 없어도 받고 「PC 작업자 꺼짐」 으로 기다린다."""
    async def scenario(db, _):
        admin = await _admin(db)
        a, new_a = await cq.create(db, kind="step", step="price", user=admin, catalog=CATALOG, now=NOW)
        b, new_b = await cq.create(db, kind="step", step="price", user=admin, catalog=CATALOG, now=NOW + timedelta(seconds=5))
        c, new_c = await cq.create(db, kind="all", step=None, user=admin, catalog=CATALOG, now=NOW + timedelta(seconds=1))
        d, new_d = await cq.create(db, kind="step", step="news", user=admin, catalog=CATALOG, now=NOW + timedelta(seconds=2))
        audits = await _audits(db, "collect.request")
        listing = await cq.listing(db, catalog=CATALOG, now=NOW + timedelta(minutes=1))
        return a, new_a, b, new_b, c, new_c, d, new_d, audits, listing, admin

    a, new_a, b, new_b, c, new_c, d, new_d, audits, listing, admin = _db(scenario)
    assert (new_a, new_b, new_c, new_d) == (True, False, True, True)
    assert a["id"] == b["id"] and len({a["id"], c["id"], d["id"]}) == 3
    assert a["status"] == "queued" and a["status_label"] == "대기" and a["step_label"] == "시세"
    assert c["kind_label"] == "전체 수집" and c["step"] is None
    assert len(audits) == 3 and {x.payload["request_id"] for x in audits} == {a["id"], c["id"], d["id"]}
    assert all(str(x.user_id) == admin["id"] for x in audits)
    rows = listing["requests"]
    assert [r["id"] for r in rows] == [d["id"], c["id"], a["id"]], "새 요청이 먼저"
    assert all("PC 작업자 꺼짐" in (r["wait"] or "") for r in rows) and listing["worker"]["status"] == "missing"
    assert rows[0]["requested_by_name"] == "관리자"


@needs_db
def test_stale_queued_request_expires(db_schema):
    """TC-CQ-10 · 3시간 안에 시작하지 못한 대기 요청은 만료 — 같은 요청을 다시 누르면 옛 줄은 「만료」 · 새 줄이 생긴다
    (작업자가 꺼져 있던 요청이 몇 시간 뒤 엉뚱한 때 돌지 않게)."""
    async def scenario(db, _):
        admin = await _admin(db)
        old, _ = await cq.create(db, kind="step", step="news", user=admin, catalog=CATALOG, now=NOW - timedelta(hours=3, minutes=1))
        new, created = await cq.create(db, kind="step", step="news", user=admin, catalog=CATALOG, now=NOW)
        n = await cq.expire_stale(db, now=NOW)
        listing = await cq.listing(db, catalog=CATALOG, now=NOW)
        return old, new, created, n, listing

    old, new, created, n, listing = _db(scenario)
    assert created is True and new["id"] != old["id"] and n == 0
    by_id = {r["id"]: r for r in listing["requests"]}
    assert by_id[old["id"]]["status"] == "expired" and by_id[old["id"]]["status_label"] == "만료"
    assert "3시간" in by_id[old["id"]]["result"]


@needs_db
def test_listing_shows_expiry_before_anyone_rewrites_the_row(db_schema):
    """TC-CQ-15 · 목록은 읽기만 한다 — 3시간 넘게 아무도 고치지 않은 대기 줄(작업자 꺼짐)도 보이기는 「만료」 · DB 줄은 그대로
    대기(다음 만들기 · 작업자가 고친다) · 만료 전 줄은 남은 시각(expires_at)과 기다리는 까닭을 함께."""
    from sqlalchemy import insert, select

    from app.models.collect import CollectRequest

    async def scenario(db, _):
        old = (await db.execute(insert(CollectRequest).values(kind="step", step="price", status="queued",
                                                              requested_at=NOW - timedelta(hours=4))
                                .returning(CollectRequest.id))).scalar_one()
        new = (await db.execute(insert(CollectRequest).values(kind="all", step="", status="queued",
                                                              requested_at=NOW - timedelta(minutes=5))
                                .returning(CollectRequest.id))).scalar_one()
        await db.commit()
        listing = await cq.listing(db, catalog=CATALOG, now=NOW)
        raw = (await db.execute(select(CollectRequest.status).where(CollectRequest.id == old))).scalar_one()
        return str(old), str(new), listing, raw

    old, new, listing, raw = _db(scenario)
    by_id = {r["id"]: r for r in listing["requests"]}
    assert by_id[old]["status"] == "expired" and "3시간" in by_id[old]["result"] and by_id[old]["wait"] is None
    assert raw == "queued", "목록(GET)은 줄을 고치지 않는다"
    assert by_id[new]["status"] == "queued" and by_id[new]["expires_at"].startswith("2026-10-12T16:55")
    assert "PC 작업자 꺼짐" in by_id[new]["wait"]


@needs_db
def test_cancel_only_while_queued(db_schema):
    """TC-CQ-11 · 취소는 「대기」 일 때만 — 취소 줄 + 감사 줄 · 두 번째 취소 409 · 도는 중 409 · 없는 ID 404."""
    async def scenario(db, _):
        admin = await _admin(db)
        a, _ = await cq.create(db, kind="step", step="price", user=admin, catalog=CATALOG, now=NOW)
        b, _ = await cq.create(db, kind="all", step=None, user=admin, catalog=CATALOG, now=NOW)
        out = await cq.cancel(db, request_id=a["id"], user=admin, catalog=CATALOG, now=NOW)
        codes = []
        for rid in (a["id"], str(uuid.uuid4())):
            try:
                await cq.cancel(db, request_id=rid, user=admin, catalog=CATALOG, now=NOW)
            except cq.RequestError as e:
                codes.append(e.status)
        assert await cq.claim(db, request_id=b["id"], worker="PC-1", now=NOW) is True
        try:
            await cq.cancel(db, request_id=b["id"], user=admin, catalog=CATALOG, now=NOW)
        except cq.RequestError as e:
            codes.append((e.status, e.message))
        return out, codes, await _audits(db, "collect.cancel")

    out, codes, audits = _db(scenario)
    assert out["status"] == "cancelled" and out["finished_at"] and "취소" in out["result"]
    assert codes[0] == 409 and codes[1] == 404 and codes[2][0] == 409 and "도는 중" in codes[2][1]
    assert len(audits) == 1 and audits[0].payload["request_id"] == out["id"]


@needs_db
def test_db_constraints_hold_without_the_service(db_schema):
    """TC-CQ-12 · 서비스를 거치지 않아도 DB 가 지킨다 — 같은 대상의 활성 줄 둘 · 전체에 단계 이름 · 모르는 상태 · 단계 없는 step."""
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    from app.models.collect import CollectRequest

    async def scenario(db, maker):
        bad = [
            [{"kind": "step", "step": "price", "status": "queued"}, {"kind": "step", "step": "price", "status": "running"}],
            [{"kind": "all", "step": "price", "status": "queued"}],
            [{"kind": "step", "step": "price", "status": "bogus"}],
            [{"kind": "step", "step": "", "status": "queued"}],
            [{"kind": "shell", "step": "", "status": "queued"}],
        ]
        failed = []
        for rows in bad:
            async with maker() as s:
                try:
                    for r in rows:
                        await s.execute(insert(CollectRequest).values(**r))
                    await s.commit()
                    failed.append(False)
                except IntegrityError:
                    failed.append(True)
        async with maker() as s:                              # 끝난 줄은 몇 개든 된다(활성 줄만 하나)
            for st in ("done", "failed", "cancelled", "queued"):
                await s.execute(insert(CollectRequest).values(kind="step", step="news", status=st))
            await s.commit()
        return failed

    assert _db(scenario) == [True] * 5


@needs_db
def test_claim_is_atomic_and_finish_only_from_running(db_schema):
    """TC-CQ-13 · 작업자 쪽 상태 바꾸기 — 가져가기는 대기 줄 하나를 한 번만(두 작업자가 같은 줄을 못 가져간다) ·
    끝 적기는 도는 중에서만 · 되돌리기(막힘)는 도는 중 → 대기 · 거절은 대기에서만 · 심장 박동은 한 줄을 고친다."""
    async def scenario(db, maker):
        admin = await _admin(db)
        a, _ = await cq.create(db, kind="step", step="price", user=admin, catalog=CATALOG, now=NOW)
        b, _ = await cq.create(db, kind="step", step="upload", user=admin, catalog=CATALOG, now=NOW)

        async def claim_with(name):
            async with maker() as s:
                return await cq.claim(s, request_id=a["id"], worker=name, now=NOW)
        both = await asyncio.gather(claim_with("PC-1"), claim_with("PC-2"))
        early_finish = await cq.finish(db, request_id=b["id"], status="done", exit_code=0, result="x", now=NOW)
        back = await cq.requeue(db, request_id=a["id"], note="다른 실행이 돌고 있다 — 다시 기다림")
        again = await cq.claim(db, request_id=a["id"], worker="PC-1", now=NOW)
        done = await cq.finish(db, request_id=a["id"], status="done", exit_code=0, result="✅ 시세 · 12초",
                               log_path="data/collector/logs/x.log", now=NOW + timedelta(seconds=12))
        twice = await cq.finish(db, request_id=a["id"], status="failed", exit_code=1, result="y", now=NOW)
        rej = await cq.reject(db, request_id=b["id"], why="이 작업자는 올리기 단계를 받지 않는다", now=NOW)
        for i in range(3):
            await cq.heartbeat(db, name="PC-1", pid=100 + i, started_at=NOW, state="idle", allow_upload=False,
                               now=NOW + timedelta(seconds=i))
        listing = await cq.listing(db, catalog=CATALOG, now=NOW + timedelta(seconds=30))
        return both, early_finish, back, again, done, twice, rej, listing

    both, early_finish, back, again, done, twice, rej, listing = _db(scenario)
    assert sorted(both) == [False, True]
    assert early_finish is False and back is True and again is True and done is True and twice is False and rej is True
    by_step = {r["step"]: r for r in listing["requests"]}
    p = by_step["price"]
    assert p["status"] == "done" and p["exit_code"] == 0 and p["worker"] == "PC-1" and p["minutes"] == 0.2
    assert p["log"] == "data/collector/logs/x.log" and p["started_at"] and p["finished_at"]
    assert by_step["upload"]["status"] == "rejected" and "올리기" in by_step["upload"]["result"]
    w = listing["worker"]
    assert w["alive"] is True and w["pid"] == 102 and w["allow_upload"] is False


@needs_db
def test_account_deletion_keeps_request_log_without_the_person(db_schema):
    """TC-CQ-14 · 탈퇴 — 수집 요청은 감사 기록처럼 운영 기록이라 줄을 남기고 요청자 칸만 비운다(account.DEIDENTIFY_TABLES)."""
    from sqlalchemy import select

    from app.models.collect import CollectRequest
    from app.services import account

    async def scenario(db, _):
        admin = await _admin(db)
        a, _ = await cq.create(db, kind="step", step="price", user=admin, catalog=CATALOG, now=NOW)
        counts = await account.delete_user_data(db, uuid.UUID(admin["id"]))
        await db.commit()
        row = (await db.execute(select(CollectRequest).where(CollectRequest.id == uuid.UUID(a["id"])))).scalar_one()
        return counts, row

    counts, row = _db(scenario)
    assert "collect_requests(사용자 칸 비움)" in counts and row.requested_by is None and row.status == "queued"
