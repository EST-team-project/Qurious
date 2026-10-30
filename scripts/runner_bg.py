"""뒤에서 도는 러너 단계 — 의존이 없는 단계를 앞 단계와 겹쳐 돌리는 실행기 (할 일 P2 · 2026-10-30 · 강사님 피드백 「속도」).

`scripts/daily_update.py` 의 단계 루프는 단계를 한 줄로 세워 돌린다. 10-29 회차에서 `search`(457초)는 가격 계산 체인
(`adjusted → total_return → benchmark → ohlcv`)의 산출물을 읽지 않고 자기 파일 `search.sqlite3` 에만 쓴다(설계 6절 H1 · 코드로 확인).
그래서 이 단계만 **자식 프로세스로 띄워 두고 루프는 다음 단계로 간다** — 루프가 끝난 뒤(백업 앞) 결과를 거둔다.

이 파일은 러너(`daily_update.py`)를 부르지 않는 **독립 부품**이다(시험이 자식 프로세스로 직접 확인한다).

규칙
  · 자식 출력은 **따로 임시 로그**에 쓰고 거둘 때 한 번에 본 로그에 붙인다 — 앞 단계 로그와 줄이 섞이지 않고,
    본 로그 위치를 읽어 까닭을 뽑는 `step_failure(mark)` 가 그대로 맞는다.
  · 시간 한도는 **띄운 때부터** 센다. 넘으면 죽이고 종료코드 124(`_run_step` 과 같다).
  · 루프가 멈추는 때(임대를 잃음 · 앞 단계 치명 실패)는 `terminate()` 로 정리한다 — 자식을 고아로 남기지 않는다.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

TIMEOUT_RC = 124            # `daily_update._run_step` 이 시간을 넘길 때 돌려주는 코드와 같다


class BackgroundStep:
    """자식 프로세스 하나 — `start()` → (다른 일) → `join()`."""

    def __init__(self, name: str, argv: List[str], *, cwd: Path, env: Dict[str, str], timeout_min: float, log_path: Path):
        self.name, self.argv, self.cwd, self.env = name, list(argv), cwd, dict(env)
        self.timeout_s = float(timeout_min) * 60
        self.log_path = Path(log_path)
        self.proc: Optional[subprocess.Popen] = None
        self._log = None
        self.t0: Optional[float] = None
        self.seconds: Optional[float] = None
        self.rc: Optional[int] = None

    def start(self) -> None:
        if self.proc is not None:
            raise RuntimeError(f"{self.name}: 이미 띄웠다")
        self._log = self.log_path.open("w", encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.t0 = time.time()
        self.proc = subprocess.Popen(self.argv, cwd=self.cwd, env=self.env, stdout=self._log, stderr=subprocess.STDOUT,
                                     creationflags=flags)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def join(self) -> int:
        """끝나기를 기다려 종료코드를 돌려준다 — 띄운 뒤 `timeout_min` 을 넘기면 죽이고 124."""
        if self.proc is None:
            raise RuntimeError(f"{self.name}: 띄운 적이 없다")
        if self.rc is not None:
            return self.rc
        remaining = max(self.timeout_s - (time.time() - (self.t0 or time.time())), 0.0)
        try:
            self.rc = self.proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            self.rc = TIMEOUT_RC
            self._log.write(f"\n⏱ {self.timeout_s / 60:g}분을 넘겨 멈췄다\n")
        self._close()
        return self.rc

    def terminate(self, why: str = "") -> int:
        """루프가 멈출 때 — 아직 돌고 있으면 죽인다(이미 끝났으면 종료코드만)."""
        if self.proc is None:
            raise RuntimeError(f"{self.name}: 띄운 적이 없다")
        if self.rc is None:
            if self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait()
                self._log.write(f"\n🛑 회차가 멈춰 같이 멈췄다{' — ' + why if why else ''}\n")
                self.rc = -9
            else:
                self.rc = self.proc.returncode
            self._close()
        return self.rc

    def _close(self) -> None:
        self.seconds = round(time.time() - (self.t0 or time.time()), 1)
        if self._log is not None:
            self._log.flush()
            self._log.close()
            self._log = None

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
