"""근거 문서(법령 · 감독규정) 규칙 한 벌 — 수집기와 앱이 함께 쓴다 (목표 기능 ① W5 · 설계서 5.3).

왜 여기에 두나
--------------
수집기(`collector/kb_law.py` · `kb_index.py` · `kb_eval.py`)는 판을 고르고 조문을 쪼개 색인하고, 앱
(`app/services/kb_search.py`)은 같은 판 · 같은 낱말 규칙으로 찾는다. 규칙이 두 벌이면 한쪽만 고쳐져
「색인한 낱말」 과 「찾는 낱말」 이 어긋난다(2026-10-02 OHLCV 주소에서 두 벌 규칙이 서로를 고친 일).
앱 이미지에는 `collector/` 가 들어가지 않으므로 규칙은 앱 쪽에 두고 수집기가 가져다 쓴다.
그래서 이 파일은 **표준 라이브러리만** 쓴다 — 수집기는 앱 스택 없이 돌아야 한다.

담은 것
-------
1. 판 고르기 — ``select_version`` (기준일에 시행 중인 판)
2. 판 점검 — ``missing_changes`` (고른 판 본문이 그 뒤 공포된 개정을 담았나)
3. 낱말 — ``grams`` · ``fts_query`` (한글 두 글자 묶음 + 조문 번호 통째)
4. 순위 합치기 — ``rrf``
5. 청크 ID — ``chunk_id`` · ``point_id``

판 고르기 — 2026-10-02 실측으로 설계서 규칙을 고쳤다
--------------------------------------------------------
국가법령정보센터 Open API 는 본문을 두 길로 준다.

    target=law    + 법령일련번호        그 개정령이 **공포될 때의 본문**
    target=eflaw  + 일련번호 + 시행일   그 **시행일에 시행 중인 본문**(뒤에 공포된 개정도 반영)

증권거래세법 시행령 제35947호(2025-12-30 공포 · 2026-01-02 시행 · 법령 DB 「현행」)의 제5조는 첫 길로는
옛 세율(유가증권시장 영)이고, 둘째 길로는 하루 뒤 공포된 제36001호의 새 세율(1만분의 5)이다.
설계서 v0.1 이 「현행 표시가 틀린다」 고 본 것은 첫 길로 읽었기 때문이었다.

그래서 **둘째 길(eflaw)만 쓰고, 시행일 ≤ 기준일 인 판 가운데 시행일이 가장 늦은 판**을 고른다.
설계서 v0.1 의 「공포일이 가장 늦은 판」 은 자본시장법 시행령에서 틀린다 — 같은 날(2026-09-29) 공포된
제36728호(10-02 시행)와 제36729호(10-01 시행) 가운데 공포번호가 큰 제36729호를 고르면, 10-02 에 시행된
제377조의2 · 제377조의3 · 제379조의2 · 제380조의 개정이 빠진다. 제36728호의 시행일 판 본문은 제36729호가
바꾼 제387조의2 까지 담고 있었다(세 판 553조를 조마다 대조).

그래도 법령 DB 가 시행일 판을 다시 만들지 않은 경우가 생길 수 있어, 고른 판보다 **뒤에 공포됐고**
기준일까지 시행된 판이 있으면 ``missing_changes`` 로 그 개정이 담겼는지 조마다 확인한다.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


# ==================================================
# 1. 판 고르기
# ==================================================
@dataclass(frozen=True)
class Version:
    """문서 한 판 — 법령은 (공포번호, 시행일) 한 쌍이 한 판이다.

    한 개정령이 조마다 시행일을 달리 두면(예: 제36543호 07-28 · 08-04) 일련번호는 같고 시행일만 다른
    판이 둘 생긴다. 그래서 판 이름(`label`)에 시행일을 넣는다.
    """

    source_id: str          # 법령일련번호(MST) · 행정규칙일련번호
    promulgation_no: str    # 공포번호 · 발령번호
    promulgated_at: str     # YYYY-MM-DD (공포일 · 발령일)
    effective_at: str       # YYYY-MM-DD (시행일)
    status: str = ""        # 받을 때 법령 DB 의 표시: 현행 · 연혁 · 시행예정
    law_type: str = ""      # 법률 · 대통령령 · 총리령 · 고시 · 세칙
    change_kind: str = ""   # 일부개정 · 타법개정 · 전부개정 · 제정

    @property
    def label(self) -> str:
        """사람이 읽는 판 이름 — 예 「대통령령 제36728호 · 2026-10-02 시행」."""
        no = self.promulgation_no.lstrip("0") or self.promulgation_no
        kind = f"{self.law_type} " if self.law_type else ""
        return f"{kind}제{no}호 · {self.effective_at} 시행"


def _num(s: str) -> Tuple[int, ...]:
    """공포번호 · 일련번호를 숫자로 견준다 — 「2026-38」 같은 발령번호는 칸마다 숫자로."""
    parts = re.findall(r"\d+", s or "")
    return tuple(int(p) for p in parts) if parts else (-1,)


def _order(v: Version) -> tuple:
    return (v.effective_at, v.promulgated_at, _num(v.promulgation_no), _num(v.source_id))


def select_version(versions: Iterable[Version], as_of: str) -> Optional[Version]:
    """기준일 ``as_of``(YYYY-MM-DD)에 시행 중인 판.

    시행일 ≤ 기준일 인 판 가운데 **시행일이 가장 늦은 판**. 시행일이 같으면 공포일 → 공포번호 → 일련번호가
    큰 판(뒤에 공포된 판이 앞 개정을 담는다). 기준일에 시행 중인 판이 없으면 None — 아직 시행 전인 문서다.
    """
    cands = [v for v in versions if v.effective_at and v.effective_at <= as_of]
    return max(cands, key=_order) if cands else None


def later_promulgated(versions: Iterable[Version], chosen: Version, as_of: str) -> List[Version]:
    """고른 판보다 **뒤에 공포됐고** 기준일까지 시행된 판 — 고른 판 본문이 그 개정을 놓쳤을 수 있다.

    같은 날 공포면 공포번호가 큰 쪽을 뒤로 본다(제36728호 · 제36729호는 같은 날).
    """
    key = (chosen.promulgated_at, _num(chosen.promulgation_no))
    out = [v for v in versions
           if v.effective_at <= as_of and (v.promulgated_at, _num(v.promulgation_no)) > key
           and v.source_id != chosen.source_id]
    return sorted(out, key=_order)


def predecessor(versions: Iterable[Version], v: Version) -> Optional[Version]:
    """``v`` 바로 앞에 시행된 판 — ``v`` 가 무엇을 바꿨는지 견줄 기준."""
    cands = [x for x in versions if x.effective_at < v.effective_at]
    return max(cands, key=_order) if cands else None


def carries_change(old: str, new: str, cur: str, ctx: int = 4) -> bool:
    """``old → new`` 개정이 넣은 글이 ``cur`` 에 모두 있나 — 넣은 글 앞뒤 ``ctx`` 자까지 함께 찾는다.

    고른 판이 뒤 판의 개정을 담고 **그 위에 더 고친** 경우(같은 조의 항이 하나 늘어 번호가 밀림)를
    「다르게 바꿨다」 로 잘못 알리지 않으려고 둔다. 2026-10-02 소득세법 제129조: 제21223호가 연금소득
    세율을 100분의 4 → 3 으로 바꿨고, 고른 판(제21221호 · 07-01 시행)은 그것을 담은 채 ⑧ 을 새로 넣었다.
    앞뒤 글자가 4자보다 길면 번호가 밀린 자리(⑧ → ⑨)에서 놓친다.
    """
    sm = difflib.SequenceMatcher(None, old or "", new or "", autojunk=False)
    for op, _i1, _i2, j1, j2 in sm.get_opcodes():
        if op in ("insert", "replace"):
            seg = (new or "")[max(0, j1 - ctx): j2 + ctx]
            if seg.strip() and seg not in (cur or ""):
                return False
    return True


def missing_changes(chosen: Dict[str, str], later: Dict[str, str], before_later: Dict[str, str]
                    ) -> Tuple[List[str], List[str]]:
    """조마다 견줘 (빠진 조, 양쪽이 다르게 바꾼 조) 를 돌려준다.

    ``later`` 가 ``before_later`` 에서 바꾼 조 가운데
      · 고른 판이 ``later`` 와 같거나, ``later`` 가 넣은 글을 모두 담았으면 → 담았다
      · 고른 판이 아직 바꾸기 전 글이면 → 빠진 조(고른 판이 그 개정을 담지 않았다)
      · 그 밖(셋이 모두 다르고 넣은 글도 없음) → 양쪽이 다르게 바꾼 조(사람이 봐야 한다)
    """
    missing, conflict = [], []
    for k in sorted(set(later) | set(before_later)):
        new, old = later.get(k), before_later.get(k)
        if new == old:
            continue
        cur = chosen.get(k)
        if cur == new:
            continue
        if cur == old:
            missing.append(k)
        elif cur is not None and new is not None and carries_change(old or "", new, cur):
            continue
        else:
            conflict.append(k)
    return missing, conflict


# ==================================================
# 2. 조문 번호
# ==================================================
#: 「제2조」 「제1-2조의2」 「제 17 조 의 3」 — 띄어 쓴 것도 잡는다. 감독규정은 「편-조」 번호다.
ARTICLE_RE = re.compile(r"제\s*(\d+(?:\s*-\s*\d+)*)\s*조(?:\s*의\s*(\d+))?")


def article_label(num: str, branch: str = "") -> str:
    """「제1-2조의2」 꼴로 맞춘다."""
    num = re.sub(r"\s+", "", num)
    return f"제{num}조" + (f"의{int(branch)}" if branch and str(branch).strip("0") else "")


def article_sort_key(label: str) -> str:
    """정렬 키 — 「제1-2조의2」 → ``0001-0002~0002``. 문자열로 견줘도 번호 순서가 된다."""
    m = ARTICLE_RE.search(label or "")
    if not m:
        return label or ""
    nums = "-".join(f"{int(p):04d}" for p in re.findall(r"\d+", m.group(1)))
    return f"{nums}~{int(m.group(2)) if m.group(2) else 0:04d}"


# ==================================================
# 3. 낱말 — 한글 두 글자 묶음
# ==================================================
# SQLite FTS5 의 기본 낱말 분리(unicode61)는 띄어쓰기로 자른다. 한국어는 「적합성을」 · 「적합성이」 처럼
# 조사가 붙어 「적합성」 으로 찾으면 맞지 않는다. 그래서 한글은 두 글자씩 겹쳐 묶는다
# (적합성을 → 적합 · 합성 · 성을). 검색어도 같은 규칙으로 묶어 「적합성」 → 적합 · 합성 이 맞는다.
# 형태소 분석기를 쓰지 않는 까닭: 앱 이미지 · 수집기 어느 쪽에도 새 의존성을 들이지 않고, 법령 낱말
# (전자적 투자조언장치 · 탄력세율)은 사전에 없는 합성어가 많아 두 글자 묶음이 오히려 덜 놓친다.
# 조문 번호(제17조 · 제1-2조의2)는 쪼개지 않고 통째 한 낱말로 둔다 — 「제17조」 가 「제1조」 · 「7조」 에
# 맞으면 안 된다.
_HANGUL_RUN = re.compile(r"[가-힣]+")
_ASCII_TOKEN = re.compile(r"[a-z0-9]+")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").lower()


def grams(text: str) -> List[str]:
    """색인 · 검색에 쓰는 낱말 목록(순서 · 중복 그대로)."""
    t = _norm(text)
    out: List[str] = []

    def _art(m: re.Match) -> str:
        out.append(article_label(m.group(1), m.group(2) or ""))
        return " "

    t = ARTICLE_RE.sub(_art, t)
    for m in _HANGUL_RUN.finditer(t):
        run = m.group()
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1))
    out.extend(_ASCII_TOKEN.findall(t))
    return out


def grams_text(text: str) -> str:
    """FTS 색인 칸에 넣을 글 — 낱말을 띄어 붙인다."""
    return " ".join(grams(text))


def fts_query(q: str, max_terms: int = 64) -> str:
    """검색어 → FTS5 MATCH 식. 낱말을 OR 로 잇고 순위는 bm25 에 맡긴다. 낱말이 없으면 빈 글."""
    seen: List[str] = []
    for g in grams(q):
        if g not in seen:
            seen.append(g)
    seen = seen[:max_terms]
    return " OR ".join('"' + g.replace('"', '""') + '"' for g in seen)


#: FTS5 낱말 분리 설정 — 「제1-2조의2」 의 「-」 를 낱말 안의 글자로 둔다(수집기 · 앱이 같은 설정).
FTS_TOKENIZE = "unicode61 tokenchars '-'"


# ==================================================
# 4. 순위 합치기 — Reciprocal Rank Fusion
# ==================================================
#: Cormack · Clarke · Büttcher (2009) 의 k=60. 낱말 검색 점수(bm25)와 벡터 유사도는 눈금이 달라
#: 점수를 더할 수 없다 — 순위만 쓴다.
RRF_K = 60


def rrf(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> List[Tuple[str, float]]:
    """여러 순위 목록 → (ID, 점수) 내림차순. 같은 점수면 먼저 나온 목록 · 순위가 앞."""
    score: Dict[str, float] = {}
    first: Dict[str, Tuple[int, int]] = {}
    for li, ranking in enumerate(rankings):
        for r, cid in enumerate(ranking, start=1):
            score[cid] = score.get(cid, 0.0) + 1.0 / (k + r)
            first.setdefault(cid, (r, li))
    return sorted(score.items(), key=lambda kv: (-kv[1], first[kv[0]]))


# ==================================================
# 5. 벡터 색인 설정 — 색인(collector/kb_index.py)과 검색(app/services/kb_search.py)이 같은 값을 쓴다
# ==================================================
#: Qdrant 컬렉션 하나(설계서 5.3.3) — 모델마다 이름 붙은 벡터(named vector)를 둔다. 평가셋으로 두 모델을
#: 견준 뒤 이긴 쪽을 기본으로 쓰되, 진 쪽 벡터도 남겨 다음 평가 때 다시 견줄 수 있게 한다.
KB_COLLECTION = "kb_v1"


@dataclass(frozen=True)
class EmbedModel:
    name: str            # Ollama 모델 이름
    vector: str          # Qdrant 이름 붙은 벡터
    dim: int
    doc_prefix: str = ""     # 문서 앞에 붙이는 말
    query_prefix: str = ""   # 검색어 앞에 붙이는 말


#: nomic-embed-text 는 문서 · 검색어에 앞말(task prefix)을 붙여야 제 성능이 난다(모델 카드 「search_document:」 ·
#: 「search_query:」). bge-m3 은 밀집 검색에 앞말이 필요 없다(BAAI 모델 카드).
EMBED_MODELS: Dict[str, EmbedModel] = {
    "bge-m3": EmbedModel("bge-m3", "bge_m3", 1024),
    "nomic-embed-text": EmbedModel("nomic-embed-text", "nomic", 768, "search_document: ", "search_query: "),
}
#: 평가 전 기본값 — 설계서 5.3.3 의 제안(다국어 · 한국어 법령 문장)
DEFAULT_EMBED_MODEL = "bge-m3"


def version_key(doc_id: str, version_label: str) -> str:
    """벡터 DB 거름(payload)에 쓰는 「문서@판」."""
    return f"{doc_id}@{version_label}"


# ==================================================
# 6. 청크 ID
# ==================================================
def chunk_id(doc_id: str, version_label: str, article: str, seq: int) -> str:
    """sha256(문서 · 판 · 조문 · 순번) 앞 32자 — 실행마다 같다.

    내장 ``hash()`` 는 프로세스마다 값이 달라(PYTHONHASHSEED) 다시 색인할 때 같은 조각이 새 점으로
    쌓였다(옛 분석 A11 · 크롤 색인). 그래서 내용이 아니라 **자리**로 ID 를 만든다 — 같은 판의 같은 조는
    본문이 고쳐져도 같은 ID 이고, 벡터 DB 에서는 덮어쓰기가 된다.
    """
    raw = "\x1f".join((doc_id, version_label, article, str(seq)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def point_id(cid: str) -> str:
    """Qdrant 점 ID — 32자 16진수를 UUID 꼴로(Qdrant 는 정수나 UUID 만 받는다)."""
    return str(uuid.UUID(hex=cid))


def text_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
