"""격리 PostgreSQL/Redis에서 실제 Beat·worker 종료/재시작·HTTP 알림을 검증한다.

DATABASE_URL의 DB 이름은 qurious_operations_*_test, Redis 호스트는
operations-redis여야 한다. 외부 통신 없는 Docker 네트워크에서 실행한다.
전략 본문만 합성 성공/실패/정지로 바꾸며 주문·외부 알림은 보내지 않는다.
결과와 자식 프로세스 로그는 --out 폴더에 남긴다.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def guard():
    database_url = urlparse(os.environ["DATABASE_URL"])
    database = database_url.path.lstrip("/")
    assert database_url.hostname == "test-db"
    assert database.startswith("qurious_operations_") and database.endswith("_test")
    assert urlparse(os.environ["REDIS_URL"]).hostname == "operations-redis"
    assert os.environ.get("QURIOUS_ALLOW_LIVE_TRADING", "").lower() not in ("1", "true", "yes")
    assert os.environ.get("KIS_PAPER_BATCH_ENABLED", "false").lower() == "false"


def configure():
    guard()
    from app.celery_app import celery_app
    from app.services import auto_trade
    from app.lib.redis_cache import get_redis

    async def synthetic_cycle(user_id):
        redis = get_redis()
        await redis.incr("operations:calls:" + user_id)
        mode = await redis.get("operations:mode:" + user_id)
        if mode == "crash":
            await redis.set("operations:entered:" + user_id, "1")
            await asyncio.Event().wait()
        if mode == "fail":
            raise RuntimeError("synthetic failure; this detail must not enter the run record")

    auto_trade._run_quant_cycle = synthetic_cycle
    # 한 시간 칸 안에서 짧은 Beat 주기를 여러 번 보내 중복을 검사한다.
    auto_trade._INTERVAL_SEC = 3600
    celery_app.conf.update(
        beat_schedule={"operations-cycle": {
            "task": "quant.auto_trade_cycle", "schedule": 1.0,
        }},
        task_default_queue="operations-test",
    )
    return celery_app


async def database_action(operation):
    from app.database.postgres import connect_postgres, close_postgres, get_session_factory
    await connect_postgres()
    try:
        async with get_session_factory()() as db:
            return await operation(db)
    finally:
        await close_postgres()


def database(operation):
    return asyncio.run(database_action(operation))


def wait_until(check, description, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := check():
            return value
        time.sleep(.2)
    raise AssertionError("timeout: " + description)


def main(out):
    guard()
    import redis
    from sqlalchemy import select, update, func
    from app.models import User, BrokerSettings, ExecutionRun, NotificationLog, NotificationSettings, LiveOrder, OrderIntent
    app = configure()
    cache = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    out.mkdir(parents=True, exist_ok=True)
    assert not (out / "result.json").exists(), "기존 증거를 덮어쓰지 않습니다"
    deliveries = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert "text" in payload
            deliveries.append(self.path)
            self.send_response(500 if self.path.endswith("/fail") else 200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    receiver = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=receiver.serve_forever, daemon=True).start()
    children, handles = [], []

    def start(role):
        handle = (out / (role + ".log")).open("a")
        handles.append(handle)
        process = subprocess.Popen([sys.executable, __file__, "--" + role, "--out", str(out)],
                                   stdout=handle, stderr=subprocess.STDOUT)
        children.append(process)
        return process

    def stop(process, kill=False):
        if process.poll() is None:
            process.kill() if kill else process.terminate()
            process.wait(timeout=15)

    def seed(mode="success", delivery="ok"):
        uid = uuid.uuid4()
        async def create(db):
            await db.execute(update(BrokerSettings).values(quant_auto_enabled=False))
            db.add(User(id=uid, name="operations test", email=f"{uid}@example.com",
                        password_hash="synthetic", client_id=uid.hex))
            await db.flush()
            db.add(BrokerSettings(user_id=uid, quant_auto_enabled=True, paper=True))
            db.add(NotificationSettings(user_id=uid, channels=["slack"],
                slack_webhook_url=f"http://127.0.0.1:{receiver.server_port}/{uid}/{delivery}"))
            await db.commit()
        database(create)
        cache.set("operations:mode:" + str(uid), mode)
        return uid

    def state(uid):
        async def query(db):
            runs = (await db.scalars(select(ExecutionRun).where(ExecutionRun.user_id == uid))).all()
            logs = (await db.scalars(select(NotificationLog).where(NotificationLog.user_id == uid))).all()
            return {"runs": [{"status": r.status, "detail": r.detail, "finished": bool(r.finished_at)} for r in runs],
                    "notifications": [{"status": n.delivery_status, "kind": n.kind, "ref": n.ref} for n in logs],
                    "calls": int(cache.get("operations:calls:" + str(uid)) or 0),
                    "deliveries": sum(str(uid) in p for p in deliveries)}
        return database(query)

    def send():
        return app.send_task("quant.auto_trade_cycle").get(timeout=30)

    checks = {}
    try:
        worker = start("worker")
        uid = seed()
        beat = start("beat")
        wait_until(lambda: state(uid)["runs"] and state(uid)["runs"][0]["finished"], "Beat scheduled run")
        wait_until(lambda: (out / "worker.log").read_text().count("succeeded in") >= 2, "second scheduled delivery")
        stop(beat)
        result = state(uid)
        assert len(result["runs"]) == 1 and result["runs"][0]["status"] == "COMPLETED"
        assert result["calls"] == 1 and result["deliveries"] == 0
        checks["beat_duplicate_suppression"] = result

        for delivery in ("ok", "fail"):
            uid = seed("fail", delivery)
            assert send()["failed"] == 1
            assert send()["failed"] == 1
            result = state(uid)
            assert result["calls"] == result["deliveries"] == len(result["notifications"]) == 1
            assert result["runs"] == [{"status": "FAILED", "detail": {"code": "EXECUTION_FAILED"}, "finished": True}]
            assert result["notifications"][0]["status"] == ("delivered" if delivery == "ok" else "failed")
            checks["failure_notification_" + delivery] = result

        uid = seed("crash")
        app.send_task("quant.auto_trade_cycle")
        wait_until(lambda: cache.get("operations:entered:" + str(uid)), "cycle entered before SIGKILL")
        assert state(uid)["runs"][0]["status"] == "RUNNING"
        stop(worker, kill=True)
        worker = start("worker")
        send()  # 새 프로세스로 동일 시간 칸을 다시 전달한다.
        send()
        result = state(uid)
        assert result["runs"] == [{"status": "INTERRUPTED", "detail": {"code": "PROCESS_INTERRUPTED"}, "finished": True}]
        assert result["calls"] == result["deliveries"] == len(result["notifications"]) == 1
        checks["sigkill_restart_same_slot"] = result

        uid = seed()
        assert send()["ran"] == 1
        result = state(uid)
        assert result["runs"][0]["status"] == "COMPLETED" and result["calls"] == 1
        checks["new_work_after_restart"] = result

        async def order_counts(db):
            return {"live_orders": await db.scalar(select(func.count()).select_from(LiveOrder)),
                    "order_intents": await db.scalar(select(func.count()).select_from(OrderIntent))}
        counts = database(order_counts)
        assert counts == {"live_orders": 0, "order_intents": 0}
        result = {"ok": True, "checks": checks, "orders": counts,
                  "scope": "real Beat/Redis/Celery/PostgreSQL/local HTTP; synthetic strategy; no external delivery"}
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False))
    finally:
        for child in children:
            stop(child)
        for handle in handles:
            handle.close()
        receiver.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--beat", action="store_true")
    args = parser.parse_args()
    if args.worker:
        configure().worker_main(["worker", "--pool=solo", "--concurrency=1", "--loglevel=INFO", "--without-mingle", "--without-gossip"])
    elif args.beat:
        configure().start(["beat", "--loglevel=INFO", "--max-interval=1", "--schedule=" + str(args.out / "beat-state")])
    else:
        main(args.out)
