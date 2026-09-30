"""계정 CRUD 시험 (TC-AC) — 이메일 대소문자 · 비밀번호 규칙 · 이름 바꾸기 · 비밀번호 바꾸기 · 탈퇴.

무엇을 지키나
1. **이메일(로그인 ID)은 대소문자를 가리지 않는다** — 가입한 그대로든 전부 대문자든 로그인되고, 대소문자만 다른
   두 번째 가입은 앱과 DB(`lower(email)` 유일 색인) 둘 다 막는다. 규칙 전에 섞여 저장된 옛 행도 찾는다.
2. **비밀번호 규칙은 새로 정할 때만** — 짧음 · 너무 김(64자 · 72바이트) · 흔함 · 같은 글자 반복 · 이메일과 같음을
   한국어 한 줄로 거절한다. 72바이트를 넘는 입력으로 로그인해도 서버 오류가 아니라 「틀림」 이다(bcrypt 5.0).
3. **민감한 변경은 재인증** — 비밀번호 변경 · 탈퇴는 현재 비밀번호를 다시 받는다. 변경 뒤 다른 기기의 세션은
   끊기고 이 기기는 새 세션 ID 를 받으며, 그 전에 나간 토큰도 끊긴다.
4. **탈퇴는 파기** — 사용자 행을 가리키는 모든 표의 행을 지운다(감사 기록은 사용자 칸만 비운다). 다른 사용자의
   행은 그대로다.

돌리는 법 — DB 시험은 `.\\scripts\\personal\\test.ps1`(일회용 PostgreSQL 컨테이너)에서 돈다. DB 주소
(`QURIOUS_TEST_DATABASE_URL`)가 없으면 규칙 · 정적 시험만 돈다.
Redis 는 가짜(`_FakeRedis`)를 끼운다 — 세션 · 토큰을 끊는 일이 어느 키를 지우고 남기는지만 보면 되기 때문이다.
⚠️ DB 시험은 그 DB 의 **모든 표를 지우고 다시 만든 뒤, 끝에 모두 지운다** — 다른 DB 시험(TC-I14)이 제 표를
   새로 만들 수 있게. 개발 DB 주소를 넣지 않는다.
"""
from __future__ import annotations

import os
import pathlib
import unicodedata
import uuid

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.services import account

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB_URL, reason="QURIOUS_TEST_DATABASE_URL 이 없다 — scripts/personal/test.ps1 로 돌린다")
GOOD_PW = "valid-pass-1234"


# ── 1. 규칙 (DB 없이 돈다) ───────────────────────────────────────────────────

def test_email_is_trimmed_and_lowercased():
    assert account.normalize_email("  Kim.Lee@Example.COM ") == "kim.lee@example.com"
    assert account.login_key(" KIM.LEE@EXAMPLE.COM ") == "kim.lee@example.com"


def test_invalid_email_gives_one_korean_line():
    with pytest.raises(account.AccountError, match="이메일 형식"):
        account.normalize_email("not-an-email")
    with pytest.raises(account.AccountError, match="입력하세요"):
        account.normalize_email("   ")


def test_name_rules():
    assert account.validate_name("  김   이  ") == "김 이"
    with pytest.raises(account.AccountError):
        account.validate_name("   ")
    with pytest.raises(account.AccountError):
        account.validate_name("가" * (account.NAME_MAX_CHARS + 1))


@pytest.mark.parametrize("pw, why", [
    ("1", "8자 이상"),
    ("password123", "흔한"),
    ("aaaaaaaaaa", "반복"),
    ("가" * 25, "72바이트"),                 # 75바이트 — bcrypt 5.0 이면 예외(500)가 나던 길이
    ("ab" * 33, "64자 이하"),                # 66자
])
def test_bad_new_passwords_are_rejected(pw, why):
    with pytest.raises(account.AccountError, match=why):
        account.check_new_password(pw)


def test_good_new_passwords_pass_and_come_back_nfc():
    assert account.check_new_password("correct horse battery") == "correct horse battery"
    edge = "가나다라마바사아자차카타파하거너더러머버서어저처"                  # 24자 = 정확히 72바이트
    assert len(edge) == 24 and len(edge.encode("utf-8")) == 72
    assert account.check_new_password(edge) == edge
    nfd = unicodedata.normalize("NFD", "한글비밀번호입니다")
    assert account.check_new_password(nfd) == "한글비밀번호입니다"            # 해시는 NFC 모양으로


