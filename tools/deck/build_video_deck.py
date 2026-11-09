r"""3차 발표 영상 모음 덱 원본 — 통합 덱 도구로 합쳐졌다(2026-11-09).

옛 명령(`python tools/deck/build_video_deck.py [--check]`)이 그대로 돌아가도록 남긴 얇은 껍데기다.
전체-발표자료-원본.html 을 쓰는 도구가 둘이면 서로 덮어쓰므로, 이제 쓰는 곳은 `build_team_deck.py` 하나다 —
표지 → 이동원 → 신장환 → 오준영 → 강민석 순서로 담당 슬라이드 · 시연 영상을 한 덱에 잇는다(영상 5편은 그대로 들어 있다).
영상 장만 있는 옛 덱이 필요하면 담당자 슬라이드 파일(<이름>/발표자료.html)이 없는 상태로 돌려야 하지만, 그럴 일은 없다.

쓰는 법(저장소 뿌리에서 · yaml 이 든 녹화용 파이썬으로):
  C:\workspace\venvs\demo\Scripts\python.exe tools/deck/build_video_deck.py            # = build_team_deck.py
  C:\workspace\venvs\demo\Scripts\python.exe tools/deck/build_video_deck.py --check
"""
from __future__ import annotations

import sys

from build_team_deck import main

if __name__ == "__main__":
  sys.exit(main())
