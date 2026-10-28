"""TC-WH — TradingView 웹훅 받는 쪽 검증 (설계 3.6 · ①-08).

DB 없이 도는 부분: 발신 IP(위조 헤더) · 본문 크기 · 형식 · 토큰 · 분당 제한 · 응답 뒤 처리 · 필수 칸 · 지연 · 중복 키.
DB 가 필요한 부분(알림 단위 중복 선점 · 동시 요청)은 test_tradingview_webhook_pg.py.
"""
import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import settings
from app.database.postgres import get_pg_session
from app.routes import tradingview as route
from app.services import tradingview as tv

TV_IP = "52.89.214.238"
SECRET = "qk_live_SECRET_TOKEN_VALUE"
NOW = datetime(2026, 10, 28, 5, 30, 0, tzinfo=timezone.utc)


class FakeDb:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def canned(status="filled", **extra):
    sig = {"id": str(uuid.uuid4()), "provider": "tradingview", "strategy": "s", "symbol": "005930", "side": "BUY",
           "quantity": 1, "signal_price": 70000.0, "fill_price": 70100.0, "status": status, "message": "m",
           "payload": {}, "created_at": None, "dup_count": 0, "delay_sec": 1.0, **extra}
    return {"user_id": str(uuid.uuid4()), "signal": sig, "alert": {}, "notification_ref": "ref-abc"}


@pytest.fixture
def env(monkeypatch):
    """라우트만 올린 앱 + 가짜 DB · 가짜 서비스. 설정은 시험마다 monkeypatch 로 바꾼다."""
    db = FakeDb()
    app = FastAPI()
    app.include_router(route.router)
    app.dependency_overrides[get_pg_session] = lambda: db
    key = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4())
    e = SimpleNamespace(
        app=app, db=db, key=key,
        resolve=AsyncMock(return_value=key),
        handle=AsyncMock(return_value=canned()),
        rate=AsyncMock(return_value=True),
        audit=AsyncMock(),
        dispatch=AsyncMock(),
    )
    monkeypatch.setattr(route.tv, "resolve_user_by_token", e.resolve)
    monkeypatch.setattr(route.tv, "handle_alert", e.handle)
    monkeypatch.setattr(route, "_check_rate_limit", e.rate)
    monkeypatch.setattr(route, "audit", e.audit)
    monkeypatch.setattr(route.notification, "dispatch", e.dispatch)
    # 마이그레이션을 도는 다른 시험이 alembic/env.py 의 fileConfig 로 이미 만든 로거를 꺼 둘 수 있다 — 로그 시험이 흔들리지 않게 되살린다
    monkeypatch.setattr(route.logger, "disabled", False)
    monkeypatch.setattr(settings, "TRADINGVIEW_ENFORCE_IP", False)
    monkeypatch.setattr(settings, "TRADINGVIEW_ALLOWED_IPS", f"{TV_IP},34.212.75.30")
    monkeypatch.setattr(settings, "TRADINGVIEW_TRUSTED_PROXY_HOPS", 0)
    monkeypatch.setattr(settings, "TRADINGVIEW_MAX_BODY_BYTES", 4096)
    e.client = lambda peer="9.9.9.9": TestClient(app, client=(peer, 50000))
    return e


GOOD = {"token": SECRET, "ticker": "KRX:005930", "action": "buy", "contracts": "1",
        "strategy_id": "ma-cross", "bar_time": "2026-10-28T00:00:00Z", "sent_at": "2026-10-28T05:30:00Z"}


# ── 3.6 #2 발신 IP ────────────────────────────────────────────────────────

def test_spoofed_x_forwarded_for_is_ignored_without_trusted_proxy(env, monkeypatch):
    """프록시를 믿지 않으면(기본) 헤더에 허용 IP 를 적어도 소켓 상대 주소가 허용 목록 밖이라 막힌다.
    예전 코드는 헤더의 맨 앞 값을 믿어 이 요청을 통과시켰다."""
    monkeypatch.setattr(settings, "TRADINGVIEW_ENFORCE_IP", True)
    r = env.client("6.6.6.6").post("/api/webhooks/tradingview", json=GOOD, headers={"X-Forwarded-For": TV_IP})
    assert r.status_code == 403
    env.handle.assert_not_awaited()
    env.resolve.assert_not_awaited()  # 토큰 조회까지 가지도 못한다


