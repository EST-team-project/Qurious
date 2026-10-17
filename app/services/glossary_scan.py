"""글 속 용어 찾기 — 답 · 신호 이름 · 본문에 든 용어사전 용어를 찾아 용어 칩으로 잇는다 (2026-10-17 · 모의투자 점검 L5).

이 파일이 답하는 질문: **"이 글에 용어사전에 있는 말이 어디에 들었나."**

왜 — 분석 · 상담 · 상품 상세 본문에서 용어 · 개념 학습으로 가는 길이 0 이었다(「사용법」 창 안 용어 칩으로만 · 모의투자 점검
D7 · L5). 글을 받아 용어를 찾아 주면, 화면은 그 자리에 칩(`public/js/termcard.js` 의 `data-term`)을 붙이기만 하면 된다.

원본 — 용어사전 파일 하나(`app/services/glossary_data/terms.json` · `glossary.read_seed`). 표(용어사전 API)가 같은 파일에서
적재되므로 같은 이름 · 같은 ID 다. 파일이 바뀌면(수정 시각) 이름 목록을 다시 만든다.

찾는 법 — 경계 · 겹침 규칙은 `text_match` 한 곳(종목 이름 찾기와 같다)
  - 대표 이름 · 별칭(약어 · 영어 이름 · 다른 이름)을 찾는다. 띄어쓰기는 접어서 견준다(「볼린저 밴드」 = 「볼린저밴드」).
  - 영문 이름은 대문자 약어만(RSI · MACD · PER) — 글 쪽도 대문자일 때만 읽는다(「per」 · 「Buy」 같은 낱말에 걸리지 않게).
  - 한글 두 글자 이하 이름은 흔한 말이 많아(「경제」 · 「분석」 · 「위험」 …) 금융 고유어 몇만 찾는다(`SHORT_KEEP`).
  - 같은 용어는 한 번 · 글에 나온 차례 · 최대 `limit` 개(칩이 글을 덮지 않게).
"""
from __future__ import annotations

import re
from pathlib import Path

from app.services import glossary, text_match

MAX_TEXT = 4000                   # 상담 답 한 번(보통 1,500자 안팎)을 넉넉히
DEFAULT_LIMIT = 6
MAX_LIMIT = 20
#: 한글 두 글자 이하 이름 가운데 자동으로 찾는 금융 고유어(2026-10-17 · 용어사전의 두 글자 이하 이름 139개를 읽고 고름)
SHORT_KEEP = frozenset({"배당", "공시", "손절", "익절", "본절", "양봉", "음봉", "분봉", "월봉", "리츠", "옵션", "선물", "스왑",
                        "델타", "베타", "알파", "도지", "락업", "승률", "금리", "눌림", "갭"})
#: 영문 약어 가운데 너무 흔해 칩이 뜻이 없는 것
LATIN_SKIP = frozenset({"AI"})

_CACHE: dict = {"key": None, "entries": []}
_SPACES = re.compile(r"\s+")


def _squash(s: str) -> str:
    return _SPACES.sub("", s)


def _usable(name: str) -> bool:
    n = _squash(name)
    if len(n) < 2 and n not in SHORT_KEEP:
        return False
    if text_match.is_latin(n):
        return n.isupper() and n not in LATIN_SKIP and len(n) >= 2
    if re.fullmatch(r"[가-힣]{1,2}", n):
        return n in SHORT_KEEP
    return bool(re.search(r"[가-힣A-Z0-9]", n))


def entries(path: Path | None = None) -> list[tuple[str, str, str, str]]:
    """(찾을 이름(띄어쓰기 접음), 용어 ID, 대표 이름, 한 줄 풀이) — 파일 수정 시각이 같으면 지난 목록을 쓴다."""
    p = path or glossary.SEED_PATH
    key = (str(p), p.stat().st_mtime_ns)
    if _CACHE["key"] == key:
        return _CACHE["entries"]
    data, _checksum = glossary.read_seed(p)
    out, seen = [], set()
    for t in data["terms"]:
        names = [t["term"], *[a["alias"] for a in t.get("aliases", [])]]
        for name in names:
            n = _squash(name)
            if not _usable(name) or n in seen:
                continue          # 다른 용어가 먼저 가진 이름은 먼저 가진 쪽(용어사전 별칭 표와 같은 규칙)
            seen.add(n)
            out.append((n, t["id"], t["term"], t.get("summary", "")))
    _CACHE.update(key=key, entries=out)
    return out


def _squashed_with_index(text: str) -> tuple[str, list[int]]:
    chars, idx = [], []
    for i, ch in enumerate(text):
        if not ch.isspace():
            chars.append(ch)
            idx.append(i)
    return "".join(chars), idx


def scan(text: str, *, limit: int = DEFAULT_LIMIT, table: list | None = None) -> list[dict]:
    """글 속 용어 — 나온 차례 · 같은 용어 한 번 · 최대 `limit` 개. `at` · `matched` 는 원래 글의 자리 · 글자."""
    text = (text or "")[:MAX_TEXT]
    limit = max(1, min(int(limit), MAX_LIMIT))
    flat, idx = _squashed_with_index(text)
    spans = []
    for name, tid, term, summary in (entries() if table is None else table):
        at = flat.find(name)
        while at != -1:
            start, end = idx[at], idx[at + len(name) - 1] + 1
            matched = text[start:end]
            latin_ok = not text_match.is_latin(name) or _squash(matched) == name   # 대문자 그대로일 때만
            if latin_ok and text_match.edges_ok(text, start, end, name):
                spans.append((start, end, tid, term, summary, matched))
                break
            at = flat.find(name, at + 1)
    out, seen = [], set()
    for start, _end, tid, term, summary, matched in text_match.longest_first(spans):
        if tid in seen:
            continue
        seen.add(tid)
        out.append({"id": tid, "term": term, "summary": summary, "matched": matched, "at": start})
        if len(out) >= limit:
            break
    return out
