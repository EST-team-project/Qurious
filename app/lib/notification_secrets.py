"""알림 설정 비밀값 저장 보호.

증권사 자격증명(`broker_secrets`)과 **같은 키 파일**(BROKER_CREDENTIAL_KEY_FILE)을 읽되, 암호문 접두어(`qnc1:`)와
AAD(`notification_settings.<칸>`)를 따로 둬 도메인을 나눈다 — 한 칸의 암호문을 다른 칸이나 증권사 표로 옮겨 붙이면 복호화가 실패한다.
증권사 모듈의 암호문 형식 · AAD · 키 ID 는 건드리지 않는다(형제 모듈).

- 평문 호환 경로는 없다. 기존 평문은 배포 마이그레이션(0044)에서만 전환한다.
- 키 누락 · 변조 · 복호화 실패는 `NotificationStorageError` — 증권사 예외의 하위 클래스라 `get_pg_session` 의 503 계약에 그대로 걸린다.
- 이번 범위(9칸): 토큰 · 웹훅 · SMTP 비밀번호 · 카카오 키/시크릿/발신 프로필 키 · 문자 키/시크릿. 전화번호 · 주소 칸은 후속(개인정보 처리방침 판단).
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import Text, TypeDecorator

from app.lib.broker_secrets import CredentialStorageError, keyring

PREFIX = "qnc1:"
FIELDS = (
    "telegram_token", "slack_webhook_url", "discord_webhook_url", "email_password",
    "kakao_api_key", "kakao_api_secret", "kakao_sender_key", "sms_api_key", "sms_api_secret",
)
TABLE = "notification_settings"


class NotificationStorageError(CredentialStorageError):
    """알림 비밀값을 암호화·복호화하지 못했다. 문구에 값 · 암호문을 넣지 않는다."""

    def __init__(self):
        RuntimeError.__init__(self, "알림 비밀값 보호 설정을 확인하지 못했습니다. 관리자 확인이 필요합니다.")


def _keyring():
    try:
        return keyring()
    except Exception:
        raise NotificationStorageError() from None


def _aad(header: str, field: str) -> bytes:
    return (header + TABLE + "." + field).encode()


def encrypt(value, field):
    if value in (None, ""):
        return value
    try:
        if field not in FIELDS or not isinstance(value, str):
            raise ValueError
        active, keys = _keyring()
        nonce = os.urandom(12)  # 매번 새 nonce
        header = PREFIX + active + ":"
        blob = nonce + AESGCM(keys[active]).encrypt(nonce, value.encode(), _aad(header, field))
        return header + base64.urlsafe_b64encode(blob).decode()
    except Exception:
        raise NotificationStorageError() from None


def decrypt(value, field):
    if value in (None, ""):
        return value
    try:
        if field not in FIELDS or not value.startswith(PREFIX):
            raise ValueError  # 런타임 평문 호환 없음 — 기존 값은 0044 마이그레이션에서만 전환한다
        _, kid, encoded = value.split(":", 2)
        _, keys = _keyring()
        blob = base64.b64decode(encoded, altchars=b"-_", validate=True)
        return AESGCM(keys[kid]).decrypt(blob[:12], blob[12:], _aad(PREFIX + kid + ":", field)).decode()
    except Exception:
        raise NotificationStorageError() from None


class EncryptedNotificationSecret(TypeDecorator):
    """DB 에는 `qnc1:<키ID>:<base64>` 암호문(Text), 파이썬에서는 평문 문자열."""

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
    """현재 active 키로 9칸을 다시 암호화한다. 호출자가 트랜잭션을 관리한다 — 전체 변환·검증 성공 또는 전체 rollback.

    - 빈 값은 그대로 둔다. 이미 암호화된 값은 복호화한 뒤 한 번만 다시 암호화한다(이중 암호화 없음).
    - `allow_legacy=False` 면 평문을 만났을 때 멈춘다(회전용). 마이그레이션만 True.
    """
    from sqlalchemy import text
    _keyring()  # 빈 DB 라도 잘못된 키 설정으로 성공했다고 보고하지 않는다
    connection.execute(text(f"LOCK TABLE {TABLE} IN EXCLUSIVE MODE"))
    rows = connection.execute(text(f"SELECT id, {', '.join(FIELDS)} FROM {TABLE} FOR UPDATE")).mappings().all()
    converted = 0
    assignments = ", ".join(f"{f} = :{f}" for f in FIELDS)
    for row in rows:
        values = {}
        for field in FIELDS:
            value = row[field]
            if value:
                if value.startswith(PREFIX):
                    value = decrypt(value, field)
                elif not allow_legacy:
                    raise NotificationStorageError()
                encoded = encrypt(value, field)
                if decrypt(encoded, field) != value:  # 복호화 왕복 검증
                    raise NotificationStorageError()
                values[field] = encoded
                converted += 1
            else:
                values[field] = value
        connection.execute(text(f"UPDATE {TABLE} SET {assignments} WHERE id = :id"), {**values, "id": row["id"]})
    return {"rows": len(rows), "encrypted_fields": converted}
