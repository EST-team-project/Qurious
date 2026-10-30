"""TC-NH — 알림 이력에 전달 결과를 보인다 (할 일 ①-14 · 2026-10-30)

①-14 완료 기준의 「실패는 기록 · 알림 설정 화면에서 이력이 보인다」. 전달 결과(`delivery_status`)는 DB 에 이미 있었으나 API · 화면에 안 나왔다.
1. 이력 API 가 결과 · 글 · 종류를 싣고, 모르는 결과는 「확인 필요」 로 보이며(정상으로 꾸미지 않는다) 옛 필드는 그대로다. (TC-NH-01)
2. 글 표가 서비스가 쓰는 결과 이름을 모두 덮는다(서비스에 새 결과가 생기면 이 시험이 알린다). (TC-NH-02)
3. 화면은 서버 글을 그대로 보이고 실패 · 결과 불명을 빨강으로 보인다. (TC-NH-03)
"""
from __future__ import annotations

import asyncio
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routes import notification as route  # noqa: E402


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.rows))


def _row(status, **kw):
    base = dict(subject="[TradingView] 매수 신호 – 005930", message="m", channels=[{"channel": "email", "ok": status == "delivered"}],
                created_at=datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc), kind="tradingview_signal", delivery_status=status)
    base.update(kw)
    return SimpleNamespace(**base)


def _history(rows):
    return asyncio.run(route.notification_history(limit=50, user={"id": str(uuid.uuid4())}, db=_FakeDB(rows)))


def test_history_carries_delivery_result_and_keeps_old_fields():
    """TC-NH-01 · 결과 · 종류가 실리고 옛 칸(subject · message · channels · created_at)은 그대로 · 모르는 결과는 「확인 필요」."""
    out = _history([_row("delivered"), _row("failed"), _row("partial"), _row("sending"), _row("no_channels"), _row("legacy"), _row("brand_new")])
    labels = [e["status_label"] for e in out["events"]]
    assert labels == ["전달됨", "전달 실패", "일부만 전달", "결과 불명 · 자동 재발송 안 함", "보낼 채널 없음", "이전 기록", "확인 필요"]
    first = out["events"][0]
    assert {"subject", "message", "channels", "created_at"} <= set(first) and first["kind"] == "tradingview_signal"
    assert first["delivery_status"] == "delivered" and out["count"] == 7
    assert "확인 필요" == out["events"][-1]["status_label"] != route.DELIVERY_LABELS["delivered"]
    assert _history([])["events"] == [] and _history([])["count"] == 0


def test_label_table_covers_every_status_the_service_writes():
    """TC-NH-02 · 서비스(`notification.py`)가 쓰는 전달 결과 이름을 글 표가 모두 안다 — 새 결과가 생기면 이 시험이 알린다."""
    svc = (ROOT / "app" / "services" / "notification.py").read_text(encoding="utf-8")
    written = set(re.findall(r'delivery_status\s*=\s*\(?\s*"([a-z_]+)"', svc)) | set(re.findall(r'else "([a-z_]+)"', svc)) \
        | set(re.findall(r'"(no_channels|delivered|failed|partial)"', svc)) | set(re.findall(r'delivery_status="([a-z_]+)"', svc))
    model = (ROOT / "app" / "models" / "misc.py").read_text(encoding="utf-8")
    written |= set(re.findall(r'default="(legacy)"', model))
    assert {"sending", "delivered", "failed", "partial", "no_channels", "legacy"} <= written, written
    missing = written - set(route.DELIVERY_LABELS)
    assert not missing, f"글 표에 없는 전달 결과: {sorted(missing)}"


def test_screen_shows_server_label_and_marks_failures_red():
    """TC-NH-03 · 화면은 서버가 정한 글을 그대로 보이고(다시 계산하지 않음) 실패 · 결과 불명을 빨강으로 보인다."""
    js = (ROOT / "public" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "ev.status_label" in js and '["failed", "sending"].includes(ev.delivery_status)' in js and "var(--red)" in js
