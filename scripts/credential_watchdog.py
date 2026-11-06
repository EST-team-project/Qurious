"""호스트 암호화 오류 감시. 앱 키·DB에 의존하지 않고 기존 Discord로 경보를 보낸다.

Windows 사용자 DPAPI로 보호한 전용 설정을 사용한다. 로그 원문·웹훅은 출력하지 않는다.
종료 코드: 0 정상, 1 암호화 오류 관측, 2 로그 조회 실패, 3 설정/전달/상태 저장 실패.
주기 실행은 install_credential_watchdog.ps1의 Windows 작업 스케줄러가 맡는다.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from scripts.check_credential_storage_logs import check_logs, SERVICES
except ModuleNotFoundError:
    from check_credential_storage_logs import check_logs, SERVICES

MAX_LINES = 5000
REMIND_SECONDS = 3600


def validate_webhook(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc not in ("discord.com", "discordapp.com")
            or not re.fullmatch(r"/api/webhooks/[0-9]+/[A-Za-z0-9_.-]+", parsed.path)
            or parsed.query or parsed.fragment):
        raise ValueError("invalid_webhook")
    return value


def protect(data: bytes, *, decrypt: bool = False) -> bytes:
    """Windows 현재 사용자 DPAPI. 앱의 BROKER_CREDENTIAL_KEY_FILE을 읽지 않는다."""
    if os.name != "nt":
        raise RuntimeError("windows_dpapi_required")
    import ctypes as c
    from ctypes import wintypes as w

    class Blob(c.Structure):
        _fields_ = [("size", w.DWORD), ("data", c.POINTER(c.c_ubyte))]

    buffer = c.create_string_buffer(data)
    source = Blob(len(data), c.cast(buffer, c.POINTER(c.c_ubyte)))
    target = Blob()
    crypt = c.WinDLL("crypt32", use_last_error=True)
    kernel = c.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [c.POINTER(Blob), c.c_void_p, c.c_void_p, c.c_void_p,
                   c.c_void_p, w.DWORD, c.POINTER(Blob)]
    fn.restype = w.BOOL
    kernel.LocalFree.argtypes = [c.c_void_p]
    kernel.LocalFree.restype = c.c_void_p
    if not fn(c.byref(source), None, None, None, None, 1, c.byref(target)):
        raise RuntimeError("dpapi_failed")
    try:
        return c.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    result = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(result, dict) or result.get("schema") != 1
            or not isinstance(result.get("notified_signature"), str)
            or not isinstance(result.get("last_notification_at", 0), (int, float))):
        raise ValueError("invalid_state")
    return result


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def bounded_logs(docker: str) -> dict:
    unavailable = {"status": "unavailable", "since": "10m", "services": {
        service: {"status": "unavailable", "error_lines": None} for service in SERVICES}}
    try:
        probe = subprocess.run([docker, "inspect", "--format", "{{.State.Running}}", *SERVICES],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
        states = probe.stdout.decode("ascii").splitlines()
        if probe.returncode or len(states) != len(SERVICES) or any(s not in ("true", "false") for s in states):
            return unavailable
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return unavailable
    running = dict(zip(SERVICES, states))

    def run(args, **kwargs):
        # 세 서비스 순차 조회. 폭주한 로그를 잘라 놓고 정상으로 판정하지 않는다.
        # 중지된 컨테이너도 docker logs는 성공할 수 있으므로 가동 상태를 먼저 확인한다.
        if running[args[-1]] != "true":
            return subprocess.CompletedProcess(args, 1, b"", b"")
        result = subprocess.run(args[:-1] + ["--tail", str(MAX_LINES), args[-1]],
                                **{**kwargs, "timeout": 15})
        if len((result.stdout + b"\n" + result.stderr).splitlines()) >= MAX_LINES:
            return subprocess.CompletedProcess(args, 1, b"", b"")
        return result

    return check_logs(docker, "10m", runner=run)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_discord(webhook: str, text: str) -> None:
    parsed = urlsplit(validate_webhook(webhook))
    url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "wait=true", ""))
    body = json.dumps({"content": text, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json",
                                             "User-Agent": "Qurious-Credential-Watchdog/1"})
    # 자동 재전송·리디렉션 없음. Discord가 메시지 ID를 반환한 경우만 전달 확인.
    with build_opener(NoRedirect()).open(request, timeout=10) as response:
        ack = json.loads(response.read(65536))
        if response.status != 200 or not ack.get("id"):
            raise RuntimeError("delivery_not_confirmed")


def observation(result: dict) -> tuple[str, str]:
    if result.get("status") not in ("ok", "error", "unavailable"):
        raise ValueError("invalid_observation")
    safe = []
    for service in SERVICES:
        row = result["services"][service]
        if row["status"] not in ("ok", "error", "unavailable"):
            raise ValueError("invalid_service_status")
        safe.append((service, row["status"]))
    return result["status"], json.dumps(safe, separators=(",", ":"))


def run_once(result: dict, state: dict, sender, *, now: float) -> tuple[dict, dict, int]:
    status, signature = observation(result)
    previous = state.get("notified_signature", "")
    repeated = (status != "ok" and signature == previous
                and now - state.get("last_notification_at", 0) >= REMIND_SECONDS)
    needs_send = (signature != previous and (status != "ok" or bool(previous))) or repeated
    updated = {**state, "schema": 1, "observed_at": now, "status": status}
    outcome = "suppressed"
    if needs_send:
        kind = "로그 감시 정상화" if status == "ok" else "암호화 오류 관측" if status == "error" else "로그 조회 실패"
        detail = " · ".join(f"{service}: {result['services'][service]['status']}" for service in SERVICES)
        stamp = datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds")
        note = ("최근 10분 로그 조회 성공·암호화 오류 미관측. 키 복호화 기능 자체의 복구 확인은 별도입니다."
                if status == "ok" else "앱 키·DB와 독립된 Windows 호스트 감시입니다. 원문·비밀값은 전송하지 않습니다.")
        message = f"[Qurious 호스트 경보] {kind}{' (1시간 지속)' if repeated else ''}\n{stamp}\n{detail}\n{note}"
        try:
            sender(message)
        except Exception:
            # URL이 든 urllib 예외 등을 출력/저장하지 않는다. 다음 회차에서 다시 시도한다.
            updated.setdefault("notified_signature", previous)
            return {"status": status, "notification": "failed"}, updated, 3
        updated.update(notified_signature=signature, last_notification_at=now)
        outcome = "sent"
    elif not previous:
        updated.update(notified_signature=signature, last_notification_at=0)
        outcome = "initial_ok"
    return {"status": status, "notification": outcome}, updated, {"ok": 0, "error": 1, "unavailable": 2}[status]


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--configure", action="store_true", help="웹훅을 표준입력 한 줄로 받아 DPAPI 저장")
    parser.add_argument("--docker", default="docker.exe", help="설정 때 사용할 Docker 실행 파일")
    parser.add_argument("--test", action="store_true", help="표시가 붙은 연결 시험 알림 1건; 감시 상태는 변경하지 않음")
    args = parser.parse_args(argv)
    try:
        if args.configure:
            if args.test or args.config.exists():
                raise ValueError("configuration_exists_or_invalid_mode")
            value = validate_webhook(sys.stdin.readline().strip())
            write_json(args.config, {"schema": 1, "docker": args.docker,
                                     "discord_dpapi": base64.b64encode(protect(value.encode())).decode()})
            print(json.dumps({"status": "configured", "storage": "current_user_dpapi"}))
            return 0
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if config.get("schema") != 1 or not isinstance(config.get("docker"), str):
            raise ValueError("invalid_config")
        webhook = validate_webhook(protect(base64.b64decode(config["discord_dpapi"], validate=True), decrypt=True).decode())
        if args.test:
            send_discord(webhook, "[Qurious 호스트 경보 · 연결 시험] Windows 독립 경보 경로 확인입니다. 실제 키 장애·주문 발생 알림이 아닙니다.")
            print(json.dumps({"status": "test_sent", "notification": "confirmed"}))
            return 0
        state_path = args.config.with_name("state.json")
        with exclusive_lock(args.config.with_name("watchdog.lock")):
            result, state, code = run_once(bounded_logs(config["docker"]), load_state(state_path),
                                           lambda text: send_discord(webhook, text), now=datetime.now(timezone.utc).timestamp())
            write_json(state_path, state)
        print(json.dumps(result))
        return code
    except Exception:
        print(json.dumps({"status": "watchdog_failed", "notification": "not_confirmed"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
