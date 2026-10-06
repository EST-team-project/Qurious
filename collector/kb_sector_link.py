"""섹터 법령을 앱 근거 DB 에 넣는다 — 섹터 질문일 때만 찾게 (목표 기능 ① W8 · 설계서 5.3.7 · 14.1 ⑮).

    python -m collector.kb_sector_link build [--year 2026]       섹터 법령 그해 판 조각 → 근거 DB + 분류 낱말 표
    python -m collector.kb_sector_link vectors [--no-reuse]      벡터 — 실험 컬렉션의 같은 조각을 옮기고 나머지만 임베딩
    python -m collector.kb_sector_link status

무엇을 하나
-----------
1. **조각** — 섹터 법령 DB(`kb_sector.sqlite3`)가 그해(기본 2026) 고른 판을 받아 둔 원문으로 다시 읽어(네트워크 · 키 없음)
   근거 문서와 같은 길(`kb_law.chunk_article` · `store_version`)로 앱 근거 DB(`kb.sqlite3`)에 넣는다. 문서 ID 는 `sec:` +
   띄어쓰기를 뺀 법 이름이다(실험 `kb_sector_exp` 와 같다 — 섹터 평가셋의 정답 칸 `sec:은행법:제8조` 가 그대로 맞는다).
   근거 문서에 이미 있는 법(자본시장법 · 시행령 · 상법)은 넣지 않는다(같은 법이 두 판으로 섞이지 않게).
2. **분류 낱말 표** `kb_sector_word` — 질문에 이 낱말이 있으면 그 섹터 법령(법률과 그 시행령)이 검색 후보에 든다
   (`app/services/kb_search.sector_route`). 낱말은 세 가지다.

   ==========  ===============================================  ==============================
   출처         무엇                                               어디서
   ==========  ===============================================  ==============================
   정식 이름     「은행법」 · 「화학물질관리법」                           섹터 표 title
   약칭         「반도체특별법」 · 「중대재해처벌법」                        법령 목록 원문의 법령약칭명(법령 API)
   업 이름       「은행업」 · 「리츠」 · 「종편」 · 「카지노」                     섹터 표 words 칸(사람이 고름)
   ==========  ===============================================  ==============================

   맞추는 꼴은 띄어쓰기 · 가운뎃점을 빼고 로마자는 소문자다(`kb_search.norm_word`).
3. **벡터** — 2026-10-05 실험(`kb_sector_exp`)이 같은 조각을 bge-m3 로 `kb_v1_sector` 에 넣어 두었다(9,725조각 · 42분).
   조각 ID · 본문 지문 · 모델이 모두 같은 것만 그 벡터를 `kb_v1` 로 옮기고, 나머지는 `kb_index.run` 이 새로 넣는다.
   옮긴 뒤 몇 조각을 지금 다시 임베딩해 코사인으로 견준다(같은 글 · 같은 모델이면 1 에 가깝다).

앱 근거 DB 에 넣어도 섹터 질문이 아니면 답이 바뀌지 않는다 — 검색이 `sec:` 문서를 분류가 고를 때만 후보로 삼는다.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import sqlite3
import sys
import time
from typing import Dict, List, Optional, Sequence, Set, Tuple

from collector import config, kb_index, kb_law, kb_sector, kb_sector_exp
from collector.console import utf8_stdio

sys.path.insert(0, str(config.ROOT))
from app.services import kb_search, kb_text  # noqa: E402

DOC_PREFIX = kb_search.SECTOR_PREFIX
assert DOC_PREFIX == kb_sector_exp.DOC_PREFIX, "실험 · 앱의 섹터 문서 ID 머리가 같아야 평가셋 정답 칸이 맞는다"

SECTOR_FTS = kb_search.SECTOR_FTS
WORD_SCHEMA = f"""
-- 섹터 질문 분류 낱말 — 질문에 word 가 있으면 doc_id 가 검색 후보에 든다(kb_sector_link 가 통째로 다시 만든다).
CREATE TABLE IF NOT EXISTS kb_sector_word (
    word        TEXT NOT NULL,   -- 맞추는 꼴(띄어쓰기 · 가운뎃점 뺌 · 로마자 소문자)
    shown       TEXT NOT NULL,   -- 표에 적힌 꼴 — 응답 route.sector_words 에 보인다
    doc_id      TEXT NOT NULL,   -- sec:… (법률과 그 시행령)
    sector_code TEXT NOT NULL,   -- En · Ma · … · All
    sector      TEXT NOT NULL,   -- 에너지 · 소재 · … · 공통
    source      TEXT NOT NULL,   -- 정식 이름 · 약칭 · 업 이름
    PRIMARY KEY (word, doc_id, sector_code)
);
-- 섹터 법령 조각의 낱말 색인 — 근거 문서 색인(kb_chunk_fts)과 따로 둔다. bm25 는 표 전체의 통계(낱말이 드문 정도 ·
-- 평균 길이)로 순위를 매기므로, 같은 표에 섹터 조각 9,725개를 넣자 섹터 문서를 후보에서 빼도 기존 질문의 순위가
-- 흔들렸다(2026-10-06 · 손실 보전 Q27 1위 → 12위 · 펀드 청약 철회 Q33 1위 → 18위). rowid = kb_chunk.rid
CREATE VIRTUAL TABLE IF NOT EXISTS {SECTOR_FTS} USING fts5(grams, tokenize="{kb_text.FTS_TOKENIZE}");
"""
SOURCES = ("정식 이름", "약칭", "업 이름")
#: 맞추는 꼴이 이보다 짧은 낱말은 넣지 않는다(한 글자는 아무 질문에나 걸린다).
MIN_WORD = 2


def doc_id_for(title: str) -> str:
    return DOC_PREFIX + kb_sector._slug(title)


# ==================================================
# 1. 약칭 — 법령 목록 원문의 법령약칭명
# ==================================================
def official_abbr(sconn: sqlite3.Connection) -> Dict[str, str]:
    """{정식 이름(띄어쓰기 뺌): 약칭} — 섹터 법령 DB 가 받아 둔 목록 원문(eflaw/search/<이름>)에서 읽는다."""
    out: Dict[str, str] = {}
    for (body,) in sconn.execute("SELECT body FROM kb_raw WHERE target LIKE 'eflaw/search/%' ORDER BY fetched_at"):
        try:
            data = json.loads(gzip.decompress(body).decode("utf-8"))
        except (OSError, ValueError):
            continue
        laws = (data.get("LawSearch") or {}).get("law") or []
        for x in (laws if isinstance(laws, list) else [laws]):
            name, abbr = (x.get("법령명한글") or "").strip(), (x.get("법령약칭명") or "").strip()
            if name and abbr:
                out[kb_sector._slug(name)] = abbr   # 뒤에 받은 원문이 앞을 덮는다
    return out


# ==================================================
# 2. 조각 + 분류 낱말 표
# ==================================================
def _split_words(cell: str) -> List[str]:
    return [w.strip() for w in (cell or "").split("|") if w.strip()]


def word_rows(table: Sequence[kb_sector.SectorLaw], abbr: Dict[str, str], have_docs: Set[str],
              base_slugs: Set[str]) -> List[Tuple[str, str, str, str, str, str]]:
    """분류 낱말 표의 행 — (맞추는 꼴, 보이는 꼴, 문서, 섹터 코드, 섹터, 출처).

    한 법이 두 섹터에 있으면(유통산업발전법 · 국가첨단전략산업법) 두 줄의 업 이름을 합쳐 두 섹터 모두로 낸다.
    근거 문서에 이미 있는 법(base_slugs) · 근거 DB 에 없는 문서는 건너뛴다.
    """
    by_title: Dict[str, List[kb_sector.SectorLaw]] = {}
    for s in table:
        by_title.setdefault(s.title, []).append(s)
    out: List[Tuple[str, str, str, str, str, str]] = []
    seen: Set[Tuple[str, str, str]] = set()
    for title, rows in by_title.items():
        if kb_sector._slug(title) in base_slugs:
            continue
        docs = [d for d in (doc_id_for(title), doc_id_for(f"{title} 시행령")) if d in have_docs]
        if not docs:
            continue
        words: List[Tuple[str, str]] = [(title, "정식 이름")]
        if abbr.get(kb_sector._slug(title)):
            words.append((abbr[kb_sector._slug(title)], "약칭"))
        for s in rows:
            words += [(w, "업 이름") for w in _split_words(s.words)]
        for shown, source in words:
            word = kb_search.norm_word(shown)
            if len(word) < MIN_WORD:
                continue
            for s in rows:
                for d in docs:
                    key = (word, d, s.sector_code)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append((word, shown, d, s.sector_code, s.sector, source))
    return out


def build(year: int = 2026, *, quiet: bool = False) -> Dict[str, int]:
    """섹터 법령 그해 판을 앱 근거 DB 에 넣고 분류 낱말 표를 다시 만든다."""
    conn = kb_law.connect()
    conn.executescript(WORD_SCHEMA)
    base_slugs = {kb_sector._slug(r[0]) for r in conn.execute(
        "SELECT DISTINCT title FROM kb_document WHERE doc_id NOT LIKE ?", (DOC_PREFIX + "%",))}
    sconn = kb_sector.connect()
    replay = kb_law.RawReplay(sconn)
    stats = {"docs": 0, "changed": 0, "chunks": 0, "articles": 0, "skipped_dup": 0, "failed": 0, "removed": 0, "words": 0}
    rows = sconn.execute("SELECT c.title, c.as_of, c.source_id, c.effective_at, d.dept FROM ks_choice c "
                         "LEFT JOIN ks_doc d ON d.title = c.title WHERE c.year=? ORDER BY c.title", (year,)).fetchall()
    keep: Set[str] = set()
    for title, as_of, source_id, effective_at, dept in rows:
        if kb_sector._slug(title) in base_slugs:
            stats["skipped_dup"] += 1
            continue
        spec = kb_law.DocSpec(doc_id=doc_id_for(title), title=title, kind="law", grade=1)
        try:
            versions = kb_sector.law_versions_all(replay, title, kb_sector_exp.OLDEST_AS_OF)
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
        # 이 판의 옛 조각 색인을 섹터 색인에서 먼저 지운다 — store_version 은 근거 문서 색인(kb_chunk_fts)만 지우고
        # 새 rid 로 다시 넣는다(옛 rid 가 섹터 색인에 남으면 나중에 같은 rid 를 받은 다른 조각에 잘못 붙는다)
        _drop_sector_fts(conn, _rids(conn, spec.doc_id, chosen.label))
        n, changed = kb_law.store_version(conn, spec, chosen, title, dept or "", chunks, len(used), sha, as_of,
                                          f"섹터 법령 {year} 판(kb_sector_link · 섹터 질문일 때만 찾는다) — "
                                          + " / ".join(notes), "")
        _move_to_sector_fts(conn, _rids(conn, spec.doc_id, chosen.label))
        keep.add(spec.doc_id)
        stats["docs"] += 1
        stats["changed"] += int(changed)
        stats["articles"] += len(used)
        stats["chunks"] += n
        if not quiet and stats["docs"] % 20 == 0:
            print(f"  문서 {stats['docs']} · 조각 {stats['chunks']:,}", flush=True)
    # 표에서 빠진 섹터 법령은 지운다 — 이번에 하나도 못 넣었으면 지우지 않는다(받기 실패를 「빠짐」 으로 읽지 않게)
    if keep:
        stale = [r[0] for r in conn.execute("SELECT DISTINCT doc_id FROM kb_document WHERE doc_id LIKE ?",
                                            (DOC_PREFIX + "%",)) if r[0] not in keep]
        for d in stale:
            remove_doc(conn, d)
        stats["removed"] = len(stale)
    stats["fts_moved"], stats["fts_orphans"] = sweep_fts(conn)
    have_docs = {r[0] for r in conn.execute("SELECT DISTINCT doc_id FROM kb_document WHERE doc_id LIKE ?",
                                            (DOC_PREFIX + "%",))}
    words = word_rows(kb_sector.load_map(), official_abbr(sconn), have_docs, base_slugs)
    if words or not have_docs:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM kb_sector_word")
            conn.executemany("INSERT INTO kb_sector_word(word, shown, doc_id, sector_code, sector, source) "
                             "VALUES (?,?,?,?,?,?)", words)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    stats["words"] = len(words)
    conn.close()
    sconn.close()
    return stats


def _rids(conn: sqlite3.Connection, doc_id: str, label: str) -> List[int]:
    return [r[0] for r in conn.execute("SELECT rid FROM kb_chunk WHERE doc_id=? AND version_label=?", (doc_id, label))]


def _drop_sector_fts(conn: sqlite3.Connection, rids: Sequence[int]) -> None:
    conn.executemany(f"DELETE FROM {SECTOR_FTS} WHERE rowid=?", [(r,) for r in rids])


def _move_to_sector_fts(conn: sqlite3.Connection, rids: Sequence[int]) -> int:
    """근거 문서 색인(kb_chunk_fts)에 들어간 섹터 조각의 행을 섹터 색인으로 옮긴다 → 옮긴 행 수."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        n = 0
        for i in range(0, len(rids), 500):
            part = list(rids[i:i + 500])
            marks = ",".join("?" * len(part))
            got = conn.execute(f"SELECT rowid, grams FROM kb_chunk_fts WHERE rowid IN ({marks})", part).fetchall()
            conn.executemany(f"DELETE FROM {SECTOR_FTS} WHERE rowid=?", [(r[0],) for r in got])
            conn.executemany(f"INSERT INTO {SECTOR_FTS}(rowid, grams) VALUES (?, ?)", [(r[0], r[1]) for r in got])
            conn.executemany("DELETE FROM kb_chunk_fts WHERE rowid=?", [(r[0],) for r in got])
            n += len(got)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return n


