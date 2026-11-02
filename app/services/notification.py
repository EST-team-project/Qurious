"""다중 채널 알림 서비스.

지원 채널:
  telegram  – 텔레그램 봇
  slack     – Slack Incoming Webhook
  discord   – Discord 웹훅(.env 공용 주소 · 2026-11-01)
  email     – SMTP 이메일
  kakao     – 카카오 알림톡 (CoolSMS REST API)
  sms       – SMS (CoolSMS REST API)

채널 활성화 방법:
  1. .env 글로벌 설정 (전체 사용자 공용)
  2. MongoDB notification_settings 컬렉션의 사용자별 설정 우선 적용

사용법:
  텔레그램: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 설정
  Slack:    SLACK_WEBHOOK_URL 설정
  Discord:  DISCORD_WEBHOOK_URL 설정
  이메일:   SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_TO 설정
  카카오:   COOLSMS_API_KEY, COOLSMS_API_SECRET, KAKAO_SENDER_KEY, KAKAO_PHONE 설정
  SMS:      COOLSMS_API_KEY, COOLSMS_API_SECRET, SMS_FROM, SMS_TO 설정
"""
import asyncio
import hashlib
import hmac
import logging
import re
import smtplib
import socket
import ssl
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.config import settings
from app.services import alert_format, alert_prefs

logger = logging.getLogger(__name__)

#: 재시도 정책(할 일 ①-14 · 교차검증 설계 알림 정책): 전달이 안 된 게 **확실한** 실패만 다시 보낸다.
#: 처음 1번 + 재시도 최대 3번, 간격은 늘린다(1초 · 3초 · 9초). 응답이 불명확한 실패(읽기 시간 초과 · 서버 5xx ·
#: 인증 거절 등)는 중복 발송이 더 나쁘므로 다시 보내지 않는다(증권사 연동 설계의 「불명확하면 재발송 금지」).
MAX_RETRIES = 3
RETRY_DELAYS = (1.0, 3.0, 9.0)


def is_retryable(exc: BaseException) -> bool:
    """보내지 못한 게 확실한 실패인가 — 연결 단계 실패와 속도 제한(429)만 참이다."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429
    return isinstance(exc, (ConnectionRefusedError, socket.gaierror, smtplib.SMTPConnectError))


def _safe_exc(exc: BaseException) -> str:
    """실패 로그에 쓸 짧은 설명 — 예외 종류(와 HTTP 상태)만. 예외 글에는 요청 주소가 들어 있고 텔레그램 주소에는 봇 토큰이,
    슬랙 · 디스코드 주소에는 웹훅 비밀이 들어 있어 그대로 로그에 남기면 비밀이 샌다(2026-11-01 점검)."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"{type(exc).__name__}" + (f"(HTTP {status})" if status else "")


def _mark(outcome: dict | None, exc: BaseException) -> None:
    """실패 까닭을 호출한 쪽(`_send_with_retry`)에 알린다 — 반환 값(bool)은 그대로 둔다."""
    if outcome is not None:
        outcome["retryable"] = is_retryable(exc)


async def _send_with_retry(call) -> tuple[bool, int]:
    """`call(outcome)` 을 부르고, 확실한 미전달 실패일 때만 간격을 늘려 다시 부른다. (성공 여부, 시도 횟수)"""
    attempts = 0
    while True:
        attempts += 1
        outcome: dict = {}
        ok = await call(outcome)
        if ok is True:
            return True, attempts
        if not outcome.get("retryable") or attempts > MAX_RETRIES:
            return False, attempts
        await asyncio.sleep(RETRY_DELAYS[attempts - 1])


# ── 채널별 전송 함수 ────────────────────────────────────────────────────────


async def send_telegram(
    message: str,
    token: str = "",
    chat_id: str = "",
    outcome: dict | None = None,
    *, silent: bool = False,
) -> bool:
    """텔레그램 메시지 전송 (HTML 태그 지원). `silent` 면 소리·진동 없이(`disable_notification`)."""
    tok = token or settings.TELEGRAM_BOT_TOKEN
    cid = chat_id or settings.TELEGRAM_CHAT_ID
    if not tok or not cid:
        logger.debug("텔레그램 설정 없음 – 건너뜀")
        return False
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            body: dict = {"chat_id": cid, "text": message, "parse_mode": "HTML"}
            if silent:
                body["disable_notification"] = True
            r = await cli.post(url, json=body)
            r.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("텔레그램 알림 실패: %s", _safe_exc(exc))
        _mark(outcome, exc)
        return False


async def send_slack(message: str, webhook_url: str = "", outcome: dict | None = None,
                     *, blocks: list | None = None) -> bool:
    """Slack Incoming Webhook 메시지 전송. `blocks` 가 있으면 Block Kit 으로 꾸며 보내고 `message` 는 미리보기 글이 된다."""
    url = webhook_url or settings.SLACK_WEBHOOK_URL
    if not url:
        logger.debug("Slack 웹훅 URL 없음 – 건너뜀")
        return False
    if webhook_url and not is_slack_webhook(webhook_url):
        # 사용자가 넣은 주소는 서버가 대신 부른다 — 슬랙 주소 모양이 아니면(내부망 주소 등) 보내지 않는다(2026-11-02 보안 점검)
        logger.warning("Slack 웹훅 주소 모양이 아니라 보내지 않습니다(https://hooks.slack.com/services/… 여야 함)")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            body: dict = {"text": message}
            if blocks:
                body["blocks"] = blocks
            r = await cli.post(url, json=body)
            r.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Slack 알림 실패: %s", _safe_exc(exc))
        _mark(outcome, exc)
        return False