def test_peer_in_allowlist_passes(env, monkeypatch):
    monkeypatch.setattr(settings, "TRADINGVIEW_ENFORCE_IP", True)
    r = env.client(TV_IP).post("/api/webhooks/tradingview", json=GOOD)
    assert r.status_code == 200 and r.json()["status"] == "filled"


def test_trusted_hop_reads_rightmost_value_not_the_first(env, monkeypatch):
    monkeypatch.setattr(settings, "TRADINGVIEW_ENFORCE_IP", True)
    monkeypatch.setattr(settings, "TRADINGVIEW_TRUSTED_PROXY_HOPS", 1)
    c = env.client("10.0.0.2")  # 앞단 프록시의 주소
    # 보낸 쪽이 맨 앞에 허용 IP 를 적어도, 프록시가 덧붙인 오른쪽 값(진짜 상대)이 기준이다
    assert c.post("/api/webhooks/tradingview", json=GOOD, headers={"X-Forwarded-For": f"{TV_IP}, 6.6.6.6"}).status_code == 403
    assert c.post("/api/webhooks/tradingview", json=GOOD, headers={"X-Forwarded-For": f"6.6.6.6, {TV_IP}"}).status_code == 200


def test_trusted_hop_without_header_is_rejected(env, monkeypatch):
    monkeypatch.setattr(settings, "TRADINGVIEW_ENFORCE_IP", True)
    monkeypatch.setattr(settings, "TRADINGVIEW_TRUSTED_PROXY_HOPS", 1)
    assert env.client("10.0.0.2").post("/api/webhooks/tradingview", json=GOOD).status_code == 403


def test_ip_check_is_off_by_default(env):
    assert env.client("6.6.6.6").post("/api/webhooks/tradingview", json=GOOD).status_code == 200


# ── 3.6 #3 본문 ───────────────────────────────────────────────────────────

def test_body_over_limit_is_413_even_when_chunked(env, monkeypatch):
    monkeypatch.setattr(settings, "TRADINGVIEW_MAX_BODY_BYTES", 100)
    c = env.client()
    ok = c.post("/api/webhooks/tradingview", content=b"ticker=" + b"A" * 93)  # 정확히 100바이트는 통과
    assert ok.status_code == 200
    assert c.post("/api/webhooks/tradingview", content=b"ticker=" + b"A" * 94).status_code == 413  # 101바이트
    # Content-Length 없이 쪼개 보내도 읽다가 넘으면 막는다
    def chunks():
        for _ in range(5):
            yield b"ticker=" + b"A" * 30 + b","
    assert c.post("/api/webhooks/tradingview", content=chunks()).status_code == 413


def test_empty_and_unparseable_body_are_400(env):
    c = env.client()
    assert c.post("/api/webhooks/tradingview", content=b"").status_code == 400
    assert c.post("/api/webhooks/tradingview", content=b"[1, 2]").status_code == 400
    assert c.post("/api/webhooks/tradingview", content=b"\xff\xfe\x00garbage").status_code == 400
    env.handle.assert_not_awaited()


def test_key_value_body_is_accepted(env):
    r = env.client().post("/api/webhooks/tradingview",
                          content=f"token={SECRET}, ticker=005930, action=buy, contracts=1".encode())
    assert r.status_code == 200
    sent = env.handle.await_args.args[1]
    assert sent["ticker"] == "005930" and sent["action"] == "buy"


# ── 3.6 #1 토큰 · #6 분당 제한 ────────────────────────────────────────────

def test_bad_token_is_401_and_never_logged(env, caplog):
    env.resolve.side_effect = tv.WebhookError(401, "유효하지 않거나 폐기된 API 키입니다.")
    with caplog.at_level(logging.WARNING):
        r = env.client().post("/api/webhooks/tradingview", json=GOOD)
    assert r.status_code == 401 and r.json()["detail"]["error"] == "UNAUTHORIZED"
    env.handle.assert_not_awaited()
    assert env.db.rollbacks == 1
    assert "rejected_auth" in caplog.text      # 거부는 기록하되
    assert SECRET not in caplog.text           # 토큰 원문은 로그에 없다


def test_rate_limit_is_429_before_any_processing(env):
    env.rate.return_value = False
    r = env.client().post("/api/webhooks/tradingview", json=GOOD)
    assert r.status_code == 429
    env.handle.assert_not_awaited()


# ── 3.6 #3 · #4 · #5 결과의 응답 ──────────────────────────────────────────

