"""글 속 이름 찾기의 공통 규칙 — 종목 이름(`stock_hub.mentions`)과 용어 이름(`glossary_scan.scan`)이 같이 쓴다 (2026-10-17).

이 파일이 답하는 질문: **"글의 이 자리에 든 이름을 그 이름으로 읽어도 되나, 이름 둘이 겹치면 무엇을 남기나."**

규칙 — 한 곳에만 둔다(두 찾기가 서로 다른 경계를 쓰면 같은 글에서 다르게 읽는다)
  - 영문 · 숫자 이름(SK · PER · KT&G)은 앞뒤가 영문 · 숫자가 아닐 때만 — 「SKT」 · 「performance」 안에서는 읽지 않는다.
  - 한글 두 글자 이하 이름은 앞이 한글 · 영문 · 숫자가 아니고(낱말 시작) 뒤가 끝 · 띄어쓰기 · 문장부호 · 조사 첫 글자일 때만 —
    「태양광」 의 「태양」 · 「부채권」 의 「부채」 는 읽지 않는다.
  - 세 글자 이상 한글 이름은 글자 그대로 — 뒤에 조사가 붙어도(「신한지주는」) 읽는다.
  - 겹치면 긴 이름이 이긴다(「SK하이닉스」 안의 「SK」 · 「삼성전자우」 안의 「삼성전자」 는 따로 읽지 않는다) · 남은 것은 글에 나온 차례.
"""
from __future__ import annotations

import re

LONG_NAME = 3
#: 이름 바로 뒤에 붙어도 되는 글자(조사 · 문장부호의 첫 글자) — 두 글자 이하 한글 이름에만 본다
TAIL_OK = frozenset("은는이가을를의도와과에로만랑께서요 ,.?!·)」』\"'\n\t:;")
_LATIN = re.compile(r"[A-Za-z0-9&]+")
_WORDISH = re.compile(r"[A-Za-z0-9&]")
_HANGUL_OR_WORD = re.compile(r"[가-힣A-Za-z0-9]")


def is_latin(name: str) -> bool:
    return bool(_LATIN.fullmatch(name))


def edges_ok(text: str, start: int, end: int, name: str) -> bool:
    """`text[start:end]` 가 `name` 일 때 그 자리를 이름으로 읽어도 되나 — 위 규칙 셋."""
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    if is_latin(name.replace(" ", "")):
        return not _WORDISH.match(before) and not _WORDISH.match(after)
    if len(name) >= LONG_NAME:
        return True
    return not _HANGUL_OR_WORD.match(before) and after in TAIL_OK


def longest_first(spans: list[tuple]) -> list[tuple]:
    """(시작, 끝, …) 들 → 겹치지 않는 것만 · 긴 것 먼저 고르고 · 글에 나온 차례로."""
    taken: list[tuple] = []
    for s in sorted(spans, key=lambda s: (-(s[1] - s[0]), s[0])):
        if all(s[1] <= t[0] or s[0] >= t[1] for t in taken):
            taken.append(s)
    return sorted(taken, key=lambda s: s[0])
