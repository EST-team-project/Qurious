"""TC-UC — 동의 · 철회 기록 표(user_consents)와 알림 연동 선택 동의 (2026-10-29 · 할 일 ①-09)

무엇을 지키나
1. **표** — 마이그레이션 0032(부모 0031 · 머리 하나 · 처음 0031 로 만들었다가 #402 의 0031 과 겹쳐 옮겼다) · 모델 등록(탈퇴 탐색이 찾는다) · 행은 grant / withdraw 뿐. (TC-UC-01)
2. **필수와 선택이 섞이지 않는다** — 알림 연동 동의는 가입 필수 · 가입 선택 목록에 없고, 동의문은 terms.js 의 TERMS 밖에 있다.
   판은 화면(terms.js)과 서버(consent.py)가 같다 · 제15조 ② 네 가지가 있다 · 앱이 하지 않는 일을 쓰지 않는다. (TC-UC-02)
3. **게이트 규칙** — 새로 채워진 개인정보 칸만 동의를 요구한다. 가림값 · 저장된 그대로 · 빈 값 · 포트 숫자는 새 입력이 아니다. (TC-UC-03)
4. **화면** — 동의 칸 · 동의 보내기 · 철회 단추가 이어져 있다. (TC-UC-04)
5. **같은 트랜잭션** — 가입은 사용자 행과 동의 행을 한 번에 commit 한다(audit() 이 삼켜도 동의 행은 남는다 · 동의 행이 못 들어가면
   가입도 안 된다). (TC-UC-05 · 08)
6. **쌓기만 한다** — 철회도 새 행이다. 앱 코드에 동의 행을 고치거나 지우는 곳이 없다(탈퇴 제외). (TC-UC-06 · 09)
7. **알림 설정 라우트** — 동의 없이 개인정보 칸을 저장하면 422 · 동의하면 저장 + 행 · 철회하면 연동 정보를 지운다 ·
   동의 없이 이미 저장된 사람은 아무것도 안 바꾸고 저장해도 막히지 않는다. (TC-UC-09 · 10)
8. **탈퇴** — 그 사람의 동의 행만 지워진다. (TC-UC-11)

돌리는 법 — DB 시험은 `.\\scripts\\personal\\test.ps1`(일회용 PostgreSQL 컨테이너)에서 돈다. 주소(`QURIOUS_TEST_DATABASE_URL`)가
없으면 규칙 · 정적 시험만 돈다. ⚠️ DB 시험은 그 DB 의 모든 표를 지우고 다시 만든다 — 개발 DB 주소를 넣지 않는다.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import func, select

from app.models.base import Base
from app.models.consent import CONSENT_GRANT, CONSENT_WITHDRAW, UserConsent
from app.routes import auth, notification as noti_route
from app.services import account, consent

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
APP_HTML = (PUB / "app.html").read_text(encoding="utf-8")
SETTINGS_JS = (PUB / "js" / "settings.js").read_text(encoding="utf-8")
TERMS_JS = (PUB / "js" / "terms.js").read_text(encoding="utf-8")
DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB_URL, reason="QURIOUS_TEST_DATABASE_URL 이 없다 — scripts/personal/test.ps1 로 돌린다")

NOTIFY_BLOCK = TERMS_JS.split("export const NOTIFY_CONSENT_VERSION", 1)[1].split("/** 개인정보 처리방침", 1)[0]
POLICY_TEXT = TERMS_JS.split("export const POLICY = {", 1)[1].split("/** 한 항목 → HTML.", 1)[0]


# ── 1. 표 ────────────────────────────────────────────────────────────────────

def test_migration_0032_chain_and_table():
    """TC-UC-01 · 0032 의 부모는 0031(오준영 님 broker_secrets · #402) · alembic 머리는 하나 · 표가 모델에 있고 탈퇴 탐색이 찾는다(삭제 대상)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    rev = script.get_revision("0032_user_consents")
    assert rev.down_revision == "0031_broker_secrets"
    assert len(script.get_heads()) == 1, script.get_heads()
    table = Base.metadata.tables["user_consents"]
    assert {c.name for c in table.columns} == {"id", "user_id", "consent_key", "action", "terms_version", "source", "created_at"}
    assert any("grant" in str(c.sqltext) and "withdraw" in str(c.sqltext) for c in table.constraints if hasattr(c, "sqltext"))
    owned = {t.name for t, _col in account.user_owned_columns()}
    assert "user_consents" in owned
    assert "user_consents" not in account.DEIDENTIFY_TABLES        # 탈퇴하면 지운다 — 남기려면 이 목록과 처리방침을 함께 고친다
    import app.models as models
    assert models.UserConsent is UserConsent


# ── 2. 필수와 선택이 섞이지 않는다 · 문구 ───────────────────────────────────────

def test_notify_consent_is_separate_from_signup_lists_and_versions_match():
    """TC-UC-02 · 알림 연동 동의는 가입 필수 · 선택 목록에 없다 · 동의문은 TERMS 밖 · 판과 항목 id 가 화면과 서버에서 같다."""
    assert consent.NOTIFY_CONSENT_KEY not in auth.REQUIRED_AGREEMENTS
    assert consent.NOTIFY_CONSENT_KEY not in auth.OPTIONAL_AGREEMENTS
    assert auth.OPTIONAL_AGREEMENTS == ()                           # 가입 때 선택 항목은 여전히 받지 않는다
    assert re.search(r'export const NOTIFY_CONSENT_VERSION = "([^"]+)"', TERMS_JS).group(1) == consent.NOTIFY_CONSENT_VERSION
    assert re.search(r'export const NOTIFY_CONSENT = \{\s*id: "([a-z_]+)"', TERMS_JS).group(1) == consent.NOTIFY_CONSENT_KEY
    terms_array = TERMS_JS.split("export const TERMS = [", 1)[1].split("export const TERMS_FOOTER", 1)[0]
    assert consent.NOTIFY_CONSENT_KEY not in terms_array             # 가입 때 체크하는 목록에 섞이지 않는다
    assert re.search(r'export const POLICY_VERSION = "[0-9]{4}-[0-9]{2}-[0-9]{2}-p[0-9.]+"', TERMS_JS)


def test_notify_consent_text_has_the_four_notices_and_no_false_promises():
    """TC-UC-02b · 제15조 ② 네 가지가 이 차례로 있다 · 거부 불이익을 사실대로(저장 불가) · 앱에 없는 일을 쓰지 않는다 · 처리방침이 같은 말."""
    heads = re.findall(r'h: "(\d\. [^"]+)"', NOTIFY_BLOCK)
    assert heads == ["1. 수집 · 이용 목적", "2. 수집하는 항목", "3. 보유 · 이용 기간", "4. 동의를 거부할 권리와 불이익"], heads
    assert "제15조 제2항" in NOTIFY_BLOCK and "선택" in NOTIFY_BLOCK
    assert "저장할 수 없습니다" in NOTIFY_BLOCK
    # 운영자 공용 알림 설정(.env)으로도 발송되므로 「알림을 받을 수 없다」 는 사실이 아니다
    assert "알림을 받을 수 없" not in NOTIFY_BLOCK and "알림을 보낼 수 없" not in NOTIFY_BLOCK
    for banned in ("암호화해", "암호화되어", "안전하게 보관", "다시 동의를 받", "마케팅", "광고성"):
        assert banned not in NOTIFY_BLOCK
    assert "암호화 저장은 하지 않습니다" in NOTIFY_BLOCK and "서비스 데이터베이스에 저장" in NOTIFY_BLOCK
    # 철회하면 연동 정보를 바로 지운다는 말이 코드(라우트)가 실제로 하는 일이다 — 라우트 소스에 삭제가 있다
    route_src = (ROOT / "app" / "routes" / "notification.py").read_text(encoding="utf-8")
    assert "await db.delete(row)" in route_src and "바로 삭제합니다" in NOTIFY_BLOCK
    assert "선택 동의(알림 연동 정보 수집 · 이용)" in POLICY_TEXT and "철회하면 저장된 알림 연동 정보를 바로 삭제합니다" in POLICY_TEXT
    # 동의 · 철회 기록도 수집 항목이다 — 가입 동의문과 처리방침이 같이 적는다
    assert TERMS_JS.count("동의 · 철회 기록(항목 · 판 · 시각)") == 2


# ── 3. 게이트 규칙 ───────────────────────────────────────────────────────────

def _body(**kw):
    return noti_route.NotificationSettingsBody(**kw)


def _row(**kw):
    return SimpleNamespace(**{**{f: "" for f in (noti_route._SECRET_FIELDS + noti_route._PHONE_FIELDS + noti_route._PLAIN_FIELDS)}, **kw})


def test_gate_counts_only_new_personal_data():
    """TC-UC-03 · 새 개인정보 칸만 동의가 필요하다 — 가림값 · 저장된 그대로 · 빈 값 · 포트 숫자 · 채널 목록만은 아니다."""
    f = noti_route.brings_new_personal_data
    assert f(_body(), None) is False
    assert f(_body(channels=["telegram"], email_port=2525), None) is False          # 채널 고르기 · 포트 숫자는 개인정보가 아니다
    assert f(_body(telegram_token="****", email_password="****", kakao_api_secret="****"), _row(telegram_token="t")) is False
    assert f(_body(kakao_phone="***-****-5678", sms_to="***-****-5678"), _row(kakao_phone="01012345678")) is False
    assert f(_body(telegram_chat_id="123"), _row(telegram_chat_id="123")) is False  # 저장된 값 그대로
    assert f(_body(sms_to="01012345678"), _row(sms_to="01012345678")) is False
    # 새로 채우거나 바꾸면 동의가 필요하다
    assert f(_body(telegram_token="123:abc"), None) is True
    assert f(_body(email_password="pw"), _row(email_password="old")) is True        # 비밀값은 가림값이 아닌 값이면 새 입력
    assert f(_body(kakao_phone="01099998888"), _row(kakao_phone="01012345678")) is True
    assert f(_body(sms_from="01011112222"), None) is True
    assert f(_body(slack_webhook_url="https://hooks.slack.com/x"), None) is True
    assert f(_body(email_host="smtp.example.com"), _row(email_host="old.example.com")) is True
    # 비우는 것은 새 수집이 아니다
    assert f(_body(telegram_chat_id="", email_user="", kakao_phone=""), _row(telegram_chat_id="1", email_user="u", kakao_phone="010")) is False
    # 모든 개인정보 칸이 규칙에 들어 있다(칸을 더하고 여기에 안 넣으면 동의 없이 저장된다)
    declared = set(noti_route.NotificationSettingsBody.model_fields)
    covered = set(noti_route._SECRET_FIELDS + noti_route._PHONE_FIELDS + noti_route._PLAIN_FIELDS)
    rest = declared - covered - {"channels", "email_port", "integration_consent", "integration_consent_version"}
    assert rest == set(), f"게이트가 보지 않는 칸: {rest}"


# ── 4. 화면 ─────────────────────────────────────────────────────────────────

def test_settings_screen_wires_consent_box_send_and_withdraw():
    """TC-UC-04 · 알림 설정 화면에 동의 칸이 있고, 저장이 동의와 판을 보내고, 철회 단추가 false 를 보낸다 · 문구는 terms.js 한 곳."""
    view = APP_HTML.split('data-view="notification-settings"', 1)[1].split('<div class="view"', 1)[0]
    for el in ("noti-consent-check", "noti-consent-label", "noti-consent-body", "noti-consent-withdraw", "noti-consent-granted"):
        assert f'id="{el}"' in view, el
    assert 'from "/js/terms.js"' in SETTINGS_JS and "NOTIFY_CONSENT_VERSION" in SETTINGS_JS
    assert "integration_consent: giveConsent ? true : null" in SETTINGS_JS
    assert "integration_consent_version: giveConsent ? NOTIFY_CONSENT_VERSION : null" in SETTINGS_JS
    assert "integration_consent: false" in SETTINGS_JS                                # 철회 단추
    assert "renderNotiConsent(cfg.integration_consent)" in SETTINGS_JS
    assert "동의 철회 · 저장된 연동 정보 삭제" in view and "선택 동의입니다" in view
    # 문구를 화면에 또 적지 않는다 — 한쪽만 고쳐 어긋나지 않게
    assert "목적 · 항목" not in view and "제15조" not in view


# ── 5. 같은 트랜잭션 · 쌓기만 한다 (소스) ───────────────────────────────────────

def test_register_writes_consent_rows_in_the_users_transaction():
    """TC-UC-05 · register 가 flush 로 id 를 받고, 동의 행을 더한 뒤 commit 한 번 — audit() 의 예외 삼킴과 무관하게 남는다."""
    src = (ROOT / "app" / "routes" / "auth.py").read_text(encoding="utf-8")
    block = src.split("async def register(", 1)[1].split("async def _guard_check", 1)[0]
    order = [block.index(s) for s in ("await db.flush()", "consent_service.add_rows(", "await db.commit()", 'await audit(user_id, client_id, "terms.agree", consent)')]
    assert order == sorted(order), "flush → 동의 행 → commit → audit 순서여야 한다"
    assert block.count("await db.commit()") == 1


def test_app_code_never_updates_or_deletes_consent_rows():
    """TC-UC-06 · 앱 코드에 동의 행을 고치거나 지우는 곳이 없다 — 탈퇴(account.delete_user_data 의 일괄 삭제)만 예외."""
    pattern = re.compile(r"(update|delete)\(\s*UserConsent\b")
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "UserConsent" in text and pattern.search(text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], offenders
    # 서비스는 행을 더하기만 한다
    svc = (ROOT / "app" / "services" / "consent.py").read_text(encoding="utf-8")
    assert "db.add_all(rows)" in svc and ".commit(" not in svc.split('"""', 2)[2]    # commit 은 호출자 몫 — 머리말 설명 밖 코드에 없다


def test_add_rows_builds_unique_sorted_rows_and_rejects_unknown_action():
    """TC-UC-06b · add_rows 는 중복 없이 이름순으로 행을 만들고 알 수 없는 동작은 거절한다 — commit 하지 않는다."""
    added = []
    fake_db = SimpleNamespace(add_all=lambda rows: added.extend(rows))
    uid = uuid.uuid4()
    rows = consent.add_rows(fake_db, uid, ["privacy", "service", "privacy"], CONSENT_GRANT, "v1", "signup")
    assert [r.consent_key for r in rows] == ["privacy", "service"] and added == rows
    assert all(r.user_id == uid and r.action == "grant" and r.terms_version == "v1" and r.source == "signup" for r in rows)
    with pytest.raises(ValueError):
        consent.add_rows(fake_db, uid, ["service"], "update", "v1", "signup")


# ── 6. DB 시험 ──────────────────────────────────────────────────────────────

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def factory(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.models  # noqa: F401

    engine = create_async_engine(DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _no_audit(*_a, **_k):                  # audit() 이 기록을 못 남기는 상황 — 동의 행은 audit 에 기대지 않는다
        return None

    async def _sid(*_a, **_k):
        return "sid-test"

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(auth, "get_session_factory", lambda: maker)
    monkeypatch.setattr(auth, "audit", _no_audit)
    monkeypatch.setattr(auth, "create_session", _sid)
    monkeypatch.setattr(auth, "mark_online", _noop)
    yield maker
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _register_body(email: str, **kw):
    base = dict(name="시험", email=email, password="valid-pass-1234", terms_version=auth.TERMS_VERSION,
                agreed=list(auth.REQUIRED_AGREEMENTS), birth_date="1990-01-01")
    return auth.RegisterBody(**{**base, **kw})


async def _make_user(maker, email: str) -> uuid.UUID:
    from app.models import User
    async with maker() as db:
        user = User(name="시험", email=email, password_hash="x", client_id=uuid.uuid4().hex[:16].upper(), roles=["user"])
        db.add(user)
        await db.commit()
        return user.id


async def _rows(maker, uid: uuid.UUID, key: str | None = None) -> list[UserConsent]:
    async with maker() as db:
        q = select(UserConsent).where(UserConsent.user_id == uid).order_by(UserConsent.created_at, UserConsent.consent_key)
        if key:
            q = q.where(UserConsent.consent_key == key)
        return list((await db.execute(q)).scalars().all())


@needs_db
@pytest.mark.anyio
async def test_register_writes_one_grant_row_per_required_item(factory):
    """TC-UC-08 · 가입하면 필수 셋의 grant 행이 약관 판 · 화면 출처로 남는다 — audit() 이 아무것도 못 남겨도."""
    from app.models import User
    out = await auth.register(_register_body("uc1@example.com"), Response())
    assert out["ok"] is True
    async with factory() as db:
        uid = (await db.execute(select(User.id).where(User.email == "uc1@example.com"))).scalar_one()
    rows = await _rows(factory, uid)
    assert [r.consent_key for r in rows] == sorted(auth.REQUIRED_AGREEMENTS)
    assert all(r.action == "grant" and r.terms_version == auth.TERMS_VERSION and r.source == "signup" for r in rows)


@needs_db
@pytest.mark.anyio
async def test_register_fails_whole_when_consent_rows_cannot_be_written(factory, monkeypatch):
    """TC-UC-08b · 동의 행을 못 쓰면 가입도 안 된다 — 사용자 행만 남고 동의 기록이 빠지는 일이 없다."""
    from app.models import User

    def _boom(*_a, **_k):
        raise RuntimeError("동의 행 쓰기 실패")

    monkeypatch.setattr(auth.consent_service, "add_rows", _boom)
    with pytest.raises(RuntimeError):
        await auth.register(_register_body("uc2@example.com"), Response())
    async with factory() as db:
        assert (await db.execute(select(func.count()).select_from(User))).scalar_one() == 0
        assert (await db.execute(select(func.count()).select_from(UserConsent))).scalar_one() == 0


def _save(body, uid, db):
    return noti_route.save_notification_settings(body, user={"id": str(uid)}, db=db)


@needs_db
@pytest.mark.anyio
async def test_notification_save_requires_consent_then_stacks_rows(factory):
    """TC-UC-09 · 동의 없이 개인정보 칸을 저장하면 422(아무것도 안 저장) → 동의하며 저장 → 평소 저장은 동의 칸 없이도 된다 →
    철회하면 연동 정보를 지운다 → 다시 동의 · 행은 grant · withdraw · grant 로 쌓이고 앞 행은 그대로다."""
    uid = await _make_user(factory, "uc3@example.com")
    ver = consent.NOTIFY_CONSENT_VERSION

    async with factory() as db:                                       # 동의 없이 → 422 · 저장 없음
        with pytest.raises(HTTPException) as e:
            await _save(_body(channels=["telegram"], telegram_token="123:abc", telegram_chat_id="99"), uid, db)
        assert e.value.status_code == 422 and "동의해야" in e.value.detail
    async with factory() as db:
        assert await noti_route._get_settings_row(db, uid) is None
        assert (await noti_route.get_notification_settings({"id": str(uid)}, db))["integration_consent"]["granted"] is False
    assert await _rows(factory, uid) == []

    async with factory() as db:                                       # 판이 다르면 거절(오래된 화면)
        with pytest.raises(HTTPException) as e:
            await _save(_body(telegram_token="123:abc", integration_consent=True, integration_consent_version="old"), uid, db)
        assert e.value.status_code == 422 and "새로고침" in e.value.detail
    assert await _rows(factory, uid) == []

    async with factory() as db:                                       # 동의하며 저장
        assert (await _save(_body(channels=["telegram"], telegram_token="123:abc", telegram_chat_id="99",
                                  integration_consent=True, integration_consent_version=ver), uid, db))["ok"] is True
    first = await _rows(factory, uid, consent.NOTIFY_CONSENT_KEY)
    assert [r.action for r in first] == ["grant"] and first[0].terms_version == ver and first[0].source == "notification_settings"

    async with factory() as db:                                       # 평소 저장 — 동의 칸 없이 · 가림값을 되돌려 보내도 된다
        await _save(_body(channels=["telegram"], telegram_token="****", telegram_chat_id="77"), uid, db)
        got = await noti_route.get_notification_settings({"id": str(uid)}, db)
    assert got["telegram_token"] == "****" and got["telegram_chat_id"] == "77"
    assert got["integration_consent"]["granted"] is True and got["integration_consent"]["version"] == ver
    assert len(await _rows(factory, uid, consent.NOTIFY_CONSENT_KEY)) == 1     # 이미 동의했으면 새 행을 안 쌓는다

    async with factory() as db:                                       # 철회 → 연동 정보 삭제
        assert (await _save(_body(integration_consent=False), uid, db)).get("withdrawn") is True
    async with factory() as db:
        assert await noti_route._get_settings_row(db, uid) is None
        assert (await noti_route.get_notification_settings({"id": str(uid)}, db))["integration_consent"]["granted"] is False
        with pytest.raises(HTTPException):                            # 철회 뒤에는 다시 동의가 있어야 저장된다
            await _save(_body(telegram_token="123:abc"), uid, db)

    async with factory() as db:                                       # 다시 동의
        await _save(_body(telegram_token="123:abc", integration_consent=True, integration_consent_version=ver), uid, db)
    rows = await _rows(factory, uid, consent.NOTIFY_CONSENT_KEY)
    assert [r.action for r in rows] == ["grant", "withdraw", "grant"]
    assert rows[0].id == first[0].id and rows[0].created_at == first[0].created_at          # 앞 행은 덮어쓰지 않았다
    async with factory() as db:
        assert await consent.is_granted(db, uid, consent.NOTIFY_CONSENT_KEY) is True


@needs_db
@pytest.mark.anyio
async def test_notification_legacy_user_and_withdraw_edge_cases(factory):
    """TC-UC-10 · 동의 없이 이미 저장된 사람(옛 데이터)은 아무것도 안 바꾸고 저장해도 막히지 않고, 바꾸면 동의를 요구한다 ·
    동의한 적 없는 사람의 철회는 연동 정보만 지우고 withdraw 행은 쌓지 않는다."""
    from app.models import NotificationSettings
    uid = await _make_user(factory, "uc4@example.com")
    async with factory() as db:                                       # 동의 제도 전에 저장된 값
        db.add(NotificationSettings(user_id=uid, channels=["sms"], sms_api_key="k", sms_api_secret="s",
                                    sms_from="01011112222", sms_to="01033334444"))
        await db.commit()
    async with factory() as db:
        got = await noti_route.get_notification_settings({"id": str(uid)}, db)
        assert got["integration_consent"]["granted"] is False and got["sms_api_key"] == "****"
        # 화면이 받은 값 그대로(가림값) 저장 — 막히지 않는다
        await _save(_body(channels=["sms"], sms_api_key="****", sms_api_secret="****", sms_from=got["sms_from"], sms_to=got["sms_to"]), uid, db)
        # 번호를 바꾸면 동의가 필요하다
        with pytest.raises(HTTPException) as e:
            await _save(_body(channels=["sms"], sms_to="01055556666"), uid, db)
        assert e.value.status_code == 422
    async with factory() as db:                                       # 동의한 적 없는 사람의 철회
        assert (await _save(_body(integration_consent=False), uid, db))["withdrawn"] is True
    async with factory() as db:
        assert await noti_route._get_settings_row(db, uid) is None
    assert await _rows(factory, uid, consent.NOTIFY_CONSENT_KEY) == []


@needs_db
@pytest.mark.anyio
async def test_account_deletion_removes_only_that_users_consent_rows(factory):
    """TC-UC-11 · 탈퇴하면 그 사람의 동의 행만 지워진다 — 다른 사람의 행은 그대로(외래 키 때문에 탈퇴가 막히지도 않는다)."""
    a = await _make_user(factory, "uc5a@example.com")
    b = await _make_user(factory, "uc5b@example.com")
    async with factory() as db:
        for uid in (a, b):
            consent.add_rows(db, uid, auth.REQUIRED_AGREEMENTS, CONSENT_GRANT, auth.TERMS_VERSION, "signup")
        consent.add_rows(db, a, [consent.NOTIFY_CONSENT_KEY], CONSENT_WITHDRAW, consent.NOTIFY_CONSENT_VERSION, "notification_settings")
        await db.commit()
    assert len(await _rows(factory, a)) == 4 and len(await _rows(factory, b)) == 3
    async with factory() as db:
        counts = await account.delete_user_data(db, a)
        await db.commit()
    assert counts.get("user_consents") == 4
    assert await _rows(factory, a) == [] and len(await _rows(factory, b)) == 3
