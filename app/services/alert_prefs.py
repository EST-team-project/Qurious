"""알림 사건별 설정 · 조용한 시간 · 묶음 규칙 — DB 없는 순수 함수 (2026-11-01 S183).

설정(`notification_settings.preferences`, JSONB) 모양:
    {"events": {"risk_skip": "silent", "order_fill": "on", ...},
     "quiet":  {"enabled": false, "start": "21:00", "end": "08:00"}}

모드는 on / silent / off 세 단계뿐이다(Freqtrade 와 같은 방식).
  on     그대로 보낸다.
  silent 소리·진동 없이 보낸다 — Telegram(disable_notification) · Discord(SUPPRESS_NOTIFICATIONS) 만 지원.
         Slack · 이메일은 그대로 보내고, 카카오 알림톡 · SMS 는 건너뛴다(건당 요금 · 소리가 나는 채널이라).
  off    보내지 않는다. 단 「끌 수 없는」 사건(긴급)은 off 를 거부한다.

조용한 시간(기본 꺼짐, 켜면 기본 21~08시 KST)에는 긴급이 아닌 알림을 보관했다가 끝나면 요약 1건으로 보낸다.
같은 사건이 몰려 오는 종류(묶음 대상)는 짧은 창(`GROUP_WINDOW_SEC`) 동안 보관했다가 한 건으로 합친다.
보관과 몰림 합치기는 같은 장치(보관 행)이고, 풀어 주는 조건만 둘이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.services.alert_format import KST

MODES = ("on", "silent", "off")
DEFAULT_QUIET = {"enabled": False, "start": "21:00", "end": "08:00"}
#: 묶음 대상 사건을 모아 두는 시간(초) — 이 창이 지나면 한 건(또는 요약)으로 나간다
GROUP_WINDOW_SEC = 120


@dataclass(frozen=True)
class EventDef:
    kind: str
    label: str
    severity: str          # urgent | important | normal | info
    default_mode: str      # on | silent
    groupable: bool = False
    lockable: bool = True  # False 면 off 로 끌 수 없다


#: 설정 화면 표의 순서와 같다
EVENT_DEFS: tuple[EventDef, ...] = (
    EventDef("risk_halt", "비상 정지 (일손실 한도 · 수동)", "urgent", "on", lockable=False),
    EventDef("order_error", "주문 오류 · 거절", "important", "on"),
    EventDef("insufficient_funds", "예수금 부족", "important", "on"),
    EventDef("reconcile", "정합성 불일치", "important", "on"),
    EventDef("run_failed", "자동매매 회차 중단 · 실패", "important", "on"),
    EventDef("order_fill", "체결 확정 (실주문)", "normal", "on"),
    EventDef("order_placed", "주문 접수", "normal", "on"),
    EventDef("auto_fill", "자동매매 가상 체결", "normal", "on"),
    EventDef("tv_signal", "TradingView 신호", "normal", "on"),   # 매매 신호는 지연시키지 않는다(묶음 대상 아님)
    EventDef("risk_skip", "위험관리로 주문 생략", "info", "silent", groupable=True),
    EventDef("auto_state", "자동매매 시작 · 중지", "info", "silent"),
)
_DEFS = {d.kind: d for d in EVENT_DEFS}

#: 설정에 나오지 않는(항상 보내는) 종류 — 수집 회차 보고(`collect_report`)는 운영자의 `.env` 채널로 가는 알림이라 사용자 설정 표에 없다
ALWAYS_ON = {"test", "digest", "legacy"}

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def event_def(kind: str) -> EventDef | None:
    return _DEFS.get(kind)


def default_events() -> dict[str, str]:
    return {d.kind: d.default_mode for d in EVENT_DEFS}


def normalize(raw: dict | None) -> dict:
    """저장된 설정을 읽어 모르는 키는 버리고 빠진 값은 기본값으로 채운다(읽기용 — 오류를 내지 않는다)."""
    raw = raw if isinstance(raw, dict) else {}
    events = default_events()
    for kind, mode in (raw.get("events") or {}).items():
        d = _DEFS.get(kind)
        if d and mode in MODES and (mode != "off" or d.lockable):
            events[kind] = mode
    quiet = dict(DEFAULT_QUIET)
    q = raw.get("quiet")
    if isinstance(q, dict):
        quiet["enabled"] = bool(q.get("enabled", False))
        for key in ("start", "end"):
            if isinstance(q.get(key), str) and _HHMM.match(q[key]):
                quiet[key] = q[key]
    # 자기 디스코드 주소가 없을 때 서버 공용 채널로 받을지(2026-11-01 · 기본 꺼짐 — 개인 알림이 팀 채널로 새지 않게)
    return {"events": events, "quiet": quiet, "discord_use_shared": raw.get("discord_use_shared") is True}


def validate(raw: dict) -> dict:
    """저장 요청을 검사한다 — 모르는 사건 · 모르는 모드 · 끌 수 없는 사건을 끄려는 요청 · 시각 모양이 틀리면 ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("preferences 는 객체여야 합니다.")
    out_events: dict[str, str] = {}
    for kind, mode in (raw.get("events") or {}).items():
        d = _DEFS.get(kind)
        if d is None:
            raise ValueError(f"알 수 없는 알림 사건: {kind}")
        if mode not in MODES:
            raise ValueError(f"{d.label}: 모드는 on / silent / off 중 하나여야 합니다.")
        if mode == "off" and not d.lockable:
            raise ValueError(f"{d.label} 알림은 안전을 위해 끌 수 없습니다(조용히 받기는 가능).")
        out_events[kind] = mode
    q = raw.get("quiet") or {}
    quiet = dict(DEFAULT_QUIET)
    if "enabled" in q:
        if not isinstance(q["enabled"], bool):
            raise ValueError("조용한 시간 사용 여부는 true / false 여야 합니다.")
        quiet["enabled"] = q["enabled"]
    for key, label in (("start", "시작"), ("end", "끝")):
        if key in q:
            if not (isinstance(q[key], str) and _HHMM.match(q[key])):
                raise ValueError(f"조용한 시간 {label} 시각은 HH:MM 형식이어야 합니다.")
            quiet[key] = q[key]
    if quiet["enabled"] and quiet["start"] == quiet["end"]:
        raise ValueError("조용한 시간의 시작과 끝이 같으면 하루 종일이 되어 지정할 수 없습니다.")
    shared = raw.get("discord_use_shared", False)
    if not isinstance(shared, bool):
        raise ValueError("공용 디스코드 채널로 받기 여부는 true / false 여야 합니다.")
    return normalize({"events": out_events, "quiet": quiet, "discord_use_shared": shared})


