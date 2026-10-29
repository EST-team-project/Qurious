"""증권사 자격증명 저장 보호. 키 파일은 DB·이미지·소스와 분리해 읽기 전용으로 제공한다."""
import base64
import json
import os
from pathlib import Path
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import Text, TypeDecorator

PREFIX = "qbc1:"
FIELDS = ("app_key", "app_secret", "account_no")


class CredentialStorageError(RuntimeError):
    def __init__(self):
        super().__init__("증권사 자격증명 보호 설정을 확인하지 못했습니다. 관리자 확인이 필요합니다.")


def keyring():
    try:
        from app.config import settings
        path = os.environ.get("BROKER_CREDENTIAL_KEY_FILE", settings.BROKER_CREDENTIAL_KEY_FILE)
        if not path:
            raise ValueError
        data = json.loads(Path(path).read_text())
        active = data["active"]
        keys = {k: base64.b64decode(v, altchars=b"-_", validate=True) for k, v in data["keys"].items()}
        if active not in keys or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", k) or len(v) != 32 for k, v in keys.items()):
            raise ValueError
        return active, keys
    except Exception:
        raise CredentialStorageError() from None


def encrypt(value, field):
    if value in (None, ""):
        return value
    try:
        if field not in FIELDS or not isinstance(value, str):
            raise ValueError
        active, keys = keyring()
        nonce = os.urandom(12)
        header = PREFIX + active + ":"
        aad = (header + "broker_settings." + field).encode()
        blob = nonce + AESGCM(keys[active]).encrypt(nonce, value.encode(), aad)
        return header + base64.urlsafe_b64encode(blob).decode()
    except Exception:
        raise CredentialStorageError() from None


def decrypt(value, field):
    if value in (None, ""):
        return value
    try:
        if field not in FIELDS or not value.startswith(PREFIX):
            raise ValueError  # 런타임 평문 호환 없음. 기존 값은 배포 마이그레이션에서만 전환.
        _, kid, encoded = value.split(":", 2)
        _, keys = keyring()
        blob = base64.b64decode(encoded, altchars=b"-_", validate=True)
        aad = (PREFIX + kid + ":broker_settings." + field).encode()
        return AESGCM(keys[kid]).decrypt(blob[:12], blob[12:], aad).decode()
    except Exception:
        raise CredentialStorageError() from None


class EncryptedCredential(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, field):
        self.field = field
        super().__init__()

    def process_bind_param(self, value, dialect):
        return encrypt(value, self.field)

    def process_result_value(self, value, dialect):
        return decrypt(value, self.field)


def reencrypt(connection, *, allow_legacy=False):
    """호출자가 트랜잭션을 관리한다. 전체 변환/검증 성공 또는 전체 rollback."""
    from sqlalchemy import text
    keyring()  # 빈 DB라도 잘못된 키 설정으로 성공했다고 보고하지 않는다.
    connection.execute(text("LOCK TABLE broker_settings IN EXCLUSIVE MODE"))
    rows = connection.execute(text("SELECT id, app_key, app_secret, account_no FROM broker_settings FOR UPDATE")).mappings().all()
    converted = 0
    for row in rows:
        values = {}
        for field in FIELDS:
            value = row[field]
            if value:
                if value.startswith(PREFIX):
                    value = decrypt(value, field)
                elif not allow_legacy:
                    raise CredentialStorageError()
                encoded = encrypt(value, field)
                if decrypt(encoded, field) != value:
                    raise CredentialStorageError()
                values[field] = encoded
                converted += 1
            else:
                values[field] = value
        connection.execute(text("UPDATE broker_settings SET app_key=:app_key, app_secret=:app_secret, account_no=:account_no WHERE id=:id"), {**values, "id": row["id"]})
    return {"rows": len(rows), "encrypted_fields": converted}
