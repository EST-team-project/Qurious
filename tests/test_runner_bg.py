"""TC-BG — 뒤에서 도는 러너 단계 실행기 (scripts/runner_bg.py · 할 일 P2 · 2026-10-30)

실제 자식 파이썬을 띄워 본다(짧은 스크립트). 러너 루프에 연결하기 전에 부품이 약속대로 도는지:
1. 띄운 채 다른 일을 할 수 있고(겹침) 끝나면 종료코드 · 걸린 시간을 돌려준다. (TC-BG-01)
2. 실패 종료코드를 그대로 돌려준다. (TC-BG-02)
3. 시간 한도는 띄운 때부터 — 넘으면 죽이고 124. (TC-BG-03)
4. 루프가 멈출 때 `terminate` 가 자식을 정리한다 · 이미 끝났으면 종료코드만. (TC-BG-04)
5. 자식 로그는 따로 쓰고 거둘 때 본 로그 끝에 붙이며, 붙이기 전 크기(mark)를 돌려준다. (TC-BG-05)
6. 이 부품은 러너(`daily_update`)를 부르지 않는다 · 같은 124 를 쓴다. (TC-BG-06)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import runner_bg as bg  # noqa: E402

PY = sys.executable


def _step(tmp_path, code, *, timeout_min=1.0, name="search"):
    return bg.BackgroundStep(name, [PY, "-c", code], cwd=tmp_path, env=dict(os.environ), timeout_min=timeout_min,
                             log_path=tmp_path / f"{name}.log")


def test_runs_in_background_and_returns_exit_code_and_seconds(tmp_path):
    """TC-BG-01 · 띄운 채 다른 일을 하는 동안 자식이 돌고, join 이 종료코드 0 · 걸린 시간을 돌려준다."""
    s = _step(tmp_path, "import time; print('시작'); time.sleep(0.6); print('끝')")
    t0 = time.time()
    s.start()
    assert time.time() - t0 < 0.5, "start 는 기다리지 않는다"
    assert s.running()
    other_work = sum(range(1000))                 # 루프가 다음 단계로 간 것을 흉내
    assert other_work == 499500 and s.running()
    assert s.join() == 0 and not s.running() and s.seconds >= 0.5
    assert "시작" in s.log_text() and "끝" in s.log_text()
    assert s.join() == 0, "join 은 여러 번 불러도 같다"


def test_failure_exit_code_is_returned_as_is(tmp_path):
    """TC-BG-02 · 실패 종료코드 · 예외 글이 로그에 남는다."""
    s = _step(tmp_path, "import sys; print('깨졌다', file=sys.stderr); sys.exit(3)")
    s.start()
    assert s.join() == 3 and "깨졌다" in s.log_text()
    s2 = _step(tmp_path, "raise RuntimeError('boom')", name="x")
    s2.start()
    assert s2.join() == 1 and "RuntimeError" in s2.log_text()


def test_timeout_counts_from_start_and_kills_with_124(tmp_path):
    """TC-BG-03 · 한도는 띄운 때부터 센다 — 다른 일을 한 시간도 포함 · 넘으면 죽이고 124(`_run_step` 과 같다)."""
    s = _step(tmp_path, "import time; time.sleep(30)", timeout_min=0.03)       # 1.8초
    s.start()
    time.sleep(1.0)                                                            # 루프가 다른 단계를 도는 동안
    t0 = time.time()
    rc = s.join()
    assert rc == bg.TIMEOUT_RC == 124
    assert time.time() - t0 < 3, "남은 시간만 기다린다(한도를 처음부터 다시 주지 않는다)"
    assert "넘겨 멈췄다" in s.log_text() and not s.running()


def test_terminate_stops_a_running_child_and_keeps_finished_code(tmp_path):
    """TC-BG-04 · 루프가 멈출 때 돌고 있는 자식은 죽이고, 이미 끝난 자식은 종료코드만 돌려준다."""
    running = _step(tmp_path, "import time; time.sleep(30)")
    running.start()
    assert running.terminate("임대를 잃음") == -9 and not running.running()
    assert "같이 멈췄다" in running.log_text() and "임대를 잃음" in running.log_text()
    done = _step(tmp_path, "pass", name="done")
    done.start()
    time.sleep(0.8)
    assert done.terminate() == 0
    with pytest.raises(RuntimeError, match="띄운 적이 없다"):
        _step(tmp_path, "pass", name="never").terminate()


def test_log_is_separate_and_merged_with_mark(tmp_path):
    """TC-BG-05 · 자식 로그는 따로 쓰이고, 거둘 때 본 로그 끝에 붙는다 — 붙이기 전 크기가 mark."""
    main = tmp_path / "round.log"
    s = _step(tmp_path, "print('검색 색인 만듦')")
    with main.open("w", encoding="utf-8") as log:
        log.write("앞 단계 로그\n")
        s.start()
        log.write("▶ adjusted …\n")                         # 겹쳐 도는 동안 본 로그는 다른 단계가 쓴다
        assert s.join() == 0
        assert "검색 색인 만듦" not in main.read_text(encoding="utf-8"), "거두기 전에는 본 로그에 안 섞인다"
        mark = s.merge_into(log)
    text = main.read_text(encoding="utf-8")
    raw = main.read_bytes()                                  # 윈도 텍스트 모드는 줄바꿈이 2바이트 — 러너 `_log_mark` 도 같은 크기를 잰다
    assert raw[:mark].decode("utf-8").replace("\r\n", "\n") == "앞 단계 로그\n▶ adjusted …\n"
    assert text.index("▶ adjusted") < text.index("뒤에서 돎") < text.index("검색 색인 만듦")
    assert raw[mark:].decode("utf-8").lstrip().startswith("=")
    s.cleanup()
    assert not (tmp_path / "search.log").exists()
    with pytest.raises(RuntimeError, match="이미 띄웠다"):
        s2 = _step(tmp_path, "pass", name="twice")
        s2.start()
        s2.start()


def test_component_is_independent_of_the_runner_and_shares_the_timeout_code():
    """TC-BG-06 · 이 부품이 러너를 부르지 않고(독립), 러너 `_run_step` 과 같은 124 를 쓴다."""
    src = (ROOT / "scripts" / "runner_bg.py").read_text(encoding="utf-8")
    assert "import daily_update" not in src and "from daily_update" not in src
    runner = (ROOT / "scripts" / "daily_update.py").read_text(encoding="utf-8")
    assert "return 124" in runner and bg.TIMEOUT_RC == 124
