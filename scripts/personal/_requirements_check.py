"""requirements.txt 에 적힌 패키지 가운데 이 파이썬에 설치되지 않은 것을 찾는다.

dev.ps1(개발 모드)이 앱을 띄우기 전에 부른다. 직접 돌려도 된다::

    python scripts/personal/_requirements_check.py            # 빠진 것이 없으면 종료 코드 0
    python scripts/personal/_requirements_check.py requirements-dev.txt
    python scripts/personal/_requirements_check.py --lock     # 이 파이썬 판이 잠금(requirements.lock)과 다른 것(2026-10-23)

--lock(test.ps1 첫머리가 부른다 · 결정 D6) — 잠금은 앱 이미지의 판이다. 이 파이썬에 깔린 것 가운데 판이 다른 것을
「LOCKDIFF <수>」 다음 줄마다 「이름 이 파이썬판 잠금판」 으로 낸다(늘 종료 코드 0 · 알리기만). 이 파이썬에 없는 것
(qdrant-client 등)과 이 플랫폼 표지가 아닌 줄(sys_platform == 'emscripten' 등)은 세지 않는다.

왜 import 가 아니라 설치 목록(importlib.metadata)으로 보나 —
  패키지 이름과 import 이름이 다른 것이 많다(python-jose → jose, beautifulsoup4 → bs4,
  Pillow → PIL, python-pptx → pptx …). 설치 목록은 requirements.txt 에 적힌 **배포 이름**
  그대로 찾을 수 있어 대응표가 필요 없다.
한계 —
  「설치돼 있다」 만 보고 버전 조건(>=)은 보지 않는다. 버전이 낮아 생기는 문제는 앱을 띄울 때
  오류로 드러난다. 같은 패키지의 설치 흔적(dist-info)이 두 벌 남은 환경에서는 설치 목록이
  실제 import 되는 판과 다를 수 있다.
"""
from __future__ import annotations

import importlib.metadata as metadata
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # <저장소>/scripts/personal/ 에서 두 단계 위


def requirement_names(path: Path) -> list[str]:
    """requirements 파일에서 배포 이름만 뽑는다. `-r 다른파일` 은 따라가서 합친다."""
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()          # 줄 끝 주석을 뗀다
        if not line:
            continue
        if line.startswith("-r "):                    # requirements-dev.txt 의 `-r requirements.txt`
            names += requirement_names(path.parent / line[3:].strip())
            continue
        if line.startswith("-"):                      # 그 밖의 pip 옵션 줄은 건너뛴다
            continue
        # `uvicorn[standard]>=0.32.0` → `uvicorn` : 추가 기능([ ])과 버전 조건 앞에서 자른다
        names.append(re.split(r"[\[<>=!~ ;]", line, maxsplit=1)[0])
    return names


def lock_diffs(lock: Path) -> list[tuple[str, str, str]]:
    """잠금 줄(`이름==판 ; 표지`) 가운데 이 파이썬에 깔렸는데 판이 다른 것 — [(이름, 이 파이썬판, 잠금판)]."""
    try:
        from packaging.markers import Marker
    except ImportError:            # packaging 이 없으면 표지를 보지 않고 모두 센다
        Marker = None
    out = []
    for raw in lock.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        spec, _, marker = line.partition(";")
        name, _, ver = spec.strip().partition("==")
        if marker.strip() and Marker is not None and not Marker(marker.strip()).evaluate():
            continue
        try:
            here = metadata.version(name.split("[", 1)[0])
        except metadata.PackageNotFoundError:
            continue
        if here != ver.strip():
            out.append((name, here, ver.strip()))
    return out


def main(argv: list[str]) -> int:
    if argv[:1] == ["--lock"]:
        diffs = lock_diffs(ROOT / "requirements.lock") if (ROOT / "requirements.lock").is_file() else []
        direct = {n.lower().replace("_", "-") for n in requirement_names(ROOT / "requirements.txt")}
        diffs.sort(key=lambda d: (d[0].lower().replace("_", "-") not in direct, d[0].lower()))   # 직접 의존이 먼저
        print(f"LOCKDIFF {len(diffs)}")       # 영문 · 숫자만 — PowerShell 5.1 이 콘솔 인코딩과 무관하게 읽게
        for name, here, ver in diffs:
            print(f"{name} {here} {ver}")
        return 0
    target = ROOT / (argv[0] if argv else "requirements.txt")
    missing = []
    for name in requirement_names(target):
        try:
            metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        # PowerShell 이 이 줄을 읽어 사람에게 보여 준다 — 영문 · 숫자만 써서 콘솔 인코딩과 무관하게
        print("MISSING " + " ".join(missing))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
