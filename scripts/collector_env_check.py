"""수집기 환경 점검 — 수집기 · 러너가 쓰는 바깥 패키지가 이 파이썬에 다 있고 요구 파일에 선언돼 있나 (할 일 ①-31 · DF-157 · 2026-10-26).

까닭 — 분봉 받기 패키지(DF-157)는 분봉 수집 코드가 함수 안에서 import 하는데 어느 요구 파일에도 없었다. 노트북에는
손으로 깔려 있었고, 데스크톱 첫 회차에서 분봉 60분 · 5분 단계가 `ModuleNotFoundError` 로 실패했다. 함수 안(늦은) import 는 시작할 때
드러나지 않으므로 코드를 **읽어서** 센다(ast — 실행하지 않는다 · 네트워크 없음).

세 가지를 본다
1. 설치 — 이 파이썬에서 import 할 수 있나(새 PC 첫 켜짐 · 판이 다른 가상환경)
2. 선언 — 설치된 것이 속한 배포판이 `requirements.lock`(요구 파일을 풀어 쓴 전이 의존까지)에 있나. 없으면 노트북 손 설치처럼
   `pip install -r requirements.txt -c requirements.lock` 만 한 다음 PC 에서 또 빠진다. 선언된 패키지의 전이 의존(httpx2 · pyyaml)은 잠금에 있어 통과한다
3. 고치는 법 — 막다른 길로 만들지 않는다: 무엇을 해야 하는지를 한 줄로 낸다

쓰는 법: `python scripts/collector_env_check.py` (0 = 이상 없음 · 1 = 설치 안 됨 · 2 = 설치됐지만 선언 안 됨)
"""
from __future__ import annotations

import ast
import importlib.metadata as md
import importlib.util
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

#: 훑는 코드 — 수집기 전체 · 러너 · 작업자 · 임대 · 올리기 · 맞추기 · 복구 시험(호스트에서 도는 것들)
SCAN_DIRS = ("collector",)
SCAN_FILES = ("scripts/daily_update.py", "scripts/collect_worker.py", "scripts/run_lease.py", "scripts/hf_dataset.py",
              "scripts/hf_sync.py", "scripts/weekly_rehearsal.py")
LOCK_FILE = "requirements.lock"

#: 이 저장소 안의 최상위 이름 — 바깥 패키지가 아니다
_LOCAL = {"collector", "scripts", "app", "config"}

#: 일부러 요구 파일에 넣지 않은 선택 도구 — 깔려 있지 않아도 이상이 아니다(쓰는 명령이 막다른 길 없이 할 일을 안내한다)
OPTIONAL: Dict[str, str] = {
    "FinanceDataReader": "일봉 대조(`ohlcv_load crosscheck`) 한 명령만 쓴다 — robots.txt 로 막힌 경로를 타서 요구 파일에 넣지 않기로 했다(#23 · #33)",
    "ragas": "근거 답 충실도 평가(`kb_faith_eval`) — 호스트 평가 도구 · 앱 이미지에는 없다",
    "sentence_transformers": "재순위 실측(`kb_rerank_eval`) — 호스트 평가 도구 · 앱 이미지에는 없다",
    "torch": "재순위 실측(`kb_rerank_eval`) — 호스트 평가 도구 · 앱 이미지에는 없다",
}


def _canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def scan_files(root: Path = ROOT) -> List[Path]:
    files: List[Path] = []
    for d in SCAN_DIRS:
        files += sorted((root / d).rglob("*.py"))
    files += [root / f for f in SCAN_FILES if (root / f).exists()]
    return files


def imported_top_levels(path: Path) -> Set[str]:
    """한 파일이 import 하는 최상위 이름 — 함수 안(늦은) import 도 센다. 상대 import 는 이 저장소 것이라 뺀다."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def third_party_imports(root: Path = ROOT) -> Dict[str, List[str]]:
    """바깥 패키지의 최상위 이름 → 그것을 부르는 파일들(저장소 기준 경로). 표준 라이브러리 · 이 저장소 안 이름은 뺀다."""
    found: Dict[str, List[str]] = {}
    for f in scan_files(root):
        for name in imported_top_levels(f):
            if name in sys.stdlib_module_names or name in _LOCAL or name == "__future__":
                continue
            if (root / name).exists() or (root / f"{name}.py").exists():
                continue
            found.setdefault(name, []).append(f.relative_to(root).as_posix())
    return {k: sorted(v) for k, v in sorted(found.items())}


def locked_names(root: Path = ROOT) -> Set[str]:
    """잠금 파일에 정확한 판으로 적힌 배포판 이름 — 요구 파일을 풀어 쓴 전이 의존까지(`pip install -r … -c 잠금` 이 까는 것)."""
    p = root / LOCK_FILE
    text = p.read_text(encoding="utf-8-sig") if p.exists() else ""
    return {_canon(m.group(1)) for m in re.finditer(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", text, re.M)}


def check(root: Path = ROOT) -> Tuple[List[Tuple[str, List[str]]], List[Tuple[str, str, List[str]]]]:
    """(설치 안 됨: [(이름, 부르는 파일들)], 선언 안 됨: [(이름, 배포판, 부르는 파일들)])."""
    declared = locked_names(root)
    dist_of = md.packages_distributions()
    not_installed: List[Tuple[str, List[str]]] = []
    not_declared: List[Tuple[str, str, List[str]]] = []
    for name, users in third_party_imports(root).items():
        if name in OPTIONAL:
            continue
        if importlib.util.find_spec(name) is None:
            not_installed.append((name, users))
            continue
        dists = {_canon(d) for d in dist_of.get(name, [])}
        if dists and not (dists & declared):
            not_declared.append((name, sorted(dists)[0], users))
    return not_installed, not_declared


def main(argv: Iterable[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    not_installed, not_declared = check()
    imports = third_party_imports()
    n = len([k for k in imports if k not in OPTIONAL])
    optional_missing = [k for k in imports if k in OPTIONAL and importlib.util.find_spec(k) is None]
    if not not_installed and not not_declared:
        print(f"🟢 수집기가 쓰는 바깥 패키지 {n}개가 모두 설치돼 있고 잠금에 선언돼 있다")
    for name, users in not_installed:
        print(f"🔴 설치 안 됨 — {name} ({', '.join(users[:3])}{' …' if len(users) > 3 else ''})")
    for name, dist, users in not_declared:
        print(f"🟡 선언 안 됨 — {name}(배포판 {dist})이 잠금에 없다 ({', '.join(users[:3])}) — 이 PC 에만 손으로 깔린 것이다")
    for name in optional_missing:
        print(f"ℹ️ 선택 도구 없음 — {name}: {OPTIONAL[name]}")
    if not_installed:
        print("   고치는 법: python -m pip install -r requirements.txt -c requirements.lock   (가상환경 .venv 안에서)")
        print("   numpy 처럼 미리 불러온 패키지의 판이 바뀌면 이 파이썬을 다시 시작한다")
    if not_declared:
        print("   고치는 법: requirements.txt 에 그 이름을 더하고 잠금을 다시 만든다(로컬실행안내서 9.2절 · uv pip compile ...)")
    return 1 if not_installed else (2 if not_declared else 0)


if __name__ == "__main__":
    raise SystemExit(main())
