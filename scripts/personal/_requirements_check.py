"""requirements.txt 에 적힌 패키지 가운데 이 파이썬에 설치되지 않은 것을 찾는다.

dev.ps1(개발 모드)이 앱을 띄우기 전에 부른다. 직접 돌려도 된다::

    python scripts/personal/_requirements_check.py            # 빠진 것이 없으면 종료 코드 0
    python scripts/personal/_requirements_check.py requirements-dev.txt

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


def main(argv: list[str]) -> int:
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
