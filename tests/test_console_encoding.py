"""사용자가 git bash 에서 직접 돌리는 스크립트가 cp949 표준출력에서 죽지 않는지 본다.

2026-09-28 S54 실측 — git bash(mintty)에서 파이썬은 표준출력을 콘솔이 아니라 파이프로 보고 cp949 로
인코딩한다. 그래서 `daily_update.py status` 가 ✅ 에서 `UnicodeEncodeError` 로 죽었고, 한글은 `▒▒` 로
깨졌다. `post_check.py` 도 같았다 — S51 부터 PR 블록의 "올릴 글 검사" 단계가 사용자 셸에서 한 번도
끝까지 돌지 않았다. Claude 의 셸에는 `PYTHONIOENCODING=utf-8` 이 잡혀 있어서 보이지 않았다.

여기서는 그 조건을 `PYTHONIOENCODING=cp949` 로 고정해 재현한다 — OS 와 무관하게 같은 결과가 나온다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_cp949(args: list[str]) -> subprocess.CompletedProcess:
    """사용자 git bash 와 같은 조건(표준출력 cp949)으로 자식 파이썬을 돌린다."""
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp949"
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, *args], cwd=ROOT, env=env,
                          capture_output=True, timeout=60)


def test_post_check_prints_marks_under_cp949(tmp_path):
    md = tmp_path / "글.md"
    md.write_text("# 제목\n\n본문 ✅\n", encoding="utf-8")
    p = _run_cp949(["scripts/post_check.py", str(md)])
    out = p.stdout.decode("utf-8")
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    assert "✅ 통과" in out
    assert "초과 0개" in out


def test_daily_update_main_prints_marks_under_cp949():
    """`status` 는 예약 상태·마지막 실행에 따라 출력이 달라서, 출력만 ✅ 로 바꿔 끼우고 `main` 을 탄다."""
    code = ("from scripts import daily_update as du\n"
            "du.status = lambda: print('✅ 성공 · 업로드 켬') or 0\n"
            "raise SystemExit(du.main(['status']))\n")
    p = _run_cp949(["-c", code])
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    assert "✅ 성공 · 업로드 켬" in p.stdout.decode("utf-8")


def test_daily_update_main_survives_pythonw_without_stdout():
    """작업 스케줄러는 `pythonw` 로 부른다 — 표준출력·표준오류가 None 이어도 그대로 돌아야 한다."""
    code = ("import sys\n"
            "sys.stdout = sys.stderr = None\n"
            "from scripts import daily_update as du\n"
            "du.status = lambda: print('✅') or 0\n"
            "raise SystemExit(du.main(['status']))\n")
    p = _run_cp949(["-c", code])
    assert p.returncode == 0
