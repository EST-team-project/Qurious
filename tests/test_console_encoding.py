"""사용자가 git bash 에서 직접 돌리는 스크립트가 cp949 표준출력에서 죽지 않는지 본다.

2026-09-28 S54 실측 — git bash(mintty)에서 파이썬은 표준출력을 콘솔이 아니라 파이프로 보고 cp949 로
인코딩한다. 그래서 `daily_update.py status` 가 ✅ 에서 `UnicodeEncodeError` 로 죽었고, 한글은 `▒▒` 로
깨졌다. `post_check.py` 도 같았다 — S51 부터 PR 블록의 "올릴 글 검사" 단계가 사용자 셸에서 한 번도
끝까지 돌지 않았다. Claude 의 셸에는 `PYTHONIOENCODING=utf-8` 이 잡혀 있어서 보이지 않았다.

여기서는 그 조건을 `PYTHONIOENCODING=cp949` 로 고정해 재현한다 — OS 와 무관하게 같은 결과가 나온다.

2026-09-29 S62 (DF-11) — 위 두 스크립트만 지키던 것을 사람이 직접 돌리는 진입점 **전부**로 넓혔다.
v1.2 는 `print` 안의 **그림 글자**를 세어 10파일이라 적었지만, S60 에 `benchmark status` 를 죽인 것은
그림 글자가 아니라 줄표 `—`(U+2014)였다. cp949 로 못 쓰는 글자 전체로 다시 세면 15곳이다.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


# ── DF-11 — 사람이 직접 돌리는 진입점 전부 (2026-09-29 S62) ──────────────────────────
# argparse 로 인자를 받는 11곳은 `--help` 로 직접 돌려 본다. 나머지 4곳(`verify_*` 3 · `take_screenshots` —
# 인자 없이 곧바로 Postgres · Redis · 브라우저를 연다)은 돌리지 않고 아래 정적 검사가 지킨다.
ARGPARSE_ENTRY_POINTS = [
    "collector.backfill", "collector.benchmark", "collector.dividend", "collector.manifest",
    "collector.preprocess", "collector.total_return",
    "scripts/hf_dataset.py", "scripts/probe_kis_fee_rate.py", "scripts/rtm_scan.py",
    "scripts/schema_scan.py", "scripts/sync_fills.py",
]

# 자식 파이썬 안에서: DB 를 여는 길을 막고 → 진입점을 `--help` 로 돌리고 → 끝난 뒤 한 줄 더 찍는다.
# 마지막 줄이 요점이다 — 도움말 문구가 우연히 cp949 로 써지는 모듈(rtm_scan 등)도 `main` 이 표준출력을
# UTF-8 로 바꾸지 않았다면 여기서 죽는다. DB 를 막는 이유는 옛 `preprocess` 가 `--help` 를 보지 않고 곧바로
# 전 종목 재계산을 시작하기 때문이다(DF-16) — 옛 코드로 이 시험을 돌려도 실제 수집 DB 에 닿지 않는다.
_HELP_DRIVER = """
import runpy, sqlite3, sys
import collector.db

def _refuse(*a, **k):
    raise RuntimeError("--help 가 DB 를 열었다")

collector.db.connect = _refuse
sqlite3.connect = _refuse
target = sys.argv[1]
sys.argv = [target, "--help"]
try:
    if target.endswith(".py"):
        runpy.run_path(target, run_name="__main__")
    else:
        runpy.run_module(target, run_name="__main__", alter_sys=True)
except SystemExit as e:
    if e.code not in (0, None):
        raise
print("✅ — 도움말 뒤에도 UTF-8")
"""


@pytest.mark.parametrize("target", ARGPARSE_ENTRY_POINTS)
def test_entry_point_help_and_later_output_survive_cp949(target):
    p = _run_cp949(["-c", _HELP_DRIVER, target])
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")[-800:]
    out = p.stdout.decode("utf-8")
    assert "usage:" in out
    assert out.rstrip().endswith("✅ — 도움말 뒤에도 UTF-8")


_MAIN_RE = re.compile(r"""__name__\s*==\s*["']__main__["']""")
_UTF8_FIX = ("utf8_stdio()", 'reconfigure(encoding="utf-8")')
_OUTPUT_CALLS = {"print", "ArgumentParser", "add_argument", "add_parser"}


def _non_cp949_output(src: str) -> list[str]:
    """표준출력 · 표준오류로 나가는 문자열 안의 cp949 밖 글자 — ``U+2014@250`` 모양(문자열마다 첫 글자만)."""
    found = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        to_std = (name == "write" and isinstance(fn, ast.Attribute)
                  and ast.unparse(fn.value) in ("sys.stdout", "sys.stderr"))
        if name not in _OUTPUT_CALLS and not to_std:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                for ch in sub.value:
                    try:
                        ch.encode("cp949")
                    except UnicodeEncodeError:
                        found.append(f"U+{ord(ch):04X}@{sub.lineno}")
                        break
    return found


def test_every_entry_point_printing_outside_cp949_switches_to_utf8():
    """정적 검사 — 새 진입점이 같은 길을 다시 밟지 않게.

    파일마다 따로 고치면 새 파일이 또 빠진다(S54 에 둘 · S60 재측정에 열 · S62 재측정에 다섯).
    `collector/` 는 `collector.console.utf8_stdio()` 를, `scripts/` 는 같은 세 줄(`reconfigure`)을 쓴다.
    """
    missing = {}
    for folder in ("collector", "scripts"):
        for f in sorted((ROOT / folder).glob("*.py")):
            src = f.read_text(encoding="utf-8")
            if not _MAIN_RE.search(src) or any(fix in src for fix in _UTF8_FIX):
                continue
            bad = _non_cp949_output(src)
            if bad:
                missing[f"{folder}/{f.name}"] = bad[:3]
    assert missing == {}, f"cp949 밖 글자를 찍는데 UTF-8 로 바꾸지 않는 진입점 {len(missing)}곳: {missing}"
