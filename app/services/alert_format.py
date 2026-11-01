"""보고식 알림 — 사건 하나(`AlertEvent`)를 채널마다 알맞은 모양으로 꾸미는 순수 함수 모음 (2026-11-01 S183).

DB · 네트워크를 쓰지 않는다(시험이 쉽다). 보내는 일은 `app/services/notification.py` 의 `dispatch_event` 가 한다.

「보통안」 한 건의 8요소: 사건(제목) · 이유 · 금액/수량(항목) · 결과(요약) · 위험 · 다음 행동 · KST 시각 · 출처/모의투자 표시.
채널 한도(공식 문서 기준)와 이스케이프:
  Telegram  본문 4,096자 · HTML 모드라 값의 `<` `>` `&` 를 이스케이프(틀의 태그만 살림)
  Discord   embed 필드 25 · 제목 256 · 설명 4,096 · 필드값 1,024 · embed 합계 6,000자
  Slack     blocks 50 · 헤더 150자 · 섹션 글 3,000자
  이메일     HTML 표 + 텍스트 대체 본문(multipart/alternative)
  SMS       한 줄(약 80자)
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

#: KST 는 서머타임이 없어 고정 오프셋으로 충분하다(tzdata 가 없는 환경에서도 동작).
KST = timezone(timedelta(hours=9))

SEVERITIES = ("urgent", "important", "normal", "info")
_SEV_EMOJI = {"urgent": "🛑", "important": "⚠️", "normal": "✅", "info": "ℹ️"}
_SEV_LABEL = {"urgent": "긴급", "important": "중요", "normal": "일반", "info": "참고"}
_SEV_COLOR = {"urgent": 0xE74C3C, "important": 0xF39C12, "normal": 0x3498DB, "info": 0x95A5A6}

_FOOTER_MOCK = "모의투자(가상 자금) 기록이며 투자 권유가 아닙니다."
_FOOTER_REAL = "Qurious 자동 알림 · 투자 권유가 아닙니다."

#: 저장용 payload(JSONB) 크기 상한 — 넘으면 항목을 줄인다
PAYLOAD_MAX_BYTES = 8192


@dataclass
class AlertEvent:
    """알림 사건 하나. 값은 모두 **표시용 문자열**로 미리 만들어 넘긴다(금액 `won()` · 비율 `pct()` 보조 함수 사용)."""

    kind: str
    title: str
    summary: str = ""
    severity: str = "normal"
    fields: list[tuple[str, str]] = field(default_factory=list)
    reason: str = ""
    risk: str = ""
    next_action: str = ""
    mock: bool = False
    emoji: str = ""
    ref: str | None = None
    group_key: str | None = None
    ts: datetime | None = None
    subject: str = ""
    #: 옛 호출(`dispatch(message, html_message)`) 호환 — 채워져 있으면 렌더러가 이 글을 그대로 쓴다
    legacy_plain: str = ""
    legacy_html: str = ""

    def stamp(self) -> datetime:
        return (self.ts or datetime.now(KST)).astimezone(KST)

    def stamp_text(self) -> str:
        return self.stamp().strftime("%Y-%m-%d %H:%M:%S KST")

    def footer(self) -> str:
        return _FOOTER_MOCK if self.mock else _FOOTER_REAL

    def icon(self) -> str:
        return self.emoji or _SEV_EMOJI.get(self.severity, "✅")

    def mail_subject(self) -> str:
        return self.subject or f"[매매 알림] {self.title}"


# ── 표시 보조 ───────────────────────────────────────────────────────────────


def won(value: float | int | None, digits: int = 0) -> str:
    """원 단위 금액 — 없으면 `-`."""
    if value is None:
        return "-"
    return f"{value:,.{digits}f}원"


def pct(value: float | None, digits: int = 2, signed: bool = True) -> str:
    if value is None:
        return "-"
    return f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"


def _cut(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _esc(text: object) -> str:
    return html.escape(str(text), quote=False)


_TG_MAX = 4096


def _esc_fit(text: str, limit: int = _TG_MAX) -> str:
    """이스케이프한 결과가 `limit` 자 이하가 되도록 **이스케이프 전의 글**을 줄인다(줄임표 포함)."""
    cut = len(text)
    while cut > 0:
        s = text if cut == len(text) else text[: cut - 1] + "…"
        out = _esc(s)
        if len(out) <= limit:
            return out
        cut = int(cut * 0.9) if cut > 20 else cut - 1
    return ""


def _detail_lines(ev: AlertEvent) -> list[tuple[str, str]]:
    out = []
    if ev.reason:
        out.append(("이유", ev.reason))
    if ev.risk:
        out.append(("위험", ev.risk))
    if ev.next_action:
        out.append(("다음 행동", ev.next_action))
    return out


# ── 렌더러 ──────────────────────────────────────────────────────────────────


def render_plain(ev: AlertEvent) -> str:
    """일반 텍스트(카카오 · 이력 · 대체 본문)."""
    if ev.legacy_plain:
        return ev.legacy_plain
    lines = [f"{ev.icon()} [{ev.title}]"]
    if ev.summary:
        lines.append(ev.summary)
    lines += [f"- {k}: {v}" for k, v in ev.fields]
    lines += [f"{k}: {v}" for k, v in _detail_lines(ev)]
    lines.append(f"{ev.stamp_text()} · {ev.footer()}")
    return "\n".join(lines)


def render_sms(ev: AlertEvent, limit: int = 80) -> str:
    """SMS 는 한 줄 요약만 — 보고식 본문은 어울리지 않는다."""
    if ev.legacy_plain:
        return _cut(ev.legacy_plain.replace("\n", " "), limit)
    text = f"[{ev.title}] {ev.summary}".strip() if ev.summary else f"[{ev.title}]"
    return _cut(text.replace("\n", " "), limit)


def render_telegram(ev: AlertEvent) -> str:
    """텔레그램 HTML — **값은 전부 이스케이프**, 틀의 태그만 살린다(외부 글 `<` `&` 가 400 오류를 내지 않게)."""
    if ev.legacy_html and len(ev.legacy_html) <= _TG_MAX:
        return ev.legacy_html
    if ev.legacy_plain:
        # HTML 이 한도를 넘으면 태그를 버리고 평문을 **이스케이프 전에** 줄인다(이스케이프한 글을 자르면 `&amp;` · 태그가 반으로 갈린다)
        return _esc_fit(ev.legacy_plain)
    head = [f"{_esc(ev.icon())} <b>{_esc(ev.title)}</b>"]
    if ev.summary:
        head.append(_esc(ev.summary))
    field_lines = [f"<b>{_esc(k)}</b>: {_esc(v)}" for k, v in ev.fields]
    details = _detail_lines(ev)
    foot = ["", f"<i>{_esc(ev.stamp_text())} · {_esc(ev.footer())}</i>"]

    def compose(n_fields: int) -> str:
        out = list(head)
        if n_fields:
            out += [""] + field_lines[:n_fields]
        if details:
            block = "\n".join(f"<b>{_esc(k)}</b>: {_esc(v)}" for k, v in details)
            raw_len = sum(len(k) + len(v) + 2 for k, v in details)
            # 길면 접어서 보여 준다(텔레그램만 공식 지원하는 접기)
            out += ["", f"<blockquote expandable>{block}</blockquote>" if raw_len > 400 else block]
        return "\n".join(out + foot)

    # 한도를 넘으면 **항목을 하나씩 뺀다**(글을 중간에서 자르면 태그 · 이스케이프가 깨져 텔레그램이 400 을 낸다)
    n = len(field_lines)
    text = compose(n)
    while len(text) > _TG_MAX and n > 0:
        n -= 1
        text = compose(n)
    if len(text) > _TG_MAX:                      # 항목을 다 빼고도 길면(이유 · 위험이 아주 긴 경우) 평문으로 줄여 보낸다
        return _esc_fit(render_plain(ev))
    return text


def render_discord(ev: AlertEvent) -> dict:
    """디스코드 embed 한 개. 합계 6,000자를 넘지 않게 필드를 줄인다."""
    if ev.legacy_plain:
        return {"content": _cut(ev.legacy_plain, 2000)}
    embed_fields = []
    for k, v in ev.fields[:25]:
        embed_fields.append({"name": _cut(k, 256) or "-", "value": _cut(v, 1024) or "-", "inline": len(str(v)) <= 24})
    for k, v in _detail_lines(ev):
        if len(embed_fields) < 25:
            embed_fields.append({"name": k, "value": _cut(v, 1024), "inline": False})
    embed = {
        "title": _cut(f"{ev.icon()} {ev.title}", 256),
        "description": _cut(ev.summary, 4096),
        "color": _SEV_COLOR.get(ev.severity, _SEV_COLOR["normal"]),
        "fields": embed_fields,
        "footer": {"text": _cut(f"{_SEV_LABEL.get(ev.severity, '')} · {ev.stamp_text()} · {ev.footer()}", 2048)},
    }
    total = lambda e: (len(e["title"]) + len(e["description"]) + len(e["footer"]["text"])  # noqa: E731
                       + sum(len(f["name"]) + len(f["value"]) for f in e["fields"]))
    while total(embed) > 6000 and embed["fields"]:
        embed["fields"].pop()
    return {"embeds": [embed]}


def render_slack(ev: AlertEvent) -> tuple[str, list[dict]]:
    """슬랙 — (대체 글, blocks). 대체 글은 알림 미리보기에 쓰인다."""
    if ev.legacy_plain:
        return ev.legacy_plain, []
    fallback = _cut(f"{ev.icon()} {ev.title} — {ev.summary}" if ev.summary else f"{ev.icon()} {ev.title}", 300)
    blocks: list[dict] = [{"type": "header", "text": {"type": "plain_text", "text": _cut(f"{ev.icon()} {ev.title}", 150)}}]
    if ev.summary:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _cut(_slack_esc(ev.summary), 3000)}})
    if ev.fields:
        flds = [{"type": "mrkdwn", "text": _cut(f"*{_slack_esc(k)}*\n{_slack_esc(v)}", 2000)} for k, v in ev.fields[:10]]
        blocks.append({"type": "section", "fields": flds})
    details = _detail_lines(ev)
    if details:
        txt = "\n".join(f"*{k}*: {_slack_esc(v)}" for k, v in details)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _cut(txt, 3000)}})
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": _cut(f"{_SEV_LABEL.get(ev.severity, '')} · {ev.stamp_text()} · {ev.footer()}", 2000)}]})
    return fallback, blocks[:50]


def _slack_esc(text: object) -> str:
    """슬랙 mrkdwn 에서 `&` `<` `>` 만 이스케이프한다(공식 규칙)."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_email(ev: AlertEvent) -> tuple[str, str, str]:
    """이메일 — (제목, HTML, 텍스트 대체 본문)."""
    subject = ev.mail_subject()
    text = render_plain(ev)
    if ev.legacy_html:
        return subject, ev.legacy_html, text
    if ev.legacy_plain:
        return subject, "<pre style=\"font-family:inherit\">" + _esc(ev.legacy_plain) + "</pre>", text
    color = "#%06x" % _SEV_COLOR.get(ev.severity, _SEV_COLOR["normal"])
    rows = "".join(
        f"<tr><th align=\"left\" style=\"padding:4px 12px 4px 0;color:#555;white-space:nowrap\">{_esc(k)}</th>"
        f"<td style=\"padding:4px 0\">{_esc(v)}</td></tr>"
        for k, v in list(ev.fields) + _detail_lines(ev)
    )
    body = (
        "<div style=\"font-family:'Malgun Gothic',Arial,sans-serif;font-size:14px;color:#222;max-width:560px\">"
        f"<div style=\"border-left:4px solid {color};padding:6px 12px;margin-bottom:10px\">"
        f"<div style=\"font-size:16px;font-weight:bold\">{_esc(ev.icon())} {_esc(ev.title)}</div>"
        f"<div style=\"color:#555\">{_esc(_SEV_LABEL.get(ev.severity, ''))}</div></div>"
        + (f"<p>{_esc(ev.summary)}</p>" if ev.summary else "")
        + (f"<table style=\"border-collapse:collapse\">{rows}</table>" if rows else "")
        + f"<p style=\"color:#888;font-size:12px;margin-top:14px\">{_esc(ev.stamp_text())} · {_esc(ev.footer())}</p></div>"
    )
    return subject, body, text