def sweep_fts(conn: sqlite3.Connection) -> Tuple[int, int]:
    """두 색인을 맞춘다 → (근거 문서 색인에 남아 있던 섹터 조각을 옮긴 수, 섹터 색인의 떠돌이 행을 지운 수)."""
    sec_rids = [r[0] for r in conn.execute("SELECT rid FROM kb_chunk WHERE doc_id LIKE ?", (DOC_PREFIX + "%",))]
    moved = _move_to_sector_fts(conn, sec_rids)
    live = set(sec_rids)
    orphans = [r[0] for r in conn.execute(f"SELECT rowid FROM {SECTOR_FTS}") if r[0] not in live]
    _drop_sector_fts(conn, orphans)
    return moved, len(orphans)


def remove_doc(conn: sqlite3.Connection, doc_id: str) -> None:
    """섹터 문서 하나를 근거 DB 에서 지운다(조각 · 낱말 색인 · 판). 벡터 점은 다음 `kb_index.run` 의 prune 이 치운다."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        rids = [r[0] for r in conn.execute("SELECT rid FROM kb_chunk WHERE doc_id=?", (doc_id,))]
        conn.executemany("DELETE FROM kb_chunk_fts WHERE rowid=?", [(r,) for r in rids])
        conn.executemany(f"DELETE FROM {SECTOR_FTS} WHERE rowid=?", [(r,) for r in rids])
        conn.execute("DELETE FROM kb_chunk WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM kb_document WHERE doc_id=?", (doc_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ==================================================
# 3. 벡터 — 실험 컬렉션에서 옮기기 + 나머지 임베딩
# ==================================================
def _cos(a: Sequence[float], b: Sequence[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def reuse_vectors(conn: sqlite3.Connection, model: kb_text.EmbedModel, docs: Sequence[str],
                  batch: int = 128) -> int:
    """실험(`kb_exp_sector.sqlite3` · `kb_v1_sector`)이 같은 조각 · 같은 본문 지문 · 같은 모델로 넣은 벡터를 `kb_v1` 로 옮긴다."""
    if not kb_sector_exp.EXP_DB.exists():
        print("  실험 DB 가 없다 — 옮기지 않고 새로 임베딩한다", flush=True)
        return 0
    exp = sqlite3.connect(f"file:{kb_sector_exp.EXP_DB}?mode=ro", uri=True)
    exp_sha = dict(exp.execute(
        "SELECT v.chunk_id, v.text_sha256 FROM kb_vector v JOIN kb_chunk k ON k.chunk_id=v.chunk_id "
        "AND k.text_sha256=v.text_sha256 WHERE v.model=? AND k.doc_id LIKE ?", (model.name, DOC_PREFIX + "%")))
    exp.close()
    rows = [r for r in kb_index.pending(conn, model, docs) if exp_sha.get(r["chunk_id"]) == r["text_sha256"]]
    base = kb_index.QDRANT_URL
    moved = 0
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        ids = [kb_text.point_id(r["chunk_id"]) for r in part]
        got = kb_index._http("POST", f"{base}/collections/{kb_sector_exp.EXP_COLLECTION}/points",
                             {"ids": ids, "with_vector": [model.vector], "with_payload": False})["result"]
        vec = {str(p["id"]): (p.get("vector") or {}).get(model.vector) for p in got}
        pts, done = [], []
        for r, pid in zip(part, ids):
            v = vec.get(str(pid))
            if v and len(v) == model.dim:
                pts.append({"id": pid, "vector": {model.vector: v}, "payload": kb_index._payload(r)})
                done.append(r)
        if pts:
            kb_index._http("PUT", f"{base}/collections/{kb_text.KB_COLLECTION}/points?wait=true", {"points": pts})
            now = kb_law.now_kst()
            conn.executemany("INSERT OR REPLACE INTO kb_vector(chunk_id, model, text_sha256, dim, indexed_at) "
                             "VALUES (?,?,?,?,?)", [(r["chunk_id"], model.name, r["text_sha256"], model.dim, now)
                                                    for r in done])
        moved += len(done)
    return moved


def spot_check(conn: sqlite3.Connection, model: kb_text.EmbedModel, docs: Sequence[str], n: int = 4) -> List[float]:
    """옮긴 벡터를 지금 다시 임베딩한 것과 견준다 — 코사인(1 에 가까워야 같은 글 · 같은 모델)."""
    rows = conn.execute(
        f"SELECT c.chunk_id, c.text FROM kb_chunk c JOIN kb_vector v ON v.chunk_id=c.chunk_id AND v.model=? "
        f"AND v.text_sha256=c.text_sha256 WHERE c.doc_id IN ({','.join('?' * len(docs))})",
        [model.name, *docs]).fetchall()
    if not rows:
        return []
    pick = random.Random(20261006).sample(rows, min(n, len(rows)))
    fresh = kb_index.embed(model, [r["text"] for r in pick], model.doc_prefix)
    got = kb_index._http("POST", f"{kb_index.QDRANT_URL}/collections/{kb_text.KB_COLLECTION}/points",
                         {"ids": [kb_text.point_id(r["chunk_id"]) for r in pick], "with_vector": [model.vector],
                          "with_payload": False})["result"]
    stored = {str(p["id"]): p["vector"][model.vector] for p in got}
    return [round(_cos(f, stored[str(kb_text.point_id(r["chunk_id"]))]), 6) for r, f in zip(pick, fresh)]


def vectors(model_name: str = kb_text.DEFAULT_EMBED_MODEL, *, reuse: bool = True, batch: int = 8) -> int:
    model = kb_text.EMBED_MODELS[model_name]
    conn = kb_law.connect()
    docs = [r[0] for r in conn.execute("SELECT DISTINCT doc_id FROM kb_document WHERE doc_id LIKE ? ORDER BY 1",
                                       (DOC_PREFIX + "%",))]
    if not docs:
        print("  섹터 법령이 근거 DB 에 없다 — python -m collector.kb_sector_link build", flush=True)
        return 1
    kb_index.ensure_collection()
    left = len(kb_index.pending(conn, model, docs))
    print(f"― 섹터 법령 벡터 {model.name} · 문서 {len(docs)} · 넣을 조각 {left:,} ―", flush=True)
    if reuse and left:
        t0 = time.time()
        moved = reuse_vectors(conn, model, docs)
        print(f"  실험 컬렉션 {kb_sector_exp.EXP_COLLECTION} 에서 옮김 {moved:,} · {time.time() - t0:.0f}초", flush=True)
        cos = spot_check(conn, model, docs)
        if cos:
            print(f"  옮긴 벡터 ↔ 지금 임베딩 코사인 {', '.join(f'{c:.6f}' for c in cos)}", flush=True)
    conn.close()
    return kb_index.run(model_name, docs, batch, None)


# ==================================================
# 4. 상태
# ==================================================
def status() -> None:
    conn = kb_law.connect()
    conn.executescript(WORD_SCHEMA)
    n_doc, n_chunk = conn.execute("SELECT COUNT(DISTINCT doc_id), COALESCE(SUM(chunks), 0) FROM kb_document "
                                  "WHERE doc_id LIKE ?", (DOC_PREFIX + "%",)).fetchone()
    vec = {name: conn.execute("SELECT COUNT(*) FROM kb_vector v JOIN kb_chunk c ON c.chunk_id=v.chunk_id AND "
                              "c.text_sha256=v.text_sha256 WHERE v.model=? AND c.doc_id LIKE ?",
                              (name, DOC_PREFIX + "%")).fetchone()[0] for name in kb_text.EMBED_MODELS}
    words = conn.execute("SELECT source, COUNT(DISTINCT word) FROM kb_sector_word GROUP BY source").fetchall()
    sectors = conn.execute("SELECT COUNT(DISTINCT sector_code) FROM kb_sector_word").fetchone()[0]
    n_fts = conn.execute(f"SELECT COUNT(*) FROM {SECTOR_FTS}").fetchone()[0]
    leak = conn.execute("SELECT COUNT(*) FROM kb_chunk_fts f JOIN kb_chunk k ON k.rid=f.rowid WHERE k.doc_id LIKE ?",
                        (DOC_PREFIX + "%",)).fetchone()[0]
    print(f"섹터 법령 — 문서 {n_doc} · 조각 {n_chunk:,} · 벡터 " + " · ".join(f"{m} {v:,}" for m, v in vec.items()))
    print(f"낱말 색인 — 섹터 색인 {n_fts:,}행 · 근거 문서 색인에 섞인 섹터 조각 {leak:,}(0 이어야 기존 질문의 bm25 가 그대로)")
    print(f"분류 낱말 — 섹터 {sectors} · " + " · ".join(f"{s} {n}" for s, n in words))
    conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.kb_sector_link", description="섹터 법령 → 앱 근거 DB")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="그해 판 조각 + 분류 낱말 표")
    b.add_argument("--year", type=int, default=2026)
    v = sub.add_parser("vectors", help="벡터 — 실험 컬렉션에서 옮기고 나머지만 임베딩")
    v.add_argument("--model", default=kb_text.DEFAULT_EMBED_MODEL, choices=sorted(kb_text.EMBED_MODELS))
    v.add_argument("--no-reuse", action="store_true", help="옮기지 않고 모두 새로 임베딩")
    sub.add_parser("status")
    a = p.parse_args(argv)
    if a.cmd == "build":
        t0 = time.time()
        s = build(a.year)
        print(f"  끝 — 섹터 법령 {s['docs']}문서(바뀜 {s['changed']}) · 조 {s['articles']:,} · 조각 {s['chunks']:,} · "
              f"겹쳐서 뺀 문서 {s['skipped_dup']} · 지운 문서 {s['removed']} · 분류 낱말 {s['words']:,}줄 · 실패 {s['failed']} · "
              f"색인 정리(옮김 {s['fts_moved']} · 떠돌이 {s['fts_orphans']}) · {time.time() - t0:.0f}초", flush=True)
        return 0 if not s["failed"] else 1
    if a.cmd == "vectors":
        try:
            return vectors(a.model, reuse=not a.no_reuse)
        except kb_index.IndexError_ as e:
            print(f"🔴 {e}")
            return 1
    status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
