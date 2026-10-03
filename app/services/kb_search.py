"""근거 문서 찾기 — 낱말 색인(FTS5) + 벡터(Qdrant) → 순위 합치기(RRF) · 질문 분류 가중 (목표 기능 ① W5 · 설계서 5.3.3).

- ``documents(kind)``  : 받아 둔 문서 판 목록 — API-KB-01 ``GET /api/kb/documents``
- ``search(q, …)``     : 근거 청크 상위 k — API-KB-02 ``GET /api/kb/search``

어디서 읽나
-----------
수집기(``collector/kb_law.py``)가 만든 ``data/collector/kb.sqlite3`` 를 **읽기 전용**으로 연다. 도커 앱은
compose 가 호스트 ``./data`` 를 ``/app/data/csv`` 에 읽기 전용으로 붙여 두어 ``data/csv/collector/kb.sqlite3``
로 보인다(수집 DB 와 같은 길 · ``collector_db``). 벡터는 Qdrant ``kb_v1``(``collector/kb_index.py`` 가 넣음).
낱말 · 판 · 청크 ID 규칙은 ``kb_text`` 한 벌을 수집기와 함께 쓴다.

어떻게 찾나
-----------
1. **기준일의 판만** — 문서마다 ``kb_text.select_version`` (수집기가 판을 고른 규칙 그대로)으로 기준일에 시행
   중인 판을 고르고, 그 판의 청크만 찾는다. 판이 없는 문서는 ``missing`` 으로 알린다(조용히 옛 판을 쓰지 않는다).
2. **낱말** — 한글 두 글자 묶음 + 조문 번호 통째(``kb_text.fts_query``) · bm25 순.
3. **벡터** — 검색어를 Ollama 로 임베딩해 Qdrant 에 묻는다(판 거름은 HNSW 탐색 중에 걸린다 — 앞뒤 거름 아님).
4. **질문 분류 가중** — 「세율 · 원천징수」 는 세법, 「주주총회 · 자기주식」 은 상법, 「투자권유 · 공매도」 는
   자본시장법 · 금융소비자보호법 · 감독규정 쪽 후보만 모은 순위 목록을 하나 더 RRF 에 넣는다. 거르지 않고
   가중만 하는 까닭은 분류가 틀렸을 때 답이 0건이 되지 않게 하려는 것이다(사용자 결정 2026-10-03 「둘 다 전부 +
   대처법」 — 상법 · 소득세법을 전부 넣고 섞임은 머리 경로 · 가중 · 다음 단계의 재순위로 막는다).
5. **순위 합치기** — RRF(k=60). 점수 눈금이 다른 bm25 와 코사인을 더하지 않고 순위만 쓴다.

벡터 쪽(Qdrant · Ollama)이 꺼져 있으면 낱말만으로 답하고 ``retrieval.dense_error`` 에 까닭을 싣는다 —
검색 화면이 통째로 비는 것보다 낫다. kb.sqlite3 가 없으면 503(할 일: ``python -m collector.kb_law fetch``).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from app.services import kb_text

KST = timezone(timedelta(hours=9))

ENV_DB_PATH = "KB_DB_PATH"
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CANDIDATES = (
    _ROOT / "data" / "collector" / "kb.sqlite3",         # 로컬 실행
    _ROOT / "data" / "csv" / "collector" / "kb.sqlite3",  # 도커 — ./data 가 /app/data/csv 에 읽기 전용
)

#: 한 번에 돌려줄 수 있는 근거 수 · 기본값
MAX_K = 20
DEFAULT_K = 8
#: 순위 목록마다 뽑는 후보 수 — 합칠 때 한쪽에만 있는 청크도 들어오게 k 보다 넉넉히
CANDIDATES = 40
MODES = ("hybrid", "lexical", "dense")
KINDS = ("law", "admrul")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SOURCE = "국가법령정보센터 Open API(law.go.kr) — 법령 · 행정규칙 원문 · kb.sqlite3"
NOTICE = "법령 원문 검색 결과입니다. 투자 권유가 아니며, 법률 자문을 대신하지 않습니다."


class KbError(Exception):
    """화면에 보일 수 있는 잘못 — 상태 코드 · 고칠 방법과 함께."""

    def __init__(self, status: int, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.status, self.message, self.hint = status, message, hint

    def detail(self) -> dict:
        return {"message": self.message, **({"hint": self.hint} if self.hint else {})}


# ==================================================
# 1. 질문 분류 — 낱말로 고르는 문서 묶음
# ==================================================
# 사용자가 고른 세 묶음(2026-10-03): 세금 · 회사 · 투자 규제. 묶음 이름은 응답 route.domains 에 그대로 실린다.
# 낱말은 「이 말이 나오면 그 법을 먼저 보라」 는 뜻이라 넓게 잡지 않는다 — 「배당」 처럼 세 묶음에 다 걸리는
# 말은 넣지 않고(배당소득 · 이익배당 · 배당 한도처럼 붙은 말로 가른다) 가중만 하니 틀려도 답이 사라지지 않는다.
DOMAINS: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "tax": (
        ("세금", "세율", "과세", "비과세", "원천징수", "양도소득", "배당소득", "이자소득", "금융소득", "종합과세",
         "분리과세", "종합소득", "거래세", "농어촌특별세", "농특세", "세액", "소득세", "납세", "탄력세율"),
        ("income_tax_act", "stt_act", "stt_decree", "rural_tax_act"),
    ),
    "company": (
        ("주주총회", "주총", "이사회", "정관", "신주", "자기주식", "자사주", "합병", "분할", "주식교환", "주식이전",
         "이익배당", "중간배당", "주식배당", "현물배당", "배당가능이익", "자본금", "준비금", "전환사채",
         "신주인수권", "감자", "소수주주", "주주명부"),
        ("commercial_act",),
    ),
    "regulation": (
        ("투자권유", "적합성", "적정성", "설명의무", "설명 의무", "위험 고지", "투자위험", "투자자문", "투자일임", "로보어드바이저",
         "로보 어드바이저", "전자적 투자조언장치", "불건전", "손실보전", "손실 보전", "부당권유", "청약철회",
         "위법계약", "금융소비자", "투자자 보호", "투자자보호", "공매도", "시세조종", "미공개", "내부자",
         "단기매매차익", "대량보유", "증권신고서", "신용공여", "증거금", "반대매매", "신용거래", "금융투자업"),
        ("capmkt_act", "capmkt_decree", "capmkt_rule", "fcpa_act", "fcpa_decree",
         "fis_reg", "fis_reg_rule", "fcp_reg", "fcp_reg_rule"),
    ),
}


def classify(q: str) -> Tuple[List[str], List[str]]:
    """질문 → (걸린 묶음, 가중할 문서 ID). 아무 묶음에도 안 걸리면 둘 다 빈 목록."""
    t = re.sub(r"\s+", " ", q or "")
    flat = t.replace(" ", "")
    hit: List[str] = []
    docs: List[str] = []
    for name, (words, ids) in DOMAINS.items():
        if any(w in t or w.replace(" ", "") in flat for w in words):
            hit.append(name)
            docs += [d for d in ids if d not in docs]
    return hit, docs


# ==================================================
# 2. kb.sqlite3
# ==================================================
def db_path() -> Optional[Path]:
    env = os.environ.get(ENV_DB_PATH)
    if env:
        p = Path(env)
        return p if p.is_file() else None
    for p in _DEFAULT_CANDIDATES:
        if p.is_file():
            return p
    return None


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = path or db_path()
    if path is None:
        raise KbError(503, "근거 문서 DB(kb.sqlite3)가 없다 — 이 PC 에서 근거 문서를 받은 적이 없다",
                      hint="python -m collector.kb_law fetch  (또는 KB_DB_PATH)")
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e:
        raise KbError(503, f"근거 문서 DB 를 열지 못했다: {e}") from None
    conn.row_factory = sqlite3.Row
    return conn


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _as_of(v: Optional[str]) -> str:
    if not v:
        return _today()
    if not _DAY.match(v):
        raise KbError(422, f"as_of 는 YYYY-MM-DD 다: {v!r}")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise KbError(422, f"as_of 는 없는 날짜다: {v!r}") from None
    return v


def _versions(conn: sqlite3.Connection) -> Dict[str, List[Tuple[kb_text.Version, sqlite3.Row]]]:
    out: Dict[str, List[Tuple[kb_text.Version, sqlite3.Row]]] = {}
    for r in conn.execute("SELECT * FROM kb_document ORDER BY doc_id, effective_at"):
        v = kb_text.Version(source_id=r["source_id"], promulgation_no=r["promulgation_no"],
                            promulgated_at=r["promulgated_at"], effective_at=r["effective_at"],
                            status=r["status"], law_type=r["law_type"])
        out.setdefault(r["doc_id"], []).append((v, r))
    return out


def _pick(conn: sqlite3.Connection, as_of: str, kind: Optional[str], docs: Optional[Sequence[str]]
          ) -> Tuple[Dict[str, sqlite3.Row], List[dict]]:
    """문서마다 기준일 판 → ({판 키: 문서 행}, [판이 없는 문서])."""
    chosen: Dict[str, sqlite3.Row] = {}
    missing: List[dict] = []
    for doc_id, pairs in _versions(conn).items():
        row0 = pairs[-1][1]
        if kind and row0["kind"] != kind:
            continue
        if docs and doc_id not in docs:
            continue
        v = kb_text.select_version([p[0] for p in pairs], as_of)
        if v is None:
            missing.append({"doc_id": doc_id, "title": row0["title"],
                            "earliest_effective_at": min(p[0].effective_at for p in pairs)})
            continue
        row = next(r for vv, r in pairs if vv == v)
        chosen[kb_text.version_key(doc_id, row["version_label"])] = row
    return chosen, missing


# ==================================================
# 3. 낱말 · 벡터
# ==================================================
def lexical(conn: sqlite3.Connection, q: str, keys: Iterable[str], n: int = CANDIDATES) -> List[str]:
    """FTS5 bm25 순 청크 ID — 고른 판의 청크만."""
    match = kb_text.fts_query(q)
    keys = list(keys)
    if not match or not keys:
        return []
    marks = ",".join("?" * len(keys))
    rows = conn.execute(
        "SELECT k.chunk_id FROM kb_chunk_fts f JOIN kb_chunk k ON k.rid = f.rowid"
        f" WHERE kb_chunk_fts MATCH ? AND (k.doc_id || '@' || k.version_label) IN ({marks})"
        " ORDER BY bm25(kb_chunk_fts) LIMIT ?", [match, *keys, n]).fetchall()
    return [r["chunk_id"] for r in rows]


def _http_json(method: str, url: str, body: Optional[dict], timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


@dataclass
class DenseBackend:
    """벡터 검색 길 — 시험에서는 가짜로 바꿔 끼운다(네트워크 없이)."""

    ollama_url: str
    qdrant_url: str
    timeout: float = 30.0
    http: Callable[[str, str, Optional[dict], float], dict] = _http_json

    @classmethod
    def from_settings(cls) -> "DenseBackend":
        from app.config import settings  # 시험이 가짜 백엔드만 쓸 때 설정을 읽지 않게 늦게 가져온다

        return cls(ollama_url=settings.OLLAMA_BASE_URL.rstrip("/"), qdrant_url=settings.QDRANT_URL.rstrip("/"))

    def embed(self, model: kb_text.EmbedModel, q: str) -> List[float]:
        out = self.http("POST", f"{self.ollama_url}/api/embed",
                        {"model": model.name, "input": [model.query_prefix + q]}, self.timeout)
        vecs = out.get("embeddings") or []
        if len(vecs) != 1 or len(vecs[0]) != model.dim:
            raise RuntimeError(f"{model.name} 임베딩 모양이 다르다({len(vecs)}개)")
        return vecs[0]

    def query(self, model: kb_text.EmbedModel, vec: List[float], keys: Sequence[str], n: int) -> List[str]:
        body = {"query": vec, "using": model.vector, "limit": n, "with_payload": ["chunk_id"],
                "filter": {"must": [{"key": "version_key", "match": {"any": list(keys)}}]}}
        out = self.http("POST", f"{self.qdrant_url}/collections/{kb_text.KB_COLLECTION}/points/query",
                        body, self.timeout)
        pts = (out.get("result") or {}).get("points") or []
        return [p["payload"]["chunk_id"] for p in pts if (p.get("payload") or {}).get("chunk_id")]


def dense(backend: DenseBackend, model: kb_text.EmbedModel, q: str, keys: Sequence[str],
          n: int = CANDIDATES) -> List[str]:
    if not keys:
        return []
    return backend.query(model, backend.embed(model, q), keys, n)


def _dense_error(e: Exception) -> str:
    """벡터 쪽 실패를 한 줄로 — 주소 · 키를 싣지 않는다."""
    if isinstance(e, urllib.error.HTTPError):
        return f"벡터 검색 HTTP {e.code} — kb_v1 컬렉션 · 임베딩 모델이 있는지(python -m collector.kb_index status)"
    if isinstance(e, (urllib.error.URLError, TimeoutError, OSError)):
        return f"벡터 검색 서버에 닿지 못했다({type(e).__name__}) — Qdrant · Ollama 가 켜져 있는지"
    return f"벡터 검색 실패 — {e}"


# ==================================================
# 4. 찾기 · 문서 목록
# ==================================================
def _hit(r: sqlite3.Row, doc: sqlite3.Row, rank: int, score: float, ranks: Dict[str, int]) -> dict:
    return {
        "rank": rank, "chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "title": doc["title"],
        "grade": r["grade"], "kind": r["kind"], "version_label": r["version_label"],
        "effective_at": r["effective_at"], "article": r["article"], "article_title": r["article_title"],
        "part": kb_text.clean_part(r["part"]), "paras": r["paras"], "text": r["text"],
        "url": doc["source_url"], "score": round(score, 6), "ranks": ranks,
    }


def search(q: str, k: int = DEFAULT_K, *, as_of: Optional[str] = None, kind: Optional[str] = None,
           docs: Optional[Sequence[str]] = None, mode: str = "hybrid", model: Optional[str] = None,
           route: bool = True, path: Optional[Path] = None, backend: Optional[DenseBackend] = None) -> dict:
    q = (q or "").strip()
    if not q:
        raise KbError(422, "검색어가 비었다")
    if not 1 <= k <= MAX_K:
        raise KbError(422, f"k 는 1~{MAX_K} 다: {k}")
    if mode not in MODES:
        raise KbError(422, f"mode 는 {' · '.join(MODES)} 가운데 하나다: {mode!r}")
    if kind and kind not in KINDS:
        raise KbError(422, f"kind 는 law(법령) · admrul(행정규칙) 가운데 하나다: {kind!r}")
    model_name = model or kb_text.DEFAULT_EMBED_MODEL
    if model_name not in kb_text.EMBED_MODELS:
        raise KbError(422, f"model 은 {' · '.join(kb_text.EMBED_MODELS)} 가운데 하나다: {model_name!r}")
    emb = kb_text.EMBED_MODELS[model_name]
    as_of = _as_of(as_of)

    conn = _connect(path)
    try:
        known = {r[0] for r in conn.execute("SELECT DISTINCT doc_id FROM kb_document")}
        if docs:
            bad = sorted(set(docs) - known)
            if bad:
                raise KbError(422, f"모르는 문서: {', '.join(bad)}", hint=f"있는 것: {', '.join(sorted(known))}")
        chosen, missing = _pick(conn, as_of, kind, docs)
        keys = list(chosen)

        lists: Dict[str, List[str]] = {}
        dense_err = None
        if mode in ("hybrid", "lexical"):
            lists["lexical"] = lexical(conn, q, keys)
        if mode in ("hybrid", "dense"):
            try:
                lists["dense"] = dense(backend or DenseBackend.from_settings(), emb, q, keys)
            except Exception as e:  # noqa: BLE001 — 벡터가 안 돼도 낱말로 답한다(위 머리말)
                dense_err = _dense_error(e)
                if mode == "dense":
                    raise KbError(503, dense_err) from None

        # 벡터 DB 에는 다시 쪼개기 전의 옛 점이 남아 있을 수 있다 — 지금 SQLite 에 있는 청크만 쓴다.
        cand = list(dict.fromkeys(cid for lst in lists.values() for cid in lst))
        rows: Dict[str, sqlite3.Row] = {}
        for i in range(0, len(cand), 500):
            part = cand[i:i + 500]
            for r in conn.execute(f"SELECT * FROM kb_chunk WHERE chunk_id IN ({','.join('?' * len(part))})", part):
                rows[r["chunk_id"]] = r
        lists = {name: [c for c in lst if c in rows] for name, lst in lists.items()}

        domains, route_docs = classify(q) if route else ([], [])
        rankings = [lists[name] for name in ("lexical", "dense") if name in lists]
        if route_docs:
            # 두 목록을 먼저 합친 순서에서 가중할 문서의 후보만 골라 셋째 목록으로 — 순위만 쓰는 RRF 와 같은 눈금
            base = [cid for cid, _ in kb_text.rrf(rankings)]
            routed = [cid for cid in base if rows[cid]["doc_id"] in route_docs]
            if routed:
                rankings.append(routed)
        fused = kb_text.rrf(rankings)[:k]

        hits = []
        for i, (cid, score) in enumerate(fused, start=1):
            r = rows[cid]
            ranks = {name: lst.index(cid) + 1 for name, lst in lists.items() if cid in lst}
            hits.append(_hit(r, chosen[kb_text.version_key(r["doc_id"], r["version_label"])], i, score, ranks))
    finally:
        conn.close()

    method = "+".join(["fts5"] * ("lexical" in lists) + ["dense"] * ("dense" in lists)) + ("+rrf" if len(lists) > 1 else "")
    return {
        "query": q, "as_of": as_of, "mode": mode, "model": model_name if "dense" in lists else None,
        "route": {"domains": domains, "docs": route_docs},
        "retrieval": {"k": k, "method": method, "candidates": {n: len(v) for n, v in lists.items()},
                      **({"dense_error": dense_err} if dense_err else {})},
        "missing": missing,
        "hits": hits,
        "source": SOURCE,
        "notice": NOTICE,
    }


def documents(kind: Optional[str] = None, *, path: Optional[Path] = None) -> dict:
    """받아 둔 문서 판 목록 — 화면의 「근거 문서」 표 · 답 아래 출처의 판 정보."""
    if kind and kind not in KINDS:
        raise KbError(422, f"kind 는 law(법령) · admrul(행정규칙) 가운데 하나다: {kind!r}")
    conn = _connect(path)
    try:
        vec = {(r["doc_id"], r["version_label"], r["model"]): r["n"] for r in conn.execute(
            "SELECT c.doc_id, c.version_label, v.model, COUNT(*) n FROM kb_vector v JOIN kb_chunk c"
            " ON c.chunk_id = v.chunk_id AND c.text_sha256 = v.text_sha256 GROUP BY 1, 2, 3")}
        out = []
        for r in conn.execute("SELECT * FROM kb_document ORDER BY grade, doc_id, effective_at DESC"):
            if kind and r["kind"] != kind:
                continue
            out.append({
                "doc_id": r["doc_id"], "title": r["title"], "kind": r["kind"], "grade": r["grade"],
                "law_type": r["law_type"], "issuer": r["issuer"], "version_label": r["version_label"],
                "promulgation_no": r["promulgation_no"], "promulgated_at": r["promulgated_at"],
                "effective_at": r["effective_at"], "status_when_fetched": r["status"],
                "selected_for": r["selected_for"], "fetched_at": r["fetched_at"], "url": r["source_url"],
                "scope": r["scope"] or "전부", "articles": r["articles"], "chunks": r["chunks"],
                "content_sha256": r["content_sha256"], "note": r["note"],
                "vectors": {m: vec.get((r["doc_id"], r["version_label"], m), 0) for m in kb_text.EMBED_MODELS},
            })
        last = conn.execute("SELECT MAX(fetched_at) FROM kb_document").fetchone()[0]
    finally:
        conn.close()
    return {"as_of": (last or "")[:10] or None, "fetched_at": last, "documents": out,
            "source": SOURCE, "notice": "법령 · 고시는 저작권 보호 대상이 아니다(저작권법 제7조) — 원문은 url 에서."}