def test_password_equal_to_email_or_current_is_rejected():
    with pytest.raises(account.AccountError, match="이메일"):
        account.check_new_password("kimlee12", email="kimlee12@example.com")
    with pytest.raises(account.AccountError, match="같습니다"):
        account.check_new_password(GOOD_PW, current=GOOD_PW)


def test_min_length_follows_setting(monkeypatch):
    monkeypatch.setattr(settings, "PASSWORD_MIN_LENGTH", 15)
    with pytest.raises(account.AccountError, match="15자 이상"):
        account.check_new_password("twelve-chars")
    assert account.password_policy()["min_length"] == 15


def test_verify_password_never_raises():
    h = account.hash_password(account.check_new_password("정상 비밀번호 1234"))
    assert account.verify_password("정상 비밀번호 1234", h) is True
    assert account.verify_password("틀린 비밀번호 1234", h) is False
    assert account.verify_password("p" * 100, h) is False           # 72바이트 초과 — 예외 대신 False
    assert account.verify_password(GOOD_PW, None) is False          # 없는 계정 — 가짜 해시로 시간만 쓴다
    assert account.verify_password("", h) is False


def test_nfd_input_matches_nfc_hash():
    h = account.hash_password("한글비밀번호입니다")
    assert account.verify_password(unicodedata.normalize("NFD", "한글비밀번호입니다"), h) is True


def test_user_owned_columns_cover_every_fk_to_users():
    import app.models  # noqa: F401
    from app.models.base import Base

    expected = {(t.name, fk.parent.name) for t in Base.metadata.tables.values()
                for fk in t.foreign_keys if fk.column.table.name == "users"}
    got = {(t.name, c.name) for t, c in account.user_owned_columns()}
    assert got == expected
    assert ("audit_events", "user_id") in got and len(got) >= 25


def test_auth_routes_use_the_account_rules():
    """인증 라우트가 비밀번호를 직접 해시 · 비교하지 않는다 — 규칙이 한 곳(account)에만 있게."""
    src = (ROOT / "app" / "routes" / "auth.py").read_text(encoding="utf-8")
    assert "bcrypt" not in src.split('"""', 2)[2]          # 모듈 설명 뒤 코드에 bcrypt 직접 호출이 없다
    for name in ("normalize_email", "check_new_password", "verify_password", "delete_user_data"):
        assert f"account.{name}" in src


def test_entry_pages_look_at_the_session():
    """첫 주소 · 로그인 · 가입 · 앱 화면이 로그인 상태를 보고 갈 곳을 고른다(주소를 다시 열면 로그아웃처럼 보이던 것)."""
    src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    for fn in ("async def index", "async def login_page", "async def register_page", "async def app_page"):
        body = src.split(fn, 1)[1].split("@app.", 1)[0]
        assert "_logged_in(" in body, fn


# ── 2. DB · 라우트 (일회용 PostgreSQL + 가짜 Redis) ──────────────────────────

class _FakeRedis:
    """세션 · 캐시 코드가 쓰는 Redis 명령만 흉내 낸다(만료는 숫자로만 기억)."""

    def __init__(self):
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, k): return self.kv.get(k)
    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        if ex:
            self.ttls[k] = ex
        return True
    async def setex(self, k, ttl, v): self.kv[k] = v; self.ttls[k] = ttl
    async def delete(self, *ks):
        for k in ks:
            self.kv.pop(k, None); self.sets.pop(k, None); self.ttls.pop(k, None)
    async def exists(self, k): return int(k in self.kv or k in self.sets)
    async def sadd(self, k, v): self.sets.setdefault(k, set()).add(v)
    async def srem(self, k, v): self.sets.get(k, set()).discard(v)
    async def smembers(self, k): return set(self.sets.get(k, set()))
    async def expire(self, k, ttl): self.ttls[k] = ttl
    async def ttl(self, k): return self.ttls.get(k, -1)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fake_redis(monkeypatch):
    from app.lib import redis_cache
    fake = _FakeRedis()
    monkeypatch.setattr(redis_cache, "_redis", fake)
    return fake


