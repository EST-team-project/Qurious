"""TC-NS — 알림 설정 비밀값 저장 암호화 (app/lib/notification_secrets.py · 0044 마이그레이션 · 2026-11-05 S205)

설계: 증권사 키 파일(BROKER_CREDENTIAL_KEY_FILE)을 재사용하되 접두어 `qnc1:` · AAD `notification_settings.<칸>` 으로 도메인을 나눈다
(오준영 님 #533 동의 · 안 A). 9칸 — 토큰 · 웹훅 둘 · SMTP 비밀번호 · 카카오 키 · 시크릿 · 발신 프로필 키 · 문자 키 · 시크릿.
전화번호 · 주소 칸은 이번 범위 밖(개인정보 처리방침 판단과 함께 후속).

 1. 왕복 · 매번 다른 암호문 · 접두어  (TC-NS-01)
 2. AAD 분리 — 다른 칸 · 증권사 표 · 변조 · 평문은 복호화 거부, 오류 문구에 비밀 없음  (TC-NS-02)
 3. 키 없음 · 틀린 키 → fail-closed, 빈 값은 키 없이 통과, 예외는 증권사 예외의 하위(503 계약)  (TC-NS-03)
 4. get_pg_session 이 알림 키 오류를 503 으로 바꾸되 문구는 알림 쪽  (TC-NS-04)
 5. 기동 때 키 검증 — 실패해도 기동을 막지 않고 error 로그만, 비밀 · 암호문은 로그에 없음  (TC-NS-05)
 6. 발송 서비스 — 복호화 오류를 일반 조회 실패와 구분해 `CREDENTIAL_STORAGE` 로 남기고 NO_SETTINGS  (TC-NS-06)
 7. 구조 — 모델 9칸 · CHECK 제약 · 마이그레이션 · 회전 스크립트 · 연결 지점  (TC-NS-07)
 8. 일회용 PG — 저장 · 평문 거부 · 회전 · 이중 암호화 없음 · 전체 롤백 · 마이그레이션 · 증권사 표 불변  (TC-NS-08~12)
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import logging
import os
import re
import uuid
from pathlib import Path

import pytest

from app.lib import broker_secrets
from app.lib import notification_secrets as ns

ROOT = Path(__file__).resolve().parents[1]
NEEDS_PG = pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요")
SENTINEL = "synthetic-notification-secret-" + "x" * 40


# ── 1~3. 순수 함수 ────────────────────────────────────────────────────────────

def test_tc_ns_01_roundtrip_unique_ciphertext_and_prefix():
  assert len(ns.FIELDS) == 9 and len(set(ns.FIELDS)) == 9
  for field in ns.FIELDS:
    a, b = ns.encrypt(SENTINEL, field), ns.encrypt(SENTINEL, field)
    assert a != b, "nonce 를 매번 새로 써야 한다"
    assert a.startswith("qnc1:") and SENTINEL not in a
    assert ns.decrypt(a, field) == SENTINEL == ns.decrypt(b, field)


def test_tc_ns_02_aad_binding_and_tamper_rejected():
  token = ns.encrypt(SENTINEL, "telegram_token")
  broker = broker_secrets.encrypt(SENTINEL, "app_secret")
  bad = [
    (token, "slack_webhook_url"),                     # 다른 칸으로 옮겨 붙임
    (token[:-7] + "INVALID", "telegram_token"),       # 변조
    (SENTINEL, "telegram_token"),                     # 평문 호환 없음
    (broker, "telegram_token"),                       # 증권사 암호문
    (token.replace("qnc1:", "qbc1:", 1), "telegram_token"),
  ]
  for value, field in bad:
    with pytest.raises(ns.NotificationStorageError) as exc:
      ns.decrypt(value, field)
    assert SENTINEL not in str(exc.value) and token not in str(exc.value)
  # 반대 방향 — 알림 암호문을 증권사 쪽이 읽을 수 없다(증권사 암호문 형식 · AAD 는 그대로)
  with pytest.raises(broker_secrets.CredentialStorageError):
    broker_secrets.decrypt(token, "app_secret")
  with pytest.raises(ns.NotificationStorageError):
    ns.encrypt(SENTINEL, "kakao_phone")               # 이번 범위 밖 칸은 암호화하지 않는다
  with pytest.raises(ns.NotificationStorageError):
    ns.encrypt(123, "telegram_token")


def test_tc_ns_03_missing_and_wrong_key_fail_closed(monkeypatch, tmp_path):
  token = ns.encrypt(SENTINEL, "email_password")
  assert issubclass(ns.NotificationStorageError, broker_secrets.CredentialStorageError), "503 계약은 증권사 예외에 걸려 있다"
  assert ns.encrypt("", "email_password") == "" and ns.decrypt("", "email_password") == ""
  assert ns.encrypt(None, "email_password") is None
  monkeypatch.delenv("BROKER_CREDENTIAL_KEY_FILE")
  assert ns.encrypt("", "email_password") == "", "빈 값은 키 없이도 통과(마이그레이션 · 빈 행)"
  for op in (lambda: ns.encrypt(SENTINEL, "email_password"), lambda: ns.decrypt(token, "email_password")):
    with pytest.raises(ns.NotificationStorageError):
      op()
  path = tmp_path / "wrong.json"
  path.write_text(json.dumps({"active": "test", "keys": {"test": base64.urlsafe_b64encode(os.urandom(32)).decode()}}))
  monkeypatch.setenv("BROKER_CREDENTIAL_KEY_FILE", str(path))
  with pytest.raises(ns.NotificationStorageError):
    ns.decrypt(token, "email_password")
  with pytest.raises(ns.NotificationStorageError):
    ns.decrypt(token.replace(":test:", ":unknown:"), "email_password")


# ── 4. 503 ────────────────────────────────────────────────────────────────────

def test_tc_ns_04_pg_session_maps_notification_key_error_to_503_with_own_message():
  from fastapi import HTTPException
  from sqlalchemy.exc import StatementError
  from app.database import postgres

  class _Factory:
    def __call__(self):
      return self
    async def __aenter__(self):
      return object()
    async def __aexit__(self, *a):
      return False

  async def run(exc):
    gen = postgres.get_pg_session()
    await gen.__anext__()
    with pytest.raises(HTTPException) as caught:
      await gen.athrow(exc)
    return caught.value

  orig_factory = postgres.get_session_factory
  postgres.get_session_factory = lambda: _Factory()
  try:
    direct = asyncio.run(run(ns.NotificationStorageError()))
    wrapped = asyncio.run(run(StatementError("x", "stmt", {}, ns.NotificationStorageError())))
    broker = asyncio.run(run(broker_secrets.CredentialStorageError()))
  finally:
    postgres.get_session_factory = orig_factory
  for err in (direct, wrapped):
    assert err.status_code == 503 and err.detail["code"] == "CREDENTIAL_STORAGE_UNAVAILABLE"
    assert "알림" in err.detail["message"] and "증권사" not in err.detail["message"]
  assert broker.status_code == 503 and "증권사" in broker.detail["message"], "증권사 쪽 문구는 그대로"


# ── 5. 기동 때 키 검증 ──────────────────────────────────────────────────────────

def test_tc_ns_05_startup_key_check_never_raises_and_never_logs_secrets(monkeypatch, caplog):
  from app.services import notification_key_check as kc
  token = ns.encrypt(SENTINEL, "discord_webhook_url")
  with caplog.at_level(logging.INFO):
    assert kc.check_sample(token, "discord_webhook_url") == "ok"
    assert kc.check_sample(None, None) == "ok", "행이 없어도 키 파일은 본다"
    assert kc.check_sample("", "telegram_token") == "ok"
  caplog.clear()
  monkeypatch.delenv("BROKER_CREDENTIAL_KEY_FILE")
  with caplog.at_level(logging.INFO):
    assert kc.check_sample(token, "discord_webhook_url") == "key_unavailable"
    assert kc.check_sample(None, None) == "key_unavailable"
  errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
  assert errors and all("CREDENTIAL_STORAGE" in r.getMessage() for r in errors)
  assert all(SENTINEL not in r.getMessage() and token not in r.getMessage() for r in caplog.records)


def test_tc_ns_05b_wrong_key_with_ciphertext_is_reported(monkeypatch, tmp_path, caplog):
  from app.services import notification_key_check as kc
  token = ns.encrypt(SENTINEL, "sms_api_key")
  path = tmp_path / "wrong.json"
  path.write_text(json.dumps({"active": "test", "keys": {"test": base64.urlsafe_b64encode(os.urandom(32)).decode()}}))
  monkeypatch.setenv("BROKER_CREDENTIAL_KEY_FILE", str(path))
  with caplog.at_level(logging.INFO):
    assert kc.check_sample(token, "sms_api_key") == "decrypt_failed"
  assert any(r.levelno >= logging.ERROR and "CREDENTIAL_STORAGE" in r.getMessage() for r in caplog.records)
  assert not any(token in r.getMessage() for r in caplog.records)


# ── 6. 발송 서비스: 복호화 오류 구분 ──────────────────────────────────────────────

def _factory_raising(exc):
  class _Db:
    async def execute(self, *a, **k):
      raise exc
  class _F:
    def __call__(self):
      return self
    async def __aenter__(self):
      return _Db()
    async def __aexit__(self, *a):
      return False
  return _F()


def test_tc_ns_06_dispatch_distinguishes_key_errors(monkeypatch, caplog):
  from sqlalchemy.exc import StatementError
  from app.database import postgres
  from app.services import notification
  uid = str(uuid.uuid4())

  def run(exc):
    monkeypatch.setattr(postgres, "get_session_factory", lambda: _factory_raising(exc))
    caplog.clear()
    with caplog.at_level(logging.INFO):
      return asyncio.run(notification._load_user_settings(uid))

  for exc in (ns.NotificationStorageError(), StatementError("x", "stmt", {}, ns.NotificationStorageError())):
    out = run(exc)
    assert out == notification.NO_SETTINGS or out.get("_no_settings"), "공용 채널로 새지 않는다"
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs and all("CREDENTIAL_STORAGE" in r.getMessage() for r in errs)
  out = run(RuntimeError("db down"))
  assert out.get("_no_settings")
  assert not any("CREDENTIAL_STORAGE" in r.getMessage() for r in caplog.records), "일반 조회 실패와 구분"


# ── 7. 구조 ───────────────────────────────────────────────────────────────────

def test_tc_ns_07_model_migration_rotation_and_wiring():
  from app.models import NotificationSettings
  cols = NotificationSettings.__table__.c
  for field in ns.FIELDS:
    assert isinstance(cols[field].type, ns.EncryptedNotificationSecret), field
    assert cols[field].type.field == field
  assert set(ns.FIELDS).isdisjoint({"kakao_phone", "sms_from", "sms_to", "email_to", "email_user", "email_host", "email_from", "telegram_chat_id"})
  names = {c.name for c in NotificationSettings.__table__.constraints}
  assert {f"ck_notification_encrypted_{f}" for f in ns.FIELDS} <= names

  mig = (ROOT / "alembic/versions/0044_notification_secrets.py").read_text(encoding="utf-8")
  assert 'down_revision = "0043_regime_targets"' in mig
  assert "reencrypt" in mig and "allow_legacy=True" in mig and "RuntimeError" in mig.split("def downgrade")[1]

  # 키 회전 — 증권사 스크립트(오준영 님 코드)는 건드리지 않고 형제 스크립트가 알림 표를 맡는다. 둘 다 돌린 뒤에 옛 키를 지운다
  rot = (ROOT / "scripts/rotate_notification_credentials.py").read_text(encoding="utf-8")
  assert "notification_secrets" in rot and "reencrypt" in rot and "rotate_broker_credentials" in rot
  assert "notification" not in (ROOT / "scripts/rotate_broker_credentials.py").read_text(encoding="utf-8"), "증권사 회전 스크립트는 그대로"

  main = (ROOT / "app/main.py").read_text(encoding="utf-8")
  assert "notification_key_check" in main
  celery = (ROOT / "app/celery_app.py").read_text(encoding="utf-8")
  assert "worker_ready" in celery and "beat_init" in celery and "notification_key_check" in celery

  route = (ROOT / "app/routes/notification.py").read_text(encoding="utf-8")
  assert "delete(NotificationSettings)" in route, "동의 철회는 행을 읽지 않고 지운다(키가 깨져도 철회 가능)"
  # 엔티티를 읽는 곳은 설정 라우트와 발송 서비스(+기동 검증)뿐 — 다른 곳이 이 행을 읽기 시작하면 키 오류의 영향을 받는다
  readers = []
  for path in (ROOT / "app").rglob("*.py"):
    text = path.read_text(encoding="utf-8")
    if re.search(r"select\(\s*NotificationSettings\s*\)", text):
      readers.append(path.relative_to(ROOT).as_posix())
  assert sorted(readers) == ["app/routes/notification.py", "app/services/notification.py"] or \
      sorted(readers) == ["app/routes/notification.py", "app/services/notification.py", "app/services/notification_key_check.py"]


# ── 8~12. 일회용 PG ─────────────────────────────────────────────────────────────

def _engine():
  from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
  from sqlalchemy.pool import NullPool
  engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool, hide_parameters=True)
  return engine, async_sessionmaker(engine, expire_on_commit=False)


def _secret_values(tag: str) -> dict:
  return {f: f"{tag}-{f}-" + "v" * 60 for f in ns.FIELDS}


@pytest.fixture
def notif_db_clean(rebalance_db_schema):
  """일회용 DB 표는 시험 사이에 공유된다 — 알림 행을 비우고 CHECK 제약을 복원해 시험끼리 영향을 주지 않게 한다
  (회전 시험이 다른 키 ID 로 다시 암호화한 행이나 손상 시험 행이 남으면 뒤 시험의 reencrypt 가 깨진다)."""
  from sqlalchemy import text

  async def reset():
    engine, _ = _engine()
    async with engine.begin() as conn:
      await conn.execute(text("DELETE FROM notification_settings"))
      for f in ns.FIELDS:
        await conn.execute(text(f"ALTER TABLE notification_settings DROP CONSTRAINT IF EXISTS ck_notification_encrypted_{f}"))
        await conn.execute(text(f"ALTER TABLE notification_settings ADD CONSTRAINT ck_notification_encrypted_{f} "
                                f"CHECK ({f} = '' OR {f} LIKE 'qnc1:%')"))
    await engine.dispose()

  asyncio.run(reset())
  yield
  asyncio.run(reset())


async def _make_user(db, name="ns"):
  from app.models import User
  uid = uuid.uuid4()
  db.add(User(id=uid, name=name, email=f"{uid}@example.test", password_hash="fake", client_id=uid.hex))
  await db.flush()
  return uid


@pytest.mark.usefixtures("notif_db_clean")
@NEEDS_PG
def test_tc_ns_08_real_pg_encrypted_storage_and_plaintext_constraint():
  from sqlalchemy import select, text
  from sqlalchemy.exc import IntegrityError
  from app.models import NotificationSettings

  async def scenario():
    engine, sessions = _engine()
    original = _secret_values("a")
    async with sessions() as db:
      uid = await _make_user(db)
      db.add(NotificationSettings(user_id=uid, channels=["telegram"], telegram_chat_id="chat-1", email_to="a@example.test",
                                  kakao_phone="010-1234-5678", **original))
      await db.commit()
    async with sessions() as db:
      raw = (await db.execute(text("SELECT * FROM notification_settings WHERE user_id=:u"), {"u": uid})).mappings().one()
      assert all(raw[f].startswith("qnc1:") and original[f] not in raw[f] for f in ns.FIELDS)
      assert raw["telegram_chat_id"] == "chat-1" and raw["email_to"] == "a@example.test" and raw["kakao_phone"] == "010-1234-5678"
      row = await db.scalar(select(NotificationSettings).where(NotificationSettings.user_id == uid))
      assert all(getattr(row, f) == original[f] for f in ns.FIELDS)
    for field in ns.FIELDS:
      with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
          await conn.execute(text(f"UPDATE notification_settings SET {field}='plain-text' WHERE user_id=:u"), {"u": uid})
    async with engine.begin() as conn:  # 빈 값은 허용
      await conn.execute(text("UPDATE notification_settings SET telegram_token='' WHERE user_id=:u"), {"u": uid})
    await engine.dispose()

  asyncio.run(scenario())


@pytest.mark.usefixtures("notif_db_clean")
@NEEDS_PG
def test_tc_ns_09_rotation_reencrypts_once_and_old_key_can_be_dropped(monkeypatch, tmp_path):
  from sqlalchemy import select, text
  from app.models import NotificationSettings

  async def scenario():
    engine, sessions = _engine()
    original = _secret_values("r")
    async with sessions() as db:
      uid = await _make_user(db, "rot")
      db.add(NotificationSettings(user_id=uid, **original))
      await db.commit()
    async with engine.connect() as conn:
      before = (await conn.execute(text("SELECT telegram_token FROM notification_settings WHERE user_id=:u"), {"u": uid})).scalar()
    old = json.loads(Path(os.environ["BROKER_CREDENTIAL_KEY_FILE"]).read_text())
    new = base64.urlsafe_b64encode(os.urandom(32)).decode()
    path = tmp_path / "rotate.json"
    path.write_text(json.dumps({"active": "next", "keys": {**old["keys"], "next": new}}))
    monkeypatch.setenv("BROKER_CREDENTIAL_KEY_FILE", str(path))
    async with engine.begin() as conn:
      result = await conn.run_sync(ns.reencrypt)
    assert result["encrypted_fields"] >= len(ns.FIELDS) and result["rows"] >= 1
    async with engine.connect() as conn:
      after = (await conn.execute(text("SELECT telegram_token FROM notification_settings WHERE user_id=:u"), {"u": uid})).scalar()
    assert after != before and after.startswith("qnc1:next:"), "새 키 ID 로 한 번만 암호화"
    assert after.count("qnc1:") == 1, "이미 암호화된 값을 두 번 감싸지 않는다"
    path.write_text(json.dumps({"active": "next", "keys": {"next": new}}))  # 옛 키를 지운다
    async with sessions() as db:
      row = await db.scalar(select(NotificationSettings).where(NotificationSettings.user_id == uid))
      assert all(getattr(row, f) == original[f] for f in ns.FIELDS)
    await engine.dispose()

  asyncio.run(scenario())


@pytest.mark.usefixtures("notif_db_clean")
@NEEDS_PG
def test_tc_ns_10_reencrypt_is_all_or_nothing_and_broker_rows_untouched():
  from sqlalchemy import text
  from app.models import BrokerSettings, NotificationSettings

  async def scenario():
    engine, sessions = _engine()
    async with sessions() as db:
      u1, u2 = await _make_user(db, "n1"), await _make_user(db, "n2")
      db.add(BrokerSettings(user_id=u1, broker="kis", app_key="bk", app_secret="bs", account_no="12345678-01"))
      db.add(NotificationSettings(user_id=u1, **_secret_values("p")))
      db.add(NotificationSettings(user_id=u2, **_secret_values("q")))
      await db.commit()
    async with engine.connect() as conn:
      snap = (await conn.execute(text("SELECT user_id, telegram_token, slack_webhook_url FROM notification_settings ORDER BY user_id"))).all()
      broker_before = (await conn.execute(text("SELECT app_key, app_secret, account_no FROM broker_settings WHERE user_id=:u"), {"u": u1})).one()
    # 한 행의 칸을 손상(제약 없이 정상 접두어 + 깨진 본문) — 변환 중 실패해야 전체가 되돌아간다
    async with engine.begin() as conn:
      for f in ns.FIELDS:
        await conn.execute(text(f"ALTER TABLE notification_settings DROP CONSTRAINT ck_notification_encrypted_{f}"))
      await conn.execute(text("UPDATE notification_settings SET slack_webhook_url='qnc1:test:AAAA' WHERE user_id=:u"), {"u": u2})
    with pytest.raises(ns.NotificationStorageError):
      async with engine.begin() as conn:
        await conn.run_sync(ns.reencrypt)
    async with engine.connect() as conn:
      after = (await conn.execute(text("SELECT user_id, telegram_token, slack_webhook_url FROM notification_settings ORDER BY user_id"))).all()
      broker_after = (await conn.execute(text("SELECT app_key, app_secret, account_no FROM broker_settings WHERE user_id=:u"), {"u": u1})).one()
    assert [r[1] for r in after] == [r[1] for r in snap], "한 칸이 실패하면 다른 행도 그대로"
    assert broker_after == broker_before, "증권사 정보 불변"
    await engine.dispose()

  asyncio.run(scenario())


def _load_migration():
  spec = importlib.util.spec_from_file_location("notif_migration", ROOT / "alembic/versions/0044_notification_secrets.py")
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod


@pytest.mark.usefixtures("notif_db_clean")
@NEEDS_PG
def test_tc_ns_11_legacy_migration_is_atomic_and_preserves_values(monkeypatch):
  from alembic.migration import MigrationContext
  from alembic.operations import Operations
  from sqlalchemy import select, text
  from app.models import BrokerSettings, NotificationSettings
  migration = _load_migration()

  def upgrade(conn):
    migration.op = Operations(MigrationContext.configure(conn))
    migration.upgrade()

  async def scenario():
    engine, sessions = _engine()
    legacy = _secret_values("legacy")
    async with sessions() as db:
      uid = await _make_user(db, "legacy")
      db.add(BrokerSettings(user_id=uid, broker="kis", app_key="bk2", app_secret="bs2", account_no="87654321-01"))
      db.add(NotificationSettings(user_id=uid, channels=["slack"], email_to="legacy@example.test", telegram_chat_id="c9",
                                  kakao_phone="010-0000-1111", preferences={"quiet": {"enabled": True}}))
      await db.commit()
    async with engine.begin() as conn:
      for f in ns.FIELDS:
        await conn.execute(text(f"ALTER TABLE notification_settings DROP CONSTRAINT ck_notification_encrypted_{f}"))
      sets = ",".join(f"{f}=:{f}" for f in ns.FIELDS)
      await conn.execute(text(f"UPDATE notification_settings SET {sets} WHERE user_id=:u"), {**legacy, "u": uid})
      broker_before = (await conn.execute(text("SELECT app_key, app_secret, account_no FROM broker_settings WHERE user_id=:u"), {"u": uid})).one()
    key_path = os.environ["BROKER_CREDENTIAL_KEY_FILE"]

    # (a) 키가 없으면 전체 롤백 — 평문이 그대로 남고 제약도 안 생긴다
    monkeypatch.delenv("BROKER_CREDENTIAL_KEY_FILE")
    with pytest.raises(broker_secrets.CredentialStorageError):
      async with engine.begin() as conn:
        await conn.run_sync(upgrade)
    async with engine.connect() as conn:
      assert await conn.scalar(text("SELECT telegram_token FROM notification_settings WHERE user_id=:u"), {"u": uid}) == legacy["telegram_token"]
    monkeypatch.setenv("BROKER_CREDENTIAL_KEY_FILE", key_path)

    # (b) 가림값 `****` 가 저장돼 있으면 암호화하지 않고 멈춘다(사전 점검)
    async with engine.begin() as conn:
      await conn.execute(text("UPDATE notification_settings SET slack_webhook_url='****' WHERE user_id=:u"), {"u": uid})
    with pytest.raises(RuntimeError, match=r"\*\*\*\*"):
      async with engine.begin() as conn:
        await conn.run_sync(upgrade)
    async with engine.begin() as conn:
      await conn.execute(text("UPDATE notification_settings SET slack_webhook_url=:v WHERE user_id=:u"), {"v": legacy["slack_webhook_url"], "u": uid})

    # (c) 정상 전환 — 값 · 다른 칸 · 증권사 표 그대로
    async with engine.begin() as conn:
      await conn.run_sync(upgrade)
    async with sessions() as db:
      row = await db.scalar(select(NotificationSettings).where(NotificationSettings.user_id == uid))
      assert all(getattr(row, f) == legacy[f] for f in ns.FIELDS)
      assert (row.channels, row.email_to, row.telegram_chat_id, row.kakao_phone, row.preferences) == (
          ["slack"], "legacy@example.test", "c9", "010-0000-1111", {"quiet": {"enabled": True}})
    async with engine.connect() as conn:
      raw = (await conn.execute(text("SELECT telegram_token FROM notification_settings WHERE user_id=:u"), {"u": uid})).scalar()
      assert raw.startswith("qnc1:") and legacy["telegram_token"] not in raw
      assert (await conn.execute(text("SELECT app_key, app_secret, account_no FROM broker_settings WHERE user_id=:u"), {"u": uid})).one() == broker_before
    with pytest.raises(RuntimeError):
      migration.downgrade()
    await engine.dispose()

  asyncio.run(scenario())


@pytest.mark.usefixtures("notif_db_clean")
@NEEDS_PG
def test_tc_ns_12_routes_mask_keep_withdraw_and_503(monkeypatch):
  from fastapi import FastAPI
  from fastapi.testclient import TestClient
  from sqlalchemy import select, text
  from app.database import postgres
  from app.lib.session import get_current_user
  from app.models import NotificationSettings
  from app.routes import notification as route

  async def seed():
    engine, sessions = _engine()
    uid_box = {}
    async with sessions() as db:
      uid = await _make_user(db, "route")
      db.add(NotificationSettings(user_id=uid, channels=["telegram"], **_secret_values("route")))
      await db.commit()
    uid_box["uid"] = uid
    return engine, sessions, uid_box

  engine, sessions, box = asyncio.run(seed())
  uid = box["uid"]
  monkeypatch.setattr(postgres, "get_session_factory", lambda: sessions)
  app = FastAPI()
  app.include_router(route.router)
  app.dependency_overrides[get_current_user] = lambda: {"id": str(uid)}
  key_path = os.environ["BROKER_CREDENTIAL_KEY_FILE"]

  with TestClient(app) as client:
    got = client.get("/api/notification/settings")
    assert got.status_code == 200
    body = got.json()
    for f in ("telegram_token", "slack_webhook_url", "discord_webhook_url", "email_password", "kakao_api_key",
              "kakao_api_secret", "sms_api_key", "sms_api_secret"):
      assert body[f] == "****", f
    assert "route-" not in got.text.replace(body["kakao_sender_key"], ""), "비밀 평문이 응답에 새지 않는다"

    # 가림값을 다시 보내면 기존 값 유지(암호문이 바뀌지 않아도 복호화 값이 같다)
    put = client.post("/api/notification/settings", json={"channels": ["telegram"], "telegram_token": "****",
                                                         "slack_webhook_url": "****", "discord_webhook_url": "****",
                                                         "email_password": "", "kakao_api_key": "****"})
    assert put.status_code == 200, put.text

    async def read_token():
      async with sessions() as db:
        return (await db.scalar(select(NotificationSettings).where(NotificationSettings.user_id == uid))).telegram_token
    assert asyncio.run(read_token()) == _secret_values("route")["telegram_token"]

    # 키가 없으면 설정 GET · 저장 모두 503 — 알림 쪽 문구, 비밀 없음
    monkeypatch.delenv("BROKER_CREDENTIAL_KEY_FILE")
    for resp in (client.get("/api/notification/settings"),
                 client.post("/api/notification/settings", json={"channels": ["telegram"], "telegram_token": "new-token-value"})):
      assert resp.status_code == 503, resp.text
      assert resp.json()["detail"]["code"] == "CREDENTIAL_STORAGE_UNAVAILABLE" and "알림" in resp.json()["detail"]["message"]
      assert "route-" not in resp.text and "qnc1:" not in resp.text

    # 동의 철회는 키가 없어도 된다 — 행을 읽지 않고 지운다(개인정보 삭제는 막지 않는다)
    wd = client.post("/api/notification/settings", json={"integration_consent": False})
    assert wd.status_code == 200 and wd.json().get("withdrawn") is True, wd.text

  async def count():
    async with engine.connect() as conn:
      return await conn.scalar(text("SELECT count(*) FROM notification_settings WHERE user_id=:u"), {"u": uid})
  assert asyncio.run(count()) == 0
  monkeypatch.setenv("BROKER_CREDENTIAL_KEY_FILE", key_path)
  asyncio.run(engine.dispose())
