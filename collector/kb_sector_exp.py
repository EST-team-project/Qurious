"""섹터 법령을 근거 답에 넣을지 재는 실험 — 「넣은 길」 을 운영 근거 DB 밖에 따로 만든다 (목표 기능 ① · 설계서 5.3.7).

    python -m collector.kb_sector_exp build [--year 2026]              근거 DB 사본 + 섹터 법령 그해 판 조각
    python -m collector.kb_sector_exp index [--batch 16]               Qdrant kb_v1 → kb_v1_sector 복사 + 새 조각 임베딩
    python -m collector.kb_sector_exp search [kb_eval 인자 …]          「넣은 길」 로 검색 평가(collector.kb_eval 그대로)
    python -m collector.kb_sector_exp answer [kb_answer_eval 인자 …]   「넣은 길」 로 근거 답 평가(collector.kb_answer_eval 그대로)
    python -m collector.kb_sector_exp status

왜 따로 만드나
--------------
앱이 읽는 근거 DB(`data/collector/kb.sqlite3` · Qdrant `kb_v1`)에 섹터 법령을 바로 넣으면 평가하기 전에 화면의 답이 바뀐다.
그래서 「넣은 길」 은 사본 DB(`data/collector/kb_exp_sector.sqlite3`)와 다른 컬렉션(`kb_v1_sector`)에 만들고, 평가 도구는
같은 코드로 그 둘을 읽게 한다 — 프로세스 안에서 `KB_DB_PATH` 환경 변수와 `kb_text.KB_COLLECTION` 만 바꾼다(운영 코드는 그대로).
「안 넣은 길」 은 지금 그대로의 `kb_eval` · `kb_answer_eval` 이다.

무엇을 넣나
-----------
섹터 법령 DB(`kb_sector.sqlite3`)가 해마다 고른 판 가운데 **그해(기본 2026) 판**만 — 받아 둔 원문(`kb_raw`)을 `kb_law.RawReplay`
로 다시 읽어 근거 문서와 같은 길(판 목록 → 고른 판 본문 → 뒤에 공포된 판 대조 → `chunk_article`)로 조각을 만든다. 네트워크 ·
키 없이 돈다. 근거 DB 에 이미 있는 문서(자본시장법 · 시행령 · 상법)는 넣지 않는다(같은 법이 두 판으로 섞이지 않게).
문서 ID 는 `sec:` + 띄어쓰기를 뺀 법 이름이다(근거 DB 의 영문 ID 와 겹치지 않는다).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from collector import config, kb_law, kb_sector
from collector.console import utf8_stdio

sys.path.insert(0, str(config.ROOT))
from app.services import kb_text  # noqa: E402

EXP_DB = config.DATA_DIR / "kb_exp_sector.sqlite3"
EXP_COLLECTION = "kb_v1_sector"
DOC_PREFIX = "sec:"
#: 섹터 법령을 받은 기준일 — 2026 판은 받은 날(2026-10-05)에 고른 판이다(`ks_choice.as_of`). 실행일로 다시 고르지 않는다.
OLDEST_AS_OF = "2020-12-31"


def doc_id_for(title: str) -> str:
    return DOC_PREFIX + kb_sector._slug(title)


# ==================================================
# 1. 사본 DB + 섹터 법령 조각
# ==================================================
def build(year: int = 2026, *, out: Path = EXP_DB, quiet: bool = False) -> Dict[str, int]:
    """근거 DB 를 통째로 복사한 뒤 섹터 법령 그해 판의 조각을 더한다(사본은 매번 새로 — 지난 실험의 찌꺼기가 없게)."""
    src = sqlite3.connect(f"file:{kb_law.KB_DB_PATH}?mode=ro", uri=True)
    if out.exists():
        out.unlink()
    for side in (Path(str(out) + "-wal"), Path(str(out) + "-shm")):
        if side.exists():
            side.unlink()
    dst = sqlite3.connect(out)
    src.backup(dst)
    dst.close()
    src.close()
    conn = kb_law.connect(out)
    have = {kb_sector._slug(r[0]) for r in conn.execute("SELECT DISTINCT title FROM kb_document")}
    sconn = kb_sector.connect()
    replay = kb_law.RawReplay(sconn)
    stats = {"docs": 0, "skipped_dup": 0, "chunks": 0, "articles": 0, "failed": 0}
    rows = sconn.execute("SELECT c.title, c.as_of, c.source_id, c.effective_at, d.dept FROM ks_choice c "
                         "LEFT JOIN ks_doc d ON d.title = c.title WHERE c.year=? ORDER BY c.title", (year,)).fetchall()
    for title, as_of, source_id, effective_at, dept in rows:
        if kb_sector._slug(title) in have:
            stats["skipped_dup"] += 1
            continue
        spec = kb_law.DocSpec(doc_id=doc_id_for(title), title=title, kind="law", grade=1)
        try:
            versions = kb_sector.law_versions_all(replay, title, OLDEST_AS_OF)
            chosen = next(v for v in versions if v.source_id == source_id and v.effective_at == effective_at)
            info, arts = kb_law.fetch_body(replay, spec, chosen)
            arts, notes = kb_law.check_later(replay, spec, versions, chosen, arts, as_of)
        except (kb_law.LawApiError, StopIteration) as e:
            stats["failed"] += 1
            print(f"  ✗ {title} — {type(e).__name__}: {str(e)[:100]}", flush=True)
            continue
        used = [a for a in arts if not a.deleted]
        chunks = [c for a in used for c in kb_law.chunk_article(title, a)]
        sha = kb_text.text_sha256("\n\n".join(f"{a.label}\n{a.body}" for a in used))
        kb_law.store_version(conn, spec, chosen, title, dept or "", chunks, len(used), sha, as_of,
                             "섹터 법령 실험(kb_sector_exp) — " + " / ".join(notes), "")
        stats["docs"] += 1
        stats["articles"] += len(used)
        stats["chunks"] += len(chunks)
        if not quiet and stats["docs"] % 20 == 0:
            print(f"  문서 {stats['docs']} · 조각 {stats['chunks']:,}", flush=True)
    conn.close()
    sconn.close()
    return stats


# ==================================================
# 2. 다른 컬렉션 — 운영 점 복사 + 새 조각 임베딩
# ==================================================
def _use_experiment() -> None:
    """이 프로세스에서만 「넣은 길」 을 보게 한다 — 사본 DB · 다른 컬렉션."""
    os.environ["KB_DB_PATH"] = str(EXP_DB)
    kb_law.KB_DB_PATH = EXP_DB
    kb_text.KB_COLLECTION = EXP_COLLECTION


def copy_points(batch: int = 256) -> int:
    """`kb_v1` 의 점을 벡터 · payload 째로 `kb_v1_sector` 에 옮긴다(컬렉션 설정도 그대로)."""
    from collector import kb_index

    base = kb_index.QDRANT_URL
    info = kb_index._http("GET", f"{base}/collections/kb_v1")["result"]["config"]["params"]
    try:
        kb_index._http("DELETE", f"{base}/collections/{EXP_COLLECTION}")
    except kb_index.IndexError_:
        pass
    kb_index._http("PUT", f"{base}/collections/{EXP_COLLECTION}", {"vectors": info["vectors"]})
    for field, schema in (("version_key", "keyword"), ("doc_id", "keyword"), ("kind", "keyword"),
                          ("grade", "integer"), ("effective_at", "keyword")):
        kb_index._http("PUT", f"{base}/collections/{EXP_COLLECTION}/index?wait=true",
                       {"field_name": field, "field_schema": schema})
    n, offset = 0, None
    while True:
        body = {"limit": batch, "with_payload": True, "with_vector": True}
        if offset is not None:
            body["offset"] = offset
        res = kb_index._http("POST", f"{base}/collections/kb_v1/points/scroll", body)["result"]
        pts = res.get("points") or []
        if pts:
            kb_index._http("PUT", f"{base}/collections/{EXP_COLLECTION}/points?wait=true",
                           {"points": [{"id": p["id"], "vector": p["vector"], "payload": p["payload"]} for p in pts]})
            n += len(pts)
        offset = res.get("next_page_offset")
        if offset is None:
            break
    return n


def index(batch: int = 16, model: str = kb_text.DEFAULT_EMBED_MODEL) -> int:
    from collector import kb_index

    n = copy_points()
    print(f"  kb_v1 → {EXP_COLLECTION} 점 {n:,}개 복사", flush=True)
    _use_experiment()
    conn = kb_law.connect(EXP_DB)
    left = len(kb_index.pending(conn, kb_text.EMBED_MODELS[model], None))
    conn.close()
    print(f"  새 조각 {left:,}개를 {model} 로 넣는다(묶음 {batch})", flush=True)
    return kb_index.run(model, None, batch, None)


# ==================================================
# 3. 평가 — 같은 도구를 「넣은 길」 로
# ==================================================
def run_search_eval(argv: List[str]) -> int:
    from collector import kb_eval

    _use_experiment()
    return kb_eval.main(argv)


def run_answer_eval(argv: List[str]) -> int:
    from collector import kb_answer_eval

    _use_experiment()
    return kb_answer_eval.main(argv)


def status() -> None:
    if not EXP_DB.exists():
        print(f"실험 DB 없음 — python -m collector.kb_sector_exp build")
        return
    c = sqlite3.connect(f"file:{EXP_DB}?mode=ro", uri=True)
    n_doc, n_chunk = c.execute("SELECT COUNT(*), SUM(chunks) FROM kb_document WHERE doc_id LIKE 'sec:%'").fetchone()
    base = c.execute("SELECT COUNT(*), SUM(chunks) FROM kb_document WHERE doc_id NOT LIKE 'sec:%'").fetchone()
    vec = c.execute("SELECT COUNT(*) FROM kb_vector v JOIN kb_chunk k ON k.chunk_id=v.chunk_id "
                    "WHERE k.doc_id LIKE 'sec:%' AND v.model='bge-m3'").fetchone()[0]
    print(f"실험 DB {EXP_DB.name} · 근거 문서 {base[0]}(조각 {base[1]:,}) + 섹터 법령 {n_doc}(조각 {n_chunk or 0:,} · "
          f"bge-m3 넣음 {vec:,})")


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("search", "answer"):
        return run_search_eval(argv[1:]) if argv[0] == "search" else run_answer_eval(argv[1:])
    p = argparse.ArgumentParser(prog="python -m collector.kb_sector_exp", description="섹터 법령 근거 답 실험")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--year", type=int, default=2026)
    i = sub.add_parser("index")
    i.add_argument("--batch", type=int, default=16)
    sub.add_parser("status")
    a = p.parse_args(argv)
    if a.cmd == "build":
        t0 = time.time()
        s = build(a.year)
        print(f"  끝 — 섹터 법령 {s['docs']}문서 · 조 {s['articles']:,} · 조각 {s['chunks']:,} · 겹쳐서 뺀 문서 {s['skipped_dup']} · "
              f"실패 {s['failed']} · {time.time() - t0:.0f}초 → {EXP_DB}")
        return 0 if not s["failed"] else 1
    if a.cmd == "index":
        return index(a.batch)
    status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