def test_rejected_format_is_400_but_the_row_is_kept(env):
    env.handle.return_value = canned("rejected_format", message="strategy_id 가 없습니다.")
    r = env.client().post("/api/webhooks/tradingview", json=GOOD)
    assert r.status_code == 400 and "strategy_id" in r.json()["detail"]["message"]
    assert env.db.commits == 1  # 거부 기록은 남긴다
    env.dispatch.assert_not_awaited()


def test_late_is_200_not_ok_and_is_notified(env):
    env.handle.return_value = canned("late", message="늦게 도착")
    r = env.client().post("/api/webhooks/tradingview", json=GOOD)
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["status"] == "late"
    env.dispatch.assert_awaited_once()
    assert env.dispatch.await_args.kwargs["kind"] == "tradingview_signal" and env.dispatch.await_args.kwargs["ref"] == "ref-abc"


def test_duplicate_is_200_ok_and_does_not_notify_again(env):
    env.handle.return_value = canned("duplicate")
    r = env.client().post("/api/webhooks/tradingview", json=GOOD)
    assert r.status_code == 200 and r.json()["ok"] is True
    env.dispatch.assert_not_awaited()
    env.audit.assert_awaited_once()


# ── 3.6 #7 3초 응답 ───────────────────────────────────────────────────────

def test_response_does_not_wait_for_a_slow_channel(env):
    """알림 채널이 5초 걸려도 라우트는 바로 돌아온다 — 알림은 응답 뒤(BackgroundTasks)에서 돈다."""
    async def slow(*a, **kw):
        await asyncio.sleep(5)
    env.dispatch.side_effect = slow
    body = b'{"token":"%s","ticker":"005930","action":"buy","contracts":1}' % SECRET.encode()

    async def go():
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        scope = {"type": "http", "method": "POST", "path": "/api/webhooks/tradingview", "query_string": b"",
                 "headers": [(b"content-type", b"application/json")], "client": ("9.9.9.9", 1)}
        background = BackgroundTasks()
        t0 = time.monotonic()
        res = await route.tradingview_webhook(Request(scope, receive), background, env.db)
        took = time.monotonic() - t0
        assert res["status"] == "filled"
        assert took < 1.0                                  # 느린 채널을 기다리지 않았다
        env.dispatch.assert_not_awaited()                  # 아직 보내지 않았다
        assert len(background.tasks) == 1                  # 응답 뒤로 예약됐다
        return background
    background = asyncio.run(go())
    assert background.tasks[0].func is route._after_response


def test_after_response_failures_do_not_raise(env, caplog):
    env.audit.side_effect = RuntimeError("audit down")
    env.dispatch.side_effect = RuntimeError("channel down")
    with caplog.at_level(logging.WARNING):
        asyncio.run(route._after_response(canned()))
    assert "audit 실패" in caplog.text and "알림 전달 실패" in caplog.text


# ── 순수 함수 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("xff,peer,hops,expected", [
    ("6.6.6.6, 52.89.214.238", "1.1.1.1", 0, "1.1.1.1"),     # 프록시를 믿지 않으면 헤더는 무시
    ("6.6.6.6, 52.89.214.238", "1.1.1.1", 1, "52.89.214.238"),
    ("52.89.214.238, 6.6.6.6", "1.1.1.1", 1, "6.6.6.6"),     # 맨 앞 값을 믿지 않는다
    ("a, b, c", "p", 2, "b"),
    ("a", "p", 2, None),                                      # 신뢰 단계보다 값이 모자라면 거부
    ("", "1.1.1.1", 1, None),
    ("", "", 0, None),
])
def test_client_ip(xff, peer, hops, expected):
    assert tv.client_ip(xff, peer, hops) == expected


@pytest.mark.parametrize("value,expected", [
    ("2026-10-28T05:30:00Z", NOW),
    ("2026-10-28T14:30:00+09:00", NOW),
    ("2026-10-28 05:30:00", NOW),                              # 시간대 없으면 UTC
    (str(int(NOW.timestamp())), NOW),
    (str(int(NOW.timestamp()) * 1000), NOW),
    ("garbage", None), ("", None), (None, None), ("12345", None),
])
def test_parse_time(value, expected):
    assert tv.parse_time(value) == expected