#: 디스코드가 받는 웹훅 주소의 머리(공식 · 미리보기 · 카나리 도메인) — 잘못 적은 주소로 글을 보내지 않게 막는다
_DISCORD_HOOK_PREFIXES = (
    "https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
    "https://ptb.discord.com/api/webhooks/", "https://canary.discord.com/api/webhooks/",
)
def is_discord_webhook(url: str) -> bool:
    """디스코드 웹훅 주소 모양인가 — 알림 설정 저장 때와 보내기 직전에 같은 검사를 쓴다."""
    return bool(url) and url.startswith(_DISCORD_HOOK_PREFIXES) and len(url) > len(_DISCORD_HOOK_PREFIXES[0])


#: 슬랙이 받는 웹훅 주소 — 공식 도메인의 services · workflows · triggers 경로만. 사용자가 넣은 주소를 서버가 대신 부르므로
#: 아무 주소나 받으면 내부망(메타데이터 · 사설 IP)으로 요청이 나간다(2026-11-02 보안 점검)
_SLACK_HOOK_RE = re.compile(r"^https://hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9/_.\-]{4,}$")


def is_slack_webhook(url: str) -> bool:
    """슬랙 웹훅 주소 모양인가 — 알림 설정 저장 때와 보내기 직전에 같은 검사를 쓴다."""
    return bool(url) and bool(_SLACK_HOOK_RE.match(url))


#: 사용자가 정한 메일 서버로 STARTTLS 로 보낼 수 있는 포트(465 는 암호화 접속 방식이 달라 이 길에서 쓰지 않는다)
SMTP_PORTS = (25, 587, 2525)
_SMTP_HOST_RE = re.compile(r"^(?=.{4,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$")


def smtp_shape_error(host: str, port: int) -> str:
    """메일 서버 이름 · 포트 모양 검사(이름 풀기 없음 — 저장 때 쓴다). 괜찮으면 빈 글, 아니면 까닭."""
    if not _SMTP_HOST_RE.match(host or ""):
        return "메일 서버 주소는 smtp.example.com 같은 이름이어야 합니다(http:// · 경로 · IP 숫자 주소는 쓸 수 없습니다)."
    if port not in SMTP_PORTS:
        return f"메일 서버 포트는 {' · '.join(map(str, SMTP_PORTS))} 중 하나여야 합니다(STARTTLS 접속)."
    return ""


def smtp_target_error(host: str, port: int, *, resolve=None) -> str:
    """사용자가 정한 메일 서버로 나가도 되는가 — 모양 검사 + 그 이름이 가리키는 **모든** IP 가 공인 주소여야 한다. 괜찮으면 빈 글.

    이름 풀기는 막힐 수 있어(느린 DNS) 보내는 쪽에서 스레드로 부른다. 시험은 `resolve` 로 바꿔 끼운다.
    """
    why = smtp_shape_error(host, port)
    if why:
        return why
    from app.services import url_guard  # noqa: PLC0415 – 알림 서비스가 가볍게 뜨도록 필요할 때만
    try:
        ips = (resolve or url_guard._resolve)(host)
    except OSError:
        return "메일 서버 이름을 찾지 못했습니다."
    for ip in ips:
        bad = url_guard._bad_ip(ip)
        if bad:
            return f"내부망 주소로는 보낼 수 없습니다({bad})."
    return ""


#: 디스코드 글(content) 한 번에 최대 2,000자(공식 한도) — 넘으면 끝을 줄임표로 자른다
_DISCORD_MAX = 2000


#: 디스코드 메시지 플래그 SUPPRESS_NOTIFICATIONS(1<<12) — 웹훅 실행에서 허용되는 플래그(공식 문서)
_DISCORD_SUPPRESS_NOTIFICATIONS = 4096


async def send_discord(message: str, webhook_url: str = "", outcome: dict | None = None,
                       *, embeds: list | None = None, silent: bool = False, allow_shared: bool = True) -> bool:
    """Discord 웹훅 메시지 전송(2026-11-01). 주소는 사용자 설정이 먼저, 없으면 `DISCORD_WEBHOOK_URL`(.env 공용) — 성공은 204 로 온다.
    `embeds` 가 있으면 카드 모양으로 보내고, `silent` 면 알림음 없이(SUPPRESS_NOTIFICATIONS) 보낸다."""
    # allow_shared 가 거짓이면 공용(.env) 주소로 넘어가지 않는다 — 자기 주소가 없는 사용자의 개인 알림이 팀 채널로 새지 않게(2026-11-01)
    url = webhook_url or (settings.DISCORD_WEBHOOK_URL if allow_shared else "")
    if not url:
        logger.debug("Discord 웹훅 URL 없음 – 건너뜀")
        return False
    if not url.startswith(_DISCORD_HOOK_PREFIXES):
        logger.warning("Discord 웹훅 주소 모양이 아니라 보내지 않습니다(https://discord.com/api/webhooks/… 여야 함)")
        return False
    text = message if len(message) <= _DISCORD_MAX else message[:_DISCORD_MAX - 1] + "…"
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            # allowed_mentions 를 비워 메시지 속 @everyone · @here 가 사람을 호출하지 않게 한다
            body: dict = {"allowed_mentions": {"parse": []}}
            if embeds:
                body["embeds"] = embeds[:10]
                if text:
                    body["content"] = text
            else:
                body["content"] = text
            if silent:
                body["flags"] = _DISCORD_SUPPRESS_NOTIFICATIONS
            r = await cli.post(url, json=body)
            r.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Discord 알림 실패: %s", _safe_exc(exc))   # 주소에 비밀 토큰이 있어 예외 글(주소 포함)은 남기지 않는다
        _mark(outcome, exc)
        return False


