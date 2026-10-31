"""TC-CPU — 자식 프로세스(와 손자)의 CPU 시간 (scripts/proc_stats.py · 할 일 P1 · 2026-10-31)

수집 단계가 계산에 묶였는지(CPU 초 ≈ 걸린 초), 기다림에 묶였는지(CPU 초 ≪ 걸린 초) 가리는 재료다. 가상환경의 `python.exe` 는 진짜
인터프리터를 다시 띄우는 껍데기라 자식 핸들 하나만 읽으면 계산도 0.06초로 나온다 — 작업 개체(Job Object)로 손자까지 합친다.
Windows 에서만 재므로 그 밖에서는 `None` 을 돌려주는 것이 약속이다(기록 칸이 비는 것이지 오류가 아니다).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from scripts import daily_update as du
from scripts.proc_stats import CpuMeter, measure

WIN = os.name == "nt"
BUSY = "import time; t=time.time()\nwhile time.time()-t < {s}: pass"


def _spawn(code: str):
    p = subprocess.Popen([sys.executable, "-c", code])
    return p, measure(p)


@pytest.mark.skipif(not WIN, reason="작업 개체는 Windows 것")
def test_busy_child_has_cpu_time_and_sleeping_child_has_almost_none():
    """TC-CPU-01 · 계산하는 자식은 CPU 초가 걸린 시간과 비슷하고, 기다리기만 하는 자식은 거의 0 이다 — 가상환경 껍데기 아래 진짜
    인터프리터(손자)의 시간까지 들어온다(자식 핸들 하나만 읽으면 0.06초였다)."""
    busy, mb = _spawn(BUSY.format(s=0.6))
    busy.wait()
    sleepy, ms = _spawn("import time; time.sleep(0.6)")
    sleepy.wait()
    assert mb is not None and ms is not None
    assert mb.seconds() >= 0.4, f"0.6초 계산했는데 CPU 초가 {mb.seconds()} — 손자가 빠졌나"
    assert ms.seconds() < 0.3, "기다리기만 했는데 CPU 초가 크다"
    mb.close()
    ms.close()


@pytest.mark.skipif(not WIN, reason="작업 개체는 Windows 것")
def test_grandchildren_are_counted():
    """TC-CPU-02 · 자식이 다시 띄운 손자 프로세스의 계산도 합쳐진다."""
    code = f"import subprocess,sys; subprocess.run([sys.executable,'-c',{BUSY.format(s=0.6)!r}])"
    p, m = _spawn(code)
    p.wait()
    assert m is not None and m.seconds() >= 0.4
    m.close()


@pytest.mark.skipif(WIN, reason="Windows 밖의 약속")
def test_returns_none_outside_windows():
    """TC-CPU-03 · Windows 가 아니면 재지 않고 None — 오류를 내지 않는다."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert measure(p) is None


def test_wrong_objects_are_never_attached():
    """TC-CPU-04 · Popen 이 아닌 것(핸들 -1 = 내 자신을 가리키는 가짜 포함)은 작업 개체에 넣지 않고 None — 시험 프로세스가 작업 개체에
    들어가거나 잘못 재는 일이 없다."""
    class Fake:
        _handle = -1

    assert measure(Fake()) is None and measure(object()) is None and measure(None) is None


@pytest.mark.skipif(not WIN, reason="작업 개체는 Windows 것")
def test_runner_records_cpu_seconds_on_the_step_row(tmp_path):
    """TC-CPU-05 · 러너가 순차 단계의 CPU 초를 단계 줄(`cpu_seconds`)에 적고 이력 줄(`_compact`)에도 남긴다 — 계산 단계는 0.3 이상.
    시간을 넘긴 단계는 124 이고 CPU 초는 적지 않는다(끝까지 못 돌았다)."""
    step = du.Step("busy", ["-c", BUSY.format(s=0.5)], 1, label="계산", group="계산", desc="시험")
    log_path = tmp_path / "run.log"
    with log_path.open("w", encoding="utf-8") as log:
        run = du.Run(du.now_kst(), False, log, log_path)
        assert du._run_step(run, step) == 0
        rec = du._rec(step)
        du._put_dart(run, step, rec)
    assert rec["cpu_seconds"] >= 0.3 and "dart_calls" not in rec
    assert du._compact([dict(rec, rc=0)])[0]["cpu_seconds"] == rec["cpu_seconds"]
    slow = du.Step("slow", ["-c", "import time; time.sleep(30)"], 0.02, label="느림", group="계산", desc="시험")
    with log_path.open("a", encoding="utf-8") as log:
        run2 = du.Run(du.now_kst(), False, log, log_path)
        t0 = time.time()
        assert du._run_step(run2, slow, timeout_min=0.02) == 124 and time.time() - t0 < 5
    assert "slow" not in run2.cpu


@pytest.mark.skipif(not WIN, reason="작업 개체는 Windows 것")
def test_background_step_cpu_seconds_reach_the_row(tmp_path):
    """TC-CPU-06 · 뒤에서 돈 단계의 CPU 초도 거둘 때 같은 칸에 들어간다."""
    from scripts.runner_bg import BackgroundStep

    bg = BackgroundStep("idx", [sys.executable, "-c", BUSY.format(s=0.5)], cwd=tmp_path, env=dict(os.environ),
                        timeout_min=1, log_path=tmp_path / "idx.log")
    bg.start()
    assert bg.join() == 0 and bg.cpu_seconds is not None and bg.cpu_seconds >= 0.3