# ── 저장용 payload · 묶음 요약 ──────────────────────────────────────────────


def to_payload(ev: AlertEvent) -> dict:
    """알림 이력(JSONB)에 저장할 보고 원본. 웹훅 주소 · 토큰 · 계좌번호는 애초에 사건에 넣지 않는다. 8KB 를 넘으면 항목을 줄인다."""
    import json

    data = {
        "kind": ev.kind, "severity": ev.severity, "title": _cut(ev.title, 200), "summary": _cut(ev.summary, 600),
        "fields": [[_cut(k, 60), _cut(v, 300)] for k, v in ev.fields[:25]],
        "reason": _cut(ev.reason, 600), "risk": _cut(ev.risk, 600), "next_action": _cut(ev.next_action, 600),
        "mock": bool(ev.mock), "ts": ev.stamp().isoformat(), "ref": ev.ref, "group_key": ev.group_key,
        "subject": _cut(ev.subject, 300),
    }
    if ev.legacy_plain:
        data["legacy_plain"] = _cut(ev.legacy_plain, 1500)
    if ev.legacy_html:
        data["legacy_html"] = _cut(ev.legacy_html, 2500)
    while len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > PAYLOAD_MAX_BYTES and data["fields"]:
        data["fields"].pop()
    return data


def from_payload(data: dict) -> AlertEvent:
    """저장한 payload 로 사건을 되살린다(보관했다 풀 때)."""
    ts = None
    if data.get("ts"):
        try:
            ts = datetime.fromisoformat(data["ts"])
        except ValueError:
            ts = None
    return AlertEvent(
        kind=data.get("kind", ""), title=data.get("title", ""), summary=data.get("summary", ""),
        severity=data.get("severity", "normal"), fields=[(str(a), str(b)) for a, b in data.get("fields", [])],
        reason=data.get("reason", ""), risk=data.get("risk", ""), next_action=data.get("next_action", ""),
        mock=bool(data.get("mock")), ref=data.get("ref"), group_key=data.get("group_key"), ts=ts,
        subject=data.get("subject", ""), legacy_plain=data.get("legacy_plain", ""), legacy_html=data.get("legacy_html", ""),
    )


