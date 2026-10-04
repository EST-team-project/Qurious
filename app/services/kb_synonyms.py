"""질문 말 → 법령 말 — 근거 찾기의 검색어 넓히기와 답 문맥의 괄호 풀이 (목표 기능 ① W5 · 설계서 5.3.3 · DF-59).

왜
--
사람은 「코스피」 · 「로보어드바이저」 · 「5%룰」 로 묻고, 법령은 「유가증권시장」 · 「전자적 투자조언장치」 ·
「대량보유」 로 쓴다. 2026-10-03 검색 평가셋 v0 의 놓침 다섯이 모두 이 경우였다(「누가 내나」 ↔ 납세의무자 ·
로보어드바이저 ↔ 전자적 투자조언장치 · 지분 5% ↔ 대량보유 · 위험 고지 ↔ 설명의무). 답에도 걸린다 — 2026-10-04
실측에서 답 모델(qwen3:4b-instruct)은 「2026년 코스피 상장 주식을 팔 때 증권거래세율은?」 에 시행령 「유가증권시장
… 1만분의 5」 가 바로 옆에 있어도 법 조의 기본 세율 1만분의 35 를 답했다. 질문을 「유가증권시장」 으로 바꾸면 맞게
답했고, 「코스피(유가증권시장)」 처럼 법령 말을 괄호로 덧붙이고 위임 조(``kb_links``)까지 넣어야 맞게 답했다.

무엇을 하나
-----------
1. ``match(q)``    — 표(``kb_data/synonyms.tsv``)의 질문 말이 질문에 있으면(띄어쓰기 무시) 그 줄을 고른다.
                     질문에 법령 말이 이미 있으면 · 「조건」 말이 없으면 · 「제외」 말이 있으면 고르지 않는다.
2. ``expand(q, m)`` — 검색어 = 질문 + 법령 말(낱말 · 벡터 · 질문 분류 모두 넓힌 검색어로).
3. ``annotate(q, m)`` — 답 문맥에 넣는 질문 = 질문 말 뒤에 「(법령 말)」 · 구절 꼴(「누가 내나」)은 끝에 「(법령 말: …)」.

표는 사람이 조문으로 확인한 줄만 둔다 — 줄마다 근거(문서:조) · 확실도 · 메모. 뜻이 다른 말은 넣지 않는다
(예: 「단타」 ≠ 단기매매차익 — 단기매매차익은 내부자의 6개월 안 매매 차익 규정이다).
용어사전(``glossary``)과 따로 두는 까닭(2026-10-04 팀장 결정): 「누가 내 + 세금」 같은 구절 · 조건은 용어가 아니고,
법령 말을 용어사전 다른 이름에 넣으면 화면 밑줄 · 용어 찾기에도 걸린다.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

TABLE = Path(__file__).resolve().parent / "kb_data" / "synonyms.tsv"
PLACES = ("뒤", "끝")
CONFIDENCE = ("높음", "중간")


@dataclass(frozen=True)
class Entry:
    asks: Tuple[str, ...]      # 질문 말(여럿)
    legal: Tuple[str, ...]     # 법령 말(여럿)
    need: Tuple[str, ...]      # 이 가운데 하나가 질문에 있어야 고른다(비면 조건 없음)
    exclude: Tuple[str, ...]   # 이 가운데 하나라도 질문에 있으면 고르지 않는다
    place: str                 # 뒤: 질문 말 바로 뒤 괄호 · 끝: 질문 끝에 「(법령 말: …)」
    source: str                # 근거 「문서:조」
    confidence: str
    note: str


@dataclass(frozen=True)
class Match:
    entry: Entry
    ask: str                   # 질문에서 맞은 질문 말(표 모양)
    start: int                 # 질문 안 위치(원래 글 기준)
    end: int

    def to_dict(self) -> dict:
        return {"from": self.ask, "to": list(self.entry.legal), "source": self.entry.source,
                "confidence": self.entry.confidence}


def _flat(text: str) -> str:
    """찾기용 모양 — NFKC · 소문자 · 띄어쓰기 없음(「로보 어드바이저」 = 「로보어드바이저」)."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "").lower())


def _split(cell: str) -> Tuple[str, ...]:
    return tuple(p.strip() for p in (cell or "").split("|") if p.strip())


