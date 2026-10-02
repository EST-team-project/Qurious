"""근거 청크를 임베딩해 Qdrant ``kb_v1`` 에 넣는다 (목표 기능 ① W5 · 설계서 5.3.3).

    python -m collector.kb_index run --model bge-m3 [--docs stt_decree,fis_reg] [--batch 8]
    python -m collector.kb_index status

어디서 돌리나 — 이 PC (전역 규칙 8.2)
--------------------------------------
청크는 수천 개(2026-10-02 · 4,034)라 로컬 CPU 로 충분하다 — Colab 으로 보내는 기준은 수십만 개다(설계서 5.3.3).
속도는 이 PC 의 호스트 Ollama 로 bge-m3 348자 청크 초당 약 1.8개 · nomic-embed-text 약 3.1개(10-02 실측)라
수천 개가 수십 분 걸린다. 그래서 **이어서 돌 수 있게** 만들었다 — 넣은 청크는 ``kb_vector`` 에 (청크, 모델,
본문 지문)으로 남기고, 다시 돌리면 본문이 바뀐 것과 아직 안 넣은 것만 넣는다. 도중에 멈춰도 잃는 것이 없다.

무엇을 넣나
-----------
점 하나 = 청크 하나. ID 는 ``kb_text.point_id(chunk_id)`` 로 실행마다 같다(옛 크롤 색인은 내장 hash() 라
다시 돌릴 때마다 점이 새로 쌓였다). 모델마다 이름 붙은 벡터를 따로 둔다 — 한 모델을 넣을 때 다른 모델의
벡터를 지우지 않도록, 이미 있는 점에는 벡터만 바꿔 넣는다(``points/vectors``).
payload 에는 거르는 칸(문서 · 판 · 종류 · 등급 · 시행일)과 본문을 함께 둔다 — 앱이 SQLite 없이도 출처를 보일 수 있게.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Sequence

from collector import config
from collector.console import utf8_stdio
from collector import kb_law

sys.path.insert(0, str(config.ROOT))
from app.services import kb_text  # noqa: E402

QDRANT_URL = config.env("KB_QDRANT_URL", "http://localhost:16333")   # compose 가 호스트에 연 포트
OLLAMA_URL = config.env("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


class IndexError_(RuntimeError):
    """벡터 DB · 임베딩 서버를 쓰지 못했다."""


def _http(method: str, url: str, body: Optional[dict] = None, timeout: int = 600) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise IndexError_(f"{method} {url.split('?')[0]} → HTTP {e.code} {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise IndexError_(f"{method} {url.split('?')[0]} 에 닿지 못했다({type(e).__name__}) — "
                          f"Qdrant(16333) · Ollama(11434) 가 켜져 있는지") from None
    return json.loads(raw) if raw else {}


def embed(model: kb_text.EmbedModel, texts: Sequence[str], prefix: str) -> List[List[float]]:
    out = _http("POST", f"{OLLAMA_URL}/api/embed", {"model": model.name, "input": [prefix + t for t in texts]})
    vecs = out.get("embeddings") or []
    if len(vecs) != len(texts) or any(len(v) != model.dim for v in vecs):
        raise IndexError_(f"{model.name} 임베딩 모양이 다르다 — {len(vecs)}개 · 기대 {len(texts)}개 × {model.dim}차원")
    return vecs


def ensure_collection() -> None:
    """``kb_v1`` 이 없으면 만든다 — 모델마다 이름 붙은 벡터(코사인) · 거르는 칸 색인."""
    url = f"{QDRANT_URL}/collections/{kb_text.KB_COLLECTION}"
    try:
        info = _http("GET", url)
        vectors = info["result"]["config"]["params"]["vectors"]
        for m in kb_text.EMBED_MODELS.values():
            if m.vector not in vectors or vectors[m.vector]["size"] != m.dim:
                raise IndexError_(f"컬렉션 {kb_text.KB_COLLECTION} 의 벡터 {m.vector} 설정이 다르다 — 지우고 다시 만들어야 한다")
        return
    except IndexError_ as e:
        if "404" not in str(e):
            raise
    _http("PUT", url, {"vectors": {m.vector: {"size": m.dim, "distance": "Cosine"}
                                   for m in kb_text.EMBED_MODELS.values()}})
    for field, schema in (("version_key", "keyword"), ("doc_id", "keyword"), ("kind", "keyword"),
                          ("grade", "integer"), ("effective_at", "keyword")):
        _http("PUT", f"{url}/index?wait=true", {"field_name": field, "field_schema": schema})


def _payload(r) -> Dict[str, object]:
    return {"chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "version_label": r["version_label"],
            "version_key": kb_text.version_key(r["doc_id"], r["version_label"]), "article": r["article"],
            "article_title": r["article_title"], "paras": r["paras"], "kind": r["kind"], "grade": r["grade"],
            "effective_at": r["effective_at"], "title": r["title"], "text": r["text"]}


def pending(conn, model: kb_text.EmbedModel, docs: Optional[Sequence[str]]) -> list:
    """아직 넣지 않았거나 본문이 바뀐 청크 — 문서 등급 · 문서 · 조 순서."""
    q = ("SELECT c.*, d.title FROM kb_chunk c JOIN kb_document d ON d.doc_id=c.doc_id AND d.version_label=c.version_label"
         " LEFT JOIN kb_vector v ON v.chunk_id=c.chunk_id AND v.model=?"
         " WHERE (v.chunk_id IS NULL OR v.text_sha256 <> c.text_sha256)")
    args: list = [model.name]
    if docs:
        q += f" AND c.doc_id IN ({','.join('?' * len(docs))})"
        args += list(docs)
    q += " ORDER BY c.grade, c.doc_id, c.article_key, c.seq"
    return conn.execute(q, args).fetchall()


def run(model_name: str, docs: Optional[Sequence[str]], batch: int, limit: Optional[int]) -> int:
    model = kb_text.EMBED_MODELS[model_name]
    conn = kb_law.connect()
    ensure_collection()
    rows = pending(conn, model, docs)
    if limit:
        rows = rows[:limit]
    total = len(rows)
    print(f"― 임베딩 {model.name} → {kb_text.KB_COLLECTION}.{model.vector} · 넣을 청크 {total:,} ―", flush=True)
    if not total:
        return 0
    t0 = time.time()
    done = 0
    for i in range(0, total, batch):
        part = rows[i:i + batch]
        vecs = embed(model, [r["text"] for r in part], model.doc_prefix)
        has_other = {r["chunk_id"] for r in conn.execute(
            f"SELECT chunk_id FROM kb_vector WHERE model<>? AND chunk_id IN ({','.join('?' * len(part))})",
            [model.name] + [r["chunk_id"] for r in part])}
        new_pts = [{"id": kb_text.point_id(r["chunk_id"]), "vector": {model.vector: v}, "payload": _payload(r)}
                   for r, v in zip(part, vecs) if r["chunk_id"] not in has_other]
        upd_pts = [{"id": kb_text.point_id(r["chunk_id"]), "vector": {model.vector: v}}
                   for r, v in zip(part, vecs) if r["chunk_id"] in has_other]
        base = f"{QDRANT_URL}/collections/{kb_text.KB_COLLECTION}/points"
        if new_pts:
            _http("PUT", f"{base}?wait=true", {"points": new_pts})
        if upd_pts:
            _http("PUT", f"{base}/vectors?wait=true", {"points": upd_pts})
            for r in part:
                if r["chunk_id"] in has_other:
                    _http("POST", f"{base}/payload?wait=true",
                          {"payload": _payload(r), "points": [kb_text.point_id(r["chunk_id"])]})
        now = kb_law.now_kst()
        conn.executemany("INSERT OR REPLACE INTO kb_vector(chunk_id, model, text_sha256, dim, indexed_at) VALUES (?,?,?,?,?)",
                         [(r["chunk_id"], model.name, r["text_sha256"], model.dim, now) for r in part])
        done += len(part)
        if done % (batch * 25) == 0 or done == total:
            dt = time.time() - t0
            rate = done / dt if dt else 0
            left = (total - done) / rate if rate else 0
            print(f"  {done:>5,}/{total:,} · 초당 {rate:.2f}개 · 남은 {left / 60:.0f}분", flush=True)
    print(f"  끝 · {time.time() - t0:,.0f}초", flush=True)
    return 0


def cmd_status(_a) -> int:
    conn = kb_law.connect()
    n = conn.execute("SELECT COUNT(*) FROM kb_chunk").fetchone()[0]
    print(f"― 벡터 색인 · 청크 {n:,} ―")
    for name in kb_text.EMBED_MODELS:
        k = conn.execute("SELECT COUNT(*) FROM kb_vector v JOIN kb_chunk c ON c.chunk_id=v.chunk_id"
                         " AND c.text_sha256=v.text_sha256 WHERE v.model=?", (name,)).fetchone()[0]
        print(f"  {name:<17} {k:>6,} / {n:,}")
    try:
        info = _http("GET", f"{QDRANT_URL}/collections/{kb_text.KB_COLLECTION}", timeout=10)
        print(f"  Qdrant {kb_text.KB_COLLECTION} 점 {info['result'].get('points_count', 0):,}")
    except IndexError_ as e:
        print(f"  Qdrant 확인 못 함 — {e}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.kb_index", description="근거 청크 임베딩 → Qdrant kb_v1")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="아직 넣지 않은 청크를 임베딩해 넣는다(이어서 돈다)")
    r.add_argument("--model", default=kb_text.DEFAULT_EMBED_MODEL, choices=sorted(kb_text.EMBED_MODELS))
    r.add_argument("--docs", help="문서 ID 몇 개만(쉼표)")
    r.add_argument("--batch", type=int, default=8)
    r.add_argument("--limit", type=int)
    sub.add_parser("status", help="모델별 넣은 청크 수 · Qdrant 점 수")
    a = p.parse_args(argv)
    if a.cmd == "status":
        return cmd_status(a)
    docs = [s.strip() for s in a.docs.split(",")] if a.docs else None
    try:
        return run(a.model, docs, a.batch, a.limit)
    except IndexError_ as e:
        print(f"🔴 {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
