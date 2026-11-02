"""개인 KIS 모의 재주문 시험. 기본은 조회, --execute만 45분 창을 잠시 적용한다."""
import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime
try:
    import fcntl
except ImportError:
    fcntl = None  # 실행은 Linux Docker 전용. Windows에서 --help/소스 조회는 허용한다.
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.database import postgres as pg
from app.lib.redis_cache import connect_redis, close_redis
from app.models import BrokerSettings, LiveOrder
from app.services import kis_order_recovery as recovery
from app.services.execution_policy import policy_for

TERMINAL = {"restored", "unchanged"}
LEASE_SECONDS = 120


def write(path, value, *, exclusive=False):
    """설정 변경 전 기록을 디스크에 확정한다. 사용자 자료는 Git 제외 영구 볼륨에 둔다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if exclusive:
        target = path
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    else:
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        target = Path(temporary)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        if not exclusive:
            os.replace(target, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        if not exclusive:
            target.unlink(missing_ok=True)
        raise


@contextmanager
def locked(path):
    if fcntl is None:
        raise RuntimeError("시험 도구는 Linux Docker에서 실행하세요.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


async def inspect(uid, parent_id):
    """당일 시험 매도 1주와 승인된 위험 설정만 검사. 증권사 전송·설정 변경 없음."""
    async with pg.get_session_factory()() as db:
        parent = await recovery.parent_for(db, uid, parent_id)
        row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
        _, _, account_ref = recovery.verify_account(parent, row)
        policy = policy_for(row)
        now = recovery.datetime.now(recovery.control.KST)
        recovery.check_window(now.date())
        if (parent.created_at.astimezone(recovery.control.KST).date() != now.date()
                or parent.side != "SELL" or parent.strategy_id != "manual_broker"
                or parent.strategy_version != 1 or parent.quantity != 1 or parent.filled_quantity != 0
                or parent.status != "CANCELLED" or parent.retry_of is not None):
            raise ValueError("당일 취소 확정된 시험용 manual_broker 판 1 매도 1주만 가능합니다.")
        if await db.scalar(select(LiveOrder.id).where(LiveOrder.retry_of == parent.id)):
            raise ValueError("이미 재주문 기록이 있습니다. 새 주문 없이 해당 기록을 확인하세요.")
        if (row.quant_auto_enabled or row.risk_kill_switch or policy.retry_enabled
                or row.risk_cooldown_min != 30 or policy.retry_window_min != 15
                or policy.retry_max_attempts != 1 or policy.retry_price_deviation_pct != 1):
            raise ValueError("자동 실행 OFF·쿨다운 30분·창 15분·최대 1회·가격 이탈 1%가 필요합니다.")
        age = (now - parent.created_at).total_seconds()
        if not 30 * 60 <= age < 43 * 60:
            raise ValueError("새 원 주문 생성 후 30~43분 사이에만 시험합니다.")
        return {"user_id": str(uid), "parent_id": str(parent_id), "settings_id": str(row.id),
                "account_ref": account_ref, "day": now.date().isoformat(),
                "original_policy": dict(row.quant_execution_policy or {}), "parent_price": parent.price,
                "status": "prepared", "owner_pid": os.getpid(), "deadline": time.time() + LEASE_SECONDS}


async def activate(record):
    async with pg.get_session_factory()() as db:
        row = await db.scalar(select(BrokerSettings).where(
            BrokerSettings.id == uuid.UUID(record["settings_id"]),
            BrokerSettings.user_id == uuid.UUID(record["user_id"])).with_for_update())
        if row is None or dict(row.quant_execution_policy or {}) != record["original_policy"]:
            raise ValueError("준비 후 설정이 바뀌었습니다.")
        _, _, ref = recovery.context(row)
        policy = policy_for(row)
        if (ref != record["account_ref"] or row.quant_auto_enabled or row.risk_kill_switch
                or row.risk_cooldown_min != 30 or policy.retry_enabled
                or time.time() >= record["deadline"]):
            raise ValueError("시험 직전 계좌·설정·원복 기한이 바뀌었습니다.")
        row.quant_execution_policy = {**record["original_policy"], "retry_window_min": 45}
        await db.commit()


async def restore(path):
    """해당 시험의 원복을 DB와 대조. 완료된 옛 시험은 재적용하지 않는다."""
    path = Path(path)
    with locked(path):
        record = json.loads(path.read_text())
        if record["status"] in TERMINAL:
            return {"status": record["status"], "duplicate": True}
        async with pg.get_session_factory()() as db:
            row = await db.scalar(select(BrokerSettings).where(
                BrokerSettings.id == uuid.UUID(record["settings_id"]),
                BrokerSettings.user_id == uuid.UUID(record["user_id"])).with_for_update())
            if row is None:
                raise ValueError("원래 설정 행이 없어 원복을 확인할 수 없습니다.")
            _, _, ref = recovery.context(row)
            if ref != record["account_ref"]:
                raise ValueError("시험 후 계좌가 변경됐습니다. 새 계좌 설정을 덮어쓰지 않습니다.")
            current = dict(row.quant_execution_policy or {})
            original = record["original_policy"]
            old = original.get("retry_window_min", 15)
            if current.get("retry_window_min", 15) == old:
                status = "unchanged"
            elif current.get("retry_window_min") == 45:
                # 이 시험이 바꾼 필드 하나만 원복. 비상 정지·새 위험 설정을 되돌리지 않는다.
                if "retry_window_min" in original:
                    current["retry_window_min"] = original["retry_window_min"]
                else:
                    current.pop("retry_window_min", None)
                row.quant_execution_policy = current
                await db.commit()
                status = "restored"
            else:
                raise ValueError("시험 중 재주문 창이 다시 변경됐습니다. 덮어쓰지 않고 확인이 필요합니다.")
        record.update(status=status, restored_at=datetime.now(recovery.control.KST).isoformat())
        write(path, record)
        return {"status": status, "policy_restored": True}


def owner_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def watch(path, restore_command):
    """별도 프로세스. 실행기 SIGKILL 또는 120초 만료 때 주문 없이 원복만 수행한다."""
    path = Path(path)
    ready = path.with_suffix(".ready")
    ready.touch(mode=0o600, exist_ok=False)
    try:
        while True:
            record = json.loads(path.read_text())
            if record["status"] in TERMINAL:
                return
            if not owner_alive(record["owner_pid"]) or time.time() >= record["deadline"]:
                # 실행기 finally와 경합하거나 DB가 잠깐 끊겨도 원복을 다시 확인한다.
                try:
                    result = subprocess.run(restore_command, capture_output=True, timeout=30)
                    if result.returncode == 0:
                        return
                except (subprocess.TimeoutExpired, OSError):
                    pass
            time.sleep(1)
    finally:
        ready.unlink(missing_ok=True)


async def run(uid, parent_id, directory, *, execute=False):
    record = await inspect(uid, parent_id)
    if not execute:
        return {"status": "DRY_RUN", "parent_id": str(parent_id), "quantity": 1,
                "original_price": record["parent_price"], "window_during_retry": 45, "settings_changed": False}
    directory = Path(directory)
    # 같은 사용자의 시험은 하나. 과거 시험 원복 완료 파일을 새 시험 증거로 쓰지 않는다.
    with locked(directory / str(uid)):
        for pending in directory.glob(str(uid) + "-*.json"):
            if json.loads(pending.read_text())["status"] not in TERMINAL:
                raise ValueError("미원복 시험이 있습니다. restore 명령으로 먼저 복구하세요.")
        path = directory / f"{uid}-{parent_id}.json"
        write(path, record, exclusive=True)
        base = [sys.executable, str(Path(__file__).resolve())]
        watcher = subprocess.Popen(base + ["watch", "--journal", str(path.resolve())],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            for _ in range(100):
                if watcher.poll() is not None:
                    raise ValueError("독립 원복 감시기를 시작하지 못했습니다.")
                if path.with_suffix(".ready").exists():
                    break
                await asyncio.sleep(0.1)
            else:
                raise ValueError("원복 감시기 준비 시간을 초과했습니다.")
            with locked(path):
                await activate(record)
            result = await asyncio.wait_for(recovery.retry(uid, parent_id), timeout=90)
        finally:
            # SIGKILL은 독립 감시기가 처리. 컨테이너/DB 중단은 재기동 후 restore가 필요하다.
            for _ in range(10):
                try:
                    restored = await restore(path)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.2)
            else:
                raise RuntimeError("원복 감시기가 처리 중입니다. journal과 DB를 확인하세요.")
        return {**result, "policy_restored": restored["status"] in TERMINAL}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    retry = commands.add_parser("retry")
    retry.add_argument("--user-id", type=uuid.UUID, required=True)
    retry.add_argument("--parent-id", type=uuid.UUID, required=True)
    retry.add_argument("--directory", type=Path, default=Path("data/local-run/kis-recovery-trials"))
    retry.add_argument("--execute", action="store_true")
    for command in ("restore", "watch"):
        commands.add_parser(command).add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "watch":
        watch(args.journal, [sys.executable, str(Path(__file__).resolve()), "restore", "--journal", str(args.journal)])
        return
    await pg.connect_postgres()
    try:
        if args.command == "restore":
            result = await restore(args.journal)
        else:
            await connect_redis()
            result = await run(args.user_id, args.parent_id, args.directory, execute=args.execute)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await close_redis()
        await pg.close_postgres()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(main())
    except Exception as exc:
        # DB/HTTP 예외 원문에 자격증명이 포함될 수 있어 타입만 출력한다.
        print(json.dumps({"status": "needs_review", "error_type": type(exc).__name__}))
        raise SystemExit(1)