_cache: dict = {}


def load(path: Optional[Path] = None) -> List[Entry]:
    """표를 읽는다 — 파일이 바뀌면 다시 읽는다(앱을 다시 켜지 않고 줄을 더할 수 있게)."""
    path = path or TABLE
    try:
        stamp = path.stat().st_mtime_ns
    except FileNotFoundError:
        return []
    hit = _cache.get(str(path))
    if hit and hit[0] == stamp:
        return hit[1]
    entries: List[Entry] = []
    with path.open(encoding="utf-8", newline="") as f:
        for i, row in enumerate(csv.DictReader(f, delimiter="\t"), start=2):
            asks, legal = _split(row.get("질문말", "")), _split(row.get("법령말", ""))
            place = (row.get("자리") or "뒤").strip()
            conf = (row.get("확실도") or "").strip()
            if not asks or not legal or place not in PLACES or conf not in CONFIDENCE:
                raise ValueError(f"{path.name} {i}줄 모양이 틀렸다 — 질문말 · 법령말 · 자리(뒤/끝) · 확실도(높음/중간)")
            entries.append(Entry(asks=asks, legal=legal, need=_split(row.get("조건", "")),
                                 exclude=_split(row.get("제외", "")), place=place,
                                 source=(row.get("근거") or "").strip(), confidence=conf,
                                 note=(row.get("메모") or "").strip()))
    _cache[str(path)] = (stamp, entries)
    return entries


def _pattern(ask: str) -> "re.Pattern[str]":
    """질문 말 → 원래 글에서 찾는 꼴(글자 사이 띄어쓰기 허용 · 대소문자 무시)."""
    chars = [re.escape(ch) for ch in re.sub(r"\s+", "", unicodedata.normalize("NFKC", ask))]
    return re.compile(r"\s*".join(chars), re.I)


def match(q: str, entries: Optional[Sequence[Entry]] = None) -> List[Match]:
    """질문에서 고른 줄 — 질문 안 위치 순. 한 줄은 한 번만(가장 앞 자리) · 법령 말이 같은 줄은 표에서 앞 줄만
    (「5%룰」 과 「지분 5%」 가 둘 다 맞으면 「대량보유」 를 한 번만 덧붙인다)."""
    entries = load() if entries is None else entries
    text = unicodedata.normalize("NFKC", q or "")
    flat = _flat(text)
    out: List[Match] = []
    seen_legal: set = set()
    for e in entries:
        if e.legal in seen_legal:
            continue
        if any(_flat(w) in flat for w in e.legal):      # 이미 법령 말로 물었다
            continue
        if e.need and not any(_flat(w) in flat for w in e.need):
            continue
        if any(_flat(w) in flat for w in e.exclude):
            continue
        best: Optional[Match] = None
        for ask in e.asks:
            m = _pattern(ask).search(text)
            if m and (best is None or m.start() < best.start):
                best = Match(entry=e, ask=ask, start=m.start(), end=m.end())
        if best:
            out.append(best)
            seen_legal.add(e.legal)
    return sorted(out, key=lambda m: m.start)


def expand(q: str, matches: Sequence[Match]) -> str:
    """검색어 넓히기 — 질문 뒤에 법령 말을 붙인다(같은 말은 한 번)."""
    extra: List[str] = []
    for m in matches:
        for w in m.entry.legal:
            if w not in extra:
                extra.append(w)
    return f"{q} {' '.join(extra)}".strip() if extra else q


def annotate(q: str, matches: Sequence[Match]) -> str:
    """답 문맥에 넣는 질문 — 「코스피(유가증권시장) 상장 주식…」 · 「…누가 내나요? (법령 말: 납세의무자)」."""
    text = unicodedata.normalize("NFKC", q or "")
    tail: List[str] = []
    for m in sorted(matches, key=lambda m: -m.start):        # 뒤에서부터 끼워 앞 위치가 흔들리지 않게
        legal = " · ".join(m.entry.legal)
        if m.entry.place == "끝":
            tail.insert(0, legal)
        else:
            text = f"{text[:m.end]}({legal}){text[m.end:]}"
    if tail:
        text = f"{text} (법령 말: {' · '.join(tail)})"
    return text
