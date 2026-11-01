"""일일 수집 회차 보고 알림 (2026-11-01 S183 · 사용자 요청 「일일 수집 회차 보고」).

회차 하나가 끝나면 성공/실패 단계 · 소요 시간 · 자료 최신일 · DART 호출을 **한 번** `.env` 기본 채널로 알린다.
- 사용자가 없는 알림이다(`user_id=None`) → 설정 화면의 사건별 설정과 무관하게 `.env` 채널로 간다.
  앱 DB 가 꺼진 바로 그때가 보고가 가장 필요할 때라 `kind/ref` 선점(DB)을 쓰지 않는다. 이력 저장은 실패해도 삼킨다.
- **알림이 실패해도 회차는 실패하지 않는다** — 모든 예외를 삼키고 한 줄만 돌려준다(러너가 로그에 적는다).
- 예약 작업(pythonw)에서도 import 되도록 앱 모듈은 함수 안에서 늦게 가져온다.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

SEND_TIMEOUT_SEC = 90

#: 도커 앱과 같은 설정 파일 — 알림 채널 값이 들어 있다. 시험은 이 경로를 없는 파일로 바꾼다(conftest).
DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"
#: `.env` 에서 빌려 올 알림 채널 칸 — DB 주소 같은 나머지 설정은 빌리지 않는다
CHANNEL_KEYS = (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SLACK_WEBHOOK_URL", "DISCORD_WEBHOOK_URL",
    "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_TO",
    "COOLSMS_API_KEY", "COOLSMS_API_SECRET", "KAKAO_SENDER_KEY", "KAKAO_PHONE", "SMS_FROM", "SMS_TO",
)


def fill_channels_from_dotenv(settings, path: Path) -> list:
    """예약 작업(pythonw)에는 `ENV_FILE` 이 없어 앱 설정이 `.env.dev` 를 읽는다(2026-11-01 S184 확인 — 거기에는 알림 채널이 비어 있어
    수집 보고가 어느 채널로도 가지 않을 뻔했다). 알림 채널은 도커 앱과 같은 `.env` 에 있으므로, **비어 있는 채널 칸만** `.env` 에서 채운다.
    돌려주는 것은 채운 칸의 이름들(값은 돌려주지 않는다)."""
    if not path or not path.exists():
        return []
    filled = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key in CHANNEL_KEYS and value and not getattr(settings, key, ""):
            setattr(settings, key, value)
            filled.append(key)
    return filled


def _fmt(iso: Optional[str]) -> str:
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(iso).strftime("%m-%d %H:%M:%S")
    except ValueError:
        return str(iso)


def _minutes(start: Optional[str], end: Optional[str]) -> str:
    try:
        sec = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return "-"
    return f"{sec / 60:.1f}분"


def build_event(state: dict):
    """회차 결과(`LAST_PATH` 에 쓰는 사전)로 알림 사건을 만든다 — 순수 함수(시험 대상)."""
    from app.services.alert_format import AlertEvent

    steps = state.get("steps") or []
    failed = [s for s in steps if s.get("rc") not in (None, 0)]
    ran = [s for s in steps if s.get("rc") is not None]
    ok_count = len(ran) - len(failed)
    ok = bool(state.get("ok"))
    before, after = state.get("before") or {}, state.get("after") or {}

    fields = [
        ("시작 → 끝", f"{_fmt(state.get('started_at'))} → {_fmt(state.get('finished_at'))} (KST)"),
        ("소요", _minutes(state.get("started_at"), state.get("finished_at"))),
        ("단계", f"성공 {ok_count} · 실패 {len(failed)} (전체 {len(steps)})"),
    ]
    for label, key in (("시세 최신일", "price_max"), ("수정주가 최신일", "adjusted_max"),
                       ("TR 최신일", "tr_max"), ("벤치마크 최신일", "benchmark_max")):
        if after.get(key) is not None:
            old, new = before.get(key), after.get(key)
            fields.append((label, f"{old} → {new}" if old and old != new else f"{new}" + (" (변동 없음)" if old == new else "")))
    if state.get("dart_calls") is not None:
        fields.append(("DART 호출", f"{state.get('dart_calls')} / {state.get('dart_budget')}"))

    reason = ""
    if failed:
        reason = " · ".join(f"{s.get('name')}: {s.get('error') or '종료코드 ' + str(s.get('rc'))}" for s in failed[:5])
        if len(failed) > 5:
            reason += f" 외 {len(failed) - 5}단계"
    if state.get("stopped"):
        reason = f"중단: {state['stopped']}" + (f" / {reason}" if reason else "")

    if ok:
        title, summary, severity = "일일 수집 회차 완료", f"{ok_count}단계가 모두 성공했습니다.", "info"
        next_action = ""
    else:
        title, summary, severity = "일일 수집 회차 — 실패 단계 있음", f"{len(failed)}단계가 실패했습니다.", "important"
        next_action = "데이터 관제 화면 또는 회차 로그에서 실패 단계를 확인하고, 필요하면 수동으로 다시 수집하세요."
    return AlertEvent(
        kind="collect_report", severity=severity, title=title, summary=summary, fields=fields,
        reason=reason, next_action=next_action, subject=f"[수집] {title}",
        risk="" if ok else "자료가 최신이 아니면 신호·분석 화면의 기준일이 하루 이상 늦을 수 있습니다.",
    )


def send_round_report(state: dict) -> str:
    """보고를 보낸다. 반환은 러너 로그에 적을 한 줄(성공/건너뜀/실패 사유). 예외를 밖으로 내지 않는다."""
    try:
        from app.config import settings
        from app.services import notification

        fill_channels_from_dotenv(settings, DOTENV_PATH)   # `.env.dev` 만 읽는 예약 작업에 채널 값을 채운다
        # 환경 변수가 있으면 그것이 우선, 없으면 `.env` 의 설정(`settings.COLLECT_REPORT_NOTIFY`)
        env = os.environ.get("COLLECT_REPORT_NOTIFY")
        on = settings.COLLECT_REPORT_NOTIFY if env is None else env.strip().lower() not in ("0", "false", "no", "off")
        if not on:
            return "수집 보고 알림 꺼짐(COLLECT_REPORT_NOTIFY)"

        ev = build_event(state)
        asyncio.run(asyncio.wait_for(notification.dispatch_event(ev, user_id=None), SEND_TIMEOUT_SEC))
        channels = notification._default_channels()
        return f"수집 보고 알림 전송 시도 · 채널 {', '.join(channels) if channels else '없음(.env 에 채널 미설정)'}"
    except Exception as exc:                       # 알림 장애가 회차를 실패로 만들면 안 된다
        return f"🟡 수집 보고 알림 실패(회차에는 영향 없음): {type(exc).__name__}"
