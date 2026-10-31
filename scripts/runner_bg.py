"""뒤에서 도는 러너 단계 — 의존이 없는 단계를 앞 단계와 겹쳐 돌리는 실행기 (할 일 P2 · 2026-10-30 · 강사님 피드백 「속도」).

`scripts/daily_update.py` 의 단계 루프는 단계를 한 줄로 세워 돌린다. 10-29 회차에서 `search`(457초)는 가격 계산 체인
(`adjusted → total_return → benchmark → ohlcv`)의 산출물을 읽지 않고 자기 파일 `search.sqlite3` 에만 쓴다(설계 6절 H1 · 코드로 확인).
그래서 이 단계만 **자식 프로세스로 띄워 두고 루프는 다음 단계로 간다** — 루프가 끝난 뒤(백업 앞) 결과를 거둔다.
2026-10-31 에 러너 `run_all` 에 연결했다.

이 파일은 러너(`daily_update.py`)를 부르지 않는 **독립 부품**이다(시험이 자식 프로세스로 직접 확인한다).

규칙
  · 자식 출력은 **따로 임시 로그**에 쓰고 거둘 때 한 번에 본 로그에 붙인다 — 앞 단계 로그와 줄이 섞이지 않고,
    본 로그 위치를 읽어 까닭을 뽑는 `step_failure(mark)` 가 그대로 맞는다.
  · 시간 한도는 **띄운 때부터** 센다. 넘으면 죽이고 종료코드 124(`_run_step` 과 같다). 한도와 끝난 때는 **감시 스레드**가 지킨다 —
    거두는 때(`join`)에 가서야 재면 일찍 끝난 자식의 걸린 시간이 거둔 때까지 늘어나고(S178 에 연결하며 고침), 멈춘 자식이 거둘 때까지 산다.
  · 루프가 멈추는 때(임대를 잃음 · 앞 단계 치명 실패)는 `terminate()` 로 정리한다 — 자식을 고아로 남기지 않는다.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

try:                         # 러너는 `scripts.runner_bg` 로, 시험은 `runner_bg` 로 불러 온다
    from scripts.proc_stats import measure
except ImportError:          # pragma: no cover — scripts/ 폴더가 경로에 있을 때
    from proc_stats import measure

TIMEOUT_RC = 124            # `daily_update._run_step` 이 시간을 넘길 때 돌려주는 코드와 같다
KILLED_RC = -9              # `terminate` 가 죽인 자식


class BackgroundStep:
    """자식 프로세스 하나 — `start()` → (다른 일) → `join()`."""

    def __init__(self, name: str, argv: List[str], *, cwd: Path, env: Dict[str, str], timeout_min: float, log_path: Path):
        self.name, self.argv, self.cwd, self.env = name, list(argv), cwd, dict(env)
        self.timeout_s = float(timeout_min) * 60
        self.log_path = Path(log_path)
        self.proc: Optional[subprocess.Popen] = None
        self._log = None
        self.t0: Optional[float] = None
        self.t_end: Optional[float] = None          # 감시 스레드가 자식이 끝난 때(또는 죽인 때)를 적는다
        self.seconds: Optional[float] = None        # 띄운 때부터 끝난 때까지 — 거둔 때가 아니다
        self.rc: Optional[int] = None
        self.cpu_seconds: Optional[float] = None
        self._meter = None
        self._done = threading.Event()
        self._killed = False                         # `terminate` 가 죽였나 — 감시 스레드가 종료코드를 -9 로 적게
        self._closed = False

    def start(self) -> None:
        if self.proc is not None:
            raise RuntimeError(f"{self.name}: 이미 띄웠다")
        self._log = self.log_path.open("w", encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.t0 = time.time()
        self.proc = subprocess.Popen(self.argv, cwd=self.cwd, env=self.env, stdout=self._log, stderr=subprocess.STDOUT,
                                     creationflags=flags)
        self._meter = measure(self.proc)
        threading.Thread(target=self._watch, name=f"bg-{self.name}", daemon=True).start()

    def _watch(self) -> None:
        """자식이 끝나기를(또는 한도를) 기다려 종료코드 · 끝난 때를 적는다 — 이 스레드가 한도를 지킨다."""
        assert self.proc is not None
        timed_out = False
        try:
            code = self.proc.wait(timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            if not self._killed:
                timed_out = True
                self.proc.kill()
            code = self.proc.wait()
        self.t_end = time.time()
        if self._meter is not None:                     # 끝난 자식(과 손자)의 CPU 초 — Windows 만 · 잴 수 없으면 None
            self.cpu_seconds = self._meter.seconds()
            self._meter.close()
        if self._killed:
            self.rc = KILLED_RC
        elif timed_out:
            self.rc = TIMEOUT_RC
            self._write(f"\n⏱ {self.timeout_s / 60:g}분을 넘겨 멈췄다\n")
        else:
            self.rc = code
        self._done.set()

    def _write(self, text: str) -> None:
        if self._log is not None and not self._closed:
            try:
                self._log.write(text)
                self._log.flush()
            except (OSError, ValueError):
                pass

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def join(self) -> int:
        """끝나기를 기다려 종료코드를 돌려준다 — 한도(띄운 뒤 `timeout_min`)를 넘기면 감시 스레드가 죽였고 124."""
        if self.proc is None:
            raise RuntimeError(f"{self.name}: 띄운 적이 없다")
        self._done.wait()
        self._close()
        return self.rc  # type: ignore[return-value]

    def terminate(self, why: str = "") -> int:
        """루프가 멈출 때 — 아직 돌고 있으면 죽인다(이미 끝났으면 종료코드만)."""
        if self.proc is None:
            raise RuntimeError(f"{self.name}: 띄운 적이 없다")
        if not self._done.is_set() and self.proc.poll() is None:
            self._killed = True
            self.proc.kill()
            self._done.wait()
            self._write(f"\n🛑 회차가 멈춰 같이 멈췄다{' — ' + why if why else ''}\n")
        else:
            self._done.wait()
        self._close()
        return self.rc  # type: ignore[return-value]

    def _close(self) -> None:
        if self._closed:
            return
        self.seconds = round((self.t_end or time.time()) - (self.t0 or time.time()), 1)
        if self._log is not None:
            self._log.flush()
            self._log.close()
            self._log = None
        self._closed = True

    def log_text(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def merge_into(self, main_log, header: str = "") -> int:
        """자식 로그를 본 로그 파일 객체 끝에 붙이고, 붙이기 전 본 로그 크기(바이트)를 돌려준다 — `step_failure(mark)` 의 시작점."""
        main_log.flush()
        try:
            mark = Path(main_log.name).stat().st_size
        except OSError:
            mark = 0
        main_log.write(header or f"\n{'=' * 70}\n▶ {self.name} (뒤에서 돎 · 겹쳐 돌린 단계의 로그)\n{'=' * 70}\n")
        main_log.write(self.log_text())
        main_log.flush()
        return mark

    def cleanup(self) -> None:
        try:
            self.log_path.unlink()
        except OSError:
            pass
