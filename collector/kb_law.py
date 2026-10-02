"""근거 문서 — 법령 · 감독규정을 받아 기준일 판을 고르고 조문 청크로 쪼갠다 (목표 기능 ① W5 · 설계서 5.3).

    python -m collector.kb_law fetch [--as-of 2026-10-02] [--only stt_decree,fis_reg]   받기 → 판 고르기 → 쪼개기 → 저장
    python -m collector.kb_law status                                                   문서 · 판 · 청크 · 벡터 수
    python -m collector.kb_law show stt_decree 제5조                                     청크 보기

무엇을 받나 (설계서 5.3.1 표 10 의 등급 1 · 2)
------------------------------------------------
법령 10 — 자본시장법 · 시행령 · 시행규칙 / 금융소비자보호법 · 시행령 / 증권거래세법 · 시행령 · 농어촌특별세법 /
소득세법 · 상법(이 둘은 관련 조문만 — ``SCOPES``). 감독규정 4 — 금융투자업규정 · 시행세칙 / 금융소비자 보호에
관한 감독규정 · 시행세칙. 협회 · 거래소 규정(등급 3)은 받는 경로가 없어 아직 넣지 않는다(설계서 13절 위험 표).

어디서 받나 — 국가법령정보센터 Open API(DRF)
--------------------------------------------
법령은 ``target=eflaw``(시행일 판), 감독규정은 ``target=admrul``(행정규칙). 키는 ``.env`` 의 ``LAW_API_OC``.
호출은 1.1초에 한 번 — 공식 한도가 게시되지 않아 초당 1건 이하로 둔다(설계서 5.3.2).
⚠️ 목록 응답의 상세 링크 칸에 **요청한 OC 값이 그대로 실려 온다**(2026-10-02 실측). 응답을 저장하기 전에
   ``OC=…`` 를 지우고(``redact``), 오류 메시지에는 주소를 넣지 않는다.

판 고르기 — ``app/services/kb_text.py`` 머리말
-----------------------------------------------
기준일에 시행 중인 판 = 시행일 ≤ 기준일 가운데 시행일이 가장 늦은 판(eflaw 시행일 판 본문). 고른 판보다
뒤에 공포된 판이 기준일까지 시행됐으면, 고른 판 본문이 그 개정을 담았는지 조마다 대조한다(``check_later``).
빠진 조가 있으면 그 조만 뒤 판의 글로 바꾸고 문서 행 ``note`` 에 남긴다 — 조용히 넘어가지 않는다.

어떻게 쪼개나 (설계서 5.3.2)
-----------------------------
조 하나가 청크 하나다. 1,200자를 넘는 조는 항(①②…) 단위로, 항도 넘으면 호(1. 2.) 단위로 나누고, 모든 청크
머리에 「문서 이름 제○조(제목)」 를 되풀이한다 — 항만 떼어 읽어도 어느 법 몇 조인지 알 수 있어야 답에 출처를
달 수 있다. 삭제된 조(「제8조 삭제 <2016.7.28>」)는 청크를 만들지 않는다.

감독규정은 조문이 구조 없이 **한 줄 문자열**로 온다(금융투자업규정 35만 자 · 줄바꿈 0). 「제1-2조의2(제목)」
머리를 정규식으로 찾되, 본문 속 인용(「영 제2조제6호」)과 헷갈리지 않게 **바로 앞 조의 다음 번호답게 이어지는
머리만** 받는다(``plausible_next``).

어디에 두나 — ``data/collector/kb.sqlite3`` (수집 DB 와 다른 파일)
------------------------------------------------------------------
설계서 6절은 「새 표는 수집 DB 에」 라고 했지만 근거 문서는 따로 둔다. 낱말 색인(FTS5)이 보조 표 다섯 개를
함께 만들어 HF 백업의 「모든 표는 백업하거나 이유와 함께 제외」 규칙(TC-HF-01)을 흐리고, 법령은 언제든 다시
받는 공개 자료이며(저작권법 제7조 — 법령 · 고시는 보호받지 않는다), 매일 12:30 러너와 잠금을 나누지 않는다.
앱은 이 파일을 읽기 전용으로 연다(``app/services/kb_search.py``).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from collector import config
from collector.console import utf8_stdio

# 수집기와 앱이 같은 규칙을 쓰게 — 표준 라이브러리만 쓰는 파일이라 앱 스택 없이도 가져온다.
sys.path.insert(0, str(config.ROOT))
from app.services import kb_text  # noqa: E402
from app.services.kb_text import Version  # noqa: E402

KST = zoneinfo.ZoneInfo("Asia/Seoul")

KB_DB_PATH = config.DATA_DIR / "kb.sqlite3"
LAW_BASE = "https://www.law.go.kr/DRF/"
LAW_SLEEP = 1.1
USER_AGENT = "Qurious-collector/0.1 (study project; contact via GitHub EST-team-project/Qurious)"

#: 이보다 긴 조는 항 · 호 단위로 나눈다. 임베딩 시간(이 PC 의 CPU 로 bge-m3 348자 청크 초당 약 2개)과
#: 찾기 단위(답에 「제○조 제○항」 까지 달 수 있게)를 함께 본 값이다.
MAX_CHARS = 1200


# ==================================================
# 0. 받을 문서
# ==================================================
@dataclass(frozen=True)
class DocSpec:
    doc_id: str
    title: str          # 목록에서 이 이름과 (띄어쓰기를 빼고) 똑같은 행만 쓴다
    kind: str           # law | admrul
    grade: int          # 1 법령 · 2 감독규정 (설계서 표 10)


DOCS: Tuple[DocSpec, ...] = (
    DocSpec("capmkt_act", "자본시장과 금융투자업에 관한 법률", "law", 1),
    DocSpec("capmkt_decree", "자본시장과 금융투자업에 관한 법률 시행령", "law", 1),
    DocSpec("capmkt_rule", "자본시장과 금융투자업에 관한 법률 시행규칙", "law", 1),
    DocSpec("fcpa_act", "금융소비자 보호에 관한 법률", "law", 1),
    DocSpec("fcpa_decree", "금융소비자 보호에 관한 법률 시행령", "law", 1),
    DocSpec("stt_act", "증권거래세법", "law", 1),
    DocSpec("stt_decree", "증권거래세법 시행령", "law", 1),
    DocSpec("rural_tax_act", "농어촌특별세법", "law", 1),
    DocSpec("income_tax_act", "소득세법", "law", 1),
    DocSpec("commercial_act", "상법", "law", 1),
    DocSpec("fis_reg", "금융투자업규정", "admrul", 2),
    DocSpec("fis_reg_rule", "금융투자업규정시행세칙", "admrul", 2),
    DocSpec("fcp_reg", "금융소비자 보호에 관한 감독규정", "admrul", 2),
    DocSpec("fcp_reg_rule", "금융소비자 보호에 관한 감독규정 시행세칙", "admrul", 2),
)
DOC_BY_ID = {d.doc_id: d for d in DOCS}

#: 관련 조문만 받는 문서 — (첫 조, 끝 조) 범위들. 설계서 표 10 「범위는 관련 장만」.
#: 비어 있으면 전부. 범위는 ``kb_text.article_sort_key`` 로 견준다(「제462조의3」 은 제462조 와 제463조 사이).
SCOPES: Dict[str, Tuple[Tuple[str, str], ...]] = {}


# ==================================================
# 1. 저장소
# ==================================================
SCHEMA = f"""
-- 받은 것: 응답 원문(OC 를 지운 뒤 gzip). 다시 쪼갤 수 있는 유일한 근거.
CREATE TABLE IF NOT EXISTS kb_raw (
    source      TEXT    NOT NULL,          -- law.go.kr
    target      TEXT    NOT NULL,          -- eflaw/search/<이름> · eflaw/<일련번호>/<시행일> · admrul/<일련번호>
    fetched_at  TEXT    NOT NULL,          -- KST ISO8601
    body        BLOB    NOT NULL,          -- gzip(OC 를 지운 원문)
    sha256      TEXT    NOT NULL,          -- OC 를 지운 원문의 지문
    bytes       INTEGER NOT NULL,
    PRIMARY KEY (source, target, fetched_at)
);

