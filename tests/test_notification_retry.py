"""TC-NR — 알림 재시도 정책 (할 일 ①-14 · 2026-10-31)

①-14 완료 기준의 「실패는 기록 · 재시도 상한 · 같은 알림 억제」 중 재시도 상한.
정책: 전달이 안 된 게 확실한 실패(연결 단계 실패 · 429)만 처음 1번 + 재시도 최대 3번(간격 1 · 3 · 9초)으로 다시 보낸다.
응답이 불명확한 실패(읽기 시간 초과 · 5xx · 인증 거절 · 설정 없음)는 다시 보내지 않는다(증권사 연동 설계 「불명확하면 재발송 금지」).

1. 실패 종류를 분류한다. (TC-NR-01)
2. 확실한 미전달 실패는 다시 보내 성공하면 거기서 멈춘다. (TC-NR-02)
3. 계속 실패하면 상한(1 + 3 = 4번)에서 멈추고 간격이 늘어난다. (TC-NR-03)
4. 불명확한 실패 · 표시 없는 실패는 한 번만 보낸다 — 기존 「실패한 알림은 반복 발송 안 함」 시험과 같은 뜻. (TC-NR-04)
5. 실제 채널 함수가 연결 실패를 표시해 주고, 이력 줄에 시도 횟수가 남는다. (TC-NR-05)
6. 이력 기록이 실패하면 조용히 지나가지 않고 로그에 남는다. (TC-NR-06)
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import notification  # noqa: E402


def _http_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://example.invalid")
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(code, request=req))


def test_failure_kinds_are_classified():
    """TC-NR-01 · 연결 단계 실패와 429 만 「보내지 못한 게 확실」 — 읽기 시간 초과 · 5xx · 4xx 는 아니다."""
    assert notification.is_retryable(httpx.ConnectError("x"))
    assert notification.is_retryable(httpx.ConnectTimeout("x"))
    assert notification.is_retryable(_http_error(429))
    assert notification.is_retryable(ConnectionRefusedError())
    assert not notification.is_retryable(httpx.ReadTimeout("x"))
    for code in (400, 401, 403, 404, 500, 502, 503):
        assert not notification.is_retryable(_http_error(code)), code
    assert not notification.is_retryable(RuntimeError("x"))


def _run_retry(monkeypatch, outcomes):
    """outcomes: 시도마다 (성공 여부, 재시도 가능 표시). 부른 횟수와 잔 간격을 돌려준다."""
    delays: list[float] = []

    async def fake_sleep(sec):
        delays.append(sec)

    monkeypatch.setattr(notification.asyncio, "sleep", fake_sleep)
    calls: list[int] = []

    async def call(outcome):
        i = len(calls)
        calls.append(i)
        ok, retryable = outcomes[min(i, len(outcomes) - 1)]
        if retryable:
            outcome["retryable"] = True
        return ok

    result = asyncio.run(notification._send_with_retry(call))
    return result, len(calls), delays


def test_certain_failure_is_retried_until_it_succeeds(monkeypatch):
    """TC-NR-02 · 확실한 미전달 실패 → 다시 보내 두 번째에 성공하면 거기서 멈춘다(시도 2 · 간격 1초)."""
    (ok, attempts), calls, delays = _run_retry(monkeypatch, [(False, True), (True, False)])
    assert ok is True and attempts == 2 and calls == 2 and delays == [1.0]


def test_retry_stops_at_the_cap_with_growing_delays(monkeypatch):
    """TC-NR-03 · 계속 확실한 실패 → 처음 1 + 재시도 3 = 4번에서 멈추고 간격은 1 · 3 · 9초로 늘어난다."""
    (ok, attempts), calls, delays = _run_retry(monkeypatch, [(False, True)])
    assert ok is False and attempts == 4 and calls == 4 and delays == [1.0, 3.0, 9.0]
    assert notification.MAX_RETRIES == 3 and notification.RETRY_DELAYS == (1.0, 3.0, 9.0)


def test_ambiguous_or_unmarked_failure_is_sent_only_once(monkeypatch):
    """TC-NR-04 · 표시 없는 실패(예전 반환값 False · 불명확한 실패) → 한 번만 보낸다. 처음에 성공해도 한 번."""
    (ok, attempts), calls, delays = _run_retry(monkeypatch, [(False, False)])
    assert (ok, attempts, calls, delays) == (False, 1, 1, [])
    (ok, attempts), calls, delays = _run_retry(monkeypatch, [(True, False)])
    assert (ok, attempts, calls, delays) == (True, 1, 1, [])


class _FailingClient:
    """`httpx.AsyncClient` 대역 — post 가 정해 둔 예외를 던진다."""
    exc: Exception = httpx.ConnectError("x")

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **kw):
        raise type(self).exc


def test_channel_function_marks_connect_failure_and_history_keeps_attempts(monkeypatch):
    """TC-NR-05 · 실제 채널 함수(`send_slack`)가 연결 실패를 표시하고 읽기 시간 초과는 표시하지 않는다 ·
    `dispatch` 는 확실한 실패를 다시 보내고 이력에 채널별 시도 횟수를 남긴다."""
    monkeypatch.setattr(notification.httpx, "AsyncClient", _FailingClient)
    outcome: dict = {}
    assert asyncio.run(notification.send_slack("m", webhook_url="https://hooks.slack.com/services/T/B/x", outcome=outcome)) is False
    assert outcome == {"retryable": True}
    _FailingClient.exc = httpx.ReadTimeout("x")
    outcome = {}
    assert asyncio.run(notification.send_slack("m", webhook_url="https://hooks.slack.com/services/T/B/x", outcome=outcome)) is False
    assert outcome == {"retryable": False}

    _FailingClient.exc = httpx.ConnectError("x")
    delays: list[float] = []

    async def fake_sleep(sec):
        delays.append(sec)

    saved: list = []

    async def fake_log(user_id, subj, plain, names, results, attempts=None, **_kw):
        saved.append(notification._channel_rows(names, results, attempts))

    async def settings_for(_uid):
        return {"channels": ["slack"], "slack_webhook_url": "https://hooks.slack.com/services/T/B/x"}

    monkeypatch.setattr(notification.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(notification, "_load_user_settings", settings_for)
    monkeypatch.setattr(notification, "_log_dispatch", fake_log)
    asyncio.run(notification.dispatch("m"))
    assert saved == [[{"channel": "slack", "ok": False, "attempts": 4}]] and delays == [1.0, 3.0, 9.0]


def test_history_write_failure_is_logged_not_silent(monkeypatch, caplog):
    """TC-NR-06 · 이력 기록이 실패해도 알림 발송은 막지 않지만 로그에는 남긴다(예전에는 `except: pass`)."""
    import app.database.postgres as pg

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(pg, "get_session_factory", boom)
    with caplog.at_level(logging.WARNING, logger=notification.logger.name):
        asyncio.run(notification._log_dispatch(None, "s", "m", ["slack"], [True], [1]))
    assert any("알림 이력 기록 실패" in r.getMessage() for r in caplog.records)

class _RecordingClient:
    """`httpx.AsyncClient` 대역 — post 로 온 주소 · 본문을 모아 둔다(성공 응답은 디스코드처럼 204)."""
    posted: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        type(self).posted.append((url, kw.get("json")))
        req = httpx.Request("POST", url)
        return httpx.Response(204, request=req)


_HOOK = "https://discord.com/api/webhooks/123/SECRET-TOKEN"


def test_discord_sends_json_and_guards_the_address(monkeypatch, caplog):
    """TC-NR-07 · 디스코드 웹훅(2026-11-01) — 주소가 없으면 건너뛰고(False) · 디스코드 주소 모양이 아니면 보내지 않으며 ·
    맞으면 `content` 로 보내되 2,000자를 넘기면 줄임표로 자르고 `@everyone` 이 사람을 부르지 않게 하고 ·
    실패 로그에 주소(비밀 토큰)를 남기지 않는다 · 연결 실패는 「다시 보낼 수 있음」 으로 표시한다."""
    monkeypatch.setattr(notification.settings, "DISCORD_WEBHOOK_URL", "")
    _RecordingClient.posted = []
    monkeypatch.setattr(notification.httpx, "AsyncClient", _RecordingClient)
    assert asyncio.run(notification.send_discord("m")) is False and _RecordingClient.posted == []
    assert asyncio.run(notification.send_discord("m", webhook_url="http://evil.invalid/hook")) is False
    assert _RecordingClient.posted == []

    assert asyncio.run(notification.send_discord("안녕 @everyone", webhook_url=_HOOK)) is True
    url, body = _RecordingClient.posted[-1]
    assert url == _HOOK and body["content"] == "안녕 @everyone" and body["allowed_mentions"] == {"parse": []}

    assert asyncio.run(notification.send_discord("가" * 2500, webhook_url=_HOOK)) is True
    long_text = _RecordingClient.posted[-1][1]["content"]
    assert len(long_text) == 2000 and long_text.endswith("…")

    monkeypatch.setattr(notification.httpx, "AsyncClient", _FailingClient)
    _FailingClient.exc = httpx.ConnectError(f"cannot connect to {_HOOK}")
    outcome: dict = {}
    with caplog.at_level(logging.WARNING, logger=notification.logger.name):
        assert asyncio.run(notification.send_discord("m", webhook_url=_HOOK, outcome=outcome)) is False
    assert outcome == {"retryable": True}
    assert "SECRET-TOKEN" not in caplog.text and any("Discord 알림 실패" in r.getMessage() for r in caplog.records)


def test_discord_is_a_default_channel_and_dispatch_uses_it(monkeypatch):
    """TC-NR-08 · `.env` 에 `DISCORD_WEBHOOK_URL` 이 있으면 사용자 설정이 없는 알림의 기본 채널에 `discord` 가 들고,
    `dispatch` 가 그 채널로 보낸다(이력에 채널 이름 · 시도 횟수가 남는다)."""
    monkeypatch.setattr(notification.settings, "DISCORD_WEBHOOK_URL", _HOOK)
    monkeypatch.setattr(notification.settings, "SLACK_WEBHOOK_URL", "")
    monkeypatch.setattr(notification.settings, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(notification.settings, "SMTP_HOST", "")
    monkeypatch.setattr(notification.settings, "COOLSMS_API_KEY", "")
    assert notification._default_channels() == ["discord"]
    monkeypatch.setattr(notification.settings, "DISCORD_WEBHOOK_URL", "")
    assert "discord" not in notification._default_channels()

    monkeypatch.setattr(notification.settings, "DISCORD_WEBHOOK_URL", _HOOK)
    _RecordingClient.posted = []
    monkeypatch.setattr(notification.httpx, "AsyncClient", _RecordingClient)
    saved: list = []

    async def fake_log(user_id, subj, plain, names, results, attempts=None, **_kw):
        saved.append(notification._channel_rows(names, results, attempts))

    async def no_settings(_uid):
        return {}

    monkeypatch.setattr(notification, "_load_user_settings", no_settings)
    monkeypatch.setattr(notification, "_log_dispatch", fake_log)
    asyncio.run(notification.dispatch("테스트 알림"))
    assert saved == [[{"channel": "discord", "ok": True, "attempts": 1}]]
    assert _RecordingClient.posted[-1][1]["content"] == "테스트 알림"

class _StatusErrorClient:
    """post 가 주소가 든 HTTP 오류(예외 글에 주소가 들어간다)를 던지는 대역."""

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        req = httpx.Request("POST", url)
        raise httpx.HTTPStatusError(f"Server error '500' for url '{url}'", request=req, response=httpx.Response(500, request=req))


def test_failure_logs_never_contain_secrets(monkeypatch, caplog):
    """TC-NR-09 · 알림이 실패해도 로그에 웹훅 주소 · 봇 토큰이 남지 않는다 — 텔레그램 주소에는 봇 토큰이, 슬랙 · 디스코드 주소에는
    웹훅 비밀이 들어 있다(예전에는 예외 글이 주소를 담은 채 그대로 기록됐다). 로그에는 예외 종류와 HTTP 상태만 남는다."""
    monkeypatch.setattr(notification.httpx, "AsyncClient", _StatusErrorClient)
    with caplog.at_level(logging.WARNING, logger=notification.logger.name):
        assert asyncio.run(notification.send_telegram("m", token="BOT-TOKEN-SECRET", chat_id="1")) is False
        assert asyncio.run(notification.send_slack("m", webhook_url="https://hooks.slack.com/services/T/B/SLACK-SECRET")) is False
        assert asyncio.run(notification.send_discord("m", webhook_url=_HOOK)) is False
    assert "BOT-TOKEN-SECRET" not in caplog.text and "SLACK-SECRET" not in caplog.text and "SECRET-TOKEN" not in caplog.text
    assert caplog.text.count("HTTPStatusError(HTTP 500)") == 3


_HOOK_TEAM = "https://discord.com/api/webhooks/999/TEAM-TOKEN"


def test_discord_user_address_wins_over_shared_one(monkeypatch):
    """TC-NR-10 · 사용자별 디스코드 주소(2026-11-01) — 사용자 설정에 주소가 있으면 그쪽으로, 없으면 `.env` 공용 주소로 보낸다.
    사용자 설정을 읽는 쪽(`_load_user_settings`)이 그 칸을 넘겨 주는 것도 본다."""
    monkeypatch.setattr(notification.settings, "DISCORD_WEBHOOK_URL", _HOOK_TEAM)
    monkeypatch.setattr(notification.httpx, "AsyncClient", _RecordingClient)

    _RecordingClient.posted = []
    assert asyncio.run(notification.send_discord("m", webhook_url=_HOOK)) is True
    assert _RecordingClient.posted[-1][0] == _HOOK                         # 내 주소가 먼저
    assert asyncio.run(notification.send_discord("m", webhook_url="")) is True
    assert _RecordingClient.posted[-1][0] == _HOOK_TEAM                    # 비면 공용 주소로

    src = (ROOT / "app" / "services" / "notification.py").read_text(encoding="utf-8")
    block = src.split("async def _load_user_settings", 1)[1].split("def _default_channels", 1)[0]
    assert '"discord_webhook_url": row.discord_webhook_url' in block


def test_is_discord_webhook_accepts_only_discord_addresses():
    """TC-NR-11 · 디스코드 웹훅 주소 모양 검사 — 공식 도메인 네 가지만, 머리만 있는 주소 · 다른 도메인 · 빈 값은 아니다."""
    ok = notification.is_discord_webhook
    assert ok("https://discord.com/api/webhooks/1/abc") and ok("https://canary.discord.com/api/webhooks/1/abc")
    assert ok("https://ptb.discord.com/api/webhooks/1/abc") and ok("https://discordapp.com/api/webhooks/1/abc")
    assert not ok("") and not ok("https://discord.com/api/webhooks/")
    assert not ok("http://discord.com/api/webhooks/1/abc") and not ok("https://evil.example/https://discord.com/api/webhooks/1/a")


def test_discord_address_is_secret_masked_and_validated_on_save(monkeypatch):
    """TC-NR-12 · 저장된 디스코드 주소는 조회 응답에서 `****` 로 가려지고, 저장할 때 디스코드 주소 모양이 아니면 422 한국어 안내로 막는다
    (DB 를 건드리기 전에 막는다). 가림값으로 되돌려 저장하면 저장된 주소를 유지하고 빈 값이면 지운다."""
    import uuid
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    from app.routes import notification as noti_route

    me = {"id": str(uuid.uuid4())}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(noti_route.save_notification_settings(
            noti_route.NotificationSettingsBody(discord_webhook_url="http://evil.invalid/hook"), user=me, db=None))
    assert exc.value.status_code == 422 and "https://discord.com/api/webhooks/" in str(exc.value.detail)

    row = SimpleNamespace(**{name: "" for name in (
        "telegram_token", "telegram_chat_id", "slack_webhook_url", "discord_webhook_url", "email_to", "email_host", "email_user",
        "email_password", "email_from", "kakao_api_key", "kakao_api_secret", "kakao_sender_key", "kakao_phone",
        "sms_api_key", "sms_api_secret", "sms_from", "sms_to")},
        channels=["discord"], email_port=587, preferences={})
    row.discord_webhook_url = _HOOK

    async def fake_row(_db, _uid):
        return row

    async def fake_state(_db, _uid):
        return {"granted": True, "version": "v", "at": None, "current_version": "v"}

    monkeypatch.setattr(noti_route, "_get_settings_row", fake_row)
    monkeypatch.setattr(noti_route, "_consent_state", fake_state)
    out = asyncio.run(noti_route.get_notification_settings(user=me, db=None))
    assert out["discord_webhook_url"] == "****" and _HOOK not in str(out)

    class _Db:                                                  # 저장 경로가 쓰는 부분만 — 동의는 이미 한 상태
        async def commit(self):
            return None

    async def granted(*_a, **_k):
        return True

    monkeypatch.setattr(noti_route.consent, "is_granted", granted)

    async def latest_current(*_a, **_k):                        # 지금 동의문 판에 동의한 사람
        return SimpleNamespace(terms_version=noti_route.consent.NOTIFY_CONSENT_VERSION)

    monkeypatch.setattr(noti_route.consent, "latest", latest_current)
    asyncio.run(noti_route.save_notification_settings(
        noti_route.NotificationSettingsBody(channels=["discord"], discord_webhook_url="****"), user=me, db=_Db()))
    assert row.discord_webhook_url == _HOOK                     # 가림값 → 유지
    asyncio.run(noti_route.save_notification_settings(
        noti_route.NotificationSettingsBody(channels=["discord"], discord_webhook_url=""), user=me, db=_Db()))
    assert row.discord_webhook_url == ""                        # 빈 값 → 지움(공용 주소로 돌아감)


def test_tests_never_reach_the_real_alert_channels():
    """TC-NR-13 · 시험은 `.env` 의 실제 알림 채널로 글을 보내지 않는다 — conftest 가 채널 설정을 빈 값으로 시작하게 한다
    (팀 테스트 디스코드 주소를 `.env` 공용 칸에 둔 뒤, 알림 코드를 지나가는 시험이 팀 채널에 올리는 일을 막는다)."""
    for name in ("DISCORD_WEBHOOK_URL", "SLACK_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN", "SMTP_HOST", "COOLSMS_API_KEY"):
        assert getattr(notification.settings, name) == "", name
    assert notification._default_channels() == []


def test_stale_consent_must_agree_again_before_saving_a_discord_address(monkeypatch):
    """TC-NR-14 · 동의문 판이 올라(n0.1 → n0.2 — 디스코드 웹훅 주소 항목이 더해짐) 낡은 판에 동의한 사람은 **새 디스코드 주소를 저장하려면 다시 동의**해야 한다 —
    다시 동의하지 않으면 한국어 422 · 현재 판으로 다시 동의하면(요청에 동의문 판을 실어) 통과 · 저장된 주소 그대로 · 디스코드 말고 다른 칸은 막지 않는다."""
    import uuid
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    from app.routes import notification as noti_route

    me = {"id": str(uuid.uuid4())}
    row = SimpleNamespace(**{name: "" for name in (
        "telegram_token", "telegram_chat_id", "slack_webhook_url", "discord_webhook_url", "email_to", "email_host", "email_user",
        "email_password", "email_from", "kakao_api_key", "kakao_api_secret", "kakao_sender_key", "kakao_phone",
        "sms_api_key", "sms_api_secret", "sms_from", "sms_to")}, channels=["discord"], email_port=587, preferences={})

    async def fake_row(_db, _uid):
        return row

    async def granted(*_a, **_k):
        return True

    async def latest_old(*_a, **_k):
        return SimpleNamespace(terms_version="2026-10-29-n0.1")

    added = []

    class _Db:
        async def commit(self):
            return None

        def add_all(self, rows):
            added.extend(rows)

    monkeypatch.setattr(noti_route, "_get_settings_row", fake_row)
    monkeypatch.setattr(noti_route.consent, "is_granted", granted)
    monkeypatch.setattr(noti_route.consent, "latest", latest_old)
    new_addr = "https://discord.com/api/webhooks/1/NEW-TOKEN"

    with pytest.raises(HTTPException) as exc:                              # 다시 동의 없이 새 디스코드 주소 → 422
        asyncio.run(noti_route.save_notification_settings(
            noti_route.NotificationSettingsBody(channels=["discord"], discord_webhook_url=new_addr), user=me, db=_Db()))
    assert exc.value.status_code == 422 and "다시 동의" in str(exc.value.detail) and row.discord_webhook_url == ""

    asyncio.run(noti_route.save_notification_settings(                    # 디스코드 말고 다른 칸 · 가림값은 막지 않는다
        noti_route.NotificationSettingsBody(channels=["discord"], discord_webhook_url="****", email_host="smtp.example.com"), user=me, db=_Db()))

    asyncio.run(noti_route.save_notification_settings(                    # 현재 판으로 다시 동의하면 통과 · 동의 행이 쌓인다
        noti_route.NotificationSettingsBody(channels=["discord"], discord_webhook_url=new_addr, integration_consent=True,
                                            integration_consent_version=noti_route.consent.NOTIFY_CONSENT_VERSION), user=me, db=_Db()))
    assert row.discord_webhook_url == new_addr
    assert len(added) == 1 and added[0].terms_version == noti_route.consent.NOTIFY_CONSENT_VERSION and added[0].action == "grant"


def test_slack_address_is_checked_on_save_and_before_sending(monkeypatch):
    """TC-NR-15 · 사용자가 넣은 슬랙 웹훅 주소는 서버가 대신 부르므로 공식 슬랙 주소 모양만 받는다(2026-11-02 보안 점검) —
    저장할 때 422 한국어 안내, 보내기 직전에도 다시 막고(내부망 주소로 요청이 나가지 않는다), 응답에서는 `****` 로 가린다."""
    import uuid
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    from app.routes import notification as noti_route

    ok = notification.is_slack_webhook
    assert ok("https://hooks.slack.com/services/T0/B0/abcdef") and ok("https://hooks.slack.com/triggers/T0/1/abc")
    for bad in ("", "http://hooks.slack.com/services/T/B/x", "http://169.254.169.254/latest/meta-data/",
                "https://hooks.slack.com.evil.example/services/T/B/x", "https://evil.example/https://hooks.slack.com/services/T/B/x",
                "https://hooks.slack.com/", "https://hooks.slack.com/services/"):
        assert not ok(bad), bad

    _RecordingClient.posted = []
    monkeypatch.setattr(notification.httpx, "AsyncClient", _RecordingClient)
    assert asyncio.run(notification.send_slack("m", webhook_url="http://169.254.169.254/latest/meta-data/")) is False
    assert _RecordingClient.posted == []                                      # 요청이 나가지 않았다
    assert asyncio.run(notification.send_slack("m", webhook_url="https://hooks.slack.com/services/T/B/x")) is True

    me = {"id": str(uuid.uuid4())}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(noti_route.save_notification_settings(
            noti_route.NotificationSettingsBody(slack_webhook_url="http://169.254.169.254/x"), user=me, db=None))
    assert exc.value.status_code == 422 and "https://hooks.slack.com/services/" in str(exc.value.detail)

    secret = "https://hooks.slack.com/services/T/B/SLACK-SECRET"
    row = SimpleNamespace(**{n: "" for n in (
        "telegram_token", "telegram_chat_id", "discord_webhook_url", "email_to", "email_host", "email_user", "email_password",
        "email_from", "kakao_api_key", "kakao_api_secret", "kakao_sender_key", "kakao_phone", "sms_api_key", "sms_api_secret",
        "sms_from", "sms_to")}, slack_webhook_url=secret, channels=["slack"], email_port=587, preferences={})

    async def fake_row(_db, _uid):
        return row

    async def fake_state(_db, _uid):
        return {"granted": True, "version": "v", "at": None, "current_version": "v"}

    async def granted(*_a, **_k):
        return True

    async def latest_now(*_a, **_k):                                          # 지금 동의문 판으로 동의한 상태
        return SimpleNamespace(terms_version=noti_route.consent.NOTIFY_CONSENT_VERSION, action="grant")

    class _Db:
        async def commit(self):
            return None

    monkeypatch.setattr(noti_route, "_get_settings_row", fake_row)
    monkeypatch.setattr(noti_route, "_consent_state", fake_state)
    monkeypatch.setattr(noti_route.consent, "is_granted", granted)
    monkeypatch.setattr(noti_route.consent, "latest", latest_now)
    out = asyncio.run(noti_route.get_notification_settings(user=me, db=None))
    assert out["slack_webhook_url"] == "****" and "SLACK-SECRET" not in str(out)
    asyncio.run(noti_route.save_notification_settings(                       # 가림값으로 되돌려 저장 → 저장된 주소 유지
        noti_route.NotificationSettingsBody(channels=["slack"], slack_webhook_url="****"), user=me, db=_Db()))
    assert row.slack_webhook_url == secret
    asyncio.run(noti_route.save_notification_settings(                       # 빈 값이면 지운다
        noti_route.NotificationSettingsBody(channels=["slack"], slack_webhook_url=""), user=me, db=_Db()))
    assert row.slack_webhook_url == ""


def test_smtp_target_must_be_a_public_named_server():
    """TC-NR-16 · 사용자가 정한 메일 서버는 이름 모양 · 포트 · 공인 주소를 모두 만족해야 한다 — IP 숫자 · 주소 꼴 · 사설망 · 엉뚱한 포트는 안 된다."""
    err = notification.smtp_target_error
    public = lambda _h: ["93.184.216.34"]                                    # noqa: E731
    assert err("smtp.example.com", 587, resolve=public) == ""
    assert err("smtp.example.com", 25, resolve=public) == "" and err("smtp.example.com", 2525, resolve=public) == ""
    for host in ("127.0.0.1", "10.0.0.5", "http://smtp.example.com", "smtp.example.com/x", "localhost", "", "a b.example.com"):
        assert err(host, 587, resolve=public), host                          # 이름 모양이 아니다
    assert "포트" in err("smtp.example.com", 22, resolve=public) and "포트" in err("smtp.example.com", 6379, resolve=public)
    for ip in ("10.0.0.5", "192.168.1.9", "127.0.0.1", "169.254.169.254", "100.64.0.1", "::1"):
        assert "내부망" in err("smtp.example.com", 587, resolve=lambda _h, ip=ip: [ip]), ip
    assert "내부망" in err("smtp.example.com", 587, resolve=lambda _h: ["93.184.216.34", "10.0.0.5"])   # 하나라도 사설이면 막는다

    def nxdomain(_h):
        raise OSError("no such host")

    assert "찾지 못" in err("smtp.example.com", 587, resolve=nxdomain)


def test_user_mail_server_never_gets_operator_credentials(monkeypatch):
    """TC-NR-17 · 사용자가 메일 서버를 직접 정하면 운영자(.env) SMTP 아이디 · 비밀번호 · 보내는 사람을 섞지 않는다(그 서버로 운영자 계정이
    넘어가지 않게). 서버를 비우면 운영자 서버를 그대로 쓴다. 접속은 인증서를 검증한다(STARTTLS context)."""
    import ssl

    seen: list = []

    def fake_sync(subject, body, to_addr, host, port, user, password, from_addr, outcome=None, text_body=""):
        seen.append({"host": host, "port": port, "user": user, "password": password, "from": from_addr, "to": to_addr})
        return True

    s = notification.settings
    for name, val in (("SMTP_HOST", "smtp.operator.example"), ("SMTP_PORT", 587), ("SMTP_USER", "OPERATOR-ID"),
                      ("SMTP_PASSWORD", "OPERATOR-PW"), ("SMTP_FROM", "ops@operator.example"), ("SMTP_TO", "")):
        monkeypatch.setattr(s, name, val)
    monkeypatch.setattr(notification, "_send_email_sync", fake_sync)
    monkeypatch.setattr(notification, "smtp_target_error", lambda host, port, **_k: "")      # 이름 풀기 없이

    # 1) 사용자 서버 + 계정 비움 → 보내지 않는다(운영자 계정이 새지 않는다)
    assert asyncio.run(notification.send_email("s", "b", to_addr="me@x.co", host="smtp.mine.example", port=587)) is False
    assert seen == []
    # 2) 사용자 서버 + 자기 계정 → 자기 계정만
    assert asyncio.run(notification.send_email("s", "b", to_addr="me@x.co", host="smtp.mine.example", port=587,
                                               user="me", password="my-pw")) is True
    assert seen[-1] == {"host": "smtp.mine.example", "port": 587, "user": "me", "password": "my-pw", "from": "me", "to": "me@x.co"}
    # 3) 서버를 비움 → 운영자 서버 · 계정(사용자는 받는 주소만)
    assert asyncio.run(notification.send_email("s", "b", to_addr="me@x.co")) is True
    assert seen[-1]["host"] == "smtp.operator.example" and seen[-1]["user"] == "OPERATOR-ID" and seen[-1]["from"] == "ops@operator.example"
    # 4) 이름 검사에서 막히면(내부망 등) 보내지 않는다
    monkeypatch.setattr(notification, "smtp_target_error", lambda host, port, **_k: "내부망 주소로는 보낼 수 없습니다")
    n = len(seen)
    assert asyncio.run(notification.send_email("s", "b", to_addr="me@x.co", host="smtp.mine.example", user="me", password="p")) is False
    assert len(seen) == n

    # 5) STARTTLS 는 인증서를 검증하는 context 로
    got: dict = {}

    class _FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): pass
        def starttls(self, **kw): got.update(kw)
        def login(self, *a): pass
        def sendmail(self, *a): pass

    monkeypatch.undo()
    monkeypatch.setattr(notification.smtplib, "SMTP", _FakeSMTP)
    assert notification._send_email_sync("s", "b", "me@x.co", "smtp.mine.example", 587, "me", "pw", "me") is True
    ctx = got["context"]
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
