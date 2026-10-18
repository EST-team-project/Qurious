"""주 1회 복구 시험(2차-3 · 2026-10-18) — 정기 회차 밖(일요일 15:00)에 깊은 대조 → 복원 리허설 → 백업 판정 기록.

왜: 백업은 되살려 봐야 증명된다 — SRE 「Continuously test the recovery process as part of your normal operations」
(조사서 `docs/조사/자동수집-벤치마크-조사.md` 369 · 431줄). 지금까지 리허설은 손으로만 돌아(마지막 성공 2026-10-08) 적재 · 백업
판정이 「기록이 옛 매니페스트 것이다 — restore 를 다시」 로 남았다. 같은 때 매주 돌려, 관제 · 적재 · 백업 화면이
「마지막 성공 리허설 n일 전」 을 보이게 한다(규칙 · 기록은 `scripts/hf_dataset.py` 한 곳 — 이 스크립트는 차례대로 부르기만).

- 단계: `hf_dataset.py` 명령 셋을 자식으로 차례대로 — ① `verify --deep`(파케이 ↔ 수집 DB 값까지) ② `restore`(임시 폴더에
  되살려 지문 대조 · 수집 DB 는 그대로) ③ `status --write`(판정 기록). 앞 단계가 실패해도 뒤 단계는 돈다 — 셋이 따로 된 증거라서.
- 러너 잠금을 함께 쥔다 — 러너 · 화면 수집 요청이 수집 DB 를 고치는 동안 대조하면 엇갈린다. 대신 12:30 회차가 이 잠금에 걸려
  통째로 건너뛰지 않게, 「회차 시작 − 한 바퀴 한도」 ~ 「회차 시작 + 60분」 에는 시작하지 않는다(셈은 러너 `guard_window` 한 곳).
- 수집 DB 를 읽었으니 끝에 WAL 보조 파일을 다시 남긴다(`rearm_wal` — 앱이 「unable to open database file」 로 멈추지 않게 · DF-74).
- 바퀴 기록은 상태 폴더 `weekly_rehearsal.json`(예약 · 마지막 바퀴 · 건너뛴 까닭). 「마지막 성공」 의 증거는 도구가 판정 기록에
  싣는 `rehearsal` 칸이다 — 손으로 돌린 리허설도 같은 칸에 남는다.
종료코드: 0 셋 다 성공 · 1 한 단계라도 실패 · 75 지금은 못 돈다(막는 때 · 다른 실행) — 러너와 같은 약속(EX_TEMPFAIL).

쓰는 법::

    python scripts/weekly_rehearsal.py run         # 한 바퀴(작업 스케줄러가 매주 부른다 · 손으로도 된다)
    python scripts/weekly_rehearsal.py status      # 마지막 바퀴 · 예약
    python scripts/weekly_rehearsal.py install     # 작업 스케줄러에 매주 일요일 15:00 등록
    python scripts/weekly_rehearsal.py uninstall
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, TextIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402
from scripts import daily_update as du  # noqa: E402

TASK_NAME = "Qurious-weekly-rehearsal"
#: 예약 — 일요일은 회차가 가볍고(휴장) 12:30 회차가 끝난 뒤라 그날 내보낸 파케이를 대조한다.
WEEKDAY_XML, WEEKDAY_KO, TIME_HM = "Sunday", "일요일", "15:00"
#: 한 바퀴 한도(분) — 2026-10-08 리허설 495초 · 깊은 대조 포함 여유. 막는 때도 이 값으로 센다.
TIMEOUT_MIN = 60
#: 마지막 성공에서 이만큼 지나면 화면이 「확인 필요」 — 주 1회 + 하루 여유. 앱(`app/services/data_status.py`
#: `REHEARSAL_STALE_DAYS`)과 같은 값인지 TC-WR 이 맞댄다(앱 컨테이너는 이 파일을 읽지 못해 두 곳에 적는다).
STALE_AFTER_DAYS = 8
STATE_PATH = config.STATE_DIR / "weekly_rehearsal.json"
LOG_DIR = config.DATA_DIR / "logs"
KEEP_LOGS = 12
STEPS = (
    ("deep_verify", "깊은 대조", ["verify", "--deep"]),
    ("restore", "복원 리허설", ["restore"]),
    ("status", "판정 기록", ["status", "--write"]),
)


def schedule_text() -> str:
    return f"매주 {WEEKDAY_KO} {TIME_HM}"


def blocked(now: datetime.datetime) -> Optional[str]:
    """지금 시작하면 12:30 회차와 겹치는가 — 겹치면 까닭 한 줄(셈은 러너 `guard_window` 한 곳)."""
    lo, hi = du.guard_window(TIMEOUT_MIN, now)
    if lo <= now <= hi:
        return (f"{lo:%H:%M} ~ {hi:%H:%M} 에는 시작하지 않는다 — {du.DEFAULT_TIME} 회차와 겹친다"
                f"(한 바퀴 한도 {TIMEOUT_MIN}분 · 다음 예약에 다시)")
    return None


def _log_file(now: datetime.datetime) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for old in sorted(LOG_DIR.glob("weekly_rehearsal-*.log"))[:-KEEP_LOGS]:
        old.unlink(missing_ok=True)
    return LOG_DIR / f"weekly_rehearsal-{now.strftime('%Y%m%d-%H%M%S')}.log"


def run_child(args: Sequence[str], log: TextIO, timeout_s: int) -> int:
    """`hf_dataset.py <args>` 를 자식으로 — 출력은 로그 파일로(작업 스케줄러는 창 없는 pythonw 로 부른다)."""
    cmd = [du.child_python(), str(ROOT / "scripts" / "hf_dataset.py"), *args]
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    try:
        return subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout_s).returncode
    except subprocess.TimeoutExpired:
        return 124


def write_state(**kw) -> None:
    """상태 기록 — 앞 기록에 합쳐 쓴다. 예약 칸(`schedule`)은 install · uninstall 만 쓰고(손으로 돌린 바퀴가 「예약 있음」 으로
    보이지 않게), 바퀴 칸(`started_at` · `result` · `steps` …)은 run 이 쓴다. 못 써도 바퀴의 결과(종료코드)는 그대로."""
    try:
        old = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    try:
        du._write_json_atomic(STATE_PATH, {**old, "stale_after_days": STALE_AFTER_DAYS, **kw})
    except OSError:
        pass


def run(*, now: Optional[datetime.datetime] = None, child: Optional[Callable[[Sequence[str], TextIO, int], int]] = None) -> int:
    now = now or du.now_kst()
    started = du._iso(now)
    why = blocked(now)
    if why:
        write_state(started_at=started, finished_at=started, result="skipped", why=why, steps=[])
        print(f"⏭ 건너뜀 — {why}")
        return du.EX_TEMPFAIL
    held = du.acquire_lock(du.LOCK_PATH, now=now)          # 경로는 부를 때 읽는다(시험이 바꿀 수 있게)
    if held:
        write_state(started_at=started, finished_at=started, result="skipped", why=held, steps=[])
        print(f"⏭ 건너뜀 — {held}")
        return du.EX_TEMPFAIL
    steps: List[Dict] = []
    try:
        with open(_log_file(now), "a", encoding="utf-8") as log:
            deadline = time.monotonic() + TIMEOUT_MIN * 60
            for key, label, args in STEPS:
                t0 = time.monotonic()
                log.write(f"\n== {label} — hf_dataset.py {' '.join(args)} ==\n")
                log.flush()
                rc = (child or run_child)(args, log, max(60, int(deadline - t0)))
                steps.append({"key": key, "label": label, "rc": rc, "seconds": round(time.monotonic() - t0, 1)})
                print(f"{'✅' if rc == 0 else '🔴'} {label} 종료코드 {rc} · {steps[-1]['seconds']}초")
    finally:
        du.rearm_wal()                                     # 수집 DB 를 읽었다 — 보조 파일을 다시 남긴다
        du.release_lock(du.LOCK_PATH)
    ok = all(s["rc"] == 0 for s in steps)
    bad = [f"{s['label']} 종료코드 {s['rc']}" for s in steps if s["rc"] != 0]
    write_state(started_at=started, finished_at=du._iso(du.now_kst()), result="ok" if ok else "failed",
                why="" if ok else " · ".join(bad), steps=steps)
    return 0 if ok else 1


def task_xml(*, python_w: str, root: Path, today: Optional[datetime.date] = None) -> str:
    """작업 스케줄러 정의(XML · 매주). 설정의 뜻은 러너 `task_xml` 과 같다 — 다른 점만:

    · ``ScheduleByWeek`` 일요일 · ``RunOnlyIfNetworkAvailable`` 끔(리허설은 로컬 파일만 본다).
    · ``StartWhenAvailable`` — 그때 PC 가 꺼져 있었으면 켜진 뒤 돈다. 켜진 때가 회차 앞뒤면 스스로 건너뛴다(``blocked``).
    """
    hh, mm = (int(x) for x in TIME_HM.split(":"))
    day = today or datetime.date.today()
    day = day + datetime.timedelta(days=(6 - day.weekday()) % 7)     # 다음(또는 오늘) 일요일
    start = datetime.datetime.combine(day, datetime.time(hh, mm))
    args = f'"{root / "scripts" / "weekly_rehearsal.py"}" run'

    def esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    desc = ("Qurious 주 1회 복구 시험 — 깊은 대조 · 복원 리허설(임시 폴더) · 백업 판정 기록. "
            "정의: scripts/weekly_rehearsal.py")
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
      <ScheduleByWeek><DaysOfWeek><{WEEKDAY_XML} /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek>
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
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
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


def install() -> int:
    if os.name != "nt":
        print("작업 스케줄러 등록은 Windows 전용이다. 다른 OS 는 cron 에 매주 일요일 15:00 "
              f"`cd {ROOT} && python scripts/weekly_rehearsal.py run` 을 건다.")
        return 1
    xml = task_xml(python_w=du._pythonw(), root=ROOT)
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
    write_state(schedule=schedule_text(), installed_at=du._iso(du.now_kst()))
    print(f"✅ 작업 스케줄러에 등록했다 — '{TASK_NAME}' · {schedule_text()}")
    print("   상태: python scripts/weekly_rehearsal.py status · 끄기: python scripts/weekly_rehearsal.py uninstall")
    return 0


def uninstall() -> int:
    p = du._schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if p.returncode == 0:
        write_state(schedule=None, uninstalled_at=du._iso(du.now_kst()))
    print("✅ 등록 해제" if p.returncode == 0 else f"등록이 없거나 해제 실패 (종료코드 {p.returncode})")
    return 0 if p.returncode == 0 else 1


def status() -> int:
    try:
        st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = None
    print("― 마지막 바퀴 ―")
    if not st:
        print("  기록 없음 — 아직 한 번도 돌지 않았다")
    else:
        print(f"  {st.get('started_at')} → {st.get('finished_at')} · {st.get('result')} · {st.get('why') or ''}")
        for s in st.get("steps") or []:
            print(f"    {s.get('label')} · 종료코드 {s.get('rc')} · {s.get('seconds')}초")
    p = du._schtasks("/Query", "/TN", TASK_NAME, "/FO", "LIST")
    print("― 작업 스케줄러 ―")
    print("  " + (p.stdout.strip().replace("\n", "\n  ") if p.returncode == 0 else "등록 안 됨 — install"))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    du.utf8_stdio()
    ap = argparse.ArgumentParser(prog="python scripts/weekly_rehearsal.py",
                                 description="주 1회 복구 시험 — 깊은 대조 · 복원 리허설 · 백업 판정 기록")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="한 바퀴(작업 스케줄러가 매주 부른다)")
    sub.add_parser("status", help="마지막 바퀴 · 예약")
    sub.add_parser("install", help=f"작업 스케줄러에 {schedule_text()} 등록")
    sub.add_parser("uninstall", help="작업 스케줄러 등록 해제")
    a = ap.parse_args(argv)
    return {"run": run, "status": status, "install": install, "uninstall": uninstall}[a.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