def effective_mode(prefs: dict, kind: str) -> str:
    """사건 종류의 현재 모드. 설정에 없는 종류(시험 · 묶음 요약 · 옛 호출)는 항상 on."""
    if kind in ALWAYS_ON or kind not in _DEFS:
        return "on"
    return (prefs.get("events") or {}).get(kind) or _DEFS[kind].default_mode


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_quiet(prefs: dict, now: datetime) -> bool:
    """`now`(시계 대신 인자로 받아 자정을 넘는 구간도 시험할 수 있다)가 조용한 시간 안인가."""
    q = prefs.get("quiet") or {}
    if not q.get("enabled"):
        return False
    t = now.astimezone(KST)
    cur = t.hour * 60 + t.minute
    start, end = _minutes(q["start"]), _minutes(q["end"])
    if start == end:
        return False
    return start <= cur < end if start < end else (cur >= start or cur < end)


def hold_plan(kind: str, severity: str, prefs: dict, now: datetime) -> dict | None:
    """바로 보낼지(None) 보관할지를 정한다. 보관이면 `{"reason": "quiet"|"group", "release_at": ISO 또는 None}`.
    긴급은 언제나 바로. 조용한 시간이 묶음보다 앞선다(끝나면 한꺼번에 풀리므로)."""
    if severity == "urgent" or kind in ALWAYS_ON:
        return None
    if in_quiet(prefs, now):
        return {"reason": "quiet", "release_at": None}
    d = _DEFS.get(kind)
    if d and d.groupable:
        return {"reason": "group", "release_at": (now + timedelta(seconds=GROUP_WINDOW_SEC)).isoformat()}
    return None


def releasable(hold: dict, prefs: dict, now: datetime) -> bool:
    """보관 행을 지금 풀어도 되는가 — 조용한 시간 안이면 (묶음 창이 지났어도) 기다린다."""
    if in_quiet(prefs, now):
        return False
    if hold.get("reason") == "group":
        try:
            return datetime.fromisoformat(hold["release_at"]) <= now
        except (KeyError, TypeError, ValueError):
            return True      # 풀 시각이 깨졌으면 붙잡고 있지 않는다
    return True