-- 문서 한 판 = 한 행. 새 판은 덮어쓰지 않고 새 행이다(설계서 5.2.3).
CREATE TABLE IF NOT EXISTS kb_document (
    doc_id          TEXT    NOT NULL,
    version_label   TEXT    NOT NULL,      -- 「대통령령 제36728호 · 2026-10-02 시행」
    kind            TEXT    NOT NULL,      -- law | admrul
    grade           INTEGER NOT NULL,      -- 1 법령 · 2 감독규정
    title           TEXT    NOT NULL,
    law_type        TEXT    NOT NULL DEFAULT '',   -- 법률 · 대통령령 · 총리령 · 고시 · 세칙
    issuer          TEXT    NOT NULL DEFAULT '',   -- 소관 부처
    promulgation_no TEXT    NOT NULL DEFAULT '',
    promulgated_at  TEXT    NOT NULL,      -- YYYY-MM-DD
    effective_at    TEXT    NOT NULL,      -- YYYY-MM-DD
    status          TEXT    NOT NULL DEFAULT '',   -- 받을 때 법령 DB 표시: 현행 · 연혁 · 시행예정
    source_id       TEXT    NOT NULL,      -- 법령일련번호(MST) · 행정규칙일련번호
    source_url      TEXT    NOT NULL,      -- 사람이 여는 주소(키 없음)
    scope           TEXT    NOT NULL DEFAULT '',   -- 빈칸 = 전부 · 아니면 받은 조 범위
    articles        INTEGER NOT NULL,      -- 청크를 만든 조 수(삭제 조 · 범위 밖 제외)
    chunks          INTEGER NOT NULL,
    content_sha256  TEXT    NOT NULL,      -- 조문 글 전체의 지문 — 같은 판 본문이 다시 만들어졌는지 본다
    selected_for    TEXT    NOT NULL DEFAULT '',   -- 이 판을 고른 기준일
    note            TEXT    NOT NULL DEFAULT '',   -- 판 점검 결과 등
    fetched_at      TEXT    NOT NULL,
    PRIMARY KEY (doc_id, version_label)
);

