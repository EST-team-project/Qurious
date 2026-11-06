"""TC-CWD · P02-⑤-3: 호스트 경보 전이·중복 억제·전달 실패·비밀 비노출. 외부 전송 없음."""
import json
import subprocess
from unittest.mock import Mock

import pytest

from scripts import credential_watchdog as monitor


def sample(status="ok"):
    return {"status": status, "services": {name: {"status": status, "error_lines": 1 if status == "error" else 0}
                                           for name in monitor.SERVICES}}


def test_first_healthy_run_is_silent():
    sender = Mock()
    result, state, code = monitor.run_once(sample(), {}, sender, now=100)
    assert code == 0 and result["notification"] == "initial_ok"
    assert state["notified_signature"]
    sender.assert_not_called()


def test_persistent_error_deduplicates_then_reminds_after_one_hour():
    sender = Mock()
    result, state, code = monitor.run_once(sample("error"), {}, sender, now=100)
    assert code == 1 and result["notification"] == "sent"
    result, state, _ = monitor.run_once(sample("error"), state, sender, now=399)
    assert result["notification"] == "suppressed" and sender.call_count == 1
    result, state, _ = monitor.run_once(sample("error"), state, sender, now=3700)
    assert result["notification"] == "sent" and sender.call_count == 2


def test_query_outage_and_recovery_are_separate_once_each():
    sender = Mock()
    _, state, code = monitor.run_once(sample("unavailable"), {}, sender, now=100)
    assert code == 2
    result, state, code = monitor.run_once(sample(), state, sender, now=400)
    assert code == 0 and result["notification"] == "sent"
    message = sender.call_args.args[0]
    assert "로그 감시 정상화" in message and "키 복호화 기능 자체의 복구 확인은 별도" in message
    monitor.run_once(sample(), state, sender, now=700)
    assert sender.call_count == 2


def test_delivery_failure_retries_without_recording_success_or_secrets():
    sender = Mock(side_effect=RuntimeError("private-webhook-token"))
    result, state, code = monitor.run_once(sample("error"), {}, sender, now=100)
    assert code == 3 and state["notified_signature"] == ""
    assert "private" not in json.dumps([result, state])
    sender.side_effect = None
    result, state, code = monitor.run_once(sample("error"), state, sender, now=400)
    assert code == 1 and result["notification"] == "sent"


def test_service_change_is_not_suppressed_by_previous_outage():
    sender = Mock()
    _, state, _ = monitor.run_once(sample("error"), {}, sender, now=100)
    changed = sample("unavailable")
    changed["services"][monitor.SERVICES[0]]["status"] = "error"
    monitor.run_once(changed, state, sender, now=101)
    assert sender.call_count == 2


def test_log_counts_and_raw_text_do_not_affect_signature_or_message():
    sender = Mock()
    row = sample("error")
    _, state, _ = monitor.run_once(row, {}, sender, now=100)
    row["raw"] = "private-token"
    row["services"][monitor.SERVICES[0]]["error_lines"] = 400
    result, state, _ = monitor.run_once(row, state, sender, now=200)
    assert result["notification"] == "suppressed" and sender.call_count == 1
    assert "private-token" not in json.dumps(state) + str(sender.call_args)


@pytest.mark.parametrize("url", ["http://discord.com/api/webhooks/1/token", "https://discord.com.evil/api/webhooks/1/token",
                                "https://user@discord.com/api/webhooks/1/token", "https://discord.com/api/webhooks/1/token?secret=x",
                                "https://discord.com/api/webhooks/1/token#x", "https://discord.com/api/webhooks/x/token"])
def test_webhook_destination_is_restricted(url):
    with pytest.raises(ValueError, match="invalid_webhook"):
        monitor.validate_webhook(url)


def test_sender_disables_mentions_redirects_and_requires_ack(monkeypatch):
    response = Mock(status=200)
    response.read.return_value = b'{"id":"message-id"}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    factory = Mock(return_value=opener)
    monkeypatch.setattr(monitor, "build_opener", factory)
    monitor.send_discord("https://discord.com/api/webhooks/1/token", "message")
    request = opener.open.call_args.args[0]
    assert request.full_url.endswith("?wait=true")
    assert json.loads(request.data)["allowed_mentions"] == {"parse": []}
    assert isinstance(factory.call_args.args[0], monitor.NoRedirect)
    response.read.return_value = b'{}'
    with pytest.raises(RuntimeError, match="delivery_not_confirmed"):
        monitor.send_discord("https://discord.com/api/webhooks/1/token", "message")


def test_log_queries_are_bounded_and_truncation_is_not_healthy(monkeypatch):
    runner = Mock(side_effect=[subprocess.CompletedProcess([], 0, b"true\ntrue\ntrue\n", b"")]
                  + [subprocess.CompletedProcess([], 0, b"line\n" * monitor.MAX_LINES, b"")] * 3)
    monkeypatch.setattr(monitor.subprocess, "run", runner)
    result = monitor.bounded_logs("docker.exe")
    assert result["status"] == "unavailable"
    assert runner.call_count == 4
    for args, kwargs in runner.call_args_list[1:]:
        assert args[0][-3:-1] == ["--tail", str(monitor.MAX_LINES)]
        assert kwargs["timeout"] == 15


def test_stopped_service_cannot_look_healthy_from_old_logs(monkeypatch):
    runner = Mock(side_effect=[subprocess.CompletedProcess([], 0, b"true\nfalse\ntrue\n", b"")]
                  + [subprocess.CompletedProcess([], 0, b"", b"")] * 2)
    monkeypatch.setattr(monitor.subprocess, "run", runner)
    result = monitor.bounded_logs("docker.exe")
    assert result["status"] == "unavailable"
    assert result["services"][monitor.SERVICES[0]]["status"] == "ok"
    assert result["services"][monitor.SERVICES[1]]["status"] == "unavailable"
    assert runner.call_count == 3


def test_missing_docker_reports_unavailable_without_exception_text(monkeypatch):
    monkeypatch.setattr(monitor.subprocess, "run", Mock(side_effect=FileNotFoundError("private-path")))
    result = monitor.bounded_logs("missing-docker")
    assert result["status"] == "unavailable"
    assert "private-path" not in json.dumps(result)


def test_state_atomic_roundtrip_and_corruption_is_not_a_fresh_start(tmp_path):
    path = tmp_path / "state.json"
    assert monitor.load_state(path) == {}
    _, state, _ = monitor.run_once(sample(), {}, Mock(), now=100)
    monitor.write_json(path, state)
    assert monitor.load_state(path) == state
    assert list(tmp_path.iterdir()) == [path]
    path.write_text('{"unexpected":"value"}')
    with pytest.raises(ValueError):
        monitor.load_state(path)


def test_lock_rejects_a_second_process_handle_and_releases(tmp_path):
    path = tmp_path / "watchdog.lock"
    with monitor.exclusive_lock(path):
        with pytest.raises(OSError):
            with monitor.exclusive_lock(path):
                pytest.fail("second lock acquired")
    with monitor.exclusive_lock(path):
        pass


def test_cli_errors_do_not_print_configuration_or_exception(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text('{"schema":1,"docker":"docker","discord_dpapi":"private-token"}')
    assert monitor.main(["--config", str(path)]) == 3
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "watchdog_failed"
    assert "private-token" not in output
