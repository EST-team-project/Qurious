"""위임 조 함께 넣기 — 법 조가 하위 법령에 맡긴 값을 그 조와 함께 근거로 (목표 기능 ① W5 · 결함 DF-59 · 설계서 5.3.5).

왜
--
법률은 숫자 · 요건을 「대통령령으로 정하는 바에 따라」 처럼 하위 법령에 맡기고, 실제 값은 시행령 · 시행규칙 ·
감독규정에 둔다. 증권거래세법 제8조 ① 은 기본 세율 1만분의 35 이고, 2026년 코스피 주권의 세율은 제8조 ② 가
대통령령에 맡긴 시행령 제5조의 1만분의 5 다. 답 모델이 법 조만 읽으면 기본값을 답한다(DF-59 · 2026-10-04 근거 답
화면에서 확인 — 시행령 제5조를 함께 찾았는데도 답에 쓰지 않았다). 그래서 맡긴 조와 맡은 조를 짝으로 묶어
근거에 넣고, 둘이 짝이라는 것을 답 모델과 화면에 알린다.

무엇을 잇나
-----------
윗 문서의 조(찾은 근거) → 그 조를 「시행하는」 아래 문서의 조. 아래 문서는 맡은 조를 「법(영 · 규칙 · 규정)
제N조제M항」 으로 부르고, 감독규정 · 시행세칙은 머리 조에서 「법」 · 「영」 · 「규칙」 · 「규정」 이 무엇인지 정의한다
(금융투자업규정 제1-1조 · 같은 시행세칙 제1-1조 원문). 그래서 문서 짝을 표(``CHILDREN``)로 두고 글로 잇는다.

    맡기는 말(윗 조)                 받는 문서
    대통령령으로 정하는 …            시행령
    총리령으로 정하는 …              시행규칙
    금융위원회가 정하여 고시하는 …   감독규정(금융투자업규정 · 금융소비자 감독규정)
    금융감독원장이 정하는 …          시행세칙

시행령이 근거 문서에 없는 법(소득세법 · 상법 · 농어촌특별세법)은 잇지 않는다 — 없는 조를 지어 보이지 않는다.

어떻게 고르나
-------------
아래 문서에서 그 조를 부르는 청크를 모은 뒤 점수를 매긴다. ``MIN_SCORE`` 를 넘는 것만 「시행하는 조」 로 본다.
- 맡긴 말을 따옴표로 받는다 — 「영 제2조제6호다목에서 "금융위원회가 정하여 고시하는 요건"이란」  +3
- 문단 첫머리(주어 한 마디까지)에서 부른다 — 「법 제8조제2항을 적용받는 주권과 그 세율은」  +2
- 부른 항이 윗 조에서 그 단계의 맡기는 말이 든 항이다 +2 · 다른 항이다 −2
본문 중간에서 지나가며 쓰는 「법 제8조에 따른 세율을 적용하여」 는 점수가 모자라 빠진다 — 그 조를 시행하는 조가
아니라 쓰는 조라서다. 「같은 법 제N조」 · 「소득세법 제N조」 처럼 다른 법을 부르는 꼴은 아예 잇지 않는다.

넘은 것 가운데서는 **이번 질문의 검색 후보 순위 → 점수 → 조 번호** 순으로 고른다. 점수는 「시행하는 조인가」
이지 「질문에 맞는가」 가 아니어서다 — 자본시장법 제119조(증권신고)는 ① 을 시행하는 시행령 제120조(신고 대상 ·
금액)와 ③ 을 시행하는 제123조(예측정보)가 둘 다 맡은 조인데, 「신고해야 하는 금액」 을 물으면 검색 후보 2위인
제120조가 맞다(2026-10-04 실측). 그리고 질문과 동떨어진 글로 답 문맥을 채우지 않도록
- 한 조가 여러 청크로 나뉘었으면 그 조는 한 번만(검색 후보 순위가 높은 청크),
- **이번 질문의 검색 후보(합친 순위 ``IN_SEARCH_TOP`` 안)에 든 조만** 잇는다. 2026-10-04 근거답 평가셋 v1 에서
  질문과 무관했던 위임 조는 모두 후보 밖(51위 · 26위 · 22위 · 후보에 없음)이었고 쓸모 있던 것은 모두 20위 안
  (1 · 1 · 2 · 3 · 6위)이었다. 처음에는 「순위 3 안 근거의 첫째 위임 조는 후보 밖이어도」 잇게 했는데, 「주가를
  띄우려고 짜고 사고팔면」 질문에서 관련 없는 인가요건 조(51위)가 끼어 답이 시세조종 조 대신 다른 조를 들었다(A09).
2026-10-04 실측: 시행령 · 시행규칙 · 감독규정 · 시행세칙 청크 가운데 윗 문서를 문단 첫머리에서 부르는 것은
시행령 35 ~ 58% · 감독규정 15 ~ 46% 다. 감독규정은 「금융투자업자가 규정 제2-26조…에서」 처럼 주어가 앞에 와서
첫머리만 보면 놓쳐, 걸러 내지 않고 점수로 고른다.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from app.services import kb_text

#: 근거 하나에 잇는 위임 조 수 · 한 번 찾기에 잇는 전체 수 — 답 모델 문맥(설계서 5.3.4 · 4,500자)을 넘치지 않게
MAX_PER_HIT = 2
MAX_TOTAL = 4
#: 이 점수 이상이어야 「시행하는 조」 로 본다 — 따옴표로 받기(3) 하나, 또는 첫머리(2) · 항 맞음(2) 둘 다
MIN_SCORE = 3
#: 「이번 검색 후보에 든 조」 로 치는 합친 순위 상한 — 위임 조는 이 안에 든 것만 잇는다. 후보 전부(낱말 40 + 벡터
#: 40)는 너무 넓다(2026-10-04 「전문투자자는 누구인가요?」 에 불건전 영업행위 조가 둘째로 붙었다)
IN_SEARCH_TOP = 20
#: 문서 거름(docs)으로 검색에서 빠진 아래 문서는 후보 순위가 없다 — 그때만 순위 이 안의 근거에 첫째 위임 조를 잇는다
#: (「자본시장법만」 으로 찾아도 맡긴 값은 시행령에 있다)
LINK_TOP = 3

#: 맡기는 말 — 단계마다. 「정하는」 · 「정한」 · 「정할」 을 다 잡도록 어간까지만 쓴다.
LEVEL_PHRASES: Dict[str, "re.Pattern[str]"] = {
    "decree": re.compile(r"대통령령(?:으로|이)\s?정"),
    "rule": re.compile(r"총리령(?:으로|이)\s?정"),
    "notice": re.compile(r"금융위원회가\s?(?:정하여\s?)?고시"),
    "fss": re.compile(r"(?:금융)?감독원장이\s?정"),
}
LEVEL_NAMES = {"decree": "대통령령", "rule": "총리령", "notice": "금융위원회 고시", "fss": "금융감독원장"}

#: 받는 문서 → (맡는 단계, {그 문서가 윗 문서를 부르는 말: 윗 문서 ID})
CHILDREN: Dict[str, Tuple[str, Dict[str, str]]] = {
    "stt_decree": ("decree", {"법": "stt_act"}),
    "capmkt_decree": ("decree", {"법": "capmkt_act"}),
    "fcpa_decree": ("decree", {"법": "fcpa_act"}),
    "capmkt_rule": ("rule", {"법": "capmkt_act", "영": "capmkt_decree"}),
    "fis_reg": ("notice", {"법": "capmkt_act", "영": "capmkt_decree", "규칙": "capmkt_rule"}),
    "fcp_reg": ("notice", {"법": "fcpa_act", "영": "fcpa_decree"}),
    "fis_reg_rule": ("fss", {"법": "capmkt_act", "영": "capmkt_decree", "규칙": "capmkt_rule", "규정": "fis_reg"}),
    "fcp_reg_rule": ("fss", {"법": "fcpa_act", "영": "fcpa_decree", "규정": "fcp_reg"}),
}


def _parents() -> Dict[str, List[Tuple[str, str, str]]]:
    """윗 문서 → [(받는 문서, 부르는 말, 단계)]."""
    out: Dict[str, List[Tuple[str, str, str]]] = {}
    for child, (level, refs) in CHILDREN.items():
        for word, parent in refs.items():
            out.setdefault(parent, []).append((child, word, level))
    return out


PARENTS = _parents()

_PARA_MARK = re.compile(r"[①-⑳]")
#: 청크 첫 줄의 제목 사슬(「증권거래세법 > 제8조(세율)」) — 본문이 아니다
_HEAD_SEP = " > "
#: 따옴표로 맡긴 말을 받는 꼴 — 「…제6호다목에서 "…"이란」 · 「…제3호에 따른 "…"이란」
_QUOTE_AFTER = re.compile(r"^(?:\s?제\d+호)?(?:[가-하]목)?(?:\d+\))?\s?(?:에서|에\s?따른)\s?[\"“]")
#: 문단 첫머리로 볼 거리 — 항 표시 · 줄바꿈 · 본문 처음에서 이 글자 수 안(주어 한 마디: 「금융투자업자가 」)
_HEAD_REACH = 16


@dataclass(frozen=True)
class Ref:
    """아래 조가 윗 조를 부른 자리."""
    word: str                 # 법 · 영 · 규칙 · 규정
    article: str              # 제8조 · 제1-2조의2
    para: Optional[int]       # 제2항 → 2 (없으면 None)
    text: str                 # 「법 제8조제2항」 — 화면 · 문맥에 그대로
    score: int


def body_of(text: str) -> str:
    """청크 글에서 첫 줄의 제목 사슬을 뺀 본문(``kb_answer.citation_excerpt`` 와 같은 규칙)."""
    body = (text or "").strip()
    first, sep, rest = body.partition("\n")
    return rest if sep and _HEAD_SEP in first else body


def _para_no(mark: str) -> int:
    return ord(mark) - ord("①") + 1


def delegating_paragraphs(text: str) -> Dict[str, Set[Optional[int]]]:
    """윗 조 글 → {단계: 그 단계의 맡기는 말이 든 항 번호}. 항 표시(①)가 없는 조 · 첫 표시 앞 글은 None."""
    body = body_of(text)
    marks = [(m.start(), _para_no(m.group())) for m in _PARA_MARK.finditer(body)]
    segments: List[Tuple[Optional[int], str]] = []
    if not marks:
        segments.append((None, body))
    else:
        if marks[0][0] > 0:
            segments.append((None, body[:marks[0][0]]))
        for i, (pos, no) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(body)
            segments.append((no, body[pos:end]))
    out: Dict[str, Set[Optional[int]]] = {}
    for no, seg in segments:
        for level, pat in LEVEL_PHRASES.items():
            if pat.search(seg):
                out.setdefault(level, set()).add(no)
    return out


def _article_parts(label: str) -> Optional[Tuple[str, Optional[str]]]:
    m = kb_text.ARTICLE_RE.search(label or "")
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(1)), m.group(2)


def ref_pattern(word: str, article: str) -> "re.Pattern[str]":
    """아래 조에서 윗 조를 부르는 꼴 — 「법 제8조」 · 「법 제8조제2항」 · 「영 제2조제6호다목」.

    「법 제8조의2」 · 「법 제80조」 는 다른 조라 맞지 않는다. 「같은 법 제8조」(다른 법을 부른 뒤의 「같은 법」) ·
    「소득세법 제8조」 · 「「증권거래세법」 제8조」 처럼 앞에 글자가 붙은 꼴도 맞지 않는다.
    """
    parts = _article_parts(article)
    if parts is None:
        raise ValueError(f"조 번호 모양이 아니다: {article!r}")
    num, branch = parts
    art = rf"제\s?{re.escape(num)}\s?조" + (rf"의\s?{int(branch)}" if branch else r"(?!\s?의\s?\d)")
    return re.compile(rf"(?<!같은 )(?<![가-힣」\w]){re.escape(word)}\s?{art}(?:\s?제\s?(\d+)\s?항)?")


def _at_paragraph_head(body: str, pos: int) -> bool:
    """pos 가 문단 첫머리(본문 처음 · 줄바꿈 · 항 표시 · 문장 끝 뒤)에서 주어 한 마디 안인가."""
    start = max(0, pos - _HEAD_REACH)
    before = body[start:pos]
    cut = max(before.rfind("\n"), max((before.rfind(ch) for ch in "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"), default=-1),
              before.rfind(". "))
    if cut >= 0:
        gap = before[cut + 1:].strip()
    elif start == 0:
        gap = before.strip()
    else:
        return False
    # 사이에 한 마디(띄어쓰기 없는 말 하나 + 조사)까지만
    return gap == "" or (" " not in gap and len(gap) <= 12)


def find_refs(child_text: str, word: str, article: str, paras: Set[Optional[int]]) -> List[Ref]:
    """아래 조 글에서 윗 조(``word`` ``article``)를 부른 자리마다 점수를 매긴다(높은 순)."""
    body = body_of(child_text)
    pat = ref_pattern(word, article)
    out: List[Ref] = []
    for m in pat.finditer(body):
        para = int(m.group(1)) if m.group(1) else None
        score = 0
        if _QUOTE_AFTER.match(body[m.end():m.end() + 40]):
            score += 3
        if _at_paragraph_head(body, m.start()):
            score += 2
        if para is not None and paras:
            if para in paras:
                score += 2
            elif None not in paras:
                score -= 2
        out.append(Ref(word=word, article=article, para=para, text=re.sub(r"\s+", " ", m.group(0)).strip(),
                       score=score))
    return sorted(out, key=lambda r: -r.score)


@dataclass
class Link:
    """찾은 근거(윗 조) 하나에 이은 아래 조 하나."""
    parent_chunk: str
    child: sqlite3.Row
    ref: Ref
    level: str


_NOT_FOUND = 10 ** 6


def find_links(conn: sqlite3.Connection, hits: Sequence[dict], versions: Mapping[str, str],
               order: Optional[Mapping[str, int]] = None, *, per_hit: int = MAX_PER_HIT,
               total: int = MAX_TOTAL, min_score: int = MIN_SCORE, in_search_top: int = IN_SEARCH_TOP,
               searched: Optional[Iterable[str]] = None, top: int = LINK_TOP) -> Dict[str, List[Link]]:
    """찾은 근거마다 이을 아래 조 — {윗 청크 ID: [Link]}.

    ``versions`` = {문서 ID: 기준일에 고른 판 이름} — 아래 조도 같은 기준일의 판에서만 고른다(판 고르기 = 시점 고정).
    ``order`` = {청크 ID: 이번 검색 후보 순위(1부터)} — 질문에 맞는 조를 앞에 둔다(머리말 「어떻게 고르나」).
    ``searched`` = 이번 검색이 본 문서 ID(비우면 전부) — 거름으로 빠진 아래 문서는 후보 순위가 없어 ``top`` 규칙을 쓴다.
    """
    searched_docs = set(searched) if searched is not None else None
    order = order or {}
    out: Dict[str, List[Link]] = {}
    n_total = 0
    for h in hits:
        if n_total >= total:
            break
        kids = PARENTS.get(h["doc_id"])
        parts = _article_parts(h.get("article", ""))
        if not kids or parts is None:
            continue
        paras_by_level = delegating_paragraphs(h.get("text", ""))
        if not paras_by_level:
            continue
        best: Dict[Tuple[str, str], Tuple[int, int, str, Link]] = {}   # 조마다 가장 앞 청크 하나
        for child_doc, word, level in kids:
            paras = paras_by_level.get(level)
            if paras is None or child_doc not in versions:
                continue
            rows = conn.execute("SELECT * FROM kb_chunk WHERE doc_id = ? AND version_label = ? AND text LIKE ?"
                                " ORDER BY article_key, seq", (child_doc, versions[child_doc], f"%제{parts[0]}조%"))
            for r in rows:
                refs = find_refs(r["text"], word, h["article"], paras)
                if not refs or refs[0].score < min_score:
                    continue
                key = (order.get(r["chunk_id"], _NOT_FOUND), -refs[0].score, r["article_key"],
                       Link(parent_chunk=h["chunk_id"], child=r, ref=refs[0], level=level))
                art = (r["doc_id"], r["article"])
                if art not in best or key[:3] < best[art][:3]:
                    best[art] = key
        picked: List[Link] = []
        for rank, _score, _art, link in sorted(best.values(), key=lambda c: c[:3]):
            if len(picked) >= per_hit or n_total >= total:
                break
            filtered_out = searched_docs is not None and link.child["doc_id"] not in searched_docs
            if filtered_out:
                # 거름으로 검색에서 빠진 문서 — 순위 상한 안 근거의 첫째 위임 조만
                if picked or (h.get("rank") or _NOT_FOUND) > top:
                    continue
            elif rank > in_search_top:        # 이번 검색 후보 밖 — 질문과 동떨어진 조(머리말 「어떻게 고르나」)
                continue
            picked.append(link)
            n_total += 1
        if picked:
            out[h["chunk_id"]] = picked
    return out


def via(parent: dict, link: Link) -> dict:
    """아래 조에 붙이는 「어디서 맡겼나」 — API 응답 · 답 문맥 · 화면이 같은 글을 쓴다."""
    return {
        "chunk_id": parent["chunk_id"], "doc_id": parent["doc_id"], "title": parent["title"],
        "article": parent["article"], "article_title": parent.get("article_title", ""),
        "ref": link.ref.text, "para": link.ref.para, "level": link.level, "level_name": LEVEL_NAMES[link.level],
        "score": link.ref.score,
    }


def expand(hits: Sequence[dict], limit: Optional[int] = None) -> List[dict]:
    """근거 목록 → 위임 조를 윗 조 바로 뒤에 끼운 목록(겹치면 한 번만).

    위임 조가 이미 목록 뒤쪽에 있으면 윗 조 바로 뒤로 당겨 온다 — 답 모델이 「이 조가 맡긴 값은 바로 다음 근거」 로
    읽게 하려는 것이다. 아래 조가 윗 조보다 먼저 나왔으면 그 자리에 둔다(뒤로 미루지 않는다).
    끼운 항목에는 ``via``(윗 조) 가 붙는다. ``limit`` 을 넘으면 뒤에서 자른다.
    """
    out: List[dict] = []
    seen: Set[str] = set()
    for h in hits:
        if h["chunk_id"] not in seen:
            out.append(h)
            seen.add(h["chunk_id"])
        for d in h.get("delegated") or []:
            if d["chunk_id"] not in seen:
                out.append(d)
                seen.add(d["chunk_id"])
    return out[:limit] if limit else out


def pairs(evidence: Sequence[dict]) -> List[Tuple[int, int, dict]]:
    """근거 목록 안의 (윗 조 번호, 위임 조 번호, via) — 번호는 1부터. 둘 다 목록에 있을 때만."""
    pos = {e["chunk_id"]: i for i, e in enumerate(evidence, start=1) if e.get("chunk_id")}
    out: List[Tuple[int, int, dict]] = []
    for i, e in enumerate(evidence, start=1):
        v = e.get("via")
        if v and v["chunk_id"] in pos:
            out.append((pos[v["chunk_id"]], i, v))
    return out


def chain_label(v: dict) -> str:
    """「증권거래세법 제8조제2항에서 대통령령에 맡긴 조」 — 문맥 · 화면에 쓰는 한 줄.

    조사는 「에서」 로 둔다 — 조 번호 끝 글자(조 · 의3 · 항)에 따라 「이 / 가」 가 바뀌는 것을 피한다.
    """
    para = f"제{v['para']}항" if v.get("para") else ""
    return f"{v['title']} {v['article']}{para}에서 {v['level_name']}에 맡긴 조"


def doc_versions(rows: Iterable[sqlite3.Row]) -> Dict[str, str]:
    """고른 판 행들 → {문서 ID: 판 이름}."""
    return {r["doc_id"]: r["version_label"] for r in rows}