def test_dedup_key_identity():
    base = ("u1", "ma-cross", 1, "005930", "BUY", "2026-10-28T05:30:00Z")
    k = tv.build_dedup_key(*base)
    assert len(k) == 64
    assert tv.build_dedup_key("u1", "ma-cross", 1, "005930", "BUY", "2026-10-28T14:30:00+09:00") == k  # 같은 순간
    for changed in (("u2",) + base[1:], (base[0], "other") + base[2:], base[:2] + (2,) + base[3:],
                    base[:3] + ("000660",) + base[4:], base[:4] + ("SELL",) + base[5:],
                    base[:5] + ("2026-10-29T05:30:00Z",)):
        assert tv.build_dedup_key(*changed) != k
    # 시각이 아닌 신호(signal_id)는 글 그대로 구분한다
    assert tv.build_dedup_key("u1", "s", 1, "005930", "BUY", "sig-1") != tv.build_dedup_key("u1", "s", 1, "005930", "BUY", "sig-2")


def test_public_payload_drops_token_and_unknown_and_clips():
    out = tv.public_payload({"token": SECRET, "api_key": SECRET, "ticker": "005930", "evil": "x", "comment": "c" * 500,
                             "contracts": 3, "dry_run": True})
    assert "token" not in out and "api_key" not in out and "evil" not in out
    assert len(out["comment"]) == 200 and out["contracts"] == 3 and out["dry_run"] is True


def fields(alert_strategy="MA 교차", **over):
    p = {"strategy_id": "ma-cross", "strategy_version": 2, "bar_time": "2026-10-28T00:00:00Z", "sent_at": "2026-10-28T05:29:30Z"}
    p.update(over)
    return tv._order_fields(p, {"strategy": alert_strategy}, NOW)


def test_order_fields_ok_and_version_default():
    f = fields()
    assert f["status"] == "" and f["version"] == 2 and f["delay"] == 30.0 and f["strategy_id"] == "ma-cross"
    assert f["signal"] == "2026-10-28T00:00:00Z"
    assert fields(strategy_version="")["version"] == 1 and fields(strategy_version=0)["version"] == 1


def test_strategy_id_falls_back_to_strategy_name_then_default():
    assert fields(strategy_id="")["strategy_id"] == "MA 교차"
    assert fields(alert_strategy="", strategy_id="")["strategy_id"] == "default"
    assert len(fields(strategy_id="x" * 200)["strategy_id"]) == 97


def test_signal_is_signal_id_then_bar_time_then_time():
    """오준영 님 공통 관문의 signal_key 와 같은 차례 — 하나도 없을 때만 형식 거부."""
    assert fields(signal_id="abc")["signal"] == "abc"
    assert fields(bar_time="", time="2026-10-28T00:01:00Z")["signal"] == "2026-10-28T00:01:00Z"
    for over in ({"bar_time": ""}, {"bar_time": "  "}):
        assert fields(**over)["status"] == "rejected_format"
    assert tv._order_fields({}, {"strategy": "x"}, NOW)["status"] == "rejected_format"


def test_bad_sent_at_is_a_format_error():
    assert fields(sent_at="어제")["status"] == "rejected_format"


def test_without_sent_at_the_delay_is_not_measured():
    """bar_time 은 봉이 열린 시각이라 일봉에서는 몇 시간 전이 정상이다 — sent_at 이 없으면 지연을 재지 않는다."""
    f = tv._order_fields({"bar_time": "2026-10-27T00:00:00Z"}, {"strategy": "s"}, NOW)
    assert f["status"] == "" and "delay" not in f


def test_late_limit_boundary_uses_sent_at(monkeypatch):
    monkeypatch.setattr(settings, "TRADINGVIEW_MAX_DELAY_SEC", 300)
    ok = fields(sent_at=(NOW - timedelta(seconds=300)).isoformat())
    assert ok["status"] == "" and ok["delay"] == 300.0                 # 한도와 같으면 통과
    late = fields(sent_at=(NOW - timedelta(seconds=301)).isoformat())
    assert late["status"] == "late" and late["delay"] == 301.0


def test_future_sent_at_beyond_skew_is_a_format_error(monkeypatch):
    monkeypatch.setattr(settings, "TRADINGVIEW_MAX_FUTURE_SKEW_SEC", 60)
    assert fields(sent_at=(NOW + timedelta(seconds=60)).isoformat())["status"] == ""
    assert fields(sent_at=(NOW + timedelta(seconds=61)).isoformat())["status"] == "rejected_format"


def test_alert_template_carries_the_required_fields():
    for k in ("token", "strategy_id", "strategy_version", "bar_time", "sent_at", "ticker", "action", "contracts"):
        assert k in tv.ALERT_TEMPLATE
    assert tv.ALERT_TEMPLATE["bar_time"] == "{{time}}" and tv.ALERT_TEMPLATE["sent_at"] == "{{timenow}}"
