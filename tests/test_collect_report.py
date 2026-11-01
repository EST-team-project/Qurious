"""TC-CRN — 일일 수집 회차 보고 알림. 알림이 실패해도 회차는 실패하지 않아야 한다."""
import asyncio

from scripts import collect_report as cr

OK_STATE = {
    "started_at": "2026-11-02T12:30:00", "finished_at": "2026-11-02T13:12:36", "ok": True,
    "steps": [{"name": "price", "rc": 0}, {"name": "dart", "rc": 0}, {"name": "upload", "rc": 0}],
    "before": {"price_max": "2026-10-30", "adjusted_max": "2026-10-30"},
    "after": {"price_max": "2026-11-02", "adjusted_max": "2026-10-30", "tr_max": "2026-11-02"},
    "dart_calls": 120, "dart_budget": 18000,
}
FAIL_STATE = {**OK_STATE, "ok": False, "stopped": "price 종료코드 1",
              "steps": [{"name": "price", "rc": 1, "error": "연결 시간 초과"}, {"name": "dart", "rc": None}]}


def test_cr01_ok_report_has_the_numbers():
    ev = cr.build_event(OK_STATE)
    assert ev.kind == "collect_report" and ev.severity == "info" and "완료" in ev.title
    f = dict(ev.fields)
    assert f["소요"] == "42.6분" and f["단계"] == "성공 3 · 실패 0 (전체 3)"
    assert f["시세 최신일"] == "2026-10-30 → 2026-11-02"
    assert f["수정주가 최신일"].endswith("(변동 없음)") and "DART 호출" in f
    assert ev.reason == "" and ev.next_action == ""


def test_cr02_failed_report_names_failed_steps():
    ev = cr.build_event(FAIL_STATE)
    assert ev.severity == "important" and "실패 단계 있음" in ev.title
    assert "price: 연결 시간 초과" in ev.reason and "중단: price 종료코드 1" in ev.reason
    assert ev.next_action and ev.risk


def test_cr03_send_swallows_every_error(monkeypatch):
    from app.services import notification
    monkeypatch.setenv("COLLECT_REPORT_NOTIFY", "true")      # 시험 기본은 꺼짐(conftest) — 켜고 가짜 채널로

    async def boom(*a, **k):
        raise RuntimeError("채널 장애")
    monkeypatch.setattr(notification, "dispatch_event", boom)
    line = cr.send_round_report(OK_STATE)
    assert line.startswith("🟡") and "RuntimeError" in line                  # 예외가 밖으로 나가지 않는다


def test_cr04_send_uses_no_user_and_env_channels(monkeypatch):
    from app.services import notification
    monkeypatch.setenv("COLLECT_REPORT_NOTIFY", "true")      # 시험 기본은 꺼짐(conftest) — 켜고 가짜 채널로
    seen = {}

    async def fake(ev, user_id=None, **kw):
        seen["user_id"], seen["kind"], seen["dedupe"] = user_id, ev.kind, kw.get("dedupe_kind")
    monkeypatch.setattr(notification, "dispatch_event", fake)
    monkeypatch.setattr(notification, "_default_channels", lambda: ["discord"])
    line = cr.send_round_report(OK_STATE)
    assert seen == {"user_id": None, "kind": "collect_report", "dedupe": None}  # DB 선점(kind/ref) 없음
    assert "discord" in line


def test_cr05_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("COLLECT_REPORT_NOTIFY", "0")
    assert "꺼짐" in cr.send_round_report(OK_STATE)
