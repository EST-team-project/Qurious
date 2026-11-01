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
    assert asyncio.run(notification.send_slack("m", webhook_url="http://x.invalid", outcome=outcome)) is False
    assert outcome == {"retryable": True}
    _FailingClient.exc = httpx.ReadTimeout("x")
    outcome = {}
    assert asyncio.run(notification.send_slack("m", webhook_url="http://x.invalid", outcome=outcome)) is False
    assert outcome == {"retryable": False}

    _FailingClient.exc = httpx.ConnectError("x")
    delays: list[float] = []

    async def fake_sleep(sec):
        delays.append(sec)

    saved: list = []

    async def fake_log(user_id, subj, plain, names, results, attempts=None, **_kw):
        saved.append(notification._channel_rows(names, results, attempts))

    async def settings_for(_uid):
        return {"channels": ["slack"], "slack_webhook_url": "http://x.invalid"}

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

