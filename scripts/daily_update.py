"""일일 데이터 갱신 — 시세·배당·파생 표를 최신으로 만들고 HF 에 증분으로 올린다.

이 파일이 답하는 질문은 하나다
------------------------------
**"아무도 기억하지 않아도 데이터가 매일 최신이 되려면 무엇이 돌아야 하는가."**

수집기의 각 단계(`collector/README.md §1` 의 1~7)는 이미 있다. 빠진 것은 **순서대로
이어 부르는 손**이었다. 사람이 세션마다 기억해서 돌리면 결국 안 돌린다 — 2026-09-28
확인 때 원격 스냅샷은 09-21, 로컬 시세는 09-22, 수정주가·TR·벤치마크는 09-17 에
멈춰 있었다. 단계마다 멈춘 날이 달랐던 것이 그 증거다.

그래서 이 러너는 **Windows 작업 스케줄러**에 올려 매일 한 번 돈다. Claude 세션·터미널·
앱 스택(Postgres·Redis)과 **아무 관계가 없다** — 세션이 끝나도, 스택이 꺼져 있어도 돈다.
Celery Beat(`app/celery_app.py`)에도 같은 일정이 있지만 그쪽은 스택이 떠 있을 때만
돈다(`collector/README.md §2` 의 "스택이 안 뜨는 날 시세를 통째로 놓친다" 와 같은 이유).

단계 — 앞 단계가 뒤 단계의 재료다
---------------------------------
::

    ① price         backfill recent         최근 14일의 빈 거래일을 채운다 (포털)
    ② dividend      dividend scan --recent 2  이번 달·지난달 배당 공시를 **다시** 훑는다 (DART)
    ③ adjusted      preprocess              수정주가·조정 이벤트를 다시 계산
    ④ total_return  total_return build      ③+② → TR 계열
    ⑤ benchmark     benchmark build         ③+④ → 자체 재현 지수
    ⑥ manifest      manifest write          팀원 대조용 지문
    ⑦ export        hf_dataset export       바뀐 파티션만 파케이로        (--upload 일 때만)
    ⑧ verify        hf_dataset verify       지문·행수·스키마·값 게이트   (--upload 일 때만)
    ⑨ upload        hf_dataset upload --yes --incremental                 (--upload 일 때만)

· ② 가 `--recent` 인 이유 — `dividend scan` 은 다 훑은 달을 `done` 으로 찍고 다시 보지
  않는다. 09-19 에 훑은 2026-09 가 `done` 이면 그 뒤 9월 공시는 영원히 안 들어온다.
· ② 가 ③ 보다 **앞인** 이유 — 파생 단계(③④⑤)를 돌릴지는 ③ 직전에 한 번 판정한다.
  배당을 뒤에 두면 "시세는 그대로 · 배당만 새로 옴" 인 날 TR 이 건너뛰어진다. 배당 스캔은
  배당락일 계산에 시세 **달력**(`price_daily`)만 쓰므로 ① 뒤면 충분하다.
· ② 가 실패해도(DART 점검·한도) ③④⑤ 는 돈다 — 배당은 어제 것 그대로 두고 시세만이라도
  최신으로 만든다. ② 의 실패는 상태 파일에 🟡 로 남는다.
· ③④⑤ 는 **새 자료가 없으면 건너뛴다** — 같은 날 두 번 돌아도 CPU 를 태우지 않는다.
  판정은 `needs_derived()` 한 곳이다.
· ⑨ 는 **바뀐 파케이가 0개면 건너뛴다** — 안 그러면 내용 없는 커밋·태그가 매일 쌓인다.

원자료 공유 스위치 (`QURIOUS_RAW_SHARING`)
------------------------------------------
`hf_dataset.py` 는 이 스위치가 꺼져 있으면 원자료 표 내보내기·업로드를 멈춘다. 스위치는
**`.env` 로는 켜지지 않게** 설계돼 있다(실수로 켜진 채 남지 않게). 이 러너는 `--upload`
를 **명시적으로 준 실행에서만**, ⑦⑨ 자식 프로세스에게만 스위치를 켜서 넘긴다. 즉 켜는
결정은 작업 스케줄러에 등록된 **명령줄 자체**에 남는다(`status` 가 그 명령줄을 보여 준다).
private 확인·xet 확인 등 나머지 게이트는 `hf_dataset.upload()` 가 그대로 건다.

무엇을 하지 않는가
------------------
· **git 을 건드리지 않는다.** 커밋·push 없음. 산출물은 전부 gitignore 된 `data/` 아래다.
· **토큰·키를 출력하지 않는다.** 자식 프로세스 출력은 로그 파일로만 가고, 그 자식들이
  이미 토큰을 찍지 않는다(`hf_dataset._token` 머리말).
· **두 벌이 겹쳐 돌지 않는다.** 잠금 파일(`state/daily_update.lock`)에 PID 를 적는다.
  ⚠️ Windows 에서 `os.kill(pid, 0)` 은 살아 있는지 묻는 게 아니라 **그 프로세스를 죽인다**
  (TerminateProcess). 그래서 생존 확인은 `OpenProcess` 로 한다.

쓰는 법
-------
::

    python scripts/daily_update.py run              # 로컬 갱신만 (①~⑥)
    python scripts/daily_update.py run --upload     # + HF 증분 업로드 (⑦~⑨)
    python scripts/daily_update.py status           # 마지막 실행 결과 + 예약 상태
    python scripts/daily_update.py install          # 작업 스케줄러에 매일 12:30 등록 (--upload 포함)
    python scripts/daily_update.py install --time 18:30 --no-upload
    python scripts/daily_update.py start            # 등록된 작업을 지금 한 번 돌린다(비동기)
    python scripts/daily_update.py uninstall        # 등록 해제

로그는 `data/collector/logs/daily_update-*.log`(최근 30개 보관), 마지막 결과는
`data/collector/state/daily_update_last.json`, 이력은 같은 폴더 `daily_update_history.jsonl`.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import zoneinfo
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, TextIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402

KST = zoneinfo.ZoneInfo("Asia/Seoul")

TASK_NAME = "Qurious-daily-data-update"
DEFAULT_TIME = "12:30"

LOG_DIR = config.DATA_DIR / "logs"
LOCK_PATH = config.STATE_DIR / "daily_update.lock"
LAST_PATH = config.STATE_DIR / "daily_update_last.json"
HISTORY_PATH = config.STATE_DIR / "daily_update_history.jsonl"

#: 로그 보관 개수. 하루 한 번이면 한 달치다.
KEEP_LOGS = 30

#: 잠금이 이보다 오래됐으면 PID 가 살아 있어도 멈춘 것으로 본다(작업 스케줄러 한도와 같다).
LOCK_STALE_HOURS = 4

#: 변화 감지에 쓰는 되돌아보기 창. `backfill.RECENT_WINDOW`(14일)보다 넉넉히 잡는다.
SNAPSHOT_WINDOW_DAYS = 31


@dataclass
class Step:
    name: str
    args: List[str]
    timeout_min: int
    fatal: bool = True          # 실패하면 뒤 단계를 멈추는가
    derived: bool = False       # 새 자료가 없으면 건너뛰는 파생 단계인가
    upload: bool = False        # --upload 일 때만 도는가
    sharing: bool = False       # 원자료 공유 스위치를 켜서 넘기는가


STEPS: List[Step] = [
    Step("price", ["-m", "collector.backfill", "recent", "--quiet"], 30),
    Step("dividend", ["-m", "collector.dividend", "scan", "--recent", "2", "--quiet"], 60,
         fatal=False),
    Step("adjusted", ["-m", "collector.preprocess"], 30, derived=True),
    Step("total_return", ["-m", "collector.total_return", "build", "--quiet"], 30,
         derived=True),
    Step("benchmark", ["-m", "collector.benchmark", "build", "--quiet"], 30, derived=True),
    Step("manifest", ["-m", "collector.manifest", "write"], 10, fatal=False),
    Step("export", ["scripts/hf_dataset.py", "export", "--quiet"], 30,
         upload=True, sharing=True),
    Step("verify", ["scripts/hf_dataset.py", "verify"], 30, upload=True),
    Step("upload", ["scripts/hf_dataset.py", "upload", "--yes", "--incremental"], 60,
         upload=True, sharing=True),
]


# ==================================================
# 1. 작은 도구
# ==================================================
def now_kst() -> datetime.datetime:
    return datetime.datetime.now(KST)


def _iso(t: datetime.datetime) -> str:
    return t.isoformat(timespec="seconds")


def _write_json_atomic(path: Path, obj: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def pid_alive(pid: int) -> bool:
    """그 PID 의 프로세스가 아직 살아 있는가. **죽이지 않고** 묻는다."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259               # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_lock(path: Path = LOCK_PATH, *, now: Optional[datetime.datetime] = None) -> Optional[str]:
    """잠금을 잡는다. 잡으면 None, 못 잡으면 그 이유 한 줄.

    ``O_EXCL`` 로 만들어 두 프로세스가 동시에 잡는 일이 없다. 남은 잠금은 ① PID 가
    죽었거나 ② ``LOCK_STALE_HOURS`` 보다 오래됐으면 치우고 다시 잡는다.
    """
    now = now or now_kst()
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                held = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                held = {}
            pid = int(held.get("pid") or 0)
            try:
                since = datetime.datetime.fromisoformat(held.get("started_at", ""))
            except ValueError:
                since = None
            old = since is None or (now - since).total_seconds() > LOCK_STALE_HOURS * 3600
            if pid_alive(pid) and not old:
                return f"다른 실행이 돌고 있다 (PID {pid} · {held.get('started_at')} 시작)"
            path.unlink(missing_ok=True)                    # 죽었거나 너무 오래된 잠금
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "started_at": _iso(now)}, f)
        return None
    return "잠금을 잡지 못했다 (치운 직후 다른 실행이 먼저 잡았다)"


