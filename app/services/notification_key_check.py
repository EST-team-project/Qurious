"""알림 암호화 키 점검 — 기동 때 한 번 (설계 ⑦ ①+③, 2026-11-05).

키가 틀리거나 파일이 없으면 **모든 사용자의 비상 정지 · 체결 알림이 조용히 멈춘다**(발송은 fail-closed). 그 사실을 기동 로그에
`error` 한 줄로 남겨 기존 로그 감시에 걸리게 한다. 기동을 막지 않고, 비밀값 · 암호문은 로그에 쓰지 않는다.

- `check_sample` — 순수 함수. 키 파일을 읽고 암호문 한 칸이 있으면 복호화해 본다. 결과: ok · key_unavailable · decrypt_failed.
- `check_on_startup` — 앱 기동: DB 에서 비밀이 든 행 하나를 골라 `check_sample` 로 확인한다.
- `check_keyfile_only` — worker · beat 기동: DB 연결 없이 키 파일만 본다(마운트 누락을 잡는다).
"""
from __future__ import annotations

import logging

from app.lib import notification_secrets as ns

logger = logging.getLogger(__name__)

TAG = "CREDENTIAL_STORAGE"


def check_sample(ciphertext: str | None, field: str | None) -> str:
    """키 파일을 읽고(항상), 암호문이 주어지면 복호화해 본다. 절대 예외를 내지 않는다."""
    try:
        ns._keyring()
    except Exception:
        logger.error("[%s] 알림 암호화 키 파일을 읽지 못했습니다 — 알림 설정 · 발송이 멈춥니다(마운트 · 경로 · 형식 확인). 평문으로 우회하지 않습니다.", TAG)
        return "key_unavailable"
    if ciphertext and field:
        try:
            ns.decrypt(ciphertext, field)
        except Exception:
            logger.error("[%s] 알림 암호화 키로 저장된 값을 복호화하지 못했습니다 — 키가 바뀌었거나 값이 손상됐습니다. 발송은 멈춘 상태로 유지합니다.", TAG)
            return "decrypt_failed"
    return "ok"


def check_keyfile_only() -> str:
    return check_sample(None, None)


async def check_on_startup() -> str:
    """DB 에서 암호문이 든 행 하나를 골라 복호화해 본다(없으면 키 파일만). 실패해도 예외 없이 상태만 돌려준다."""
    try:
        from sqlalchemy import text
        from app.database.postgres import get_session_factory
        sample = None
        async with get_session_factory()() as db:
            for field in ns.FIELDS:
                # 원시 SQL — ORM 으로 읽으면 9칸이 모두 복호화돼 어느 칸에서 실패했는지도 모르고 예외가 올라온다
                raw = (await db.execute(text(
                    f"SELECT {field} FROM {ns.TABLE} WHERE {field} LIKE 'qnc1:%' LIMIT 1"))).scalar()
                if raw:
                    sample = (raw, field)
                    break
        status = check_sample(*(sample or (None, None)))
    except Exception as exc:  # DB 가 아직 없거나 표가 없음 등 — 기동을 막지 않는다
        logger.warning("알림 암호화 키 점검을 건너뜁니다(DB 조회 실패): %s", type(exc).__name__)
        return check_keyfile_only()
    if status == "ok":
        logger.info("알림 암호화 키 점검 통과(%s)", "저장된 값 복호화 확인" if sample else "저장된 값 없음 — 키 파일만 확인")
    return status
