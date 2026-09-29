"""표준출력·표준오류를 UTF-8 로 — 사용자 셸에서 명령이 글자 하나로 죽지 않게 (DF-11).

git bash(mintty)에서 파이썬은 표준출력을 콘솔이 아니라 파이프로 보고 cp949 로 인코딩한다. 그러면
``✅`` · ``⚠️`` 같은 그림 글자뿐 아니라 **줄표 ``—``(U+2014)** 도 못 써서 ``UnicodeEncodeError`` 로 죽는다.
2026-09-29 S60 에 ``python -m collector.benchmark status`` 가 ``—`` 에서 종료코드 1 로 끝났고, S62 에 다시
재 보니 수집기 명령 6개 중 넷은 ``--help`` 부터 죽었다(도움말 문구에도 ``—`` 가 있다).

일일 러너는 자식 단계에 ``PYTHONIOENCODING=utf-8`` 을 넣어 이 길을 피한다. 피하지 못한 것은 **사람이
Git Bash 에서 직접 돌리는** 수집기 명령이다(S59 「DB 다시 만들기」 같은).

각 명령의 ``main`` 첫 줄에서 부른다 — argparse 가 도움말을 찍기 **전에** 맞춰야 한다. 작업 스케줄러의
``pythonw`` 는 표준출력이 None 이라 ``hasattr`` 에서 걸러진다. ``scripts/`` 는 경로로 실행되고 일부는
저장소 모듈을 가져오지 않아서 같은 세 줄을 그대로 쓴다(``scripts/daily_update.py`` 의 ``utf8_stdio`` 와 같다).
"""

from __future__ import annotations

import sys


def utf8_stdio() -> None:
    """표준출력·표준오류를 UTF-8 로 맞춘다. 여러 번 불러도 같다."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
