"""TC-CW — PC 작업자 `scripts/collect_worker.py` (목표 기능 ① 수집 단추 · 2026-10-10).

작업자는 작업 스케줄러가 매 분 띄운다. 한 바퀴에 요청 표의 대기 줄을 먼저 온 차례로 보고, 받지 않는 요청은 거절 · 막는 때 ·
다른 실행이면 기다림 · 돌 수 있는 줄은 가져가 러너를 인자 목록으로 부르고 러너 기록(요청 번호)으로 결과를 적는다.
판정의 정본은 러너(daily_update)다 — 여기서는 러너를 가짜로 바꿔 끼워 작업자의 판단만 본다(진짜 러너와의 맞물림은 TC-DU).

DB 시험은 일회용 시험 DB(`QURIOUS_TEST_DATABASE_URL` · `scripts/personal/test.ps1`)가 있을 때만 돈다.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
import uuid

import pytest

from scripts import collect_worker as cw
from scripts import daily_update as du

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime(2026, 10, 12, 14, 0, tzinfo=KST)
RID = "11111111-2222-3333-4444-555555555555"

FAKE_STEPS = {s.name: s for s in (
    du.Step("price", ["-c", "pass"], 30, label="시세", group="받기", desc="시세"),
    du.Step("news", ["-c", "pass"], 10, fatal=False, label="정책뉴스", group="받기", desc="뉴스"),
    du.Step("upload", ["-c", "pass"], 60, upload=True, label="올리기", group="백업", desc="올림"),
    du.Step("signals", ["-c", "pass"], 10, fatal=False, label="신호", group="계산", desc="신호",
            fill_args=["-c", "pass", "--from", "{from}", "--to", "{to}"]),
)}


def _rec(kind="step", name="price", rc=0, steps=None, stopped=None, rid=RID, reason=None):
    if steps is None:
        steps = [{"name": name, "rc": rc, "seconds": 12.0, "note": ""} | ({"reason": reason} if reason else {})]
    return {"started_at": "2026-10-12T14:00:00+09:00", "finished_at": "2026-10-12T14:41:00+09:00",
            "only": name if kind == "step" else None, "ok": rc == 0 and not stopped, "stopped": stopped,
            "price_max": "20261008", "steps": steps, "request_id": rid, "trigger": "manual", "rc": rc,
            "log": "data/collector/logs/daily_update-x.log"}


# ── 순수 — 결과 판정 ──────────────────────────────────────────────────────
def test_outcome_maps_runner_result_like_runner_screen():
    """TC-CW-01 · 러너가 돌아온 뒤의 판정 — 러너 화면과 같은 말(성공 끝 · 멈추지 않는 단계 실패 경고 · 멈추는 단계 실패 실패 ·
    회차 멈춤 실패) · 75(막힘)는 끝이 아니라 다시 기다림 · 러너 기록에 요청 줄이 없으면 「끝」 으로 적지 않는다."""
    o = lambda kind, rc, rec, fatal=True: cw.outcome(kind, rc, rec, label="시세" if kind == "step" else "전체 수집",  # noqa: E731
                                                       fatal=fatal, tempfail=75, labels={"dividend": "배당", "schedule": "기업 일정"}.get)
    assert o("step", 0, _rec()) == ("done", "시세 · 12초 · 시세 기준일 20261008")
    assert o("step", 1, _rec(rc=1))[0] == "failed"
    assert o("step", 1, _rec(rc=1), fatal=False)[0] == "warning"
    st, msg = o("step", 3, _rec(rc=None, reason="app_db_down"))
    assert st == "warning" and "앱 DB 꺼짐" in msg
    assert o("step", 75, None)[0] == "requeue" and o("all", 75, None)[0] == "requeue"
    st, msg = o("step", 0, None)
    assert st == "failed" and "결과 기록 없음" in msg
    ok_all = _rec("all", steps=[{"name": "price", "rc": 0}, {"name": "adjusted", "rc": None}])
    assert o("all", 0, ok_all) == ("done", "단계 2 · 41분 · 시세 기준일 20261008")
    warn = _rec("all", rc=1, steps=[{"name": "price", "rc": 0}, {"name": "dividend", "rc": 1}, {"name": "schedule", "rc": 1}])
    st, msg = o("all", 1, warn)
    assert st == "warning" and msg.startswith("경고 2(배당 · 기업 일정)")
    st, msg = o("all", 1, _rec("all", rc=1, stopped="price 종료코드 1"))
    assert st == "failed" and "멈춤 — price 종료코드 1" in msg


# ── 순수 — 러너에 묻는 것(진짜 단계 목록) ─────────────────────────────────
def test_command_is_an_argument_list_from_runner_steps():
    """TC-CW-02 · 러너를 부르는 인자 목록 — 셸을 거치지 않고, 단계 이름은 러너 단계 목록에서 온 것 · 올리기 단계와 전체 수집의
    올리기는 작업자가 허락받았을 때만 ``--upload`` · 요청 번호를 넘겨 러너 기록에 남게 한다."""
    r = cw.Runner()
    up = next(s.name for s in du.STEPS if s.upload)
    plain = next(s.name for s in du.STEPS if not s.upload)
    cmd = r.command("step", plain, RID, True)
    assert cmd[0] == du.child_python() and cmd[1].endswith(os.path.join("scripts", "daily_update.py"))
    assert cmd[2:] == ["run", "--only", plain, "--request", RID]
    assert r.command("step", up, RID, True)[2:] == ["run", "--only", up, "--upload", "--request", RID]
    assert r.command("all", "", RID, True)[2:] == ["run", "--manual", "--upload", "--request", RID]
    assert r.command("all", "", RID, False)[2:] == ["run", "--manual", "--request", RID]
    assert all(isinstance(x, str) for x in cmd)


def test_reject_reason_rechecks_against_runner_steps():
    """TC-CW-03 · 작업자는 DB 줄을 믿지 않는다 — 러너 단계 목록에 없는 이름 · 허락 없는 올리기 단계는 거절(기다려도 안 바뀐다)."""
    r = cw.Runner()
    up = next(s.name for s in du.STEPS if s.upload)
    plain = next(s.name for s in du.STEPS if not s.upload)
    assert "목록에 없는" in r.reject_reason("step", "rm -rf", True)
    assert "올리기" in r.reject_reason("step", up, False)
    assert r.reject_reason("step", up, True) == "" and r.reject_reason("step", plain, False) == ""
    assert r.reject_reason("all", "", False) == "" and "종류" in r.reject_reason("shell", "", True)


def test_runner_asks_the_runner_for_windows_and_lock(tmp_path, monkeypatch):
    """TC-CW-04 · 막는 때 · 다른 실행은 러너 함수 그대로 — 전체 수집 11:00 ~ 13:30 · 한 단계는 그 단계 한도로 · 러너 잠금을 읽기만."""
    r = cw.Runner()
    at = lambda h, m: datetime.datetime(2026, 10, 12, h, m, tzinfo=du.KST)  # noqa: E731
    assert r.blocked("all", "", at(11, 30)) and r.blocked("all", "", at(13, 30))
    assert r.blocked("all", "", at(10, 59)) == "" and r.blocked("all", "", at(13, 31)) == ""
    assert r.blocked("step", "price", at(12, 10)) and r.blocked("step", "price", at(11, 50)) == ""
    lock = tmp_path / "daily_update.lock"
    monkeypatch.setattr(du, "LOCK_PATH", lock)
    assert r.busy(at(14, 0)) == ""
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": at(13, 59).isoformat()}), encoding="utf-8")
    assert "다른 실행" in r.busy(at(14, 0)) and lock.exists(), "읽기만 한다(지우지 않는다)"
    assert r.tempfail == du.EX_TEMPFAIL == 75


def test_fill_request_is_an_argument_list_with_checked_dates():
    """TC-CW-13 · 빠진 날 채우기 요청(사용자 결정 2026-10-10 — 새 종류 fill) — 러너 `run --fill <단계> --from --to` 를 인자 목록으로 ·
    채우기 인자가 없는 단계 · 목록 밖 단계 · 날짜가 없거나 틀린 줄 · 31일 넘는 줄은 거절(기다려도 안 바뀐다) · 막는 때는 러너의
    채우기 창(범위로 센 시간 한도) · 시간 한도도 범위로 · 이름은 「신호 빠진 날 채우기」."""
    r = cw.Runner()
    sig = r.step("signals")
    kw = {"date_from": "2026-10-02", "date_to": "2026-10-06"}
    cmd = r.command("fill", "signals", RID, True, **kw)
    assert cmd[2:] == ["run", "--fill", "signals", "--from", "2026-10-02", "--to", "2026-10-06", "--request", RID]
    assert all(isinstance(x, str) for x in cmd)
    assert r.reject_reason("fill", "signals", True, **kw) == ""
    assert "채우기" in r.reject_reason("fill", "price", True, **kw)
    assert "목록에 없는" in r.reject_reason("fill", "gone", True, **kw)
    assert "31일" in r.reject_reason("fill", "signals", True, date_from="2026-09-01", date_to="2026-10-06")
    assert "날짜" in r.reject_reason("fill", "signals", True, date_from=None, date_to="2026-10-06")
    at = lambda h, m: datetime.datetime(2026, 10, 12, h, m, tzinfo=du.KST)  # noqa: E731
    assert r.blocked("fill", "signals", at(12, 0), **kw) and r.blocked("fill", "signals", at(14, 0), **kw) == ""
    assert r.timeout_s("fill", "signals", **kw) == (du.fill_timeout_min(sig, "2026-10-02", "2026-10-06") + cw.STEP_GRACE_MIN) * 60
    assert r.label("fill", "signals") == "신호 빠진 날 채우기"


def test_outcome_says_why_and_the_fill_range():
    """TC-CW-14 · 결과 한 줄에 까닭(DF-101) — 러너가 그 단계 줄에 적은 `error` 를 「까닭: …」 으로 붙인다(한 단계 · 채우기는 그 줄 ·
    전체 수집은 첫 실패 단계의 이름과 함께) · 채우기는 범위를 적는다 · 결과 칸 300자를 넘지 않는다(서버 칸과 같은 한도)."""
    why = "DartError: status=800 '시스템 점검으로 인한 서비스가 중지 중입니다.'"
    st, msg = cw.outcome("step", 1, _rec(rc=1, steps=[{"name": "dividend", "rc": 1, "seconds": 25.0, "error": why}]),
                         label="배당", fatal=False, tempfail=75)
    assert st == "warning" and msg == f"배당 · 종료코드 1 · 25초 · 까닭: {why}"
    rec = _rec("all", rc=1, steps=[{"name": "price", "rc": 0}, {"name": "dividend", "rc": 1, "error": why},
                                   {"name": "schedule", "rc": 1, "error": "다른 까닭"}])
    st, msg = cw.outcome("all", 1, rec, label="전체 수집", fatal=True, tempfail=75,
                         labels={"dividend": "배당", "schedule": "기업 일정"}.get)
    assert st == "warning" and msg.startswith("경고 2(배당 · 기업 일정)") and msg.endswith(f"까닭: 배당 — {why}")
    fill = _rec("fill", name="signals", steps=[{"name": "signals", "rc": 0, "seconds": 95.0}]) | {
        "fill": {"from": "2026-10-02", "to": "2026-10-06"}}
    assert cw.outcome("fill", 0, fill, label="신호 빠진 날 채우기", fatal=False, tempfail=75) == (
        "done", "신호 빠진 날 채우기 · 2026-10-02 ~ 2026-10-06 · 1분 35초")
    bad = fill | {"rc": 1, "steps": [{"name": "signals", "rc": 1, "seconds": 3.0, "error": "OSError: 연결 거부"}]}
    st, msg = cw.outcome("fill", 1, bad, label="신호 빠진 날 채우기", fatal=False, tempfail=75)
    assert st == "warning" and msg.endswith("까닭: OSError: 연결 거부") and "2026-10-02 ~ 2026-10-06" in msg
    long = _rec(rc=1, steps=[{"name": "price", "rc": 1, "seconds": 1.0, "error": "가" * 400}])
    assert len(cw.outcome("step", 1, long, label="시세", fatal=True, tempfail=75)[1]) <= 300


def test_task_xml_every_minute(tmp_path):
    """TC-CW-05 · 작업 정의 — 1분마다 끝없이 · 앞 바퀴가 돌면 새로 띄우지 않음 · 로그온해 있을 때만 · 올리기 허락은 명령줄에."""
    xml = cw.task_xml(True, python_w="pythonw", root=tmp_path, today=datetime.date(2026, 10, 10))
    assert "<TimeTrigger>" in xml and "<Interval>PT1M</Interval>" in xml and "<Duration>" not in xml
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml and "<StartBoundary>2026-10-10T00:00:00</StartBoundary>" in xml
    assert "run --allow-upload</Arguments>" in xml and "&quot;" in xml
    assert "--allow-upload" not in cw.task_xml(False, python_w="pythonw", root=tmp_path)


def test_run_entry_lock_and_config(tmp_path, monkeypatch):
    """TC-CW-06 · 진입 — 앞 바퀴가 잠금을 쥐고 있으면 아무것도 하지 않고 0 · 앱 DB 주소를 못 만들면 78(설정 결함 · 상태 파일에 까닭) ·
    앱 DB 가 꺼져 있으면 0 과 상태 파일 「db_down」(화면도 없으니 이 PC 에만 남긴다) · 어느 경우든 작업자 잠금을 남기지 않는다."""
    monkeypatch.setattr(cw, "LOCK_PATH", tmp_path / "collect_worker.lock")
    monkeypatch.setattr(cw, "STATE_PATH", tmp_path / "collect_worker.json")
    monkeypatch.setattr(cw, "LOG_DIR", tmp_path / "logs")
    calls = []
    monkeypatch.setattr(du, "host_app_db_env", lambda: calls.append("env") or ({}, "compose 를 읽지 못했다"))
    cw.LOCK_PATH.write_text(json.dumps({"pid": os.getpid(), "started_at": du._iso(du.now_kst())}), encoding="utf-8")
    assert cw.run(True) == 0 and calls == [], "앞 바퀴가 돈다 — 손대지 않는다"
    cw.LOCK_PATH.unlink()
    assert cw.run(True) == du.EX_CONFIG == 78
    st = json.loads(cw.STATE_PATH.read_text(encoding="utf-8"))
    assert st["state"] == "config_error" and "compose" in st["note"] and st["allow_upload"] is True
    monkeypatch.setattr(du, "host_app_db_env", lambda: ({"DATABASE_URL": "postgresql+asyncpg://u:secret@127.0.0.1:1/x"}, None))
    monkeypatch.setattr(du, "app_db_unreachable", lambda env: "연결 거부")
    assert cw.run(False) == 0
    st = json.loads(cw.STATE_PATH.read_text(encoding="utf-8"))
    assert st["state"] == "db_down" and "127.0.0.1:1/x" in st["note"] and "secret" not in json.dumps(st)
    assert not cw.LOCK_PATH.exists()


# ── 일회용 시험 DB — 가짜 러너로 한 바퀴 ─────────────────────────────────
DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB_URL, reason="일회용 시험 DB 없음 — scripts/personal/test.ps1 로 돈다")
CATALOG = {"by_name": {n: {"name": n, "label": s.label} for n, s in FAKE_STEPS.items()}, "steps": [], "guards": {}}


class FakeRunner(cw.Runner):
    """가짜 러너 — 자식 파이썬이 러너처럼 이력 한 줄(요청 번호)을 쓰고 정해 둔 종료코드로 끝난다."""

    def __init__(self, tmp, *, rc=0, blocked="", busy="", write=True, sleep=0.0, steps=None, kind_steps=None):
        self.hist, self.rc, self._blocked, self._busy = tmp / "history.jsonl", rc, blocked, busy
        self.write, self.sleep, self.calls = write, sleep, []
        self.kind_steps = kind_steps

    @property
    def tempfail(self) -> int:
        return 75

    def step(self, name):
        return FAKE_STEPS.get(name)

    def blocked(self, kind, name, now):
        return self._blocked

    def busy(self, now):
        return self._busy

    def command(self, kind, name, request_id, allow_upload):
        self.calls.append((kind, name, request_id, allow_upload))
        if len(self.calls) > 5:                          # 같은 요청을 되풀이해 부르면 시험이 끝없이 돌지 않고 실패하게
            raise RuntimeError(f"러너를 {len(self.calls)}번 불렀다 — 되풀이")
        rec = _rec(kind, name, rc=self.rc, rid=request_id, steps=self.kind_steps)
        code = (f"import sys,time; time.sleep({self.sleep}); "
                + (f"open({str(self.hist)!r},'a',encoding='utf-8').write({json.dumps(rec, ensure_ascii=False)!r}+chr(10)); "
                   if self.write else "")
                + f"sys.exit({self.rc})")
        return [sys.executable, "-c", code]

    def record(self, request_id):
        if not self.hist.exists():
            return None
        for line in reversed(self.hist.read_text(encoding="utf-8").splitlines()):
            r = json.loads(line)
            if r.get("request_id") == request_id:
                return r
        return None


def _db(scenario):
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    url = make_url(DB_URL)
    assert "test" in DB_URL and url.database != "fin_ai" and url.port != 15432, "일회용 시험 DB만 사용"

    async def go():
        engine = create_async_engine(DB_URL, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE collect_workers, collect_requests, audit_events, users CASCADE"))
            return await scenario(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(go())


async def _request(maker, kind="step", step="price"):
    from app.models import User
    from app.services import collect_requests as cq
    async with maker() as db:
        u = User(name="관리자", email=f"a-{uuid.uuid4().hex[:8]}@test.local", password_hash="x",
                 client_id=uuid.uuid4().hex[:16], roles=["user", "admin"])
        db.add(u)
        await db.commit()
        out, _ = await cq.create(db, kind=kind, step=step, user={"id": str(u.id), "client_id": u.client_id},
                                 catalog=CATALOG, now=NOW - datetime.timedelta(minutes=1))
        return out["id"]


async def _rows(maker):
    from sqlalchemy import select
    from app.models.collect import CollectRequest, CollectWorker
    async with maker() as db:
        reqs = {str(r.id): r for r in (await db.execute(select(CollectRequest))).scalars()}
        workers = list((await db.execute(select(CollectWorker))).scalars())
        return reqs, workers


def _ctx(maker, runner, allow_upload=True, beat_s=5.0):
    return cw.Ctx(name="PC-T", pid=4321, started=NOW, allow_upload=allow_upload, runner=runner, maker=maker,
                  now=lambda: NOW, beat_s=beat_s)


@pytest.fixture
def db_schema(rebalance_db_schema):
    return rebalance_db_schema


@needs_db
def test_cycle_runs_one_request_and_records_result(db_schema, tmp_path):
    """TC-CW-07 · 한 바퀴 — 대기 줄을 가져가 러너를 한 번 부르고, 러너 기록의 요청 줄로 끝 · 결과 · 로그 경로를 적는다 ·
    작업자 줄은 끝에 「쉬는 중」 · 전체 수집도 같은 길(허락받은 올리기를 넘김)."""
    fr = FakeRunner(tmp_path)

    async def scenario(maker):
        a = await _request(maker, "step", "price")
        out = await cw.cycle(_ctx(maker, fr))
        b = await _request(maker, "all", None)
        out2 = await cw.cycle(_ctx(maker, fr))
        return a, b, out, out2, await _rows(maker)

    a, b, out, out2, (reqs, workers) = _db(scenario)
    assert fr.calls == [("step", "price", a, True), ("all", "", b, True)]
    assert reqs[a].status == "done" and reqs[a].exit_code == 0 and reqs[a].worker == "PC-T"
    assert reqs[a].result.startswith("시세 · 12초") and reqs[a].log_path.endswith("daily_update-x.log")
    assert reqs[b].status == "done" and reqs[b].result.startswith("단계 1")
    assert out["handled"] == [{"id": a, "status": "done", "rc": 0}] and out2["state"] == "idle"
    assert len(workers) == 1 and workers[0].state == "idle" and workers[0].allow_upload is True


@needs_db
def test_cycle_waits_in_window_and_while_runner_busy(db_schema, tmp_path):
    """TC-CW-08 · 막는 때 · 다른 실행은 거절이 아니라 기다림 — 줄은 대기 그대로 · 러너를 부르지 않음 · 작업자 줄에 까닭."""
    async def scenario(maker):
        a = await _request(maker)
        w1 = await cw.cycle(_ctx(maker, FakeRunner(tmp_path, blocked="12:00 ~ 13:30 에는 돌리지 않는다")))
        w2 = await cw.cycle(_ctx(maker, FakeRunner(tmp_path, busy="다른 실행이 돌고 있다 (PID 1 · 12:30 시작)")))
        return a, w1, w2, await _rows(maker)

    a, w1, w2, (reqs, workers) = _db(scenario)
    assert reqs[a].status == "queued" and reqs[a].started_at is None
    assert w1["state"] == "waiting" and "시세 — 12:00 ~ 13:30" in w1["note"]
    assert w2["state"] == "waiting" and "다른 실행이 돌고 있다" in w2["note"] and w2["handled"] == []
    # 까닭 글은 러너가 준 한 줄 그대로 — 12:30 회차 실측에서 앞말이 두 번 겹쳐 나왔다(2026-10-10 · 포함만 봐서 못 잡음)
    assert w2["note"].count("다른 실행이 돌고 있다") == 1 and w2["note"].endswith("끝나면 돈다")
    assert workers[0].state == "waiting"


@needs_db
def test_tempfail_requeues_once_per_cycle(db_schema, tmp_path):
    """TC-CW-09 · 러너가 75(지금은 못 돈다)로 돌아오면 다시 대기로 — 이번 바퀴에는 다시 잡지 않는다(같은 막힘을 되풀이하지 않게)."""
    fr = FakeRunner(tmp_path, rc=75, write=False)

    async def scenario(maker):
        a = await _request(maker)
        out = await cw.cycle(_ctx(maker, fr))
        return a, out, await _rows(maker)

    a, out, (reqs, _) = _db(scenario)
    assert len(fr.calls) == 1 and out["handled"] == [{"id": a, "status": "requeue", "rc": 75}]
    assert reqs[a].status == "queued" and reqs[a].worker == "" and "다시 기다림" in reqs[a].result


@needs_db
def test_rejects_what_waiting_cannot_fix(db_schema, tmp_path):
    """TC-CW-10 · 거절 — 허락 없는 올리기 단계 · 목록에서 사라진 단계(DB 에 직접 들어온 줄)는 기다려도 안 바뀌니 거절 · 러너를 부르지 않는다."""
    from sqlalchemy import insert
    from app.models.collect import CollectRequest
    fr = FakeRunner(tmp_path)

    async def scenario(maker):
        up = await _request(maker, "step", "upload")
        async with maker() as db:
            rid = (await db.execute(insert(CollectRequest).values(           # 시험 시계에 맞춘 요청 시각(아니면 만료가 먼저)
                kind="step", step="gone", status="queued", requested_at=NOW - datetime.timedelta(minutes=2))
                .returning(CollectRequest.id))).scalar_one()
            await db.commit()
        await cw.cycle(_ctx(maker, fr, allow_upload=False))
        return up, str(rid), await _rows(maker)

    up, gone, (reqs, _) = _db(scenario)
    assert fr.calls == []
    assert reqs[up].status == "rejected" and "--allow-upload" in reqs[up].result
    assert reqs[gone].status == "rejected" and "목록에 없는" in reqs[gone].result


@needs_db
def test_reconcile_orphans_from_runner_record(db_schema, tmp_path):
    """TC-CW-11 · 앞 바퀴가 끝을 적지 못한 「도는 중」 줄 — 러너가 아직 돌면 그대로 · 아니면 러너 기록의 요청 줄로 끝을 적고 ·
    기록이 없으면 「끝」 이 아니라 「결과 기록 없음」 실패."""
    from app.services import collect_requests as cq
    fr = FakeRunner(tmp_path)

    async def scenario(maker):
        a = await _request(maker, "step", "price")
        b = await _request(maker, "step", "news")
        async with maker() as db:
            for rid in (a, b):
                assert await cq.claim(db, request_id=rid, worker="PC-T", now=NOW)
        fr.hist.write_text(json.dumps(_rec("step", "price", rid=a), ensure_ascii=False) + "\n", encoding="utf-8")
        busy = FakeRunner(tmp_path, busy="다른 실행이 돌고 있다")
        busy.hist = fr.hist
        await cw.cycle(_ctx(maker, busy))
        still = (await _rows(maker))[0]
        await cw.cycle(_ctx(maker, fr))
        return a, b, still, await _rows(maker)

    a, b, still, (reqs, _) = _db(scenario)
    assert still[a].status == "running" and still[b].status == "running", "러너가 도는 동안은 손대지 않는다"
    assert reqs[a].status == "done" and reqs[a].result.startswith("(앞 바퀴) 시세")
    assert reqs[b].status == "failed" and "결과 기록 없음" in reqs[b].result
    assert fr.calls == []


@needs_db
def test_heartbeat_while_child_runs_and_missing_record_fails(db_schema, tmp_path, monkeypatch):
    """TC-CW-12 · 도는 동안에도 심장 박동(화면이 「꺼짐」 으로 보지 않게) · 러너가 0 으로 끝나도 기록에 요청 줄이 없으면 실패."""
    from app.services import collect_requests as cq
    states = []
    real = cq.heartbeat

    async def spy(db, **kw):
        states.append(kw["state"])
        return await real(db, **kw)

    monkeypatch.setattr(cq, "heartbeat", spy)
    fr = FakeRunner(tmp_path, write=False, sleep=1.2)

    async def scenario(maker):
        a = await _request(maker)
        await cw.cycle(_ctx(maker, fr, beat_s=0.3))
        return a, await _rows(maker)

    a, (reqs, _) = _db(scenario)
    assert states.count("running") >= 3, states
    assert reqs[a].status == "failed" and "결과 기록 없음" in reqs[a].result and reqs[a].exit_code == 0


class FillFakeRunner(FakeRunner):
    """채우기 줄도 받는 가짜 러너 — 작업자가 넘긴 날짜를 적어 두고, 이력 줄에 범위를 함께 쓴다."""

    def __init__(self, tmp, **kw):
        super().__init__(tmp, **kw)
        self.dates = []

    def blocked(self, kind, name, now, **kw):
        return self._blocked

    def command(self, kind, name, request_id, allow_upload, **kw):
        self.dates.append(kw)
        if kind != "fill":
            return super().command(kind, name, request_id, allow_upload)
        rec = _rec(kind, name, rc=self.rc, rid=request_id, steps=[{"name": name, "rc": self.rc, "seconds": 95.0}]) | {
            "only": name, "fill": {"from": kw["date_from"], "to": kw["date_to"]}}
        code = (f"import sys; open({str(self.hist)!r},'a',encoding='utf-8').write({json.dumps(rec, ensure_ascii=False)!r}+chr(10)); "
                f"sys.exit({self.rc})")
        return [sys.executable, "-c", code]


@needs_db
def test_cycle_runs_a_fill_request_with_its_dates(db_schema, tmp_path):
    """TC-CW-15 · 빠진 날 채우기 한 바퀴 — 요청 줄의 날짜를 러너 인자로 넘기고(작업자가 줄의 날짜를 다시 확인) · 러너 기록의
    요청 줄로 끝 · 결과에 범위를 적는다 · 날짜가 상한을 넘는 줄(DB 에 직접 들어온 줄)은 러너를 부르지 않고 거절."""
    from sqlalchemy import insert
    from app.models.collect import CollectRequest
    from app.services import collect_requests as cq
    fr = FillFakeRunner(tmp_path)
    cat = {"by_name": {n: {"name": n, "label": s.label, "fill": s.fill} for n, s in FAKE_STEPS.items()},
           "steps": [], "guards": {}, "fill_max_days": 31}

    async def scenario(maker):
        from app.models import User
        async with maker() as db:
            u = User(name="관리자", email=f"a-{uuid.uuid4().hex[:8]}@test.local", password_hash="x",
                     client_id=uuid.uuid4().hex[:16], roles=["user", "admin"])
            db.add(u)
            await db.commit()
            out, created = await cq.create(db, kind="fill", step="signals", user={"id": str(u.id), "client_id": u.client_id},
                                           catalog=cat, date_from=datetime.date(2026, 10, 2), date_to=datetime.date(2026, 10, 6),
                                           now=NOW - datetime.timedelta(minutes=1))
            long = (await db.execute(insert(CollectRequest).values(       # 서비스를 거치지 않은 상한 밖 줄
                kind="fill", step="news", status="queued", requested_at=NOW - datetime.timedelta(minutes=2),
                date_from=datetime.date(2026, 8, 1), date_to=datetime.date(2026, 10, 6)).returning(CollectRequest.id))).scalar_one()
            await db.commit()
        await cw.cycle(_ctx(maker, fr))
        return out["id"], created, str(long), await _rows(maker)

    a, created, long, (reqs, _) = _db(scenario)
    assert created is True
    assert fr.dates == [{"date_from": "2026-10-02", "date_to": "2026-10-06"}], "상한 밖 줄은 러너를 부르지 않는다"
    assert reqs[a].status == "done" and reqs[a].result == "신호 빠진 날 채우기 · 2026-10-02 ~ 2026-10-06 · 1분 35초"
    assert reqs[long].status == "rejected" and ("31일" in reqs[long].result or "채우기" in reqs[long].result)