@pytest.fixture
async def factory(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.models  # noqa: F401
    from app.models.base import Base
    from app.routes import auth as auth_routes

    engine = create_async_engine(DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _no_audit(*_a, **_k):
        return None

    monkeypatch.setattr(auth_routes, "get_session_factory", lambda: maker)
    monkeypatch.setattr(auth_routes, "audit", _no_audit)
    yield maker
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _sid(resp: Response) -> str:
    cookie = resp.headers.get("set-cookie", "")
    assert "fin_session=" in cookie
    return cookie.split("fin_session=", 1)[1].split(";", 1)[0]


async def _session_user(sid: str) -> dict:
    from app.lib.session import get_session
    return await get_session(sid)


async def _register(email: str, name: str = "시험", pw: str = GOOD_PW) -> tuple[dict, str]:
    from app.routes import auth as a
    resp = Response()
    out = await a.register(a.RegisterBody(name=name, email=email, password=pw), resp)
    return out, _sid(resp)


@needs_db
@pytest.mark.anyio
async def test_register_and_login_ignore_case(factory, fake_redis):
    from app.routes import auth as a

    out, _ = await _register("Kim.Lee@Example.COM", name="  김   이 ")
    assert out["user"]["email"] == "kim.lee@example.com" and out["user"]["name"] == "김 이"
    for typed in ("Kim.Lee@Example.COM", "KIM.LEE@EXAMPLE.COM", " kim.lee@example.com "):
        assert (await a.login(a.LoginBody(email=typed, password=GOOD_PW), Response()))["ok"] is True
    with pytest.raises(HTTPException) as dup:
        await a.register(a.RegisterBody(name="둘", email="KIM.LEE@example.com", password=GOOD_PW), Response())
    assert dup.value.status_code == 400
    with pytest.raises(HTTPException) as long_pw:                  # 예전에는 ValueError → 500
        await a.login(a.LoginBody(email="kim.lee@example.com", password="p" * 100), Response())
    assert long_pw.value.status_code == 401
    with pytest.raises(HTTPException) as short:
        await a.register(a.RegisterBody(name="셋", email="short@example.com", password="1"), Response())
    assert short.value.status_code == 422 and "8자" in short.value.detail


@needs_db
@pytest.mark.anyio
async def test_legacy_mixed_case_row_is_found_and_db_blocks_case_duplicates(factory):
    from app.models import User

    async with factory() as db:
        db.add(User(name="옛", email="Legacy@Example.com", password_hash="x", client_id="LEGACY0000000001"))
        await db.commit()
        found = await account.find_user_by_email(db, "legacy@EXAMPLE.com")
        assert found is not None and found.email == "Legacy@Example.com"
        assert await account.email_taken(db, "legacy@example.com") is True
        db.add(User(name="둘", email="legacy@example.com", password_hash="x", client_id="LEGACY0000000002"))
        with pytest.raises(IntegrityError):                         # uq_users_email_lower
            await db.commit()


@needs_db
@pytest.mark.anyio
async def test_update_name_changes_db_and_every_session(factory, fake_redis):
    from app.models import User
    from app.routes import auth as a

    out, sid1 = await _register("name@example.com", name="처음")
    resp2 = Response()
    await a.login(a.LoginBody(email="name@example.com", password=GOOD_PW), resp2)
    sid2 = _sid(resp2)
    user = await _session_user(sid1)
    res = await a.update_me(a.ProfileUpdateBody(name="  새   이름 "), user=user)
    assert res["user"]["name"] == "새 이름"
    async with factory() as db:
        assert (await db.execute(select(User.name).where(User.email == "name@example.com"))).scalar_one() == "새 이름"
    assert (await _session_user(sid1))["name"] == "새 이름" and (await _session_user(sid2))["name"] == "새 이름"
    me = await a.me(user=user)
    assert me["user"]["name"] == "새 이름" and me["user"]["createdAt"]


@needs_db
@pytest.mark.anyio
async def test_change_password_reauth_and_session_rotation(factory, fake_redis):
    from app.routes import auth as a

    _, sid_here = await _register("pw@example.com")
    resp_other = Response()
    await a.login(a.LoginBody(email="pw@example.com", password=GOOD_PW), resp_other)
    sid_other = _sid(resp_other)
    user = await _session_user(sid_here)

    with pytest.raises(HTTPException) as wrong:
        await a.change_password(a.PasswordChangeBody(current_password="wrong-pass-00", new_password="new-pass-5678"),
                                Response(), user=user, fin_session=sid_here)
    assert wrong.value.status_code == 400

    resp = Response()
    res = await a.change_password(a.PasswordChangeBody(current_password=GOOD_PW, new_password="new-pass-5678"),
                                  resp, user=user, fin_session=sid_here)
    assert res["other_sessions_revoked"] == 1
    new_sid = _sid(resp)
    assert new_sid not in (sid_here, sid_other)                     # 이 기기는 새 세션 ID (세션 고정 방지)
    assert await _session_user(sid_other) is None and await _session_user(sid_here) is None
    assert await _session_user(new_sid) is not None
    assert any(k.endswith(f"min_iat:{user['id']}") for k in fake_redis.kv)   # 그 전에 나간 토큰은 끊긴다

    with pytest.raises(HTTPException) as old:
        await a.login(a.LoginBody(email="pw@example.com", password=GOOD_PW), Response())
    assert old.value.status_code == 401
    assert (await a.login(a.LoginBody(email="pw@example.com", password="new-pass-5678"), Response()))["ok"]


@needs_db
@pytest.mark.anyio
async def test_delete_account_wipes_only_that_users_data(factory, fake_redis):
    from app.models import (ApiKey, AuditEvent, DataCache, FormulaIndicator, FormulaIndicatorVersion,
                            NotificationSettings, PaperAccount, Portfolio)
    from app.models.base import Base
    from app.routes import auth as a

    _, sid_x = await _register("bye@example.com")
    _, sid_y = await _register("stay@example.com")
    x, y = await _session_user(sid_x), await _session_user(sid_y)
    ux, uy = uuid.UUID(x["id"]), uuid.UUID(y["id"])
    async with factory() as db:
        ind = FormulaIndicator(user_id=ux, name="지표", indicator_expr="close")
        db.add_all([
            PaperAccount(user_id=ux), PaperAccount(user_id=uy),
            Portfolio(user_id=ux, symbol="005930.KS", name="삼성전자", quantity=1, avg_price=1.0),
            ApiKey(user_id=ux, key_prefix="qk_test", key_hash="h" * 64),
            NotificationSettings(user_id=ux),
            AuditEvent(user_id=ux, event_type="paper.stock.order", payload={}),
            DataCache(key=f"quant:cycle_log:{ux}", data={"cycles": []}),
            ind,
        ])
        await db.flush()
        db.add(FormulaIndicatorVersion(indicator_id=ind.id, version=1, indicator_expr="close"))
        await db.commit()

    with pytest.raises(HTTPException) as no_confirm:
        await a.delete_me(a.AccountDeleteBody(password=GOOD_PW, confirm="네"), Response(), user=x)
    assert no_confirm.value.status_code == 422
    with pytest.raises(HTTPException) as wrong:
        await a.delete_me(a.AccountDeleteBody(password="wrong-pass-00", confirm="탈퇴"), Response(), user=x)
    assert wrong.value.status_code == 400

    resp = Response()
    out = await a.delete_me(a.AccountDeleteBody(password=GOOD_PW, confirm="탈퇴"), resp, user=x)
    assert out["deleted"]["users"] == 1
    assert 'fin_session=""' in resp.headers.get("set-cookie", "") or "Max-Age=0" in resp.headers.get("set-cookie", "")
    assert await _session_user(sid_x) is None and await _session_user(sid_y) is not None

    async with factory() as db:
        for table, col in account.user_owned_columns():
            left = (await db.execute(select(func.count()).select_from(table).where(col == ux))).scalar_one()
            assert left == 0, f"{table.name}.{col.name} 에 탈퇴한 사용자 행이 남았다"
        versions = Base.metadata.tables["formula_indicator_versions"]
        assert (await db.execute(select(func.count()).select_from(versions))).scalar_one() == 0   # CASCADE
        assert (await db.execute(select(func.count()).select_from(AuditEvent)
                                 .where(AuditEvent.event_type == "paper.stock.order", AuditEvent.user_id.is_(None)))).scalar_one() == 1
        assert (await db.execute(select(func.count()).select_from(DataCache)
                                 .where(DataCache.key == f"quant:cycle_log:{ux}"))).scalar_one() == 0
        assert (await db.execute(select(func.count()).select_from(PaperAccount).where(PaperAccount.user_id == uy))).scalar_one() == 1
