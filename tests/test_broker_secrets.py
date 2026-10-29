import asyncio
import base64
import importlib
import json
import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.lib import broker_secrets as secrets
from app.models import User, BrokerSettings


def test_authenticated_ciphertext_and_field_binding():
    value = "synthetic-secret-" * 20
    a = secrets.encrypt(value, "app_secret")
    b = secrets.encrypt(value, "app_secret")
    assert a != b and value not in a
    assert secrets.decrypt(a, "app_secret") == value
    for invalid, field in ((a, "app_key"), (a[:-7] + "INVALID", "app_secret"), (value, "app_secret")):
        with pytest.raises(secrets.CredentialStorageError) as exc:
            secrets.decrypt(invalid, field)
        assert value not in str(exc.value) and a not in str(exc.value)


def test_missing_wrong_and_unknown_keys_fail_closed(monkeypatch, tmp_path):
    token = secrets.encrypt("synthetic-only", "app_key")
    monkeypatch.delenv("BROKER_CREDENTIAL_KEY_FILE")
    for operation in (lambda: secrets.encrypt("synthetic-only", "app_key"), lambda: secrets.decrypt(token, "app_key")):
        with pytest.raises(secrets.CredentialStorageError):
            operation()
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps({"active": "test", "keys": {"test": base64.urlsafe_b64encode(os.urandom(32)).decode()}}))
    monkeypatch.setenv("BROKER_CREDENTIAL_KEY_FILE", str(path))
    with pytest.raises(secrets.CredentialStorageError):
        secrets.decrypt(token, "app_key")
    with pytest.raises(secrets.CredentialStorageError):
        secrets.decrypt(token.replace(":test:", ":unknown:"), "app_key")
    assert secrets.encrypt("", "app_key") == ""


def test_backup_ciphertext_roundtrip_and_tampering():
    from scripts.protect_database_backup import seal, unseal
    original = b"PGDMP-synthetic-backup-with-secret"
    encoded = seal(original)
    assert original not in encoded and unseal(encoded) == original
    assert encoded != seal(original)
    with pytest.raises(secrets.CredentialStorageError):
        unseal(encoded[:-1] + bytes([encoded[-1] ^ 1]))


@pytest.mark.usefixtures("rebalance_db_schema")
@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요")
def test_missing_key_api_is_503_without_credential_output(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import postgres
    from app.lib.session import get_current_user
    from app.routes import stocks
    engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    uid = uuid.uuid4()
    async def setup():
        async with sessions() as db:
            db.add(User(id=uid, name="api", email=f"{uid}@example.test", password_hash="fake", client_id=uid.hex))
            await db.flush()
            db.add(BrokerSettings(user_id=uid, broker="kis", app_key="api-fake-key", app_secret="api-fake-secret", account_no="12345678-01"))
            await db.commit()
    asyncio.run(setup())
    monkeypatch.setattr(postgres, "get_session_factory", lambda: sessions)
    monkeypatch.delenv("BROKER_CREDENTIAL_KEY_FILE")
    app = FastAPI()
    app.include_router(stocks.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": str(uid)}
    with TestClient(app) as client:
        response = client.get("/api/broker/settings")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CREDENTIAL_STORAGE_UNAVAILABLE"
    assert not any(v in response.text for v in ("api-fake", "12345678", "qbc1:"))
    asyncio.run(engine.dispose())


@pytest.mark.usefixtures("rebalance_db_schema")
@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요")
def test_real_pg_encrypted_storage_rotation_and_plaintext_constraint(monkeypatch, tmp_path):
    async def scenario():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        uid = uuid.uuid4()
        original = {"app_key": "key-" + "k" * 190, "app_secret": "secret-" + "s" * 190, "account_no": "12345678-01"}
        async with sessions() as db:
            db.add(User(id=uid, name="crypto-test", email=f"{uid}@example.test", password_hash="fake", client_id=uid.hex))
            await db.flush()
            db.add(BrokerSettings(user_id=uid, broker="kis", **original))
            await db.commit()
        async with sessions() as db:
            raw = (await db.execute(text("SELECT app_key,app_secret,account_no FROM broker_settings WHERE user_id=:uid"), {"uid": uid})).mappings().one()
            assert all(raw[f].startswith(secrets.PREFIX) and original[f] not in raw[f] for f in secrets.FIELDS)
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert all(getattr(row, f) == original[f] for f in secrets.FIELDS)
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE broker_settings SET account_no='plain' WHERE user_id=:uid"), {"uid": uid})
        old = json.loads(open(os.environ["BROKER_CREDENTIAL_KEY_FILE"]).read())
        new = base64.urlsafe_b64encode(os.urandom(32)).decode()
        path = tmp_path / "rotate.json"
        path.write_text(json.dumps({"active": "next", "keys": {**old["keys"], "next": new}}))
        monkeypatch.setenv("BROKER_CREDENTIAL_KEY_FILE", str(path))
        async with engine.begin() as conn:
            result = await conn.run_sync(secrets.reencrypt)
            assert result["encrypted_fields"] >= 3  # 모듈의 다른 시험 행도 함께 교체한다.
        path.write_text(json.dumps({"active": "next", "keys": {"next": new}}))
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert all(getattr(row, f) == original[f] for f in secrets.FIELDS)
        await engine.dispose()
    asyncio.run(scenario())


@pytest.mark.usefixtures("rebalance_db_schema")
@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요")
def test_legacy_migration_is_atomic_and_preserves_credentials(monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("broker_migration", Path(__file__).resolve().parents[1] / "alembic/versions/0031_broker_secrets.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    async def scenario():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        uid = uuid.uuid4()
        async with sessions() as db:
            db.add(User(id=uid, name="legacy", email=f"{uid}@example.test", password_hash="fake", client_id=uid.hex))
            await db.flush()
            db.add(BrokerSettings(user_id=uid, quant_auto_enabled=False))
            await db.commit()
        async with engine.begin() as conn:
            for f in secrets.FIELDS:
                await conn.execute(text(f"ALTER TABLE broker_settings DROP CONSTRAINT ck_broker_encrypted_{f}"))
            await conn.execute(text("UPDATE broker_settings SET app_key='legacy-key',app_secret='legacy-secret',account_no='12345678-01'"))
        key_path = os.environ["BROKER_CREDENTIAL_KEY_FILE"]
        def upgrade(conn):
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
        monkeypatch.delenv("BROKER_CREDENTIAL_KEY_FILE")
        with pytest.raises(secrets.CredentialStorageError):
            async with engine.begin() as conn:
                await conn.run_sync(upgrade)
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT app_key FROM broker_settings")) == "legacy-key"
        monkeypatch.setenv("BROKER_CREDENTIAL_KEY_FILE", key_path)
        async with engine.begin() as conn:
            await conn.run_sync(upgrade)
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert (row.app_key, row.app_secret, row.account_no, row.quant_auto_enabled) == ("legacy-key", "legacy-secret", "12345678-01", False)
        with pytest.raises(RuntimeError):
            migration.downgrade()
        await engine.dispose()
    asyncio.run(scenario())
