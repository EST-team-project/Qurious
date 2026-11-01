"""보고식 알림 — 사건별 설정 · 조용한 시간 · 묶음 규칙(TC-ARP) 과 `dispatch_event` 흐름(TC-ADI).

규칙(`alert_prefs`)은 순수 함수라 시계 대신 `now` 를 인자로 넘겨 자정을 넘는 구간(21→08)의 앞뒤를 시험한다.
`dispatch_event` 는 채널 함수 · DB 기록 함수를 가짜로 바꿔 「무엇을 어떤 모양으로 보냈나」만 본다.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services import alert_format as af
from app.services import alert_prefs as ap
from app.services import notification

KST = af.KST


def kst(h, m=0):
    return datetime(2026, 11, 2, h, m, tzinfo=KST)


# ── TC-ARP: 설정 규칙 ────────────────────────────────────────────────────────


def test_ap01_normalize_fills_defaults_and_drops_unknown():
    p = ap.normalize({"events": {"order_fill": "silent", "없는사건": "on", "risk_halt": "off", "tv_signal": "weird"}})
    assert p["events"]["order_fill"] == "silent"
    assert "없는사건" not in p["events"]
    assert p["events"]["risk_halt"] == "on"                 # 끌 수 없는 사건은 off 가 들어와도 무시
    assert p["events"]["tv_signal"] == "on"                 # 모르는 모드는 기본값
    assert p["events"]["risk_skip"] == "silent"             # 빠진 값은 기본값
    assert p["quiet"] == {"enabled": False, "start": "21:00", "end": "08:00"}


def test_ap02_validate_rejects_bad_requests():
    for bad in ({"events": {"x": "on"}}, {"events": {"order_fill": "loud"}}, {"events": {"risk_halt": "off"}},
                {"quiet": {"enabled": "yes"}}, {"quiet": {"start": "25:00"}}, {"quiet": {"enabled": True, "start": "09:00", "end": "09:00"}}):
        with pytest.raises(ValueError):
            ap.validate(bad)
    ok = ap.validate({"events": {"risk_halt": "silent", "order_fill": "off"}, "quiet": {"enabled": True}})
    assert ok["events"]["risk_halt"] == "silent" and ok["events"]["order_fill"] == "off"
    assert ok["quiet"] == {"enabled": True, "start": "21:00", "end": "08:00"}


def test_ap03_quiet_hours_across_midnight():
    p = ap.normalize({"quiet": {"enabled": True, "start": "21:00", "end": "08:00"}})
    assert ap.in_quiet(p, kst(21, 0)) and ap.in_quiet(p, kst(23, 59)) and ap.in_quiet(p, kst(0, 0)) and ap.in_quiet(p, kst(7, 59))
    assert not ap.in_quiet(p, kst(8, 0)) and not ap.in_quiet(p, kst(12, 0)) and not ap.in_quiet(p, kst(20, 59))
    # UTC 로 들어와도 KST 로 판정한다(UTC 12:00 = KST 21:00)
    assert ap.in_quiet(p, datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
    same_day = ap.normalize({"quiet": {"enabled": True, "start": "13:00", "end": "15:00"}})
    assert ap.in_quiet(same_day, kst(14)) and not ap.in_quiet(same_day, kst(15))
    assert not ap.in_quiet(ap.normalize({}), kst(23))       # 기본은 꺼짐


def test_ap04_hold_plan():
    quiet = ap.normalize({"quiet": {"enabled": True}})
    assert ap.hold_plan("order_fill", "normal", quiet, kst(23)) == {"reason": "quiet", "release_at": None}
    assert ap.hold_plan("risk_halt", "urgent", quiet, kst(23)) is None           # 긴급은 언제나 바로
    assert ap.hold_plan("test", "info", quiet, kst(23)) is None                  # 시험은 바로
    assert ap.hold_plan("order_fill", "normal", quiet, kst(12)) is None          # 낮 · 묶음 대상 아님
    plan = ap.hold_plan("risk_skip", "info", quiet, kst(12))                     # 낮 · 묶음 대상
    assert plan["reason"] == "group"
    assert datetime.fromisoformat(plan["release_at"]) == kst(12) + timedelta(seconds=ap.GROUP_WINDOW_SEC)
    assert ap.hold_plan("risk_skip", "info", quiet, kst(23))["reason"] == "quiet"  # 조용한 시간이 우선


def test_ap05_releasable():
    quiet = ap.normalize({"quiet": {"enabled": True}})
    plain = ap.normalize({})
    assert not ap.releasable({"reason": "quiet"}, quiet, kst(7, 59))
    assert ap.releasable({"reason": "quiet"}, quiet, kst(8, 0))
    soon = {"reason": "group", "release_at": (kst(12) + timedelta(seconds=120)).isoformat()}
    assert not ap.releasable(soon, plain, kst(12, 1)) and ap.releasable(soon, plain, kst(12, 2))
    assert not ap.releasable(soon, quiet, kst(23))           # 창이 지났어도 조용한 시간이면 기다린다
    assert ap.releasable({"reason": "group", "release_at": "깨짐"}, plain, kst(12))   # 풀 시각이 깨지면 붙잡지 않는다


# ── TC-ADI: dispatch_event ───────────────────────────────────────────────────


@pytest.fixture
def rig(monkeypatch):
    """채널 함수 · 기록 함수를 가짜로 바꾼다. `rig.calls` = 채널 호출 목록, `rig.logs`/`rig.held` = 기록."""
    class Rig:
        calls: list = []
        logs: list = []
        held: list = []
        cfg: dict = {}
        store_ok = True

    r = Rig()
    r.calls, r.logs, r.held = [], [], []
    r.cfg = {"channels": ["telegram", "slack", "discord", "email", "kakao", "sms"], "preferences": {}}

    def make(name):
        async def fake(*args, outcome=None, **kw):
            r.calls.append((name, args, kw))
            return True
        return fake

    for ch in ("telegram", "slack", "discord", "email", "kakao", "sms"):
        monkeypatch.setattr(notification, f"send_{ch}", make(ch))

    async def load(user_id):
        return r.cfg

    async def log(user_id, subj, plain, names, results, attempts=None, **kw):
        r.logs.append((user_id, subj, names, results, kw))

    async def store(user_id, subject, message, payload, event_id):
        r.held.append((user_id, payload))
        return r.store_ok

    monkeypatch.setattr(notification, "_load_user_settings", load)
    monkeypatch.setattr(notification, "_log_dispatch", log)
    monkeypatch.setattr(notification, "_store_held", store)
    return r


def _ev(kind="order_fill", severity="normal", **kw):
    return af.AlertEvent(kind=kind, severity=severity, title="체결", summary="요약", fields=[("종목", "삼성전자")],
                         mock=True, **kw)


def run(coro):
    return asyncio.run(coro)


def names(r):
    return [c[0] for c in r.calls]


def test_ad01_each_channel_gets_its_own_shape(rig):
    run(notification.dispatch_event(_ev(reason="<b>x</b> & y"), user_id=None))
    by = {n: (a, k) for n, a, k in rig.calls}
    assert set(by) == {"telegram", "slack", "discord", "email", "kakao", "sms"}
    assert "&lt;b&gt;x&lt;/b&gt; &amp; y" in by["telegram"][0][0]            # 텔레그램: 값만 이스케이프
    assert by["slack"][1]["blocks"] and by["slack"][1]["blocks"][0]["type"] == "header"
    assert by["discord"][1]["embeds"][0]["fields"][0]["name"] == "종목"
    assert by["email"][1]["text_body"] and "체결" in by["email"][1]["subject"]
    assert len(by["sms"][0][0]) <= 80
    assert "silent" not in by["telegram"][1] and "silent" not in by["discord"][1]
    # 이력에는 보고 원본(payload)이 함께 남는다
    assert rig.logs and rig.logs[0][4]["payload"]["kind"] == "order_fill"


def test_ad02_mode_off_sends_nothing(rig):
    rig.cfg["preferences"] = {"events": {"order_fill": "off"}}
    run(notification.dispatch_event(_ev(), user_id="u1"))
    assert rig.calls == [] and rig.logs == [] and rig.held == []


def test_ad03_silent_mode(rig):
    rig.cfg["preferences"] = {"events": {"order_fill": "silent"}}
    run(notification.dispatch_event(_ev(), user_id=None))
    by = {n: k for n, _a, k in rig.calls}
    assert by["telegram"]["silent"] is True and by["discord"]["silent"] is True
    assert "kakao" not in by and "sms" not in by             # 소리 · 요금이 나는 채널은 건너뛴다
    assert "slack" in by and "email" in by


def test_ad04_quiet_hours_hold_non_urgent_but_not_urgent(rig, monkeypatch):
    rig.cfg["preferences"] = {"quiet": {"enabled": True, "start": "21:00", "end": "08:00"}}
    monkeypatch.setattr(notification, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: kst(23))}))
    run(notification.dispatch_event(_ev(), user_id="u1"))
    assert rig.calls == [] and len(rig.held) == 1
    payload = rig.held[0][1]
    assert payload["hold"]["reason"] == "quiet" and payload["hold"]["mode"] == "on" and payload["kind"] == "order_fill"
    run(notification.dispatch_event(_ev(kind="risk_halt", severity="urgent"), user_id="u1"))
    assert names(rig)                                         # 긴급은 조용한 시간에도 바로 나간다
    assert len(rig.held) == 1


def test_ad05_hold_store_failure_sends_immediately(rig, monkeypatch):
    rig.cfg["preferences"] = {"quiet": {"enabled": True}}
    rig.store_ok = False
    monkeypatch.setattr(notification, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: kst(23))}))
    run(notification.dispatch_event(_ev(), user_id="u1"))
    assert names(rig) and rig.logs                            # 잃는 것보다 낫다


def test_ad06_group_window_holds_groupable_kind(rig, monkeypatch):
    monkeypatch.setattr(notification, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: kst(12))}))
    run(notification.dispatch_event(_ev(kind="risk_skip", severity="info"), user_id="u1"))
    assert rig.calls == [] and rig.held[0][1]["hold"]["reason"] == "group"
    assert rig.held[0][1]["hold"]["mode"] == "silent"         # risk_skip 기본 모드가 silent — 풀 때도 조용히


def test_ad07_no_user_means_no_hold_and_defaults(rig, monkeypatch):
    """수집 보고처럼 사용자가 없는 호출은 설정 없이 기본 채널로 바로 보낸다."""
    rig.cfg = {}
    monkeypatch.setattr(notification, "_default_channels", lambda: ["discord"])
    run(notification.dispatch_event(_ev(kind="collect_report", severity="info"), user_id=None))
    assert names(rig) == ["discord"] and not rig.held


def test_ad08_legacy_dispatch_adapter(rig):
    """옛 호출: 태그 없는 html 은 평문으로 보고(이스케이프), 태그가 있는 html 은 그대로 보낸다."""
    run(notification.dispatch("TV 코멘트 <script> & x", html_message="TV 코멘트 <script> & x", subject="[TradingView] 매수", user_id=None))
    tg = [a for n, a, k in rig.calls if n == "telegram"][0][0]
    assert tg == "TV 코멘트 &lt;script&gt; &amp; x"
    rig.calls.clear()
    run(notification.dispatch("[주문 오류]", html_message="❌ <b>주문 오류</b>", subject="s", user_id=None))
    assert [a for n, a, k in rig.calls if n == "telegram"][0][0] == "❌ <b>주문 오류</b>"
    # 옛 글만 보내는 호출은 새 인자(blocks · embeds)를 넘기지 않아 예전 채널 함수 모양 그대로다
    kw = {n: k for n, a, k in rig.calls}
    assert "blocks" not in kw["slack"] and "embeds" not in kw["discord"]


def test_ad09_legacy_kind_maps_to_setting_kind(rig):
    rig.cfg["preferences"] = {"events": {"tv_signal": "off"}}
    run(notification.dispatch("신호", subject="[TradingView] 매수 신호", user_id="u1"))
    assert rig.calls == []                                    # 제목 머리글로 tv_signal 설정이 적용된다


def test_ad10_helpers_build_report_style_events(rig):
    run(notification.notify_order_error("005930", "buy", 10, 70000, "증권사 거절 <코드 40>", user_id=None))
    tg = [a for n, a, k in rig.calls if n == "telegram"][0][0]
    assert "<b>주문 오류 – 매수 005930</b>" in tg and "&lt;코드 40&gt;" in tg and "다음 행동" in tg
    rig.calls.clear()
    run(notification.notify_auto_trade_executed("005930", "삼성전자", "buy", 10, 70000, "MA 교차", user_id=None,
                                                details=[("수수료", "105원")]))
    emb = [k for n, a, k in rig.calls if n == "discord"][0]["embeds"][0]
    assert any(f["name"] == "수수료" for f in emb["fields"]) and "가상 자금" in emb["footer"]["text"]
    rig.calls.clear()
    run(notification.notify_risk_halt("일손실 한도", -3.2, user_id=None))
    assert "urgent" == rig.logs[-1][4]["payload"]["severity"]
