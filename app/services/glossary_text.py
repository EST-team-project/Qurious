"""용어사전의 글자 규칙 — 찾기용 모양과 초성.

왜 따로 두나
    용어 파일을 만드는 쪽(`scripts/glossary_build.py`)과 검색어를 받는 쪽(`app/services/glossary.py`)이
    **같은 규칙**으로 글자를 다듬어야 한다. 빌드는 「샤프비율」 로 적어 두었는데 앱이 「샤프 비율」 로 찾으면
    있는 용어를 못 찾는다. 그래서 규칙을 이 파일 한 곳에 두고 양쪽이 가져다 쓴다.
    표준 라이브러리만 쓴다 — 빌드 스크립트가 DB 드라이버 없이도 이 파일을 읽을 수 있어야 한다.
"""
from __future__ import annotations

import re
import unicodedata

# 한글 음절의 첫소리 19개 — 유니코드 음절은 (첫소리 × 21 × 28) 차례로 놓여 있어 나눗셈으로 첫소리를 얻는다.
_CHOSUNG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_HANGUL_FIRST, _HANGUL_LAST = 0xAC00, 0xD7A3
_DROP = re.compile(r"[\s·\-_/().,:;'\"‘’“”+&]")
_CHOSUNG_ONLY = re.compile(r"[ㄱ-ㅎ]{2,}")


def norm(text: str) -> str:
    """찾기용 모양 — 같은 용어를 같은 글자로. 소문자 · 공백과 구두점 없음.

    「샤프 비율」 과 「샤프비율」, 「EV/EBITDA」 와 「ev ebitda」 가 같은 값이 된다.
    NFC 로 맞추는 까닭: macOS 에서 온 한글은 자모가 풀린 모양(NFD)일 수 있어, 눈에는 같아도 다른 글자다.
    """
    text = unicodedata.normalize("NFC", text or "").lower()
    return _DROP.sub("", text)


def chosung(text: str) -> str:
    """한글 음절을 첫소리로 바꾼 글자 — 「시가총액」 → 「ㅅㄱㅊㅇ」. 한글이 아닌 글자는 찾기용 모양 그대로 둔다."""
    out = []
    for ch in norm(text):
        code = ord(ch)
        out.append(_CHOSUNG[(code - _HANGUL_FIRST) // 588] if _HANGUL_FIRST <= code <= _HANGUL_LAST else ch)
    return "".join(out)


def is_chosung_query(text: str) -> bool:
    """검색어가 첫소리만으로 되어 있나(두 글자 이상) — 그럴 때만 초성 칸에서 찾는다.

    한 글자(「ㅅ」)는 받지 않는다: 용어 절반이 걸려 찾는 의미가 없다.
    """
    return bool(_CHOSUNG_ONLY.fullmatch(norm(text)))


def escape_like(text: str) -> str:
    """SQL LIKE 의 뜻 있는 글자(% · _ · 역슬래시)를 글자 그대로 찾게 한다 — 검색어 「50%」 가 모든 줄에 걸리지 않게."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