-- 조문 청크. rid 는 낱말 색인(kb_chunk_fts)의 rowid 와 같다.
CREATE TABLE IF NOT EXISTS kb_chunk (
    rid             INTEGER PRIMARY KEY,
    chunk_id        TEXT    NOT NULL UNIQUE,   -- sha256(문서 · 판 · 조 · 순번) 앞 32자
    doc_id          TEXT    NOT NULL,
    version_label   TEXT    NOT NULL,
    article         TEXT    NOT NULL,      -- 제2조 · 제1-2조의2
    article_key     TEXT    NOT NULL,      -- 정렬 키
    article_title   TEXT    NOT NULL DEFAULT '',
    part            TEXT    NOT NULL DEFAULT '',   -- 편 · 장 · 절
    seq             INTEGER NOT NULL,      -- 조 안의 순번(나누지 않았으면 0)
    paras           TEXT    NOT NULL DEFAULT '',   -- 이 청크에 든 항(①② …)
    text            TEXT    NOT NULL,      -- 머리 「문서 이름 제○조(제목)」 + 본문
    text_sha256     TEXT    NOT NULL,
    chars           INTEGER NOT NULL,
    effective_at    TEXT    NOT NULL,
    grade           INTEGER NOT NULL,
    kind            TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_kb_chunk_doc ON kb_chunk(doc_id, version_label, article_key, seq);

-- 낱말 색인 — 한글 두 글자 묶음(kb_text.grams). rowid = kb_chunk.rid
CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunk_fts USING fts5(grams, tokenize="{kb_text.FTS_TOKENIZE}");

-- 어느 청크를 어느 모델로 벡터 DB 에 넣었나 — 본문 지문이 바뀌면 다시 넣는다(kb_index).
CREATE TABLE IF NOT EXISTS kb_vector (
    chunk_id    TEXT    NOT NULL,
    model       TEXT    NOT NULL,          -- bge-m3 · nomic-embed-text
    text_sha256 TEXT    NOT NULL,
    dim         INTEGER NOT NULL,
    indexed_at  TEXT    NOT NULL,
    PRIMARY KEY (chunk_id, model)
);
"""


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(path or KB_DB_PATH, timeout=60, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _iso(yyyymmdd: str) -> str:
    s = re.sub(r"\D", "", yyyymmdd or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else ""


def _same_name(a: str, b: str) -> bool:
    return re.sub(r"\s+", "", a or "") == re.sub(r"\s+", "", b or "")


def _as_list(x) -> list:
    if x is None or x == "":
        return []
    return x if isinstance(x, list) else [x]


# ==================================================
# 2. 받기
# ==================================================
class LawApiError(RuntimeError):
    """법령 API 를 받지 못했다. 메시지에 주소 · 키를 담지 않는다."""


_OC_RE = re.compile(rb"OC=[^&\"'\s<>]*")


def redact(body: bytes) -> bytes:
    """응답 속 ``OC=…`` 를 지운다 — 목록 응답의 상세 링크가 요청한 키를 그대로 싣는다."""
    return _OC_RE.sub(b"OC=***", body)


class LawClient:
    """국가법령정보센터 DRF 호출 — 1.1초 간격 · 원문 저장 · 키 지우기."""

    def __init__(self, oc: Optional[str] = None, *, conn: Optional[sqlite3.Connection] = None,
                 opener: Callable = urllib.request.urlopen, sleep: float = LAW_SLEEP,
                 timeout: int = 60) -> None:
        self.oc = oc if oc is not None else config.require("LAW_API_OC", "국가법령정보센터 Open API 키(OC)")
        self.conn, self.opener, self.sleep, self.timeout = conn, opener, sleep, timeout
        self.calls = 0
        self._last = 0.0

    def get(self, path: str, params: Dict[str, str], target: str) -> dict:
        wait = self.sleep - (time.monotonic() - self._last)
        if self._last and wait > 0:
            time.sleep(wait)
        q = dict(params)
        q["OC"] = self.oc
        url = LAW_BASE + path + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with self.opener(req, timeout=self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            raise LawApiError(f"법령 API HTTP {e.code} — {target}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LawApiError(f"법령 API 에 닿지 못했다({type(e).__name__}) — {target}") from None
        finally:
            self._last = time.monotonic()
            self.calls += 1
        body = redact(body)
        if self.conn is not None:
            self.conn.execute(
                "INSERT OR REPLACE INTO kb_raw(source, target, fetched_at, body, sha256, bytes) VALUES (?,?,?,?,?,?)",
                ("law.go.kr", target, now_kst(), gzip.compress(body), hashlib.sha256(body).hexdigest(), len(body)))
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            # 키가 틀리면 JSON 대신 안내 HTML 이 온다
            raise LawApiError(f"법령 API 가 JSON 이 아닌 응답을 줬다 — {target} · OC 키 · 이용 신청 상태를 확인") from None


def law_versions(client: LawClient, title: str) -> List[Version]:
    """법령 시행일 판 목록(연혁 · 현행 · 시행예정). 이름이 똑같은 행만."""
    data = client.get("lawSearch.do", {"target": "eflaw", "type": "JSON", "query": title, "display": "100",
                                       "nw": "1,2,3", "sort": "efdes"}, f"eflaw/search/{title}")
    rows = _as_list(data.get("LawSearch", {}).get("law"))
    out = []
    for r in rows:
        if not _same_name(r.get("법령명한글", ""), title):
            continue
        out.append(Version(source_id=str(r.get("법령일련번호", "")), promulgation_no=str(r.get("공포번호", "")),
                           promulgated_at=_iso(r.get("공포일자", "")), effective_at=_iso(r.get("시행일자", "")),
                           status=r.get("현행연혁코드", ""), law_type=r.get("법령구분명", ""),
                           change_kind=r.get("제개정구분명", "")))
    return out


def admrul_versions(client: LawClient, title: str, history: bool = False) -> List[Version]:
    """행정규칙 판 목록 — 기본은 현행, ``history`` 면 연혁까지."""
    params = {"target": "admrul", "type": "JSON", "query": title, "display": "100"}
    if history:
        params["nw"] = "2"
    data = client.get("lawSearch.do", params, f"admrul/search/{title}" + ("/history" if history else ""))
    rows = _as_list(data.get("AdmRulSearch", {}).get("admrul"))
    out = []
    for r in rows:
        if not _same_name(r.get("행정규칙명", ""), title):
            continue
        out.append(Version(source_id=str(r.get("행정규칙일련번호", "")), promulgation_no=str(r.get("발령번호", "")),
                           promulgated_at=_iso(r.get("발령일자", "")), effective_at=_iso(r.get("시행일자", "")),
                           status=r.get("현행연혁구분", ""), law_type=r.get("행정규칙종류", ""),
                           change_kind=r.get("제개정구분명", "")))
    return out


def source_url(spec: DocSpec, v: Version) -> str:
    """사람이 여는 주소 — 키가 들어가지 않는 국가법령정보센터 화면."""
    if spec.kind == "law":
        return f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={v.source_id}&efYd={v.effective_at.replace('-', '')}"
    return f"https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq={v.source_id}"


# ==================================================
# 3. 조문 펼치기
# ==================================================
@dataclass
class Article:
    label: str                 # 제2조 · 제1-2조의2
    title: str = ""            # 조문 제목
    part: str = ""             # 제1편 총칙 > 제2장 …
    head: str = ""             # 머리 줄(항이 없으면 본문 전체)
    paras: List[Tuple[str, str]] = field(default_factory=list)   # (항 번호, 그 항의 글 — 호 · 목 포함)
    deleted: bool = False

    @property
    def body(self) -> str:
        parts = [self.head] if self.head else []
        parts += [t for _, t in self.paras]
        return "\n".join(p for p in parts if p)


def _join(v) -> str:
    """칸 값이 글 · 글 목록 · 목록의 목록으로 섞여 온다 — 줄로 이어 붙인다."""
    if v is None:
        return ""
    if isinstance(v, list):
        return "\n".join(s for s in (_join(x) for x in v) if s)
    return str(v).strip()


_PART_RE = re.compile(r"제\s*\d+\s*(편|장|절|관)")
_PART_LEVEL = {"편": 0, "장": 1, "절": 2, "관": 3}


def _set_part(stack: Dict[int, str], heading: str) -> None:
    m = _PART_RE.search(heading)
    if not m:
        return
    lvl = _PART_LEVEL[m.group(1)]
    for k in [k for k in stack if k >= lvl]:
        del stack[k]
    stack[lvl] = re.sub(r"\s+", " ", heading).strip()


def _part_text(stack: Dict[int, str]) -> str:
    return " > ".join(stack[k] for k in sorted(stack))


_DELETED_RE = re.compile(r"^제\s*\d[\d\-]*\s*조(?:의\s*\d+)?\s*(?:\([^)]*\))?\s*삭제")


def parse_law_body(data: dict) -> Tuple[dict, List[Article]]:
    """eflaw 본문 JSON → (기본 정보, 조 목록). 「전문」 행(편 · 장 · 절)은 다음 조들의 자리로 쓴다."""
    law = data.get("법령") or {}
    info = law.get("기본정보") or {}
    stack: Dict[int, str] = {}
    out: List[Article] = []
    for u in _as_list((law.get("조문") or {}).get("조문단위")):
        if u.get("조문여부") == "전문":
            _set_part(stack, _join(u.get("조문내용")))
            continue
        if u.get("조문여부") != "조문":
            continue
        label = kb_text.article_label(str(u.get("조문번호", "")), str(u.get("조문가지번호") or ""))
        head = _join(u.get("조문내용"))
        paras: List[Tuple[str, str]] = []
        for h in _as_list(u.get("항")):
            lines = [_join(h.get("항내용"))]
            for ho in _as_list(h.get("호")):
                lines.append(_join(ho.get("호내용")))
                for mo in _as_list(ho.get("목")):
                    lines.append(_join(mo.get("목내용")))
            text = "\n".join(s for s in lines if s)
            if text:
                paras.append((_join(h.get("항번호")), text))
        title = _join(u.get("조문제목"))
        # 항이 있으면 머리 줄은 「제80조(제목)」 뿐인 경우가 많다 — 그때는 머리로 다시 붙이지 않는다
        if paras and re.fullmatch(r"제\s*\d[\d\-]*\s*조(?:의\s*\d+)?\s*(?:\([^)]*\))?", head):
            head = ""
        out.append(Article(label=label, title=title, part=_part_text(stack), head=head, paras=paras,
                           deleted=bool(_DELETED_RE.match(_join(u.get("조문내용")))) and not paras))
    return info, out


# 감독규정 — 한 줄 문자열에서 조 머리 찾기
_ADM_HEAD_RE = re.compile(
    r"제(\d+(?:-\d+)*)조(?:의(\d+))?"
    r"(?:\s*\(((?:[^()]|\([^()]*\)){1,80})\)"            # 제목이 있는 조
    r"|(?=\s*삭제)"                                         # 삭제된 조
    r"|(?=제\d+(?:-\d+)*조|제\d+(?:편|장|절|관)))"           # 번호만 남은 조(「제2-17조제2-18조…」)
)
#: 진짜 조 머리 바로 앞에 올 수 없는 글자 — 인용은 「영 제2조」 · 「(제3조」 처럼 띄어 쓰거나 괄호 안에 온다.
_REF_BEFORE = set(" \t\r\n　「(“\"'[")
#: 조 글 끝에 붙어 오는 다음 편 · 장 · 절 머리(「…한다.제2장 인가제2-1조(…)」 의 「제2장 인가」)
_ADM_TAIL_PART_RE = re.compile(r"((?:제\d+(?:-\d+)?(?:편|장|절|관)\s*(?:(?!제\d)[^<>.。」])*)+)\s*$")
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _adm_key(m: re.Match) -> Tuple[int, ...]:
    return tuple(int(x) for x in m.group(1).split("-")) + (int(m.group(2) or 0),)


def plausible_next(prev: Optional[Tuple[int, ...]], key: Tuple[int, ...]) -> bool:
    """감독규정 조 번호가 앞 조의 「다음 번호답게」 이어지나 — 본문 속 인용을 머리로 잘못 잡지 않게.

    첫 칸(편)은 1 까지, 그 아래는 3 까지 건너뛸 수 있다(삭제 · 이동으로 빈 번호). 가지 번호(의N)는 바로
    본 조 뒤에만 온다. 앞 조보다 작거나 같으면 인용이다.
    """
    if prev is None:
        return all(x <= 2 for x in key)
    if len(prev) != len(key) or key <= prev:
        return False
    last = len(key) - 1                      # 마지막 칸 = 가지 번호(의N · 없으면 0)
    for i, (a, b) in enumerate(zip(prev, key)):
        if a == b:
            continue
        if i == last:                        # 같은 조의 가지만 늘었다(제1-2조 → 제1-2조의2)
            return b - a <= 3
        limit = 1 if (i == 0 and len(key) > 2) else 3
        return b - a <= limit and all(x <= 2 for x in key[i + 1:last]) and key[last] <= 3
    return False


def _split_paras(body: str) -> List[Tuple[str, str]]:
    """「① … ② …」 를 차례대로 찾아 항으로 나눈다(②는 ① 뒤에서만 찾는다 — 순서가 어긋난 인용을 거른다)."""
    cuts = []
    pos = 0
    for c in _CIRCLED:
        i = body.find(c, pos)
        if i < 0:
            break
        cuts.append((c, i))
        pos = i + 1
    if len(cuts) < 2:
        return []
    out = []
    for n, (c, i) in enumerate(cuts):
        end = cuts[n + 1][1] if n + 1 < len(cuts) else len(body)
        out.append((c, body[i:end].strip()))
    return out


def parse_admrul_body(data: dict) -> Tuple[dict, List[Article]]:
    """행정규칙 본문 JSON → (기본 정보, 조 목록)."""
    svc = data.get("AdmRulService") or {}
    info = svc.get("행정규칙기본정보") or {}
    text = _join(svc.get("조문내용"))
    heads: List[re.Match] = []
    prev = None
    for m in _ADM_HEAD_RE.finditer(text):
        key = _adm_key(m)
        if prev is not None and (len(key) != len(prev) or key <= prev):
            continue
        # 조문이 한 줄로 이어 붙어 오므로 진짜 머리는 앞 조 끝(「한다.」 · 「<개정 …>」 · 장 제목)에 바로 붙는다.
        glued = m.start() == 0 or text[m.start() - 1] not in _REF_BEFORE
        jump_ok = prev is None or key[0] - prev[0] <= 1
        titled = m.group(3) is not None
        if (glued and jump_ok) or (titled and plausible_next(prev, key)):
            heads.append(m)
            prev = key
    stack: Dict[int, str] = {}
    lead = text[:heads[0].start()] if heads else text
    for pm in _PART_RE.finditer(lead):
        _set_part(stack, lead[pm.start():])
    out: List[Article] = []
    for n, m in enumerate(heads):
        end = heads[n + 1].start() if n + 1 < len(heads) else len(text)
        seg = text[m.end():end]
        tail_part = ""
        t = _ADM_TAIL_PART_RE.search(seg)
        if t and n + 1 < len(heads):
            tail_part = t.group(1)
            seg = seg[:t.start()]
        label = kb_text.article_label(m.group(1), m.group(2) or "")
        title = (m.group(3) or "").strip()
        body = seg.strip()
        deleted = (m.group(3) is None) or bool(re.match(r"^삭제\s*(<[^>]*>)?\s*$", body))
        paras = _split_paras(body)
        head = body[:body.find(paras[0][1])].strip() if paras else body
        out.append(Article(label=label, title=title, part=_part_text(stack), head=head, paras=paras,
                           deleted=deleted))
        if tail_part:
            # 「제2편 …제1장 …」 처럼 여럿이 붙어 올 수 있다 — 차례대로 쌓는다
            for pm in _PART_RE.finditer(tail_part):
                nxt = _PART_RE.search(tail_part, pm.end())
                _set_part(stack, tail_part[pm.start(): nxt.start() if nxt else len(tail_part)])
    return info, out


def article_texts(articles: Iterable[Article]) -> Dict[str, str]:
    """조 → 글 (판 점검에 쓴다). 공백을 접어 줄바꿈 차이를 무시한다."""
    return {a.label: re.sub(r"\s+", " ", a.body).strip() for a in articles}


# ==================================================
# 4. 쪼개기
# ==================================================
@dataclass
class Chunk:
    article: Article
    seq: int
    paras: str
    text: str


def _in_scope(label: str, scope: Sequence[Tuple[str, str]]) -> bool:
    if not scope:
        return True
    k = kb_text.article_sort_key(label)
    return any(kb_text.article_sort_key(a) <= k <= kb_text.article_sort_key(b) for a, b in scope)


def _hard_split(text: str, limit: int) -> List[str]:
    """한 줄이 너무 길면 문장(「다.」) 단위로, 그래도 길면 글자 수로 자른다."""
    sents = re.split(r"(?<=다\.)\s*", text)
    out, cur = [], ""
    for s in sents:
        while len(s) > limit:
            out.append(s[:limit])
            s = s[limit:]
        if cur and len(cur) + len(s) + 1 > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip() if cur else s
    if cur:
        out.append(cur)
    return out


def chunk_article(doc_title: str, art: Article, max_chars: int = MAX_CHARS) -> List[Chunk]:
    """조 하나 → 청크(머리 「문서 이름 제○조(제목)」 를 되풀이)."""
    header = f"{doc_title} {art.label}" + (f"({art.title})" if art.title else "")
    if art.deleted or not art.body.strip():
        return []
    budget = max(200, max_chars - len(header) - 1)
    body = art.body
    if len(body) <= budget:
        return [Chunk(art, 0, "", f"{header}\n{body}")]
    # 항 단위로 묶는다 — 항이 없으면 줄(호) 단위
    units: List[Tuple[str, str]] = []
    if art.head:
        units.append(("", art.head))
    if art.paras:
        for no, t in art.paras:
            if len(t) <= budget:
                units.append((no, t))
            else:
                for line in t.split("\n"):
                    for piece in (_hard_split(line, budget) if len(line) > budget else [line]):
                        units.append((no, piece))
    else:
        units = [("", piece) for line in body.split("\n")
                 for piece in (_hard_split(line, budget) if len(line) > budget else [line])]
    chunks: List[Chunk] = []
    cur: List[Tuple[str, str]] = []

    def _flush():
        if not cur:
            return
        nos = []
        for no, _ in cur:
            if no and no not in nos:
                nos.append(no)
        chunks.append(Chunk(art, len(chunks), "".join(nos), header + "\n" + "\n".join(t for _, t in cur)))

    size = 0
    for no, t in units:
        if cur and size + len(t) + 1 > budget:
            _flush()
            cur, size = [], 0
        cur.append((no, t))
        size += len(t) + 1
    _flush()
    return chunks


# ==================================================
# 5. 저장
# ==================================================
def store_version(conn: sqlite3.Connection, spec: DocSpec, v: Version, info_title: str, issuer: str,
                  chunks: List[Chunk], articles_used: int, content_sha: str, as_of: str, note: str,
                  scope_text: str) -> Tuple[int, bool]:
    """한 판의 청크를 통째로 바꿔 넣는다 → (청크 수, 본문이 바뀌었나)."""
    label = v.label
    conn.execute("BEGIN IMMEDIATE")
    try:
        old = conn.execute("SELECT content_sha256 FROM kb_document WHERE doc_id=? AND version_label=?",
                           (spec.doc_id, label)).fetchone()
        changed = old is None or old["content_sha256"] != content_sha
        rids = [r[0] for r in conn.execute("SELECT rid FROM kb_chunk WHERE doc_id=? AND version_label=?",
                                           (spec.doc_id, label))]
        conn.executemany("DELETE FROM kb_chunk_fts WHERE rowid=?", [(r,) for r in rids])
        conn.execute("DELETE FROM kb_chunk WHERE doc_id=? AND version_label=?", (spec.doc_id, label))
        for c in chunks:
            cid = kb_text.chunk_id(spec.doc_id, label, c.article.label, c.seq)
            cur = conn.execute(
                "INSERT INTO kb_chunk(chunk_id, doc_id, version_label, article, article_key, article_title, part, seq,"
                " paras, text, text_sha256, chars, effective_at, grade, kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, spec.doc_id, label, c.article.label, kb_text.article_sort_key(c.article.label),
                 c.article.title, c.article.part, c.seq, c.paras, c.text, kb_text.text_sha256(c.text), len(c.text),
                 v.effective_at, spec.grade, spec.kind))
            conn.execute("INSERT INTO kb_chunk_fts(rowid, grams) VALUES (?, ?)",
                         (cur.lastrowid, kb_text.grams_text(c.text)))
        conn.execute(
            "INSERT OR REPLACE INTO kb_document(doc_id, version_label, kind, grade, title, law_type, issuer,"
            " promulgation_no, promulgated_at, effective_at, status, source_id, source_url, scope, articles, chunks,"
            " content_sha256, selected_for, note, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (spec.doc_id, label, spec.kind, spec.grade, info_title or spec.title, v.law_type, issuer,
             v.promulgation_no, v.promulgated_at, v.effective_at, v.status, v.source_id, source_url(spec, v),
             scope_text, articles_used, len(chunks), content_sha, as_of, note, now_kst()))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(chunks), changed


# ==================================================
# 6. 한 문서 받기 — 목록 → 판 고르기 → 본문 → 판 점검 → 쪼개기 → 저장
# ==================================================
def fetch_body(client: LawClient, spec: DocSpec, v: Version) -> Tuple[dict, List[Article]]:
    if spec.kind == "law":
        data = client.get("lawService.do", {"target": "eflaw", "type": "JSON", "MST": v.source_id,
                                            "efYd": v.effective_at.replace("-", "")},
                          f"eflaw/{v.source_id}/{v.effective_at}")
        return parse_law_body(data)
    data = client.get("lawService.do", {"target": "admrul", "type": "JSON", "ID": v.source_id},
                      f"admrul/{v.source_id}")
    return parse_admrul_body(data)


def check_later(client: LawClient, spec: DocSpec, versions: List[Version], chosen: Version,
                articles: List[Article], as_of: str) -> Tuple[List[Article], List[str]]:
    """고른 판보다 뒤에 공포된 판이 있으면 그 개정이 담겼는지 조마다 대조한다 → (고친 조 목록, 기록 줄)."""
    notes: List[str] = []
    later = kb_text.later_promulgated(versions, chosen, as_of)
    if not later:
        return articles, notes
    by_label = {a.label: a for a in articles}
    cur_texts = article_texts(articles)
    for lv in later:
        pv = kb_text.predecessor(versions, lv)
        if pv is None:
            notes.append(f"판 점검: {lv.label} 앞 판을 찾지 못해 대조하지 못했다")
            continue
        _, la = fetch_body(client, spec, lv)
        _, pa = fetch_body(client, spec, pv)
        missing, conflict = kb_text.missing_changes(cur_texts, article_texts(la), article_texts(pa))
        la_by = {a.label: a for a in la}
        for k in missing:
            if k in la_by:
                by_label[k] = la_by[k]
        if missing:
            notes.append(f"판 점검: {lv.label} 개정이 빠진 조 {len(missing)}개({', '.join(missing[:6])}) → 그 판 글로 바꿈")
        if conflict:
            notes.append(f"판 점검: {lv.label} 과 고른 판이 다르게 바꾼 조 {len(conflict)}개({', '.join(conflict[:6])}) — 고른 판 글 유지 · 사람 확인")
        if not missing and not conflict:
            notes.append(f"판 점검: {lv.label} 개정은 고른 판에 담겨 있다")
    order = [a.label for a in articles] + [k for k in by_label if k not in {a.label for a in articles}]
    fixed = sorted((by_label[k] for k in order), key=lambda a: kb_text.article_sort_key(a.label))
    return fixed, notes


def fetch_doc(client: LawClient, conn: sqlite3.Connection, spec: DocSpec, as_of: str) -> Dict[str, object]:
    if spec.kind == "law":
        versions = law_versions(client, spec.title)
    else:
        versions = admrul_versions(client, spec.title)
        if kb_text.select_version(versions, as_of) is None:
            versions += admrul_versions(client, spec.title, history=True)
    if not versions:
        raise LawApiError(f"{spec.title} — 목록에서 이름이 같은 문서를 찾지 못했다(이름이 바뀌었는지 확인)")
    chosen = kb_text.select_version(versions, as_of)
    if chosen is None:
        raise LawApiError(f"{spec.title} — {as_of} 에 시행 중인 판이 없다(가장 이른 시행일 "
                          f"{min(v.effective_at for v in versions)})")
    info, articles = fetch_body(client, spec, chosen)
    articles, notes = check_later(client, spec, versions, chosen, articles, as_of)
    scope = SCOPES.get(spec.doc_id, ())
    used = [a for a in articles if not a.deleted and _in_scope(a.label, scope)]
    chunks = [c for a in used for c in chunk_article(spec.title, a)]
    content_sha = kb_text.text_sha256("\n\n".join(f"{a.label}\n{a.body}" for a in used))
    if spec.kind == "law":
        issuer = _join((info.get("소관부처") or {}).get("content") if isinstance(info.get("소관부처"), dict)
                       else info.get("소관부처"))
        title = _join(info.get("법령명_한글")) or spec.title
    else:
        issuer = _join(info.get("소관부처명"))
        title = _join(info.get("행정규칙명")) or spec.title
    scope_text = " · ".join(f"{a}~{b}" for a, b in scope)
    n, changed = store_version(conn, spec, chosen, title, issuer, chunks, len(used), content_sha, as_of,
                               " / ".join(notes), scope_text)
    return {"doc_id": spec.doc_id, "label": chosen.label, "status": chosen.status, "articles": len(used),
            "all_articles": sum(1 for a in articles if not a.deleted), "chunks": n, "changed": changed,
            "notes": notes, "versions": len(versions),
            "long": sum(1 for c in chunks if c.seq > 0)}


# ==================================================
# 7. 명령
# ==================================================
def cmd_fetch(args) -> int:
    as_of = args.as_of or datetime.now(KST).strftime("%Y-%m-%d")
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    specs = [d for d in DOCS if not only or d.doc_id in only]
    unknown = sorted(set(only or []) - set(DOC_BY_ID))
    if unknown:
        print(f"모르는 문서: {', '.join(unknown)} — 있는 것: {', '.join(DOC_BY_ID)}")
        return 2
    conn = connect()
    client = LawClient(conn=conn)
    t0 = time.time()
    fails = 0
    print(f"― 근거 문서 받기 · 기준일 {as_of} · 문서 {len(specs)} ―")
    for spec in specs:
        try:
            r = fetch_doc(client, conn, spec, as_of)
        except LawApiError as e:
            fails += 1
            print(f"  🔴 {spec.doc_id:<15} {e}")
            continue
        mark = "새로" if r["changed"] else "같음"
        print(f"  ✅ {spec.doc_id:<15} {r['label']:<34} {r['status'] or '-':<4} 조 {r['articles']:>4}"
              f"/{r['all_articles']:<4} 청크 {r['chunks']:>5} (나눈 조의 뒤 조각 {r['long']}) · {mark}")
        for note in r["notes"]:
            print(f"     {note}")
    tot = conn.execute("SELECT COUNT(*) FROM kb_chunk").fetchone()[0]
    print(f"  호출 {client.calls}회 · {time.time() - t0:,.0f}초 · 청크 전체 {tot:,}")
    return 1 if fails else 0


def cmd_status(_args) -> int:
    if not KB_DB_PATH.exists():
        print(f"근거 문서 DB 가 없다: {KB_DB_PATH}\n  할 일: python -m collector.kb_law fetch")
        return 1
    conn = connect()
    print(f"― 근거 문서 · {KB_DB_PATH.name} ―")
    for r in conn.execute("SELECT * FROM kb_document ORDER BY grade, doc_id, effective_at"):
        print(f"  {r['doc_id']:<15} {r['version_label']:<34} 조 {r['articles']:>4} 청크 {r['chunks']:>5}"
              f" · 고른 기준일 {r['selected_for']} · {r['fetched_at'][:16]}" + (f"\n     {r['note']}" if r["note"] else ""))
    n = conn.execute("SELECT COUNT(*) FROM kb_chunk").fetchone()[0]
    f = conn.execute("SELECT COUNT(*) FROM kb_chunk_fts").fetchone()[0]
    print(f"  청크 {n:,} · 낱말 색인 {f:,}")
    for r in conn.execute("SELECT model, COUNT(*) n, MAX(indexed_at) t FROM kb_vector GROUP BY model"):
        print(f"  벡터 {r['model']:<17} {r['n']:,} · 마지막 {r['t'][:16]}")
    return 0


def cmd_show(args) -> int:
    conn = connect()
    label = kb_text.article_label(*kb_text.ARTICLE_RE.search(args.article).groups(default=""))
    rows = conn.execute("SELECT * FROM kb_chunk WHERE doc_id=? AND article=? ORDER BY version_label, seq",
                        (args.doc_id, label)).fetchall()
    if not rows:
        print(f"없다: {args.doc_id} {label}")
        return 1
    for r in rows:
        print(f"── {r['version_label']} · {r['article']} · 조각 {r['seq']} {r['paras']} · {r['chars']}자 · {r['chunk_id']}")
        print(r["text"])
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.kb_law",
                                description="근거 문서 — 법령 · 감독규정 받기 · 판 고르기 · 조문 청크")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="받기 → 판 고르기 → 쪼개기 → 저장")
    f.add_argument("--as-of", help="기준일 YYYY-MM-DD (기본 오늘 KST)")
    f.add_argument("--only", help="문서 ID 몇 개만 (쉼표)")
    sub.add_parser("status", help="문서 · 판 · 청크 · 벡터 수")
    s = sub.add_parser("show", help="청크 보기")
    s.add_argument("doc_id")
    s.add_argument("article", help="예: 제5조 · 제1-2조의2")
    a = p.parse_args(argv)
    return {"fetch": cmd_fetch, "status": cmd_status, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