def legacy_event(message: str, html_message: str = "", subject: str = "", kind: str = "legacy",
                 severity: str = "normal", ref: str | None = None) -> AlertEvent:
    """옛 `dispatch(message, html_message, subject)` 호출을 사건으로 감싼다 — 글은 그대로 보낸다."""
    first = (message.strip().splitlines() or [""])[0]
    return AlertEvent(kind=kind, title=_cut(first, 80), severity=severity, ref=ref, subject=subject,
                      legacy_plain=message, legacy_html=html_message)


def digest_event(items: list[dict], why: str, ref: str, max_lines: int = 15) -> AlertEvent:
    """보관했던 알림 여러 건을 요약 1건으로. `items` 는 payload 사전 목록(시각 오름차순)."""
    shown = items[:max_lines]
    fields: list[tuple[str, str]] = []
    for it in shown:
        stamp = ""
        if it.get("ts"):
            try:
                stamp = datetime.fromisoformat(it["ts"]).astimezone(KST).strftime("%H:%M")
            except ValueError:
                stamp = ""
        line = it.get("title") or it.get("kind") or "알림"
        if it.get("summary"):
            line += f" — {it['summary']}"
        fields.append((stamp or "-", _cut(line, 200)))
    more = len(items) - len(shown)
    severity = "important" if any(i.get("severity") in ("urgent", "important") for i in items) else "info"
    return AlertEvent(
        kind="digest", title=f"알림 묶음 {len(items)}건", severity=severity,
        summary=f"{why} 동안 쌓인 알림입니다." + (f" (처음 {len(shown)}건만 표시, 외 {more}건)" if more > 0 else ""),
        fields=fields, ref=ref, mock=any(i.get("mock") for i in items), subject=f"[매매 알림] 알림 묶음 {len(items)}건",
    )
