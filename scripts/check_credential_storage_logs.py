"""앱·worker·beat의 암호화 오류 로그를 검사한다. 로그 원문·비밀값은 출력하지 않는다.

종료 코드: 0 정상, 1 CREDENTIAL_STORAGE 발견, 2 로그 조회 실패.
운영 감시 작업에서 주기적으로 호출할 수 있는 단발 검사이며 알림을 직접 발송하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import subprocess

SERVICES = ("qurious-app", "qurious-celery-worker", "qurious-celery-beat")
TAG = b"[CREDENTIAL_STORAGE]"


def check_logs(docker: str, since: str, *, runner=None) -> dict:
    runner = runner or subprocess.run
    results = {}
    for service in SERVICES:
        try:
            process = runner(
                [docker, "logs", "--since", since, service],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False,
            )
            if process.returncode:
                results[service] = {"status": "unavailable", "error_lines": None}
                continue
            count = sum(TAG in line for line in (process.stdout + b"\n" + process.stderr).splitlines())
            results[service] = {"status": "error" if count else "ok", "error_lines": count}
        except (OSError, subprocess.SubprocessError):
            results[service] = {"status": "unavailable", "error_lines": None}
    statuses = {r["status"] for r in results.values()}
    status = "unavailable" if "unavailable" in statuses else "error" if "error" in statuses else "ok"
    return {"status": status, "since": since, "services": results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker", help="Docker CLI 경로(Windows Docker Desktop이면 docker.exe)")
    parser.add_argument("--since", default="10m", help="조회 시작 시각 또는 기간(기본 10m)")
    args = parser.parse_args(argv)
    result = check_logs(args.docker, args.since)
    print(json.dumps(result, ensure_ascii=False))
    return {"ok": 0, "error": 1, "unavailable": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
