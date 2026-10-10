"""PC 작업자 — 화면에서 남긴 수집 요청을 가져가 러너를 돌린다 (목표 기능 ① 수집 단추 · 2026-10-10).

이 파일이 답하는 질문은 하나다
------------------------------
**"관리자가 화면에서 누른 「한 단계 다시」 · 「전체 수집」 을 누가 · 언제 · 어떻게 돌리나."**

앱은 컨테이너 안에서 수집 폴더를 읽기만 하고, 러너(`scripts/daily_update.py`)는 이 PC 의 파이썬 · 작업 스케줄러 · HF 토큰을
쓰는 프로세스다. 그래서 앱은 요청 표(`collect_requests`)에 줄만 남기고 이 작업자가 가져가 러너를 부른다(조사서
`docs/조사/러너단계결과-화면실행통로-조사.md` 안 1 — Airflow · Dagster · GitHub 러너처럼 「웹은 요청만 남기고 실행 쪽이
가져간다」. 이 PC 에 새로 여는 포트가 없다).

한 번 뜨면 — 작업 스케줄러가 매 분 띄운다(사용자 결정 2026-10-10 「매 분 예약」)
  ① 작업자 잠금(두 벌 막기 · 작업 스케줄러의 IgnoreNew 와 이중) ② 심장 박동
  ③ 결과를 모르는 「도는 중」 줄 맞추기 — 앞 바퀴의 작업자가 죽었으면 러너 기록에서 요청 번호로 끝을 찾는다
  ④ 3시간 넘은 대기 줄 만료 ⑤ 대기 줄을 먼저 온 차례로 — 받지 않는 요청은 거절 · 막는 때 · 다른 실행이면 기다림 · 돌 수 있는
     첫 줄을 가져가 러너를 인자 목록으로 부른다(셸 없음) ⑥ 도는 동안 15초마다 심장 박동 ⑦ 러너 기록으로 결과를 적는다
  ⑧ 더 할 것이 없으면 끝(다음 분에 다시 뜬다)

판정의 정본은 러너다 — 막는 때 · 잠금 · 단계 목록은 daily_update 의 함수 · 값을 그대로 쓴다(사본 없음). 러너가 「지금은 못
돈다」(종료코드 75 = EX_TEMPFAIL)로 돌아오면 거절이 아니라 다시 기다린다. 요청 줄의 상태를 바꾸는 함수는 앱과 같은
`app/services/collect_requests.py` 한 곳이다.

무엇을 하지 않는가
· DB 의 줄을 명령으로 쓰지 않는다 — 종류 · 단계 이름만 읽고 러너 단계 목록으로 다시 확인한다(앱 DB 포트는 열려 있고 계정은
  compose 에 있다 — DB 를 믿지 않는 쪽으로 짠다).
· 올리기는 등록 명령줄에 ``--allow-upload`` 가 있을 때만(원자료 공유 스위치 원칙 — 켜는 결정은 명령줄 자체에 남는다).
· 도는 중인 요청을 멈추지 않는다(수집 DB 쓰기 · 올리기 중간에 멈추면 치울 것이 생긴다). 시간 한도를 넘기면만 끊는다.
· 토큰 · 비밀번호를 찍지 않는다 — 앱 DB 주소는 로그에 호스트:포트/DB 만.

쓰는 법
-------
::

    python scripts/collect_worker.py run --allow-upload   # 한 바퀴(작업 스케줄러가 부르는 꼴)
    python scripts/collect_worker.py status               # 마지막 상태 파일 · 작업 등록
    python scripts/collect_worker.py install              # 작업 스케줄러에 매 분 등록(기본 올리기 켬 · --no-upload)
    python scripts/collect_worker.py uninstall

로그는 `data/collector/logs/collect_worker-YYYYMMDD.log`(일이 있을 때만 · 14일 보관), 상태는
`data/collector/state/collect_worker.json`(매 바퀴).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, TextIO, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402
from scripts import daily_update as du  # noqa: E402

TASK_NAME = "Qurious-collect-worker"
LOCK_PATH = config.STATE_DIR / "collect_worker.lock"
STATE_PATH = config.STATE_DIR / "collect_worker.json"
LOG_DIR = config.DATA_DIR / "logs"
KEEP_LOGS = 14
#: 도는 동안 심장 박동 간격(초) — 화면의 「꺼짐」 판정(3분)보다 훨씬 짧게.
BEAT_SECONDS = 15
#: 단계 하나의 시간 한도에 더하는 여유(분) — 러너가 단계마다 한도를 이미 건다. 이것은 러너 자체가 멈췄을 때만 쓴다.
STEP_GRACE_MIN = 15


# ==================================================
# 1. 러너에 묻는 것 — 시험은 가짜로 바꿔 끼운다
# ==================================================
class Runner:
    """러너(daily_update)에 묻는 것 한 곳 — 단계 · 막는 때 · 잠금 · 명령 · 기록."""

    @property
    def tempfail(self) -> int:
        return du.EX_TEMPFAIL

    def step(self, name: str) -> Optional[du.Step]:
        return next((s for s in du.STEPS if s.name == name), None)

    def label(self, kind: str, name: str) -> str:
        if kind == "all":
            return "전체 수집"
        s = self.step(name)
        return (s.label or s.name) if s else name

    def fatal(self, name: str) -> bool:
        s = self.step(name)
        return bool(s and s.fatal)

    def reject_reason(self, kind: str, name: str, allow_upload: bool) -> str:
        """받지 않는 요청의 까닭(기다려도 바뀌지 않는 것만) — 받으면 빈 글."""
        if kind == "all":
            return ""
        if kind != "step":
            return f"모르는 종류다 — {kind}"
        s = self.step(name)
        if s is None:
            return "러너 단계 목록에 없는 단계다(목록이 바뀌었다) — 화면을 새로 고쳐 다시 요청한다"
        if s.upload and not allow_upload:
            return "이 작업자는 올리기 단계를 받지 않는다(작업자 등록 명령줄에 --allow-upload 가 없다)"
        return ""

    def blocked(self, kind: str, name: str, now: datetime.datetime) -> str:
        """지금은 돌리지 않는 때(12:30 회차와 겹침) — 기다림의 까닭. 판정은 러너 함수 그대로."""
        if kind == "all":
            return du.full_run_blocked(now) or ""
        s = self.step(name)
        return (du.rerun_blocked(s, now) or "") if s else ""

    def busy(self, now: datetime.datetime) -> str:
        """다른 실행(12:30 회차 · 손으로 돌린 러너)이 도는가 — 러너 잠금을 읽기만 한다."""
        return du.lock_holder(du.LOCK_PATH, now=now) or ""

    def command(self, kind: str, name: str, request_id: str, allow_upload: bool) -> List[str]:
        """러너를 부를 인자 목록 — 셸을 거치지 않는다. 단계 이름은 러너 단계 목록에서 온 것만(reject_reason 을 지난 뒤)."""
        args = [du.child_python(), str(du.ROOT / "scripts" / "daily_update.py"), "run"]
        if kind == "all":
            args.append("--manual")
            if allow_upload:
                args.append("--upload")
        else:
            s = self.step(name)
            args += ["--only", s.name]
            if s.upload:                                   # 올리기 단계는 --upload 와 함께만 돈다(reject_reason 이 허락을 봤다)
                args.append("--upload")
        return args + ["--request", request_id]

    def timeout_s(self, kind: str, name: str) -> int:
        if kind == "all":
            return du.LOCK_STALE_HOURS * 3600
        s = self.step(name)
        return ((s.timeout_min if s else 30) + STEP_GRACE_MIN) * 60

    def record(self, request_id: str) -> Optional[Dict]:
        """러너 이력에서 그 요청의 줄 — 끝에서부터 찾는다(없으면 None)."""
        try:
            lines = du.HISTORY_PATH.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in reversed(lines[-500:]):
            if request_id not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("request_id") == request_id:
                return rec
        return None


def _minutes(a: Optional[str], b: Optional[str]) -> str:
    try:
        d = datetime.datetime.fromisoformat(b) - datetime.datetime.fromisoformat(a)
    except (TypeError, ValueError):
        return "?"
    return f"{d.total_seconds() / 60:.0f}"


def outcome(kind: str, rc: int, rec: Optional[Dict], *, label: str, fatal: bool, tempfail: int,
            labels: Callable[[str], str] = lambda n: n) -> Tuple[str, str]:
    """러너가 돌아온 뒤 요청 줄의 (상태, 결과 한 줄). 상태 ``requeue`` 는 끝이 아니라 다시 기다림이다.

    러너 화면과 같은 말 — 성공은 끝 · 멈추지 않는 단계의 실패는 경고 · 멈추는 단계의 실패는 실패 · 회차가 멈췄으면 실패.
    러너 기록에 그 요청 줄이 없으면 끝으로 적지 않는다(말없는 대체 금지 — 「결과 기록 없음」 실패).
    """
    from app.services import collect_requests as cq

    if rc == tempfail:
        return "requeue", "러너가 지금은 돌 수 없다고 했다(12:30 회차와 겹침 · 다른 실행) — 다시 기다림"
    if rec is None:
        return cq.FAILED, f"결과 기록 없음 — 종료코드 {rc} · 작업자 로그와 러너 로그를 확인"
    if kind == "step":
        s = (rec.get("steps") or [{}])[0]
        secs = float(s.get("seconds") or 0)
        tail = f" · 시세 기준일 {rec['price_max']}" if rec.get("price_max") else ""
        if rc == 0:
            return cq.DONE, f"{label} · {secs:,.0f}초{tail}"
        if s.get("reason") == "app_db_down":
            return cq.WARNING, f"{label} · 건너뜀 — 앱 DB 꺼짐(빠진 날은 채우기 명령으로)"
        return (cq.FAILED if fatal else cq.WARNING), f"{label} · 종료코드 {rc} · {secs:,.0f}초"
    steps = rec.get("steps") or []
    bad = [labels(x.get("name", "")) for x in steps if x.get("rc") not in (None, 0)]
    base = f"단계 {len(steps)} · {_minutes(rec.get('started_at'), rec.get('finished_at'))}분 · " \
           f"시세 기준일 {rec.get('price_max') or '없음'}"
    if rec.get("stopped"):
        return cq.FAILED, f"멈춤 — {rec['stopped']} · {base}"
    if bad or rc != 0:
        return cq.WARNING, f"경고 {len(bad)}({' · '.join(bad)}) · {base}" if bad else f"종료코드 {rc} · {base}"
    return cq.DONE, base


# ==================================================
# 2. 한 바퀴
# ==================================================
@dataclass
class Ctx:
    name: str
    pid: int
    started: datetime.datetime
    allow_upload: bool
    runner: Runner
    maker: Callable                       # async_sessionmaker — 앱 DB 세션
    now: Callable[[], datetime.datetime] = du.now_kst
    beat_s: float = BEAT_SECONDS
    log: Optional[TextIO] = None
    handled: List[Dict] = field(default_factory=list)
    state: str = "idle"
    note: str = ""

    def say(self, msg: str) -> None:
        if self.log is None:
            return
        self.log.write(f"[{self.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        self.log.flush()


async def _beat(ctx: Ctx, db, state: str, note: str = "", request_id: Optional[str] = None) -> None:
    from app.services import collect_requests as cq

    ctx.state, ctx.note = state, note
    await cq.heartbeat(db, name=ctx.name, pid=ctx.pid, started_at=ctx.started, state=state, note=note,
                       allow_upload=ctx.allow_upload, request_id=request_id, now=ctx.now())


async def reconcile(ctx: Ctx, db) -> int:
    """결과를 모르는 「도는 중」 줄(이 PC 작업자 이름) — 러너가 아직 돌면 두고, 아니면 러너 기록으로 끝을 적는다.

    작업자는 잠금으로 한 벌만 돈다 — 잠금을 잡은 지금, 이 이름의 「도는 중」 줄은 앞 바퀴가 끝을 적지 못한 줄이다(로그오프 ·
    작업 스케줄러 시간 한도 · PC 꺼짐). Windows 는 부모가 죽어도 러너(자식)를 죽이지 않으므로 러너가 아직 돌 수 있다.
    """
    from app.services import collect_requests as cq

    rows = await cq.running_of(db, worker=ctx.name)
    if not rows or ctx.runner.busy(ctx.now()):
        return 0
    n = 0
    for row in rows:
        rec = ctx.runner.record(str(row.id))
        if rec is None:
            status, result, rc = cq.FAILED, "결과 기록 없음 — 작업자가 멈춰 끝을 확인하지 못했다(러너 로그를 확인)", None
        else:
            rc = rec.get("rc")
            if rc is None:                                  # 옛 줄 꼴 — 회차 ok · 단계 종료코드에서 짐작하지 않고 실패 쪽으로
                rc = 0 if rec.get("ok") else 1
            status, result = outcome(row.kind, rc, rec, label=ctx.runner.label(row.kind, row.step),
                                     fatal=ctx.runner.fatal(row.step), tempfail=ctx.runner.tempfail,
                                     labels=lambda nm: ctx.runner.label("step", nm))
            if status == "requeue":                          # 기록이 있는데 막힘일 수는 없다 — 실패로 남긴다
                status = cq.FAILED
        if await cq.finish(db, request_id=row.id, status=status, exit_code=rc, result="(앞 바퀴) " + result,
                           log_path=(rec or {}).get("log", ""), now=ctx.now()):
            n += 1
            ctx.say(f"맞춤 · 요청 {str(row.id)[:8]} · {status} · {result}")
    return n


async def pick(ctx: Ctx, db, skip: set) -> Tuple[Optional[object], str]:
    """다음에 돌 대기 줄 — 받지 않는 줄은 거절하고, 막는 때인 줄은 건너뛰며 첫 까닭을 기억한다."""
    from app.services import collect_requests as cq

    first_wait = ""
    for row in await cq.queued(db):
        rid = str(row.id)
        if rid in skip:
            continue
        why = ctx.runner.reject_reason(row.kind, row.step, ctx.allow_upload)
        if why:
            await cq.reject(db, request_id=row.id, why=why, now=ctx.now())
            ctx.say(f"거절 · 요청 {rid[:8]} · {why}")
            continue
        wait = ctx.runner.blocked(row.kind, row.step, ctx.now())
        if wait:
            first_wait = first_wait or f"{ctx.runner.label(row.kind, row.step)} — {wait}"
            continue
        return row, ""
    return None, first_wait


async def run_child(ctx: Ctx, db, cmd: List[str], rid: str, label: str, *, timeout_s: int) -> int:
    """러너를 자식으로 띄우고 끝날 때까지 심장 박동 — 시간 한도를 넘기면 끊고 124(러너의 시간 초과와 같은 번호)."""
    from app.services import collect_requests as cq

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(du.ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    out = ctx.log if ctx.log is not None else subprocess.DEVNULL
    p = subprocess.Popen(cmd, cwd=du.ROOT, env=env, stdout=out, stderr=subprocess.STDOUT, creationflags=flags)
    t0 = time.monotonic()
    while True:
        try:
            return await asyncio.to_thread(p.wait, ctx.beat_s)
        except subprocess.TimeoutExpired:
            pass
        mins = (time.monotonic() - t0) / 60
        if time.monotonic() - t0 > timeout_s:
            p.kill()
            p.wait()
            ctx.say(f"⏱ 요청 {rid[:8]} · {timeout_s // 60}분을 넘겨 끊었다")
            return 124
        await _beat(ctx, db, cq.BUSY, f"{label} 도는 중 · {mins:.0f}분(요청 {rid[:8]})", request_id=rid)


async def run_request(ctx: Ctx, db, row) -> str:
    from app.services import collect_requests as cq

    rid = str(row.id)
    label = ctx.runner.label(row.kind, row.step)
    cmd = ctx.runner.command(row.kind, row.step, rid, ctx.allow_upload)
    await _beat(ctx, db, cq.BUSY, f"{label} 도는 중(요청 {rid[:8]})", request_id=rid)
    ctx.say(f"▶ 요청 {rid[:8]} · {label} · {' '.join(cmd[2:])}")
    rc = await run_child(ctx, db, cmd, rid, label, timeout_s=ctx.runner.timeout_s(row.kind, row.step))
    rec = ctx.runner.record(rid)
    status, result = outcome(row.kind, rc, rec, label=label, fatal=ctx.runner.fatal(row.step),
                             tempfail=ctx.runner.tempfail, labels=lambda nm: ctx.runner.label("step", nm))
    if status == "requeue":
        await cq.requeue(db, request_id=rid, note=result)
    else:
        await cq.finish(db, request_id=rid, status=status, exit_code=rc, result=result,
                        log_path=(rec or {}).get("log", ""), now=ctx.now())
    ctx.say(f"{status} · 요청 {rid[:8]} · 종료코드 {rc} · {result}")
    ctx.handled.append({"id": rid, "status": status, "rc": rc})
    return status


async def cycle(ctx: Ctx) -> Dict:
    """한 바퀴 — 맞추기 · 만료 · 대기 줄을 돌 수 있는 만큼(한 번에 하나씩) · 끝 상태를 심장 박동으로."""
    from app.services import collect_requests as cq

    async with ctx.maker() as db:
        await _beat(ctx, db, cq.IDLE, "확인 중")
        await reconcile(ctx, db)
        await cq.expire_stale(db, now=ctx.now())
        skip: set = set()
        while True:
            busy = ctx.runner.busy(ctx.now())
            if busy:
                await _beat(ctx, db, cq.WAITING, f"{busy} · 끝나면 돈다")   # busy 가 「다른 실행이 돌고 있다 (PID …)」 로 시작한다
                break
            row, wait = await pick(ctx, db, skip)
            if row is None:
                await _beat(ctx, db, cq.WAITING if wait else cq.IDLE, wait)
                break
            if not await cq.claim(db, request_id=row.id, worker=ctx.name, now=ctx.now()):
                skip.add(str(row.id))                        # 다른 작업자가 먼저 가져갔다(또는 취소됐다)
                continue
            if await run_request(ctx, db, row) == "requeue":
                skip.add(str(row.id))                        # 이번 바퀴에는 다시 잡지 않는다(같은 막힘을 되풀이하지 않게)
    return {"state": ctx.state, "note": ctx.note, "handled": ctx.handled}


# ==================================================
# 3. 진입 — 잠금 · 앱 DB 주소 · 상태 파일
# ==================================================
def _log_file(now: datetime.datetime) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for old in sorted(LOG_DIR.glob("collect_worker-*.log"))[:-KEEP_LOGS]:
        old.unlink(missing_ok=True)
    return LOG_DIR / f"collect_worker-{now.strftime('%Y%m%d')}.log"


def write_state(**kw) -> None:
    """상태 파일 — 매 바퀴 덮어쓴다(앱 DB 에 닿지 않을 때도 이 PC 에서 까닭을 본다). 못 써도 바퀴는 멈추지 않는다."""
    try:
        du._write_json_atomic(STATE_PATH, {"at": du._iso(du.now_kst()), **kw})
    except OSError:
        pass


async def _main_async(url: str, *, name: str, started: datetime.datetime, allow_upload: bool, log: TextIO) -> Dict:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(url, poolclass=NullPool)
    try:
        ctx = Ctx(name=name, pid=os.getpid(), started=started, allow_upload=allow_upload, runner=Runner(),
                  maker=async_sessionmaker(engine, expire_on_commit=False), log=log)
        return await cycle(ctx)
    finally:
        await engine.dispose()


def run(allow_upload: bool) -> int:
    """한 바퀴 — 종료코드 0(할 일 끝 · 앞 바퀴가 아직 돎 · 앱 DB 꺼짐) · 78 앱 DB 주소를 못 만듦 · 1 작업자 오류."""
    started = du.now_kst()
    name = socket.gethostname()[:64] or "pc"
    base = {"name": name, "pid": os.getpid(), "started_at": du._iso(started), "allow_upload": allow_upload}
    busy = du.acquire_lock(LOCK_PATH, now=started)
    if busy:                                                  # 앞 바퀴가 긴 수집을 돌리는 중 — 그 바퀴가 심장 박동을 맡는다
        return 0
    try:
        env, why = du.host_app_db_env()
        if not env:
            write_state(**base, state="config_error", note=f"앱 DB 주소를 만들지 못했다 — {why}")
            return du.EX_CONFIG
        down = du.app_db_unreachable(env)
        if down:                                              # 앱 DB 가 꺼져 있으면 화면도 없다 — 이 PC 에만 까닭을 남긴다
            write_state(**base, state="db_down", note=f"앱 DB 에 닿지 않는다 — {du._db_where(env['DATABASE_URL'])} {down}")
            return 0
        with _log_file(started).open("a", encoding="utf-8") as log:
            out = asyncio.run(_main_async(env["DATABASE_URL"], name=name, started=started,
                                          allow_upload=allow_upload, log=log))
        write_state(**base, state=out["state"], note=out["note"], handled=out["handled"])
        return 0
    except Exception as e:                                    # 작업자 결함도 기록으로 — 다음 바퀴가 다시 시도한다
        write_state(**base, state="error", note=f"{type(e).__name__}: {e}"[:300])
        try:
            with _log_file(started).open("a", encoding="utf-8") as log:
                log.write(f"[{du.now_kst():%Y-%m-%d %H:%M:%S}] 🔴 작업자 오류 {type(e).__name__}: {e}\n")
        except OSError:
            pass
        return 1
    finally:
        du.release_lock(LOCK_PATH)


# ==================================================
# 4. 작업 스케줄러 — 매 분
# ==================================================
def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def task_xml(upload: bool, *, python_w: str, root: Path, today: Optional[datetime.date] = None) -> str:
    """작업 스케줄러 정의 — 매 분(1분 되풀이 · 끝 없음) · 로그온해 있을 때만 · 앞 바퀴가 돌면 새로 띄우지 않음.

    · ``Repetition`` 1분 · ``Duration`` 없음 — 날마다 끝없이 되풀이한다.
    · ``IgnoreNew`` — 긴 수집을 도는 앞 바퀴가 있으면 새 바퀴를 만들지 않는다(작업자 잠금과 이중).
    · ``InteractiveToken`` — 12:30 러너와 같다(비밀번호를 저장하지 않는다 · 로그온해 있을 때만).
    · 시간 한도 4시간 — 러너 잠금이 낡았다고 보는 시간과 같다.
    """
    start = datetime.datetime.combine(today or datetime.date.today(), datetime.time(0, 0))
    args = f'"{root / "scripts" / "collect_worker.py"}" run' + (" --allow-upload" if upload else "")
    desc = ("Qurious 수집 요청 작업자 — 화면의 「한 단계 다시」 · 「전체 수집」 요청을 매 분 가져가 러너를 돌린다"
            + (" · 올리기 단계 받음" if upload else "") + ". 정의: scripts/collect_worker.py")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{_esc(desc)}</Description>
    <URI>\\{TASK_NAME}</URI>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT1M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start.isoformat(timespec="seconds")}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <ExecutionTimeLimit>PT{du.LOCK_STALE_HOURS}H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
    <WakeToRun>false</WakeToRun>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_esc(python_w)}</Command>
      <Arguments>{_esc(args)}</Arguments>
      <WorkingDirectory>{_esc(str(root))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def install(upload: bool = True) -> int:
    if os.name != "nt":
        print("작업 스케줄러 등록은 Windows 전용이다. 다른 OS 는 cron 에 매 분 "
              f"`cd {ROOT} && python scripts/collect_worker.py run --allow-upload` 를 건다.")
        return 1
    xml = task_xml(upload, python_w=du._pythonw(), root=ROOT)
    fd, tmp = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        Path(tmp).write_text(xml, encoding="utf-16")
        p = du._schtasks("/Create", "/TN", TASK_NAME, "/XML", tmp, "/F")
    finally:
        os.unlink(tmp)
    if p.returncode != 0:
        print(f"🔴 등록 실패 (schtasks 종료코드 {p.returncode})\n{p.stdout}{p.stderr}")
        return p.returncode
    print(f"✅ 작업 스케줄러에 등록했다 — '{TASK_NAME}' · 매 분 · 올리기 단계 {'받음' if upload else '받지 않음'}")
    print("   상태: python scripts/collect_worker.py status · 끄기: python scripts/collect_worker.py uninstall")
    return 0


def uninstall() -> int:
    p = du._schtasks("/Delete", "/TN", TASK_NAME, "/F")
    print("✅ 등록을 해제했다" if p.returncode == 0 else f"🟡 {p.stdout}{p.stderr}".strip())
    return p.returncode


def status() -> int:
    try:
        st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = None
    print("― 마지막 바퀴 ―")
    if not st:
        print("  기록 없음 — 아직 한 번도 돌지 않았다")
    else:
        print(f"  {st.get('at')} · {st.get('state')} · {st.get('note') or ''}")
        for h in st.get("handled") or []:
            print(f"    요청 {str(h.get('id'))[:8]} · {h.get('status')} · 종료코드 {h.get('rc')}")
    p = du._schtasks("/Query", "/TN", TASK_NAME, "/FO", "LIST")
    print("― 작업 스케줄러 ―")
    print("  " + (p.stdout.strip().replace("\n", "\n  ") if p.returncode == 0 else "등록 안 됨 — install"))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    du.utf8_stdio()
    ap = argparse.ArgumentParser(prog="python scripts/collect_worker.py",
                                 description="화면 수집 요청 작업자 — 요청 표에서 가져가 러너를 돌린다")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="한 바퀴(작업 스케줄러가 매 분 부른다)")
    r.add_argument("--allow-upload", action="store_true",
                   help="올리기 단계 · 전체 수집의 올리기를 받는다(원자료 공유 스위치 — 켜는 결정은 이 명령줄에 남는다)")
    sub.add_parser("status", help="마지막 바퀴 상태 · 작업 등록")
    i = sub.add_parser("install", help="작업 스케줄러에 매 분 등록(기본 올리기 받음)")
    i.add_argument("--no-upload", action="store_true", help="올리기 단계를 받지 않는다")
    sub.add_parser("uninstall", help="작업 스케줄러 등록 해제")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return run(a.allow_upload)
    if a.cmd == "status":
        return status()
    if a.cmd == "install":
        return install(upload=not a.no_upload)
    return uninstall()


if __name__ == "__main__":
    raise SystemExit(main())