def release_lock(path: Path = LOCK_PATH) -> None:
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if int(held.get("pid") or 0) == os.getpid():
        path.unlink(missing_ok=True)


def child_python() -> str:
    """자식 프로세스용 파이썬. 작업 스케줄러는 창이 안 뜨는 ``pythonw`` 로 이 러너를
    부르는데, 자식까지 ``pythonw`` 면 표준출력이 없어 로그가 빈다 → 같은 폴더의 ``python``."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        cand = exe.with_name("python.exe")
        if cand.exists():
            return str(cand)
    return str(exe)


# ==================================================
# 2. 변화 감지 — 파생 단계를 돌릴 것인가
# ==================================================
def snapshot(db_path: Path = config.DB_PATH) -> Dict[str, object]:
    """DB 의 '지금' 을 몇 개의 수로 접는다. **읽기 전용**으로 연다.

    전체 COUNT(*) 는 4.4M 행이라 느리다 — 최근 ``SNAPSHOT_WINDOW_DAYS`` 안만 센다.
    기본키가 ``(bas_dt, srtn_cd)`` 라 이 범위 조회는 인덱스로 끝난다.
    """
    if not db_path.exists():
        return {}
    since = (now_kst() - datetime.timedelta(days=SNAPSHOT_WINDOW_DAYS)).strftime("%Y%m%d")
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=60)
    try:
        def one(sql: str, *args):
            try:
                return conn.execute(sql, args).fetchone()
            except sqlite3.OperationalError:               # 표가 아직 없다
                return None

        out: Dict[str, object] = {}
        r = one("SELECT MAX(bas_dt), COUNT(*) FROM price_daily WHERE bas_dt >= ?", since)
        out["price_max"], out["price_recent_rows"] = (r or (None, 0))
        for key, table in (("adjusted_max", "price_adjusted"),
                           ("tr_max", "price_total_return"),
                           ("benchmark_max", "benchmark_index")):
            r = one(f"SELECT MAX(bas_dt) FROM {table}")
            out[key] = r[0] if r else None
        # 정정공시는 접수번호가 커지고, 금액만 바뀐 정정은 합이 바뀐다 — 셋을 함께 본다.
        r = one("SELECT COUNT(*), MAX(rcept_no), TOTAL(dps) FROM dividend")
        out["dividend"] = list(r) if r else None
        return out
    finally:
        conn.close()


def needs_derived(before: Dict[str, object], after: Dict[str, object]) -> Optional[str]:
    """파생 단계(수정주가·TR·벤치마크)를 돌려야 하면 그 이유, 아니면 None.

    둘 중 하나면 돈다 — ① 이번 실행에 시세·배당이 바뀌었다 ② 파생 표가 시세보다
    뒤처져 있다(예전 실행이 중간에 죽었거나, 사람이 수집만 돌리고 전처리를 잊었다).
    ②를 빼면 한 번 어긋난 파생 표가 **새 거래일이 올 때까지** 뒤처진 채로 남는다.
    """
    if not after:
        return "DB 가 없다 — 처음부터 만든다"
    if before.get("price_max") != after.get("price_max") \
            or before.get("price_recent_rows") != after.get("price_recent_rows"):
        return f"시세가 바뀌었다 ({before.get('price_max')} → {after.get('price_max')})"
    if before.get("dividend") != after.get("dividend"):
        return "배당 표가 바뀌었다"
    p = after.get("price_max") or ""
    lag = [k for k in ("adjusted_max", "tr_max", "benchmark_max")
           if (after.get(k) or "") < p]
    if lag:
        return "파생 표가 시세보다 뒤처져 있다 (" + ", ".join(
            f"{k.replace('_max', '')} {after.get(k)}" for k in lag) + f" < {p})"
    return None


# ==================================================
# 3. 실행
# ==================================================
@dataclass
class Run:
    started: datetime.datetime
    upload: bool
    log: TextIO
    log_path: Path
    steps: List[Dict] = field(default_factory=list)

    def say(self, msg: str) -> None:
        line = f"[{now_kst().strftime('%H:%M:%S')}] {msg}"
        self.log.write(line + "\n")
        self.log.flush()
        if sys.stdout is not None:                          # pythonw 면 stdout 이 없다
            try:
                print(line, flush=True)
            except (OSError, ValueError):
                pass


def _run_step(run: Run, step: Step) -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    if step.sharing and run.upload:
        env["QURIOUS_RAW_SHARING"] = "1"       # ← 머리말 "원자료 공유 스위치" 참고
    else:
        env.pop("QURIOUS_RAW_SHARING", None)
    run.log.write(f"\n{'=' * 70}\n▶ {step.name}: python {' '.join(step.args)}\n{'=' * 70}\n")
    run.log.flush()
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        p = subprocess.run([child_python(), *step.args], cwd=ROOT, env=env,
                           stdout=run.log, stderr=subprocess.STDOUT,
                           timeout=step.timeout_min * 60, creationflags=flags)
        return p.returncode
    except subprocess.TimeoutExpired:
        run.log.write(f"\n⏱ {step.timeout_min}분을 넘겨 멈췄다\n")
        return 124


def _prune_logs() -> None:
    logs = sorted(LOG_DIR.glob("daily_update-*.log"))
    for old in logs[:-KEEP_LOGS]:
        old.unlink(missing_ok=True)


def run_all(upload: bool = False, force_derived: bool = False) -> int:
    started = now_kst()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"daily_update-{started.strftime('%Y%m%d-%H%M%S')}.log"

    busy = acquire_lock()
    if busy:
        # 로그를 새로 만들지 않는다 — 돌고 있는 쪽 로그가 정본이다.
        msg = f"{_iso(started)} 건너뜀: {busy}"
        if sys.stdout is not None:
            print(msg)
        with HISTORY_PATH.open("a", encoding="utf-8") as h:
            h.write(json.dumps({"started_at": _iso(started), "skipped": busy},
                               ensure_ascii=False) + "\n")
        return 0

    rc_total = 0
    with log_path.open("w", encoding="utf-8") as log:
        run = Run(started, upload, log, log_path)
        try:
            run.say(f"일일 갱신 시작 · 업로드 {'켬' if upload else '끔'} · PID {os.getpid()}")
            before = snapshot()
            run.say(f"시작 상태 {json.dumps(before, ensure_ascii=False)}")
            derived_why: Optional[str] = None
            stop = ""
            for step in STEPS:
                rec = {"name": step.name, "rc": None, "seconds": 0.0, "note": ""}
                run.steps.append(rec)
                if step.upload and not upload:
                    rec["note"] = "업로드 끔"
                    continue
                if stop:
                    rec["note"] = f"앞 단계 실패로 건너뜀 ({stop})"
                    continue
                if step.derived:
                    if derived_why is None:
                        derived_why = "강제(--force-derived)" if force_derived \
                            else (needs_derived(before, snapshot()) or "")
                        run.say(f"파생 단계 판정: {derived_why or '새 자료 없음 — 건너뛴다'}")
                    if not derived_why:
                        rec["note"] = "새 자료 없음"
                        continue
                if step.name == "upload":
                    pending = _pending_upload()
                    if pending == []:
                        rec["note"] = "바뀐 파케이 0개 — 원격과 같다"
                        run.say("upload: 바뀐 파케이가 없어 올리지 않는다")
                        continue
                    run.say(f"upload: 바뀐 파케이 "
                            f"{'(업로드 기록 없음)' if pending is None else f'{len(pending)}개'}")
                t0 = time.time()
                run.say(f"▶ {step.name} …")
                rc = _run_step(run, step)
                rec["rc"], rec["seconds"] = rc, round(time.time() - t0, 1)
                run.say(f"{'✅' if rc == 0 else ('🟡' if not step.fatal else '🔴')} "
                        f"{step.name} · 종료코드 {rc} · {rec['seconds']:,.0f}초")
                if rc != 0:
                    rc_total = rc_total or rc
                    if step.fatal:
                        stop = f"{step.name} 종료코드 {rc}"
            after = snapshot()
            ok = not stop and all(s["rc"] in (None, 0) for s in run.steps)
            state = {
                "started_at": _iso(started), "finished_at": _iso(now_kst()),
                "ok": ok, "upload": upload, "stopped": stop or None,
                "derived": derived_why, "steps": run.steps,
                "before": before, "after": after,
                "log": log_path.relative_to(ROOT).as_posix(),
            }
            _write_json_atomic(LAST_PATH, state)
            with HISTORY_PATH.open("a", encoding="utf-8") as h:
                h.write(json.dumps({k: state[k] for k in
                                    ("started_at", "finished_at", "ok", "upload", "stopped")}
                                   | {"price_max": after.get("price_max")},
                                   ensure_ascii=False) + "\n")
            run.say(f"끝 · {'✅ 전부 성공' if ok else '🔴/🟡 실패 단계 있음'} · "
                    f"시세 {after.get('price_max')} · 수정주가 {after.get('adjusted_max')} · "
                    f"TR {after.get('tr_max')} · 벤치마크 {after.get('benchmark_max')}")
        except Exception as e:                              # 러너 자체의 결함도 기록으로 남긴다
            run.say(f"🔴 러너 오류: {type(e).__name__}: {e}")
            _write_json_atomic(LAST_PATH, {
                "started_at": _iso(started), "finished_at": _iso(now_kst()), "ok": False,
                "upload": upload, "stopped": f"러너 오류 {type(e).__name__}: {e}",
                "steps": run.steps, "log": log_path.relative_to(ROOT).as_posix()})
            rc_total = 1
        finally:
            release_lock()
    _prune_logs()
    return rc_total


def _pending_upload() -> Optional[List[str]]:
    from scripts import hf_dataset
    return hf_dataset.changed_since_upload()


# ==================================================
# 4. 작업 스케줄러 — 세션이 끝나도 도는 부분
# ==================================================
def task_xml(time_hm: str, upload: bool, *, python_w: str, root: Path,
             today: Optional[datetime.date] = None) -> str:
    """작업 스케줄러 정의(XML). ``schtasks /Create /XML`` 로 등록한다.

    PowerShell ``Register-ScheduledTask`` 대신 XML 인 이유 — Windows PowerShell 5.1 은
    BOM 없는 UTF-8 스크립트를 ANSI 로 읽어 한글 설명이 깨진다. XML 은 인코딩을 스스로
    밝힌다. 설정의 뜻:

    · ``StartWhenAvailable`` — 그 시각에 PC 가 꺼져 있었으면 **켜진 뒤 곧바로** 돈다.
      이것이 없으면 노트북을 닫아 둔 날은 통째로 건너뛴다.
    · ``RunOnlyIfNetworkAvailable`` — 네트워크 없이 돌면 ①부터 실패하므로 기다린다.
    · ``InteractiveToken`` — 로그인해 있을 때만 돈다. 비밀번호를 저장하지 않는다.
    · ``IgnoreNew`` — 이전 실행이 아직 돌면 새 실행을 만들지 않는다(러너의 잠금과 이중).
    """
    hh, mm = (int(x) for x in time_hm.split(":"))
    start = datetime.datetime.combine(today or datetime.date.today(), datetime.time(hh, mm))
    args = f'"{root / "scripts" / "daily_update.py"}" run' + (" --upload" if upload else "")

    def esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    desc = ("Qurious 수집기 일일 갱신 — 시세·배당·수정주가·TR·벤치마크"
            + (" + HF(qurious-quant/krx-daily-market) 증분 업로드" if upload else "")
            + ". 정의: scripts/daily_update.py")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{esc(desc)}</Description>
    <URI>\\{TASK_NAME}</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start.isoformat(timespec="seconds")}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
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
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <ExecutionTimeLimit>PT{LOCK_STALE_HOURS}H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
    <WakeToRun>false</WakeToRun>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{esc(python_w)}</Command>
      <Arguments>{esc(args)}</Arguments>
      <WorkingDirectory>{esc(str(root))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _pythonw() -> str:
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.exists() else exe)


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          encoding="mbcs" if os.name == "nt" else "utf-8", errors="replace")


def install(time_hm: str = DEFAULT_TIME, upload: bool = True) -> int:
    if os.name != "nt":
        print("작업 스케줄러 등록은 Windows 전용이다. 다른 OS 는 cron 에 "
              f"`cd {ROOT} && python scripts/daily_update.py run --upload` 를 건다.")
        return 1
    xml = task_xml(time_hm, upload, python_w=_pythonw(), root=ROOT)
    fd, tmp = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        Path(tmp).write_text(xml, encoding="utf-16")
        p = _schtasks("/Create", "/TN", TASK_NAME, "/XML", tmp, "/F")
    finally:
        os.unlink(tmp)
    if p.returncode != 0:
        print(f"🔴 등록 실패 (schtasks 종료코드 {p.returncode})\n{p.stdout}{p.stderr}")
        return p.returncode
    print(f"✅ 작업 스케줄러에 등록했다 — '{TASK_NAME}' · 매일 {time_hm} · "
          f"업로드 {'켬' if upload else '끔'}")
    print("   PC 가 그 시각에 꺼져 있었으면 켜진 뒤 곧바로 돈다(StartWhenAvailable).")
    print("   지금 한 번 돌리려면: python scripts/daily_update.py start")
    return 0


def uninstall() -> int:
    p = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
    print("✅ 등록을 해제했다" if p.returncode == 0 else f"🟡 {p.stdout}{p.stderr}".strip())
    return p.returncode


def start() -> int:
    p = _schtasks("/Run", "/TN", TASK_NAME)
    print(f"✅ '{TASK_NAME}' 를 시작시켰다 — 진행은 `status` 와 로그로 본다"
          if p.returncode == 0 else f"🔴 시작 실패: {p.stdout}{p.stderr}".strip())
    return p.returncode


def _task_info() -> Optional[Dict[str, str]]:
    """등록된 작업의 명령줄·마지막/다음 실행. 없으면 None. (읽기만 한다)"""
    if os.name != "nt":
        return None
    ps = (f"$t=Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue;"
          "if($t){$i=$t|Get-ScheduledTaskInfo;"
          "[pscustomobject]@{state=[string]$t.State;"
          "command=($t.Actions|%{$_.Execute+' '+$_.Arguments}) -join ' ; ';"
          "last=$i.LastRunTime.ToString('s');result=[string]$i.LastTaskResult;"
          "next=$i.NextRunTime.ToString('s')}|ConvertTo-Json -Compress}")
    p = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "").strip()
    return json.loads(out) if out.startswith("{") else None


def status() -> int:
    info = _task_info()
    print("― 예약 (작업 스케줄러) ―")
    if info:
        res = info.get("result")
        res_txt = {"0": "0 (성공)", "267009": "267009 (지금 도는 중)",
                   "267011": "267011 (아직 한 번도 안 돌았다)"}.get(res, res)
        print(f"  {TASK_NAME} · 상태 {info.get('state')}\n"
              f"  명령   {info.get('command')}\n"
              f"  마지막 {info.get('last')} · 결과 {res_txt}\n"
              f"  다음   {info.get('next')}")
    else:
        print(f"  등록돼 있지 않다 — `python scripts/daily_update.py install`")
    print("\n― 마지막 실행 ―")
    if LOCK_PATH.exists():
        try:
            held = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            held = {}
        alive = pid_alive(int(held.get("pid") or 0))
        print(f"  ⏳ {'지금 도는 중' if alive else '잠금만 남음(비정상 종료 흔적 — 다음 실행이 치운다)'}"
              f" · PID {held.get('pid')} · {held.get('started_at')} 시작")
    if not LAST_PATH.exists():
        print("  아직 끝난 실행이 없다.")
        return 0
    s = json.loads(LAST_PATH.read_text(encoding="utf-8"))
    print(f"  {s.get('started_at')} → {s.get('finished_at')} · "
          f"{'✅ 성공' if s.get('ok') else '🔴 실패 있음'} · 업로드 {'켬' if s.get('upload') else '끔'}")
    if s.get("stopped"):
        print(f"  멈춘 곳: {s['stopped']}")
    for st in s.get("steps", []):
        rc = st.get("rc")
        mark = "·" if rc is None else ("✅" if rc == 0 else "🔴")
        print(f"    {mark} {st['name']:<13} "
              + (f"종료코드 {rc} · {st.get('seconds', 0):,.0f}초" if rc is not None else "")
              + (f"  {st['note']}" if st.get("note") else ""))
    a = s.get("after") or {}
    print(f"  데이터: 시세 {a.get('price_max')} · 수정주가 {a.get('adjusted_max')} · "
          f"TR {a.get('tr_max')} · 벤치마크 {a.get('benchmark_max')} · "
          f"배당 {(a.get('dividend') or [None])[0]}건")
    print(f"  로그   {s.get('log')}")
    return 0


# ==================================================
# 5. CLI
# ==================================================
def utf8_stdio() -> None:
    """표준출력·표준오류를 UTF-8 로 맞춘다.

    git bash(mintty)에서 파이썬은 표준출력을 콘솔이 아니라 파이프로 보고 cp949 를 고른다 → `status` 가
    ✅ 에서 UnicodeEncodeError 로 죽고 한글은 `▒▒` 로 깨졌다(2026-09-28 S54 실측). 작업 스케줄러의
    ``pythonw`` 는 표준출력이 None 이라 ``hasattr`` 에서 걸러진다 — 예약 실행은 그대로다
    (자식 단계에는 ``_run_step`` 이 ``PYTHONIOENCODING=utf-8`` 을 따로 넣는다).
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python scripts/daily_update.py",
                                description="수집기 일일 갱신 — 시세·배당·파생 표 + HF 증분 업로드")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="지금 한 번 돌린다(이 터미널에서)")
    r.add_argument("--upload", action="store_true", help="HF 증분 업로드까지 한다")
    r.add_argument("--force-derived", action="store_true",
                   help="새 자료가 없어도 수정주가·TR·벤치마크를 다시 계산한다")
    sub.add_parser("status", help="마지막 실행 결과와 예약 상태")
    i = sub.add_parser("install", help="작업 스케줄러에 매일 실행 등록 (기본 업로드 포함)")
    i.add_argument("--time", default=DEFAULT_TIME, help=f"실행 시각 HH:MM (기본 {DEFAULT_TIME})")
    i.add_argument("--no-upload", action="store_true", help="로컬 갱신만 하고 HF 에 올리지 않는다")
    sub.add_parser("start", help="등록된 작업을 지금 한 번 돌린다(비동기 · 세션과 무관)")
    sub.add_parser("uninstall", help="작업 스케줄러 등록 해제")
    a = p.parse_args(argv)

    if a.cmd == "run":
        return run_all(upload=a.upload, force_derived=a.force_derived)
    if a.cmd == "status":
        return status()
    if a.cmd == "install":
        return install(a.time, upload=not a.no_upload)
    if a.cmd == "start":
        return start()
    return uninstall()


if __name__ == "__main__":
    raise SystemExit(main())
