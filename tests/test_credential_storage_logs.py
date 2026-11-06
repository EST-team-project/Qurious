"""TC-CSL · P02-⑤-3: 운영 로그 검사 4사례.

stderr 오류·조회 실패를 정상으로 취급하거나 원문을 노출하지 않는다.
단발 검사 계약이며 호스트 주기 실행·외부 경보 수신 검증은 별도다.
"""
import json
import subprocess

from scripts import check_credential_storage_logs as monitor


def test_stderr_credential_error_is_detected_without_exposing_log_text():
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, b"normal startup\n", b"[CREDENTIAL_STORAGE] private-sentinel\n")

    result = monitor.check_logs("docker.exe", "5m", runner=run)
    assert result["status"] == "error"
    assert all(v["error_lines"] == 1 for v in result["services"].values())
    assert "private-sentinel" not in json.dumps(result)
    assert calls == [["docker.exe", "logs", "--since", "5m", service] for service in monitor.SERVICES]


def test_failed_log_query_is_not_reported_as_no_errors():
    def run(args, **kwargs):
        if args[-1] == "qurious-app":
            return subprocess.CompletedProcess(args, 0, b"[CREDENTIAL_STORAGE] broken key", b"")
        if args[-1] == "qurious-celery-worker":
            return subprocess.CompletedProcess(args, 1, b"", b"private docker connection information")
        raise subprocess.TimeoutExpired(args, 30)

    result = monitor.check_logs("docker", "10m", runner=run)
    assert result["status"] == "unavailable"
    assert result["services"]["qurious-app"]["error_lines"] == 1
    assert result["services"]["qurious-celery-worker"]["error_lines"] is None
    assert result["services"]["qurious-celery-beat"]["status"] == "unavailable"
    assert "private" not in json.dumps(result)


def test_cli_exit_codes_preserve_monitoring_status(monkeypatch, capsys):
    for status, code in (("ok", 0), ("error", 1), ("unavailable", 2)):
        monkeypatch.setattr(monitor, "check_logs", lambda *args, **kwargs: {"status": status})
        assert monitor.main([]) == code
        assert json.loads(capsys.readouterr().out)["status"] == status


def test_missing_docker_binary_is_unavailable():
    def run(*args, **kwargs):
        raise FileNotFoundError("private path")

    result = monitor.check_logs("absent", "10m", runner=run)
    assert result["status"] == "unavailable"
    assert all(v["status"] == "unavailable" for v in result["services"].values())
