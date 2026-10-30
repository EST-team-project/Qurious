"""알림 설정 API.

GET  /api/notification/settings  – 현재 사용자의 알림 설정 조회
POST /api/notification/settings  – 알림 설정 저장
POST /api/notification/test      – 테스트 알림 전송
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.models import NotificationLog, NotificationSettings
from app.models.consent import CONSENT_GRANT, CONSENT_WITHDRAW
from app.services import consent, notification

router = APIRouter(prefix="/api/notification")

_SUPPORTED_CHANNELS = {"telegram", "slack", "email", "kakao", "sms"}


class NotificationSettingsBody(BaseModel):
    """알림 설정 저장 요청 모델."""

    channels: list[str] = Field(default_factory=list, description="활성화할 채널 목록")

    # 텔레그램
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # Slack
    slack_webhook_url: str = ""

    # 이메일
    email_to: str = ""
    email_host: str = ""
    email_port: int = Field(default=587, ge=1, le=65535)
    email_user: str = ""
    email_password: str = ""
    email_from: str = ""

    # 카카오 알림톡
    kakao_api_key: str = ""
    kakao_api_secret: str = ""
    kakao_sender_key: str = ""
    kakao_phone: str = ""

    # SMS
    sms_api_key: str = ""
    sms_api_secret: str = ""
    sms_from: str = ""
    sms_to: str = ""

    # 알림 연동 정보 수집·이용(선택) 동의 — 설정 화면에서 처음 저장하는 순간 받는다(2026-10-29 · ①-09).
    #   True  → 동의(현재 동의문 판 `integration_consent_version` 을 함께 보낸다) · False → 철회 + 저장된 연동 정보 삭제
    #   None  → 동의 상태를 바꾸지 않는다(이미 동의한 사람의 평소 저장)
    integration_consent: bool | None = None
    integration_consent_version: str | None = None


#: 이용자가 입력하는 **개인정보 칸**(포트 숫자는 뺀다) — 새로 채워지면 선택 동의가 있어야 저장한다.
_SECRET_FIELDS = ("telegram_token", "email_password", "kakao_api_key", "kakao_api_secret", "sms_api_key", "sms_api_secret")
_PHONE_FIELDS = ("kakao_phone", "sms_from", "sms_to")
_PLAIN_FIELDS = ("telegram_chat_id", "slack_webhook_url", "email_to", "email_host", "email_user", "email_from", "kakao_sender_key")


def brings_new_personal_data(body: "NotificationSettingsBody", row: "NotificationSettings | None") -> bool:
    """이 요청이 **새로** 채우거나 바꾸는 개인정보 칸이 있는가.

    화면이 되돌려 보내는 가림값(비밀값 `****` · 가려진 전화번호 `*` 포함)과 저장된 값 그대로인 칸은 새 입력이 아니다 —
    동의 없이 이미 저장된 사람이 아무것도 안 바꾸고 저장해도 막히지 않는다. 지우는 것(빈 값)도 새 수집이 아니다.
    """
    def current(name: str) -> str:
        return (getattr(row, name, "") or "") if row is not None else ""

    for name in _SECRET_FIELDS:
        v = getattr(body, name)
        if v and v != "****":
            return True
    for name in _PHONE_FIELDS:
        v = getattr(body, name)
        if v and "*" not in v and v != current(name):
            return True
    for name in _PLAIN_FIELDS:
        v = getattr(body, name)
        if v and v != current(name):
            return True
    return False


async def _consent_state(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """화면이 동의 칸을 그리는 데 쓰는 현재 상태 — 지금 동의했나 · 어느 판 · 언제 · 지금 동의문 판."""
    last = await consent.latest(db, user_id, consent.NOTIFY_CONSENT_KEY)
    granted = last is not None and last.action == CONSENT_GRANT
    return {
        "granted": granted,
        "version": last.terms_version if granted else None,
        "at": last.created_at.isoformat() if granted else None,
        "current_version": consent.NOTIFY_CONSENT_VERSION,
    }


def mask_phone(value: str) -> str:
    """전화번호는 끝 네 자리 숫자만 남기고 가린다(`010-1234-5678` → `***-****-5678`). 응답에 번호 전체를 싣지 않는다."""
    if not value:
        return ""
    digits = [i for i, ch in enumerate(value) if ch.isdigit()]
    keep = set(digits[-4:]) if len(digits) > 4 else set()
    return "".join(ch if (not ch.isdigit() or i in keep) else "*" for i, ch in enumerate(value))


def keep_phone(new_val: str, existing_val: str) -> str:
    """화면이 가려진 값(`*` 포함)을 그대로 돌려보내면 저장된 번호를 유지한다. 빈 값은 번호를 지운다."""
    if new_val and "*" in new_val:
        return existing_val
    return new_val


async def _get_settings_row(db: AsyncSession, user_id: uuid.UUID) -> NotificationSettings | None:
    result = await db.execute(select(NotificationSettings).where(NotificationSettings.user_id == user_id))
    return result.scalar_one_or_none()


@router.get("/settings")
async def get_notification_settings(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    """현재 사용자의 알림 설정을 반환한다. 비밀값(password/secret)은 마스킹, 전화번호는 끝 네 자리만 남긴다."""
    uid = uuid.UUID(user["id"])
    row = await _get_settings_row(db, uid)
    state = await _consent_state(db, uid)

    def mask(v: str) -> str:
        """보안을 위해 비밀값은 설정 여부만 알 수 있도록 고정 마스크로 반환."""
        return "****" if v else ""

    if not row:
        return {
            "channels": [], "telegram_token": "", "telegram_chat_id": "",
            "slack_webhook_url": "", "email_to": "", "email_host": "",
            "email_port": 587, "email_user": "", "email_password": "", "email_from": "",
            "kakao_api_key": "", "kakao_api_secret": "", "kakao_sender_key": "", "kakao_phone": "",
            "sms_api_key": "", "sms_api_secret": "", "sms_from": "", "sms_to": "",
            "integration_consent": state,
        }

    return {
        "integration_consent": state,
        "channels":          row.channels,
        "telegram_token":    mask(row.telegram_token),
        "telegram_chat_id":  row.telegram_chat_id,
        "slack_webhook_url": row.slack_webhook_url,
        "email_to":          row.email_to,
        "email_host":        row.email_host,
        "email_port":        row.email_port,
        "email_user":        row.email_user,
        "email_password":    mask(row.email_password),
        "email_from":        row.email_from,
        "kakao_api_key":     mask(row.kakao_api_key),
        "kakao_api_secret":  mask(row.kakao_api_secret),
        "kakao_sender_key":  row.kakao_sender_key,
        "kakao_phone":       mask_phone(row.kakao_phone),
        "sms_api_key":       mask(row.sms_api_key),
        "sms_api_secret":    mask(row.sms_api_secret),
        "sms_from":          mask_phone(row.sms_from),
        "sms_to":            mask_phone(row.sms_to),
    }


@router.post("/settings")
async def save_notification_settings(
    body: NotificationSettingsBody,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    """알림 설정을 저장한다. 빈 문자열 비밀값은 기존 값을 유지한다.

    알림 연동 정보(토큰 · 웹훅 · 발송 비밀번호 · 휴대전화번호 · 키)는 **선택 동의**가 있어야 새로 받는다(①-09):
    - 동의가 없는데 개인정보 칸이 새로 채워졌으면 422 — 동의 행은 이 저장과 같은 트랜잭션으로 쓴다.
    - `integration_consent=false` 는 철회다 — 철회 행을 쌓고 저장된 연동 정보(설정 행)를 지운다.
    """
    channels = [c for c in body.channels if c in _SUPPORTED_CHANNELS]
    uid = uuid.UUID(user["id"])

    row = await _get_settings_row(db, uid)
    granted = await consent.is_granted(db, uid, consent.NOTIFY_CONSENT_KEY)

    if body.integration_consent is False:
        # 철회 — 동의했던 사람이면 철회 행을 쌓는다. 연동 정보는 동의 여부와 상관없이 지운다(철회했는데 값이 남으면 안 된다).
        if granted:
            consent.add_rows(db, uid, [consent.NOTIFY_CONSENT_KEY], CONSENT_WITHDRAW,
                             consent.NOTIFY_CONSENT_VERSION, consent.SOURCE_NOTIFICATION_SETTINGS)
        if row is not None:
            await db.delete(row)
        await db.commit()
        return {"ok": True, "withdrawn": True}

    if body.integration_consent is True and not granted:
        if (body.integration_consent_version or "") != consent.NOTIFY_CONSENT_VERSION:
            # 오래된 화면(캐시)이 옛 동의문을 보여 줬을 수 있다 — 새로고침하면 새 문구를 보고 다시 동의한다
            raise HTTPException(422, "알림 연동 동의문이 바뀌었습니다. 화면을 새로고침한 뒤 다시 동의해 주세요.")
        consent.add_rows(db, uid, [consent.NOTIFY_CONSENT_KEY], CONSENT_GRANT,
                         consent.NOTIFY_CONSENT_VERSION, consent.SOURCE_NOTIFICATION_SETTINGS)
        granted = True

    if not granted and brings_new_personal_data(body, row):
        raise HTTPException(
            422, "알림 연동 정보 수집·이용(선택)에 동의해야 토큰 · 웹훅 · 비밀번호 · 휴대전화번호를 저장할 수 있습니다. "
                 "동의하지 않아도 다른 기능은 그대로 쓸 수 있습니다.")

    if row is None:
        row = NotificationSettings(user_id=uid)
        db.add(row)

    def keep_secret(new_val: str, existing_val: str) -> str:
        """값이 마스크 플레이스홀더("****")이거나 빈 문자열이면 기존 저장값을 유지한다."""
        if not new_val or new_val == "****":
            return existing_val
        return new_val

    row.channels = channels
    row.telegram_token = keep_secret(body.telegram_token, row.telegram_token)
    row.telegram_chat_id = body.telegram_chat_id
    row.slack_webhook_url = body.slack_webhook_url
    row.email_to = body.email_to
    row.email_host = body.email_host
    row.email_port = body.email_port
    row.email_user = body.email_user
    row.email_password = keep_secret(body.email_password, row.email_password)
    row.email_from = body.email_from
    row.kakao_api_key = keep_secret(body.kakao_api_key, row.kakao_api_key)
    row.kakao_api_secret = keep_secret(body.kakao_api_secret, row.kakao_api_secret)
    row.kakao_sender_key = body.kakao_sender_key
    row.kakao_phone = keep_phone(body.kakao_phone, row.kakao_phone)
    row.sms_api_key = keep_secret(body.sms_api_key, row.sms_api_key)
    row.sms_api_secret = keep_secret(body.sms_api_secret, row.sms_api_secret)
    row.sms_from = keep_phone(body.sms_from, row.sms_from)
    row.sms_to = keep_phone(body.sms_to, row.sms_to)

    await db.commit()
    return {"ok": True}


@router.post("/test")
async def test_notification(
    user=Depends(get_current_user),
):
    """현재 설정된 모든 채널로 테스트 알림을 전송한다."""
    html = (
        "🔔 <b>[알림 테스트]</b>\n\n"
        "매매 알림이 정상적으로 설정되었습니다.\n"
        "이 메시지가 수신되면 해당 채널이 활성화된 것입니다."
    )
    plain = (
        "[알림 테스트] 매매 알림이 정상적으로 설정되었습니다.\n"
        "이 메시지가 수신되면 해당 채널이 활성화된 것입니다."
    )
    await notification.dispatch(
        plain,
        html_message=html,
        subject="[매매 알림] 테스트",
        user_id=user["id"],
    )
    return {"ok": True, "message": "테스트 알림을 전송했습니다."}


#: 알림 한 건의 전달 결과(`NotificationLog.delivery_status` — `services/notification.py` 가 정한다) → 화면 글.
#: `sending` 은 선점만 하고 끝을 못 쓴 것 — 결과가 불명확해도 자동으로 다시 보내지 않으므로(중복 방지) 「확인 필요」 로 보인다.
DELIVERY_LABELS = {
    "delivered": "전달됨", "partial": "일부만 전달", "failed": "전달 실패",
    "sending": "결과 불명 · 자동 재발송 안 함", "no_channels": "보낼 채널 없음", "legacy": "이전 기록",
}


@router.get("/history")
async def notification_history(
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_pg_session),
):
    """현재 사용자의 최근 알림 발송 이력을 조회한다."""
    result = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.user_id == uuid.UUID(user["id"]))
        .order_by(NotificationLog.created_at.desc())
        .limit(limit)
    )
    events = [{
        "subject": ev.subject, "message": ev.message, "channels": ev.channels,
        "created_at": ev.created_at.isoformat(), "kind": ev.kind,
        "delivery_status": ev.delivery_status, "status_label": DELIVERY_LABELS.get(ev.delivery_status, "확인 필요"),
    } for ev in result.scalars().all()]
    return {"events": events, "count": len(events)}
