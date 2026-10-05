"""수집 자료 검색 색인 — 공시 · 뉴스를 한 파일에 모아 이름표와 낱말 색인을 단다 (목표 기능 ① W7 · 설계서 5.1.6 · 5.1.7).

왜 수집 DB(market.sqlite3) 밖에 두나
------------------------------------
이름표와 낱말 색인은 **계산한 것**이다. 규칙(``collector/tagging.py``)을 고치면 통째로 다시 만든다. 받은 것을
담는 수집 DB 에 섞으면 HF 백업 대상(스캐너가 표를 빠짐없이 센다 · TC-HF-01)과 「받은 것 · 계산한 것을 섞지
않는다」(``collector/db.py`` 머리말)가 함께 흐려진다. 그래서 ``data/collector/search.sqlite3`` 에 따로 두고,
지워도 ``python -m collector.search_index build --full`` 로 되살린다.

앱(``GET /api/data/search`` · ``app/services/data_search.py``)은 이 파일을 **읽기만** 한다.

표 넷
-----
``doc``      문서 한 건 — 공시(D:접수번호) · 뉴스(N:주소 지문). 제목 · 요약 · 원문 주소 · 게시일 · 출처 · 회사
``doc_tag``  이름표(종목 · 주제 · 용어 · 공시 유형) — ``tagging.py``
``doc_fts``  낱말 색인(FTS5) — 제목 · 요약의 한글 두 글자 묶음 + 영문 낱말(근거 문서와 같은 규칙 ``kb_text.grams``)
``meta``     만든 시각 · 규칙 지문 · 원본별 마지막으로 반영한 시각

갱신
----
``build``        원본에서 그 뒤로 바뀐 행만 더하거나 고친다(공시는 updated_at · 뉴스는 fetched_at).
                 규칙 지문(이름표 규칙 · 용어사전 파일)이 바뀌었으면 저절로 통째로 다시 만든다.
``build --full`` 통째로 다시 만든다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from collector import config, db, tagging
from collector.console import utf8_stdio

sys.path.insert(0, str(config.ROOT))
from app.services import kb_text  # noqa: E402  — 앱과 같은 낱말 규칙

SEARCH_DB_PATH = config.DATA_DIR / "search.sqlite3"

#: 공시 뷰어 주소 — 개발가이드가 안내하는 꼴(접수번호 하나로 열린다)
DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS doc (
    rid         INTEGER PRIMARY KEY,            -- 낱말 색인의 rowid
    doc_id      TEXT    NOT NULL UNIQUE,        -- D:접수번호 · N:주소 지문
    kind        TEXT    NOT NULL,               -- disclosure | news
    title       TEXT    NOT NULL,
    summary     TEXT    NOT NULL DEFAULT '',    -- 공시는 꼬리 설명 · 뉴스는 검색 API 요약(본문 아님)
    url         TEXT    NOT NULL DEFAULT '',
    published   TEXT    NOT NULL,               -- YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM(+09:00)
    source      TEXT    NOT NULL,               -- dart · naver
    corp_name   TEXT    NOT NULL DEFAULT '',
    stock_code  TEXT    NOT NULL DEFAULT '',
    extra       TEXT    NOT NULL DEFAULT '{{}}'  -- JSON — 공시 유형 · 정정 · 기간 · 검색어 …
);
CREATE INDEX IF NOT EXISTS ix_doc_pub ON doc(published);
CREATE INDEX IF NOT EXISTS ix_doc_kind_pub ON doc(kind, published);
CREATE TABLE IF NOT EXISTS doc_tag (
    rid         INTEGER NOT NULL,
    tag_type    TEXT    NOT NULL,               -- symbol · topic · term · dtype
    tag         TEXT    NOT NULL,
    method      TEXT    NOT NULL,
    PRIMARY KEY (rid, tag_type, tag)
);
CREATE INDEX IF NOT EXISTS ix_tag ON doc_tag(tag_type, tag, rid);
CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(grams, tokenize="{kb_text.FTS_TOKENIZE}");
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or SEARCH_DB_PATH, timeout=60, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    # ⚠️ WAL 로 두지 않는다(DF-67 · 2026-10-04) — 도커 앱은 data/ 를 읽기 전용으로 붙여 이 파일을 연다. WAL 파일은
    #    읽을 때도 보조 파일(-shm)이 있어야 하는데, 만든 뒤 닫으면 그 파일이 지워져 「unable to open database file」 이
    #    났다(수집 DB · 근거 문서 DB 는 -shm 이 남아 있어 우연히 열렸다). 롤백 저널이면 보조 파일 없이 읽힌다.
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def files_fingerprint(paths: Sequence[Path]) -> str:
    """파일들의 지문 — 줄 끝(CRLF · LF)은 접어서 낸다(DF-68).

    Windows 의 `core.autocrlf=true` 는 저장소의 LF 파일을 작업 트리에 CRLF 로 내놓는다. 바이트 그대로 해시하면 규칙이
    그대로인데도 pull · 브랜치 바꾸기만으로 지문이 바뀌어 색인을 통째로 다시 만든다(2026-10-05 12:30 회차 447초).
    """
    h = hashlib.sha256()
    for p in paths:
        try:
            h.update(Path(p).read_bytes().replace(b"\r\n", b"\n"))
        except OSError:
            h.update(b"-")
    return h.hexdigest()[:16]


def rules_fingerprint() -> str:
    """이름표 규칙의 지문 — 규칙 파일 · 용어사전 파일 · 이 파일의 글이 바뀌면 달라진다(줄 끝은 보지 않는다)."""
    return files_fingerprint((Path(tagging.__file__), tagging.GLOSSARY_PATH, Path(__file__)))


def _meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))


def iso_day(yyyymmdd: str) -> str:
    s = (yyyymmdd or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s


# ==================================================
# 1. 공시 → 문서
# ==================================================
def disclosure_doc(row: Dict) -> Dict:
    """``disclosure`` 한 행 → 문서. 요약 칸에는 꼬리 설명(보고서 이름 뒤 괄호)만 둔다 — 본문은 받지 않는다."""
    report_nm = row["report_nm"] or ""
    title = row["title"] or report_nm
    tail = report_nm
    if row.get("revision"):
        tail = tail.split("]", row["revision"].count("·") + 1)[-1]
    tail = tail.strip()
    summary = tail[len(title):].strip() if tail.startswith(title) else ""
    extra = {k: row[k] for k in ("pblntf_ty", "revision", "period", "corp_cls", "flr_nm", "rm") if row.get(k)}
    extra.update(rcept_no=row["rcept_no"], corp_code=row.get("corp_code") or "", title=title)
    return {
        "doc_id": f"D:{row['rcept_no']}",
        "kind": "disclosure",
        "title": report_nm,
        "summary": summary,
        "url": DART_VIEWER.format(rcept_no=row["rcept_no"]),
        "published": iso_day(row["rcept_dt"]),
        "source": "dart",
        "corp_name": row.get("corp_name") or "",
        "stock_code": row.get("stock_code") or "",
        "extra": json.dumps(extra, ensure_ascii=False),
    }


def news_doc(row: Dict) -> Dict:
    """``news_item`` 한 행 → 문서(제목 · 요약 · 주소만 — 본문은 저장하지 않는다)."""
    extra = {k: row[k] for k in ("query", "originallink", "press") if row.get(k)}
    return {
        "doc_id": f"N:{row['news_id']}",
        "kind": "news",
        "title": row["title"],
        "summary": row.get("description") or "",
        "url": row.get("originallink") or row.get("link") or "",
        "published": row["pub_at"],
        "source": row.get("source") or "naver",
        "corp_name": "",
        "stock_code": "",
        "extra": json.dumps(extra, ensure_ascii=False),
    }


_DOC_COLS = ("doc_id", "kind", "title", "summary", "url", "published", "source", "corp_name", "stock_code", "extra")


def put_doc(conn: sqlite3.Connection, d: Dict, tags: Sequence[Tuple[str, str, str]]) -> int:
    """문서 한 건을 넣거나 고친다 — 이름표 · 낱말 색인도 함께. rid 를 돌려준다."""
    row = conn.execute("SELECT rid FROM doc WHERE doc_id=?", (d["doc_id"],)).fetchone()
    if row:
        rid = row[0]
        conn.execute(f"UPDATE doc SET {', '.join(f'{c}=?' for c in _DOC_COLS[1:])} WHERE rid=?",
                     tuple(d[c] for c in _DOC_COLS[1:]) + (rid,))
        conn.execute("DELETE FROM doc_tag WHERE rid=?", (rid,))
        conn.execute("DELETE FROM doc_fts WHERE rowid=?", (rid,))
    else:
        cur = conn.execute(f"INSERT INTO doc ({', '.join(_DOC_COLS)}) VALUES ({', '.join('?' * len(_DOC_COLS))})",
                           tuple(d[c] for c in _DOC_COLS))
        rid = cur.lastrowid
    seen = set()
    for t in tags:
        if (t[0], t[1]) in seen:
            continue
        seen.add((t[0], t[1]))
        conn.execute("INSERT INTO doc_tag (rid, tag_type, tag, method) VALUES (?, ?, ?, ?)", (rid, t[0], t[1], t[2]))
    words = f"{d['title']} {d['summary']} {d['corp_name']}"
    conn.execute("INSERT INTO doc_fts (rowid, grams) VALUES (?, ?)", (rid, kb_text.grams_text(words)))
    return rid


# ==================================================
# 2. 만들기
# ==================================================
def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def name_pairs(src: sqlite3.Connection) -> List[Tuple[str, str]]:
    """종목 이름 사전 재료 — 가장 최근 시세 날의 종목 이름 + 공시에 나온 회사 이름(상장폐지 포함)."""
    pairs: Dict[str, str] = {}
    last = src.execute("SELECT MAX(bas_dt) FROM price_daily").fetchone()[0]
    if last:
        for r in src.execute("SELECT srtn_cd, itms_nm FROM price_daily WHERE bas_dt=?", (last,)):
            if r[1]:
                pairs[r[1]] = r[0]
    if _has_table(src, "disclosure"):
        for r in src.execute("SELECT stock_code, corp_name FROM disclosure WHERE stock_code<>'' "
                             "GROUP BY stock_code, corp_name"):
            if r[1]:
                pairs.setdefault(r[1], r[0])
    return [(code, name) for name, code in pairs.items()]


def build(*, full: bool = False, quiet: bool = False, src_path: Optional[Path] = None,
          out_path: Optional[Path] = None, batch: int = 5000) -> Dict[str, int]:
    """원본(수집 DB)에서 문서를 모아 색인을 만든다. 넣거나 고친 문서 수를 돌려준다."""
    t0 = time.time()
    src = db.connect(src_path) if src_path else db.connect()
    conn = connect(out_path)
    fp = rules_fingerprint()
    if not full and _meta(conn, "rules") != fp:
        full = True
        if not quiet:
            print("이름표 규칙이 바뀌었다 — 통째로 다시 만든다")
    if full:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM doc_tag")
        conn.execute("DELETE FROM doc")
        conn.execute("DELETE FROM doc_fts")
        conn.execute("DELETE FROM meta")
        conn.execute("COMMIT")
    terms = tagging.load_terms()
    out = {"disclosure": 0, "news": 0}

    if _has_table(src, "disclosure"):
        since = _meta(conn, "disclosure_updated_at")
        # 「>=」 — 같은 초에 늦게 들어온 행을 놓치지 않게 마지막 초는 다시 본다(다시 넣어도 같은 문서로 고쳐질 뿐)
        cur = src.execute("SELECT * FROM disclosure WHERE updated_at >= ? ORDER BY updated_at, rcept_no", (since,))
        last = since
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            conn.execute("BEGIN IMMEDIATE")
            for r in rows:
                d = dict(r)
                put_doc(conn, disclosure_doc(d), tagging.disclosure_tags(d, terms))
                last = max(last, d["updated_at"])
            _set_meta(conn, "disclosure_updated_at", last)
            conn.execute("COMMIT")
            out["disclosure"] += len(rows)
            if not quiet and out["disclosure"] % (batch * 20) == 0:
                print(f"  공시 {out['disclosure']:,}건 …", flush=True)

    if _has_table(src, "news_item"):
        names = tagging.build_name_dict(name_pairs(src))
        since = _meta(conn, "news_fetched_at")
        cur = src.execute("SELECT * FROM news_item WHERE fetched_at >= ? ORDER BY fetched_at, news_id", (since,))
        last = since
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            conn.execute("BEGIN IMMEDIATE")
            for r in rows:
                d = dict(r)
                put_doc(conn, news_doc(d), tagging.news_tags(d, names, terms, d.get("query_symbol") or None))
                last = max(last, d["fetched_at"])
            _set_meta(conn, "news_fetched_at", last)
            conn.execute("COMMIT")
            out["news"] += len(rows)

    conn.execute("BEGIN IMMEDIATE")
    _set_meta(conn, "rules", fp)
    _set_meta(conn, "built_at", time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.localtime()))
    total = conn.execute("SELECT COUNT(*) FROM doc").fetchone()[0]
    _set_meta(conn, "docs", str(total))
    conn.execute("COMMIT")
    if full:
        conn.execute("INSERT INTO doc_fts(doc_fts) VALUES('optimize')")
    conn.close()
    src.close()
    if not quiet:
        print(f"검색 색인 — 공시 {out['disclosure']:,} · 뉴스 {out['news']:,}건 넣거나 고침 · 문서 {total:,}건 · "
              f"{time.time() - t0:.1f}초 → {out_path or SEARCH_DB_PATH}")
    return out


def print_status() -> None:
    if not SEARCH_DB_PATH.exists():
        print("검색 색인 없음 — python -m collector.search_index build")
        return
    conn = connect()
    print(f"검색 색인 {SEARCH_DB_PATH} · {SEARCH_DB_PATH.stat().st_size / 1e6:.1f}MB · 만든 때 {_meta(conn, 'built_at')}")
    for r in conn.execute("SELECT kind, COUNT(*), MIN(published), MAX(published) FROM doc GROUP BY kind"):
        print(f"  {r[0]} {r[1]:,}건 · {r[2]} ~ {r[3]}")
    for r in conn.execute("SELECT tag_type, COUNT(*), COUNT(DISTINCT tag) FROM doc_tag GROUP BY tag_type"):
        print(f"  이름표 {r[0]} {r[1]:,}개 · 서로 다른 {r[2]:,}")
    top = conn.execute("SELECT tag, COUNT(*) n FROM doc_tag WHERE tag_type='topic' GROUP BY tag ORDER BY n DESC").fetchall()
    print("  주제: " + " · ".join(f"{t[0]} {t[1]:,}" for t in top))
    conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.search_index",
                                description="수집 자료(공시 · 뉴스) 검색 색인 — 이름표 · 낱말")
    p.add_argument("mode", choices=["build", "status"])
    p.add_argument("--full", action="store_true", help="통째로 다시 만든다")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)
    if a.mode == "status":
        print_status()
        return 0
    build(full=a.full, quiet=a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
