"""알림 설정 API.

GET  /api/notification/settings  – 현재 사용자의 알림 설정 조회 (사건별 설정 `preferences` · 사건 목록 `event_catalog` 포함)
POST /api/notification/settings  – 알림 설정 저장
POST /api/notification/test      – 테스트 알림 전송
GET  /api/notification/history   – 최근 알림 이력 (보고 원본 `payload` 포함)
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
from app.services import alert_format, alert_prefs, consent, notification

router = APIRouter(prefix="/api/notification")

_SUPPORTED_CHANNELS = {"telegram", "slack", "discord", "email", "kakao", "sms"}


class NotificationSettingsBody(BaseModel):
    """알림 설정 저장 요청 모델."""

    channels: list[str] = Field(default_factory=list, description="활성화할 채널 목록")

    # 텔레그램
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # Slack
    slack_webhook_url: str = ""

    # Discord — 비밀값(주소를 아는 사람은 누구나 그 채널에 글을 올린다). 비우면 서버 공용 주소로 간다(2026-11-01)
    discord_webhook_url: str = ""

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

    # 사건별 켜기/끄기(on·silent·off) · 조용한 시간 — None 이면 기존 값을 유지한다(2026-11-01)
    #   {"events": {"order_fill": "silent", ...}, "quiet": {"enabled": true, "start": "21:00", "end": "08:00"}}
    preferences: dict | None = None


#: 이용자가 입력하는 **개인정보 칸**(포트 숫자는 뺀다) — 새로 채워지면 선택 동의가 있어야 저장한다.
_SECRET_FIELDS = ("telegram_token", "discord_webhook_url", "email_password", "kakao_api_key", "kakao_api_secret", "sms_api_key", "sms_api_secret")
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
            # 디스코드 주소는 저장된 값과 같으면 새 입력이 아니다(공백만 다른 경우 포함)
            if name == "discord_webhook_url" and v.strip() == current(name):
                continue
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


def event_catalog() -> list[dict]:
    """설정 화면 표를 그리는 사건 목록 — 라벨 · 심각도 · 기본 모드 · 끌 수 있는지 · 묶음 대상인지."""
    return [{"kind": d.kind, "label": d.label, "severity": d.severity, "default_mode": d.default_mode,
             "lockable": d.lockable, "groupable": d.groupable} for d in alert_prefs.EVENT_DEFS]


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
            "slack_webhook_url": "", "discord_webhook_url": "", "email_to": "", "email_host": "",
            "email_port": 587, "email_user": "", "email_password": "", "email_from": "",
            "kakao_api_key": "", "kakao_api_secret": "", "kakao_sender_key": "", "kakao_phone": "",
            "sms_api_key": "", "sms_api_secret": "", "sms_from": "", "sms_to": "",
            "integration_consent": state,
            "preferences": alert_prefs.normalize({}), "event_catalog": event_catalog(),
        }

    return {
        "integration_consent": state,
        "preferences":       alert_prefs.normalize(row.preferences),
        "event_catalog":     event_catalog(),
        "channels":          row.channels,
        "telegram_token":    mask(row.telegram_token),
        "telegram_chat_id":  row.telegram_chat_id,
        "slack_webhook_url": row.slack_webhook_url,
        "discord_webhook_url": mask(row.discord_webhook_url),
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
    prefs = None
    if body.preferences is not None:
        try:
            prefs = alert_prefs.validate(body.preferences)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    discord_url = body.discord_webhook_url.strip()
    if discord_url and discord_url != "****" and not notification.is_discord_webhook(discord_url):
        # 아무 주소나 저장하지 않는다 — 잘못 붙인 주소로 알림이 나가지 않고, 비밀 토큰이 든 주소가 엉뚱한 곳에 남지 않게
        raise HTTPException(422, "디스코드 웹훅 주소는 https://discord.com/api/webhooks/… 로 시작해야 합니다. "
                                 "채널 편집 → 연동 → 웹훅 → 「웹훅 URL 복사」로 받은 주소를 그대로 붙여 주세요.")

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

    # 동의는 했지만 지금 동의문 판이 아닌 사람 — 판이 올라 새로 들어온 항목(디스코드 웹훅 주소 · n0.2)은 다시 동의해야 저장한다
    last = await consent.latest(db, uid, consent.NOTIFY_CONSENT_KEY) if granted else None
    stale = granted and last is not None and last.terms_version != consent.NOTIFY_CONSENT_VERSION

    if body.integration_consent is True and (not granted or stale):
        if (body.integration_consent_version or "") != consent.NOTIFY_CONSENT_VERSION:
            # 오래된 화면(캐시)이 옛 동의문을 보여 줬을 수 있다 — 새로고침하면 새 문구를 보고 다시 동의한다
            raise HTTPException(422, "알림 연동 동의문이 바뀌었습니다. 화면을 새로고침한 뒤 다시 동의해 주세요.")
        consent.add_rows(db, uid, [consent.NOTIFY_CONSENT_KEY], CONSENT_GRANT,
                         consent.NOTIFY_CONSENT_VERSION, consent.SOURCE_NOTIFICATION_SETTINGS)
        granted = True
        stale = False

    if not granted and brings_new_personal_data(body, row):
        raise HTTPException(
            422, "알림 연동 정보 수집·이용(선택)에 동의해야 토큰 · 웹훅 · 비밀번호 · 휴대전화번호를 저장할 수 있습니다. "
                 "동의하지 않아도 다른 기능은 그대로 쓸 수 있습니다.")

    if stale and discord_url and discord_url != "****" and discord_url != (getattr(row, "discord_webhook_url", "") or ""):
        raise HTTPException(
            422, "알림 연동 동의문이 바뀌어 「디스코드 웹훅 주소」 항목이 더해졌습니다. 디스코드 주소를 저장하려면 화면에서 동의문을 읽고 다시 동의해 주세요.")

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
    # 디스코드: 가림값("****")이면 저장된 주소를 유지하고, 빈 값이면 지운다(지우면 서버 공용 주소로 돌아간다)
    if discord_url != "****":
        row.discord_webhook_url = discord_url
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
    if prefs is not None:
        row.preferences = prefs

    await db.commit()
    return {"ok": True}


@router.post("/test")
async def test_notification(
    user=Depends(get_current_user),
):
    """현재 설정된 모든 채널로 보고식 시험 알림을 전송한다 — 채널마다 모양이 어떻게 보이는지 확인하는 용도."""
    ev = alert_format.AlertEvent(
        kind="test", severity="info", emoji="🔔", title="알림 시험 – 한글 표시 확인",
        summary="매매 알림이 정상적으로 설정되었습니다. 이 메시지가 보이면 해당 채널이 켜진 것입니다.",
        fields=[("종목", "삼성전자 (005930)"), ("구분", "매수"), ("수량·단가", "10주 × 70,000원"),
                ("거래 금액", alert_format.won(700000))],
        reason="설정 화면의 「알림 시험」 단추를 눌러 보낸 예시입니다. 실제 거래가 아닙니다.",
        risk="이 예시의 종목·금액은 실제와 무관합니다.",
        next_action="모양이 마음에 들지 않으면 사건별 설정에서 「조용히」나 「끔」을 고르세요.",
        mock=True, subject="[매매 알림] 시험",
    )
    await notification.dispatch_event(ev, user_id=user["id"])
    return {"ok": True, "message": "테스트 알림을 전송했습니다."}


#: 알림 한 건의 전달 결과(`NotificationLog.delivery_status` — `services/notification.py` 가 정한다) → 화면 글.
#: `sending` 은 선점만 하고 끝을 못 쓴 것 — 결과가 불명확해도 자동으로 다시 보내지 않으므로(중복 방지) 「확인 필요」 로 보인다.
DELIVERY_LABELS = {
    "delivered": "전달됨", "partial": "일부만 전달", "failed": "전달 실패",
    "sending": "결과 불명 · 자동 재발송 안 함", "no_channels": "보낼 채널 없음", "legacy": "이전 기록",
    "held": "보관 중 (조용한 시간 · 묶음 대기)", "digesting": "묶음 발송 중", "digested": "묶음으로 발송됨",
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
        "payload": ev.payload,
    } for ev in result.scalars().all()]
    return {"events": events, "count": len(events)}