def _send_email_sync(
    subject: str,
    body: str,
    to_addr: str,
    host: str,
    port: int,
    user: str,
    password: str,
    from_addr: str,
    outcome: dict | None = None,
    text_body: str = "",
) -> bool:
    """동기 SMTP 이메일 전송 (executor 에서 실행). `text_body` 가 있으면 텍스트 대체 본문을 함께 넣는다."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr or user
        msg["To"] = to_addr
        if text_body:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))   # 대체 본문은 먼저 — 마지막 파트(HTML)가 우선 표시된다
        msg.attach(MIMEText(body, "html", "utf-8"))
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())   # 인증서를 검증한다 — 가짜 서버에 비밀번호가 넘어가지 않게
            server.login(user, password)
            server.sendmail(from_addr or user, [to_addr], msg.as_string())
        return True
    except Exception as exc:
        logger.warning("이메일 알림 실패: %s", exc)
        _mark(outcome, exc)
        return False


async def send_email(
    subject: str,
    body: str,
    to_addr: str = "",
    host: str = "",
    port: int = 0,
    user: str = "",
    password: str = "",
    from_addr: str = "",
    outcome: dict | None = None,
    *, text_body: str = "",
) -> bool:
    """이메일 전송 (SMTP / STARTTLS)."""
    to_addr = to_addr or settings.SMTP_TO
    if host:
        # 사용자가 메일 서버를 직접 정했다 — 운영자(.env) 아이디 · 비밀번호 · 보내는 사람을 섞지 않는다(그 서버에 운영자 계정이
        # 넘어가지 않게 · 2026-11-02 보안 점검). 서버가 내부망 주소를 가리키면 보내지 않는다.
        port = port or settings.SMTP_PORT or 587
        why = await asyncio.to_thread(smtp_target_error, host, port)
        if why:
            logger.warning("이메일 알림을 보내지 않음 — 사용자가 정한 메일 서버를 쓸 수 없습니다: %s", why)
            return False
        from_addr = from_addr or user
    else:
        host      = settings.SMTP_HOST
        port      = port or settings.SMTP_PORT
        user      = user or settings.SMTP_USER
        password  = password or settings.SMTP_PASSWORD
        from_addr = from_addr or settings.SMTP_FROM or user
    if not (host and user and password and to_addr):
        logger.debug("SMTP 설정 없음 – 건너뜀")
        return False
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _send_email_sync, subject, body, to_addr, host, port, user, password, from_addr, outcome, text_body
    )


def _coolsms_auth_header(api_key: str, api_secret: str) -> str:
    """CoolSMS HMAC-SHA256 인증 헤더 생성."""
    date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    salt = str(time.time())
    sig = hmac.new(api_secret.encode(), (date_str + salt).encode(), hashlib.sha256).hexdigest()
    return f"HMAC-SHA256 apiKey={api_key}, date={date_str}, salt={salt}, signature={sig}"


async def send_kakao(
    message: str,
    api_key: str = "",
    api_secret: str = "",
    sender_key: str = "",
    phone: str = "",
    outcome: dict | None = None,
) -> bool:
    """카카오 알림톡 전송 (CoolSMS 친구톡 FriendTalk)."""
    api_key    = api_key    or settings.COOLSMS_API_KEY
    api_secret = api_secret or settings.COOLSMS_API_SECRET
    sender_key = sender_key or settings.KAKAO_SENDER_KEY
    phone      = phone      or settings.KAKAO_PHONE
    if not (api_key and api_secret and sender_key and phone):
        logger.debug("카카오 알림톡 설정 없음 – 건너뜀")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.post(
                "https://api.coolsms.co.kr/kakao/v2/send",
                headers={
                    "Authorization": _coolsms_auth_header(api_key, api_secret),
                    "Content-Type": "application/json",
                },
                json={
                    "message": {
                        "to": phone,
                        "from": sender_key,
                        "type": "FT",
                        "content": message,
                    }
                },
            )
            r.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("카카오 알림톡 실패: %s", exc)
        _mark(outcome, exc)
        return False


async def send_sms(
    message: str,
    api_key: str = "",
    api_secret: str = "",
    from_no: str = "",
    to_no: str = "",
    outcome: dict | None = None,
) -> bool:
    """SMS 문자 전송 (CoolSMS REST API)."""
    api_key    = api_key    or settings.COOLSMS_API_KEY
    api_secret = api_secret or settings.COOLSMS_API_SECRET
    from_no    = from_no    or settings.SMS_FROM
    to_no      = to_no      or settings.SMS_TO
    if not (api_key and api_secret and from_no and to_no):
        logger.debug("SMS 설정 없음 – 건너뜀")
        return False
    if len(message) > 80:
        logger.warning("SMS 메시지가 80자를 초과하여 잘립니다 (%d자 → 80자)", len(message))
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.post(
                "https://api.coolsms.co.kr/messages/v4/send",
                headers={
                    "Authorization": _coolsms_auth_header(api_key, api_secret),
                    "Content-Type": "application/json",
                },
                json={
                    "message": {
                        "to": to_no,
                        "from": from_no,
                        "text": message[:80],
                    }
                },
            )
            r.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("SMS 알림 실패: %s", exc)
        _mark(outcome, exc)
        return False


# ── 디스패처 ────────────────────────────────────────────────────────────────


#: 사용자는 있는데 알림 설정 행이 없거나 조회가 실패했다는 표시 — 빈 `{}`(사용자 없는 운영 알림)와 구분한다.
#: 이 사용자의 개인 알림(체결 · 예수금)은 `.env` 공용 채널로 보내지 않는다(2026-11-02 보안 점검: 예전엔 둘 다 `{}` 라 공용 채널로 샜다)
NO_SETTINGS = {"_no_settings": True}


async def _load_user_settings(user_id: str | None) -> dict:
    """PostgreSQL에서 사용자별 알림 설정을 조회한다. 사용자가 없는 호출은 `{}`, 설정 행이 없거나 조회가 실패하면 `NO_SETTINGS`."""
    if not user_id:
        return {}
    try:
        import uuid
        from sqlalchemy import select
        from app.database.postgres import get_session_factory  # noqa: PLC0415 – lazy import to avoid circular
        from app.models import NotificationSettings  # noqa: PLC0415

        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(NotificationSettings).where(NotificationSettings.user_id == uuid.UUID(user_id))
            )
            row = result.scalar_one_or_none()
        if not row:
            return dict(NO_SETTINGS)
        return {
            "channels": row.channels,
            "telegram_token": row.telegram_token,
            "telegram_chat_id": row.telegram_chat_id,
            "slack_webhook_url": row.slack_webhook_url,
            "discord_webhook_url": row.discord_webhook_url,
            "email_to": row.email_to,
            "email_host": row.email_host,
            "email_port": row.email_port,
            "email_user": row.email_user,
            "email_password": row.email_password,
            "email_from": row.email_from,
            "kakao_api_key": row.kakao_api_key,
            "kakao_api_secret": row.kakao_api_secret,
            "kakao_sender_key": row.kakao_sender_key,
            "kakao_phone": row.kakao_phone,
            "sms_api_key": row.sms_api_key,
            "sms_api_secret": row.sms_api_secret,
            "sms_from": row.sms_from,
            "sms_to": row.sms_to,
            "preferences": row.preferences or {},
        }
    except Exception as exc:
        logger.warning("사용자 알림 설정 조회 실패 — 이 사용자의 알림은 보내지 않습니다: %s", _safe_exc(exc))
        return dict(NO_SETTINGS)


def _channels_for(user_cfg: dict) -> list[str]:
    """이 사건을 보낼 채널 — 설정에 고른 채널, 없으면 `.env` 기본 채널. 설정 행이 없거나 조회가 실패한 사용자는 아무 데로도 보내지 않는다."""
    if user_cfg.get("_no_settings"):
        return []
    return user_cfg.get("channels") or _default_channels()


def _default_channels() -> list[str]:
    """글로벌 .env 설정을 기반으로 활성화된 채널 목록을 반환한다."""
    channels: list[str] = []
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        channels.append("telegram")
    if settings.SLACK_WEBHOOK_URL:
        channels.append("slack")
    if settings.DISCORD_WEBHOOK_URL:
        channels.append("discord")
    if settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD and settings.SMTP_TO:
        channels.append("email")
    if settings.COOLSMS_API_KEY and settings.COOLSMS_API_SECRET and settings.KAKAO_SENDER_KEY and settings.KAKAO_PHONE:
        channels.append("kakao")
    if settings.COOLSMS_API_KEY and settings.COOLSMS_API_SECRET and settings.SMS_FROM and settings.SMS_TO:
        channels.append("sms")
    return channels


#: 옛 `dispatch(kind=…)` 중복 방지 종류 · 제목 머리글을 설정 화면의 사건 종류로 옮기는 표
_LEGACY_KIND_MAP = {"tradingview_signal": "tv_signal", "quant_run_failed": "run_failed"}
_LEGACY_SUBJECT_MAP = (("[정합성]", "reconcile"), ("[TradingView]", "tv_signal"), ("[자동매매] 실행", "run_failed"))
_ALLOWED_TAGS = re.compile(r"</?(b|strong|i|em|u|s|code|pre|a|blockquote)\b", re.IGNORECASE)


def _legacy_pref_kind(kind: str | None, subject: str) -> str:
    if kind in _LEGACY_KIND_MAP:
        return _LEGACY_KIND_MAP[kind]
    for prefix, mapped in _LEGACY_SUBJECT_MAP:
        if subject.startswith(prefix):
            return mapped
    return "legacy"


async def dispatch(
    message: str,
    html_message: str = "",
    subject: str = "",
    user_id: str | None = None,
    *, kind: str | None = None, ref: str | None = None,
) -> None:
    """옛 호출 호환 어댑터 — 글을 사건으로 감싸 `dispatch_event` 로 넘긴다(글은 그대로 보낸다).

    Args:
        message:      일반 텍스트 메시지 (SMS · Slack · 카카오 사용)
        html_message: HTML 형식 메시지 (텔레그램 · 이메일 사용, 없으면 message 를 이스케이프해 사용)
        subject:      이메일 제목 (없으면 message 앞 40자 사용)
        user_id:      사용자 ID – PostgreSQL 에서 개별 설정 조회
        kind / ref:   같은 사용자·회차·사건은 한 번만 보내는 중복 방지(없으면 매번 보냄)
    """
    # 태그가 하나도 없는 「HTML」 은 평문이다(TradingView 코멘트 같은 외부 글의 `<` `&` 를 텔레그램이 해석하다 400 을 내지 않게 이스케이프)
    if html_message and not _ALLOWED_TAGS.search(html_message):
        html_message = ""
    ev = alert_format.legacy_event(
        message, html_message=html_message, subject=subject or f"[매매 알림] {message[:40]}",
        kind=_legacy_pref_kind(kind, subject),
    )
    await dispatch_event(ev, user_id=user_id, dedupe_kind=kind, ref=ref)


def _status_for(names: list[str], results: list) -> str:
    return ("no_channels" if not names else "delivered" if all(r is True for r in results)
            else "failed" if all(r is not True for r in results) else "partial")


async def _deliver(ev, user_cfg: dict, channels: list[str], silent: bool = False) -> tuple[list[str], list, list[int]]:
    """사건 하나를 채널마다 알맞은 모양으로 꾸며 동시에 보낸다. (채널 이름들, 결과들, 시도 횟수들)

    silent: 소리 없이 — 텔레그램 · 디스코드는 알림음 없이 보내고, 카카오 · SMS 는 건너뛴다.
    새 인자(blocks · embeds · silent · text_body)는 **필요할 때만** 넘긴다 — 글만 보내는 사건은 예전 인자 그대로.
    """
    plain = alert_format.render_plain(ev)
    tasks: list = []
    names: list[str] = []
    if "telegram" in channels:
        names.append("telegram")
        tg_extra = {"silent": True} if silent else {}
        tasks.append(_send_with_retry(lambda o: send_telegram(
            alert_format.render_telegram(ev),
            token=user_cfg.get("telegram_token", ""),
            chat_id=user_cfg.get("telegram_chat_id", ""),
            outcome=o, **tg_extra,
        )))
    if "slack" in channels:
        names.append("slack")
        fallback, blocks = alert_format.render_slack(ev)
        sl_extra = {"blocks": blocks} if blocks else {}
        tasks.append(_send_with_retry(lambda o: send_slack(
            fallback, webhook_url=user_cfg.get("slack_webhook_url", ""), outcome=o, **sl_extra,
        )))
    if "discord" in channels:
        names.append("discord")
        card = alert_format.render_discord(ev)
        dc_extra: dict = {}
        if card.get("embeds"):
            dc_extra["embeds"] = card["embeds"]
        if silent:
            dc_extra["silent"] = True
        # 설정이 있는 사용자(user_cfg 가 비어 있지 않음)는 「공용 채널로도 받기」 를 켠 때만 .env 공용 주소로 간다. 설정이 없는 호출(운영 알림)은 그대로 공용.
        shared_ok = (not user_cfg) or ((user_cfg.get("preferences") or {}).get("discord_use_shared") is True)
        tasks.append(_send_with_retry(lambda o: send_discord(
            card.get("content", ""), webhook_url=user_cfg.get("discord_webhook_url", ""), outcome=o, allow_shared=shared_ok, **dc_extra,
        )))
    if "email" in channels:
        names.append("email")
        subj, html_body, text_body = alert_format.render_email(ev)
        tasks.append(_send_with_retry(lambda o: send_email(
            subject=subj,
            body=html_body,
            to_addr=user_cfg.get("email_to", ""),
            host=user_cfg.get("email_host", ""),
            port=int(user_cfg.get("email_port") or 0),
            user=user_cfg.get("email_user", ""),
            password=user_cfg.get("email_password", ""),
            from_addr=user_cfg.get("email_from", ""),
            outcome=o, text_body=text_body,
        )))
    if "kakao" in channels and not silent:
        names.append("kakao")
        tasks.append(_send_with_retry(lambda o: send_kakao(
            plain,
            api_key=user_cfg.get("kakao_api_key", ""),
            api_secret=user_cfg.get("kakao_api_secret", ""),
            sender_key=user_cfg.get("kakao_sender_key", ""),
            phone=user_cfg.get("kakao_phone", ""),
            outcome=o,
        )))
    if "sms" in channels and not silent:
        names.append("sms")
        sms_text = alert_format.render_sms(ev)
        tasks.append(_send_with_retry(lambda o: send_sms(
            sms_text,
            api_key=user_cfg.get("sms_api_key", ""),
            api_secret=user_cfg.get("sms_api_secret", ""),
            from_no=user_cfg.get("sms_from", ""),
            to_no=user_cfg.get("sms_to", ""),
            outcome=o,
        )))

    results: list = []
    attempts: list[int] = []
    if tasks:
        raw = await asyncio.gather(*tasks, return_exceptions=True)
        # 채널 함수가 예외를 던지면(raw 가 예외) 시도 1번에 실패로 센다.
        results = [r[0] if isinstance(r, tuple) else r for r in raw]
        attempts = [r[1] if isinstance(r, tuple) else 1 for r in raw]
    return names, results, attempts


async def dispatch_event(ev, user_id: str | None = None, *, dedupe_kind: str | None = None, ref: str | None = None) -> None:
    """보고식 알림의 진입점 — 사건별 설정(on/silent/off) → 조용한 시간 · 묶음 보관 → 채널별 꾸며 보내기 → 이력(payload 포함).

    - 설정이 off 면 보내지 않는다(긴급은 off 불가). 사용자가 없는 호출(수집 보고 등)은 설정 없이 기본 채널로 바로 보낸다.
    - 보관 행 저장이 실패하면(DB 장애) 잃는 것보다 낫도록 **바로 보낸다**.
    - `dedupe_kind`+`ref` 가 있으면 같은 사용자·회차·사건은 한 번만(발송 결과가 불명확해도 자동 재발송 안 함).
    """
    ref = ref or ev.ref
    user_cfg = await _load_user_settings(user_id)
    prefs = alert_prefs.normalize(user_cfg.get("preferences"))
    mode = alert_prefs.effective_mode(prefs, ev.kind)
    if mode == "off":
        logger.info("알림 사건 설정이 꺼져 있어 보내지 않음: %s", ev.kind)
        return
    plain = alert_format.render_plain(ev)
    subj = ev.mail_subject()
    event_id = None
    if dedupe_kind is not None or ref is not None:
        event_id = await _claim_event(user_id, dedupe_kind, ref, subj, plain)
        if event_id is None:
            return  # 같은 사용자·회차·사건은 발송 결과가 불명확해도 자동 재발송하지 않는다.
    payload = alert_format.to_payload(ev)
    plan = alert_prefs.hold_plan(ev.kind, ev.severity, prefs, datetime.now(alert_format.KST)) if user_id else None
    if plan and await _store_held(user_id, subj, plain, {**payload, "hold": {**plan, "mode": mode}}, event_id):
        return
    channels: list[str] = _channels_for(user_cfg)
    names, results, attempts = await _deliver(ev, user_cfg, channels, silent=(mode == "silent"))
    if event_id is None:
        await _log_dispatch(user_id, subj, plain, names, results, attempts, payload=payload)
    else:
        await _finish_event(event_id, names, results, attempts, payload=payload)


async def _store_held(user_id, subject: str, message: str, payload: dict, event_id) -> bool:
    """보관 행을 저장한다(조용한 시간 · 묶음 대기). 저장하지 못하면 False — 호출한 쪽이 바로 보낸다."""
    try:
        import uuid
        from app.database.postgres import get_session_factory
        from app.models import NotificationLog
        async with get_session_factory()() as db:
            if event_id is not None:
                row = await db.get(NotificationLog, event_id)
                row.delivery_status, row.payload, row.channels = "held", payload, []
            else:
                db.add(NotificationLog(user_id=uuid.UUID(str(user_id)), subject=subject[:300], message=message[:500],
                                       channels=[], delivery_status="held", payload=payload))
            await db.commit()
        return True
    except Exception as exc:
        logger.warning("알림 보관 저장 실패 — 바로 보냅니다: %s", _safe_exc(exc))
        return False


async def _claim_held(ids: list) -> list:
    """풀 보관 행을 원자적으로 선점한다 — 주기 작업과 앱 시작 때 풀기가 겹쳐도 두 번 보내지 않는다."""
    from sqlalchemy import update
    from app.database.postgres import get_session_factory
    from app.models import NotificationLog
    async with get_session_factory()() as db:
        result = await db.execute(
            update(NotificationLog)
            .where(NotificationLog.id.in_(ids), NotificationLog.delivery_status == "held")
            .values(delivery_status="digesting")
            .returning(NotificationLog.id, NotificationLog.payload, NotificationLog.created_at))
        rows = list(result.all())
        await db.commit()
    rows.sort(key=lambda r: r.created_at)
    return rows


async def _release(uid, user_cfg: dict, claimed: list) -> int:
    """선점한 보관 행을 보낸다 — 한 건이면 원래 사건 그대로, 여러 건이면 요약 1건(kind=digest, 고유 ref)."""
    import uuid
    from app.database.postgres import get_session_factory
    from app.models import NotificationLog
    channels = _channels_for(user_cfg)
    payloads = [r.payload or {} for r in claimed]
    modes = [(p.get("hold") or {}).get("mode", "on") for p in payloads]
    if len(claimed) == 1:
        ev = alert_format.from_payload(payloads[0])
        names, results, attempts = await _deliver(ev, user_cfg, channels, silent=(modes[0] == "silent"))
        async with get_session_factory()() as db:
            row = await db.get(NotificationLog, claimed[0].id)
            row.channels = _channel_rows(names, results, attempts)
            row.delivery_status = _status_for(names, results)
            await db.commit()
        return 1
    reasons = {(p.get("hold") or {}).get("reason") for p in payloads}
    why = "조용한 시간" if "quiet" in reasons else "짧은 시간"
    digest = alert_format.digest_event(payloads, why, ref=uuid.uuid4().hex)
    names, results, attempts = await _deliver(digest, user_cfg, channels, silent=all(m == "silent" for m in modes))
    async with get_session_factory()() as db:
        for r in claimed:
            row = await db.get(NotificationLog, r.id)
            row.delivery_status = "digested"
        db.add(NotificationLog(
            user_id=uid, subject=digest.mail_subject()[:300], message=alert_format.render_plain(digest)[:500],
            channels=_channel_rows(names, results, attempts), kind="digest", ref=digest.ref,
            delivery_status=_status_for(names, results), payload=alert_format.to_payload(digest)))
        await db.commit()
    return len(claimed)


async def flush_held(now: datetime | None = None) -> int:
    """보관 중인 알림 중 풀 때가 된 것을 보낸다(조용한 시간이 끝났거나 묶음 창이 지났다). 보낸 건수를 돌려준다."""
    now = now or datetime.now(alert_format.KST)
    try:
        from sqlalchemy import select
        from app.database.postgres import get_session_factory
        from app.models import NotificationLog
        async with get_session_factory()() as db:
            rows = list((await db.execute(
                select(NotificationLog.id, NotificationLog.user_id, NotificationLog.payload)
                .where(NotificationLog.delivery_status == "held"))).all())
    except Exception as exc:
        logger.warning("보관 알림 조회 실패: %s", _safe_exc(exc))
        return 0
    by_user: dict = {}
    for r in rows:
        if r.user_id is not None:
            by_user.setdefault(r.user_id, []).append(r)
    sent = 0
    for uid, items in by_user.items():
        try:
            cfg = await _load_user_settings(str(uid))
            prefs = alert_prefs.normalize(cfg.get("preferences"))
            ids = [i.id for i in items if alert_prefs.releasable((i.payload or {}).get("hold") or {}, prefs, now)]
            if not ids:
                continue
            claimed = await _claim_held(ids)
            if claimed:
                sent += await _release(uid, cfg, claimed)
        except Exception as exc:
            logger.warning("보관 알림 풀기 실패(uid=%s): %s", uid, _safe_exc(exc))
    return sent


_flusher_task: asyncio.Task | None = None
FLUSH_INTERVAL_SEC = 60


async def _flusher_loop() -> None:
    await asyncio.sleep(10)          # 앱이 켜진 직후 한 번(08시에 꺼져 있었을 수 있다) — 연결이 준비될 시간을 준다
    while True:
        try:
            await flush_held()
        except Exception:
            logger.exception("[alert] 보관 알림 풀기 오류")
        await asyncio.sleep(FLUSH_INTERVAL_SEC)


def start_alert_flusher() -> None:
    global _flusher_task
    if _flusher_task is None or _flusher_task.done():
        _flusher_task = asyncio.create_task(_flusher_loop())


def stop_alert_flusher() -> None:
    global _flusher_task
    if _flusher_task and not _flusher_task.done():
        _flusher_task.cancel()
    _flusher_task = None


async def _claim_event(user_id, kind, ref, subject, message):
    import uuid
    from sqlalchemy.dialects.postgresql import insert
    from app.database.postgres import get_session_factory
    from app.models import NotificationLog
    if not user_id or not kind or not ref or len(kind) > 40 or len(ref) > 64:
        raise ValueError("알림 사건의 사용자·종류·회차가 필요합니다.")
    uid = uuid.UUID(str(user_id))
    async with get_session_factory()() as db:
        result = await db.execute(insert(NotificationLog).values(
            user_id=uid, kind=kind, ref=ref, subject=subject[:300], message=message[:500],
            channels=[], delivery_status="sending").on_conflict_do_nothing(
                constraint="uq_notification_event").returning(NotificationLog.id))
        event_id = result.scalar_one_or_none()
        await db.commit()  # 선점 저장 실패 때 발송하지 않는다.
        return event_id


def _channel_rows(names, results, attempts) -> list[dict]:
    """채널별 전달 결과 줄 — 시도 횟수(`attempts`)를 함께 남긴다(재시도 정책: 몇 번 만에 됐나 · 몇 번 해도 안 됐나)."""
    tries = list(attempts or []) + [1] * max(0, len(names) - len(attempts or []))
    return [{"channel": name, "ok": result is True, "attempts": tries[i]}
            for i, (name, result) in enumerate(zip(names, results))]


async def _finish_event(event_id, names, results, attempts=None, payload=None):
    from app.database.postgres import get_session_factory
    from app.models import NotificationLog
    async with get_session_factory()() as db:
        row = await db.get(NotificationLog, event_id)
        row.channels = _channel_rows(names, results, attempts)
        row.delivery_status = _status_for(names, results)
        if payload is not None:
            row.payload = payload
        await db.commit()


async def _log_dispatch(
    user_id: str | None,
    subject: str,
    message: str,
    channel_names: list[str],
    results: list,
    attempts: list[int] | None = None,
    payload: dict | None = None,
) -> None:
    """발송 시도를 notification_log 테이블에 남긴다 (알림 이력 조회용)."""
    try:
        import uuid
        from app.database.postgres import get_session_factory  # noqa: PLC0415 – lazy import to avoid circular
        from app.models import NotificationLog  # noqa: PLC0415

        resolved_user_id = None
        if user_id:
            try:
                resolved_user_id = uuid.UUID(user_id)
            except ValueError:
                resolved_user_id = None

        session_factory = get_session_factory()
        async with session_factory() as db:
            db.add(NotificationLog(
                user_id=resolved_user_id,
                subject=subject,
                message=message[:500],
                channels=_channel_rows(channel_names, results, attempts),
                payload=payload,
            ))
            await db.commit()
    except Exception as exc:
        # 이력 기록 실패는 알림 발송 자체를 막지 않는다 — 다만 조용히 지나가지 않고 로그에 남긴다(교차검증 설계 알림 정책).
        logger.warning("알림 이력 기록 실패: %s", exc)


# ── 알림 헬퍼 (보통안: 사건 · 이유 · 항목 · 위험 · 다음 행동 · KST 시각 · 모의투자 표시) ──────────────────


def _side_label(side: str) -> str:
    return "매수" if side == "buy" else "매도"


def _qty_price(quantity: int, price: float) -> str:
    return f"{quantity:,}주 × {price:,.0f}원"


async def notify_insufficient_funds(
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    required: float,
    available: float,
    user_id: str | None = None,
) -> None:
    """예수금 부족으로 주문 실패 알림."""
    label = _side_label(side)
    ev = alert_format.AlertEvent(
        kind="insufficient_funds", severity="important", emoji="🚨", title=f"주문 실패 – 예수금 부족 ({symbol})",
        summary=f"{label} {symbol} 주문이 접수되지 않았습니다.",
        fields=[("종목", symbol), ("구분", label), ("수량·단가", _qty_price(quantity, price)),
                ("필요 금액", alert_format.won(required)), ("가용 예수금", alert_format.won(available)),
                ("부족분", alert_format.won(required - available))],
        reason="가용 예수금이 주문에 필요한 금액보다 적습니다.",
        next_action="예수금을 채우거나 수량을 줄여 다시 주문하세요.",
        subject=f"[매매 알림] 주문 실패 – {symbol}",
    )
    await dispatch_event(ev, user_id=user_id)


async def notify_order_placed(
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    broker: str = "",
    user_id: str | None = None,
    *, details: list[tuple[str, str]] | None = None,
) -> None:
    """주문 접수 알림."""
    label = _side_label(side)
    fields = [("종목", symbol), ("구분", label), ("수량·단가", _qty_price(quantity, price)),
              ("총액", alert_format.won(quantity * price))]
    if broker:
        fields.append(("증권사", broker))
    fields.extend(details or [])
    ev = alert_format.AlertEvent(
        kind="order_placed", severity="normal", emoji="📈" if side == "buy" else "📉", title=f"주문 접수 – {label} {symbol}",
        summary="증권사에 주문이 접수되었습니다. 접수는 체결이 아닙니다.", fields=fields,
        risk="체결 전까지는 확정된 거래가 아니며 가격·수량이 달라질 수 있습니다.",
        next_action="체결되면 「체결 확정」 알림으로 알려 드립니다.",
        subject=f"[매매 알림] {label} 주문 접수 – {symbol}",
    )
    await dispatch_event(ev, user_id=user_id)


async def notify_order_filled(
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    environment: str = "paper",
    user_id: str | None = None,
) -> None:
    """실주문 체결 확정 알림 (quant.confirm_fills)."""
    label = _side_label(side)
    env_label = "KIS 모의" if environment == "paper" else "KIS 실전"
    ev = alert_format.AlertEvent(
        kind="order_fill", severity="normal", emoji="✅", title=f"체결 확정 – {label} {symbol} ({env_label})",
        summary=f"{quantity:,}주가 평균 {price:,.0f}원에 체결되었습니다.",
        fields=[("종목", symbol), ("구분", label), ("체결", f"{quantity:,}주 × 평균 {price:,.0f}원"),
                ("총액", alert_format.won(quantity * price)), ("환경", env_label)],
        mock=(environment == "paper"),
        next_action="보유 현황은 모의투자·포트폴리오 화면에서 확인하세요.",
        subject=f"[매매 알림] {label} 체결 확정 – {symbol}",
    )
    await dispatch_event(ev, user_id=user_id)


async def notify_order_error(
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    error: str,
    user_id: str | None = None,
) -> None:
    """주문 오류 알림. `error` 는 증권사·서버가 준 글이라 렌더러가 채널별로 이스케이프한다."""
    label = _side_label(side)
    ev = alert_format.AlertEvent(
        kind="order_error", severity="important", emoji="❌", title=f"주문 오류 – {label} {symbol}",
        summary="주문이 정상 처리되지 않았습니다.",
        fields=[("종목", symbol), ("구분", label), ("수량·단가", _qty_price(quantity, price))],
        reason=str(error)[:300],
        risk="접수 여부가 불명확할 수 있어 같은 주문을 바로 다시 내면 중복될 수 있습니다.",
        next_action="증권사 앱·주문 내역에서 접수 여부를 확인한 뒤 필요하면 다시 주문하세요.",
        subject=f"[매매 알림] 주문 오류 – {symbol}",
    )
    await dispatch_event(ev, user_id=user_id)


async def notify_auto_trade_started(user_id: str | None = None) -> None:
    """자동매매 시작 알림."""
    minutes = max(1, int(settings.QUANT_CYCLE_SEC) // 60)
    ev = alert_format.AlertEvent(
        kind="auto_state", severity="info", emoji="🤖", title="자동매매 시작",
        summary=f"{minutes}분 주기로 퀀트 신호를 분석합니다.", fields=[("분석 주기", f"{minutes}분")],
        next_action="비상 정지나 중지는 자동매매 화면에서 할 수 있습니다.", subject="[매매 알림] 자동매매 시작",
    )
    await dispatch_event(ev, user_id=user_id)


async def notify_auto_trade_stopped(user_id: str | None = None) -> None:
    """자동매매 중지 알림."""
    ev = alert_format.AlertEvent(
        kind="auto_state", severity="info", emoji="⏹", title="자동매매 중지",
        summary="자동매매가 정지되었습니다.", next_action="다시 시작하려면 자동매매 화면에서 켜세요.",
        subject="[매매 알림] 자동매매 중지",
    )
    await dispatch_event(ev, user_id=user_id)


async def notify_auto_trade_executed(
    symbol: str,
    name: str,
    action: str,
    quantity: int,
    price: float,
    reason: str,
    user_id: str | None = None,
    *, details: list[tuple[str, str]] | None = None, risk_note: str = "",
) -> None:
    """자동매매 가상 장부 기록 알림(증권사 체결 아님). `details`(수수료·세금·체결 후 현금 등)는 호출한 쪽이 알면 넘긴다."""
    label = _side_label(action)
    fields = [("종목", f"{name} ({symbol})"), ("수량·단가", _qty_price(quantity, price)),
              ("거래 금액", alert_format.won(quantity * price))] + list(details or [])
    ev = alert_format.AlertEvent(
        kind="auto_fill", severity="normal", emoji="📈" if action == "buy" else "📉",
        title=f"자동매매 {label} 가상 체결 – {name}", summary=f"{name} {quantity:,}주를 가상 장부에 기록했습니다.",
        fields=fields, reason=reason, risk=risk_note, mock=True,
        next_action="앱 가상 장부 기록이며 증권사 체결이 아닙니다. 모의투자 화면에서 보유 현황을 확인하세요.",
        subject=f"[매매 알림] {label} 가상 체결 – {name}",
    )
    await dispatch_event(ev, user_id=user_id)


async def notify_risk_halt(reason: str, day_pnl_pct: float | None = None, user_id: str | None = None) -> None:
    """위험관리 비상 정지 알림 (일손실 한도 초과 등) — 긴급: 조용한 시간에도 바로 보낸다."""
    fields = [("당일 손익", alert_format.pct(day_pnl_pct))] if day_pnl_pct is not None else []
    ev = alert_format.AlertEvent(
        kind="risk_halt", severity="urgent", emoji="🛑", title="[위험관리] 자동매매 비상 정지",
        summary="새 자동 주문이 모두 멈췄습니다.", fields=fields, reason=reason,
        risk="비상 정지 중에는 신호가 나도 주문이 나가지 않습니다.",
        next_action="원인을 확인한 뒤 설정 화면에서 비상 정지를 해제해야 재시작됩니다.",
        subject="[위험관리] 자동매매 비상 정지",
    )
    await dispatch_event(ev, user_id=user_id)


async def notify_risk_skip(symbol: str, name: str, side: str, reason: str, user_id: str | None = None,
                           *, details: list[tuple[str, str]] | None = None) -> None:
    """위험관리 규칙으로 주문을 생략했음을 알린다 (중복 주문·한도 초과). 같은 시간대 여러 건은 묶어서 나간다."""
    label = _side_label(side)
    ev = alert_format.AlertEvent(
        kind="risk_skip", severity="info", emoji="⚠️", title=f"주문 생략 – {label} {name}",
        summary=f"{name} ({symbol}) {label} 주문을 위험관리 규칙으로 건너뛰었습니다.",
        fields=[("종목", f"{name} ({symbol})"), ("구분", label)] + list(details or []), reason=reason,
        subject=f"[위험관리] {label} 주문 생략 – {name}", group_key="risk_skip",
    )
    await dispatch_event(ev, user_id=user_id)
