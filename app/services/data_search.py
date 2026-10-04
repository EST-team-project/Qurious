"""수집 자료 검색 — 공시 · 뉴스를 낱말 · 이름표로 찾는다 (API-DATA-03 · 목표 기능 ① W7 · 설계서 5.1.7).

`GET /api/data/search` 가 부른다. 수집기가 만든 검색 색인 `search.sqlite3`(`collector/search_index.py`)를
**읽기만** 한다 — 앱은 수집 DB 에 쓰지 않는다(설계서 4.1).

찾는 법
  - 검색어는 띄어쓴 낱말마다 「구절」 로 찾는다. 낱말 안의 한글은 두 글자 묶음(근거 문서와 같은 `kb_text.grams`)이
    이어져 있어야 맞으므로 「유상증자」 는 「주요사항보고서(유상증자결정)」 에 맞고 「유상 … 증자」 처럼 떨어진 글에는
    맞지 않는다. 낱말끼리는 모두 맞아야 한다(AND).
  - 이름표로 거른다 — 종목(6자리) · 주제(실적 · 배당 · 증자 …) · 용어(용어사전 id) · 공시 유형(A~J).
  - 기본 차례는 최신순이다. `sort=relevance` 면 낱말 점수(bm25) 순.

공시 요약 — 보고서 이름 · 핵심 숫자 · 주소
  공시 결과에는 수집 DB 에서 같은 공시의 숫자를 붙인다(읽기 전용) — 정기보고서는 그 기간의 매출액 · 영업이익 ·
  당기순이익(연결 먼저, 없으면 별도), 배당 공시는 1주당 배당금 · 배당 기준일. 숫자가 정정본에서 왔으면 그 접수번호를 함께 싣는다.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.services import collector_db, kb_text

KST = timezone(timedelta(hours=9))

ENV_SEARCH_DB = "COLLECTOR_SEARCH_DB_PATH"
SEARCH_DB_NAME = "search.sqlite3"

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_OFFSET = 5000
MAX_Q = 200
MAX_TERMS = 8
COUNT_CAP = 10000

KINDS = ("disclosure", "news")
SORTS = ("date", "relevance")
DTYPES = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J")

_HANGUL = re.compile(r"[가-힣]+")
_ASCII = re.compile(r"[A-Za-z0-9]+")
_SYMBOL = re.compile(r"^\d{6}$|^[0-9A-Z]{6}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: 정기보고서 요약에 싣는 계정 — 응답 이름 그대로(같은 뜻의 다른 이름을 함께 본다)
KEY_ACCOUNTS = (
    ("revenue", ("매출액", "수익(매출액)", "영업수익")),
    ("operating_income", ("영업이익", "영업이익(손실)")),
    ("net_income", ("당기순이익(손실)", "당기순이익")),
)


class SearchError(Exception):
    """고칠 수 있는 요청 잘못 — 상태 코드와 함께."""

    def __init__(self, status: int, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.status, self.code, self.message, self.hint = status, code, message, hint

    def detail(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        return d


def search_db_path() -> Path | None:
    """검색 색인 파일 — 환경 변수 → 수집 DB 와 같은 폴더(로컬 data/collector · 도커 data/csv/collector)."""
    env = os.environ.get(ENV_SEARCH_DB)
    if env:
        p = Path(env)
        return p if p.is_file() else None
    base = collector_db.db_path()
    if base is not None and (base.parent / SEARCH_DB_NAME).is_file():
        return base.parent / SEARCH_DB_NAME
    for cand in collector_db._DEFAULT_CANDIDATES:  # noqa: SLF001 — 수집 DB 와 같은 후보 폴더
        p = cand.parent / SEARCH_DB_NAME
        if p.is_file():
            return p
    return None


def _open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def match_expr(q: str) -> str:
    """검색어 → FTS5 MATCH 식. 낱말마다 한글 덩어리는 두 글자 묶음 구절, 영문 · 숫자는 그 낱말. 모두 AND."""
    parts: list[str] = []
    for tok in (q or "").split()[:MAX_TERMS]:
        for run in _HANGUL.findall(tok):
            g = kb_text.grams(run)
            if g:
                parts.append('"' + " ".join(x.replace('"', '""') for x in g) + '"')
        for word in _ASCII.findall(tok):
            g = kb_text.grams(word)
            if g:
                parts.append('"' + " ".join(x.replace('"', '""') for x in g) + '"')
    return " AND ".join(parts)


def _day(v: str | None, name: str) -> str | None:
    if v is None or v == "":
        return None
    if not _DAY.match(v):
        raise SearchError(422, "bad_date", f"{name} 는 YYYY-MM-DD 꼴이어야 합니다: {v!r}")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise SearchError(422, "bad_date", f"{name} 가 없는 날짜입니다: {v!r}") from None
    return v


def _next_day(v: str) -> str:
    return (date.fromisoformat(v) + timedelta(days=1)).isoformat()


def search(q: str = "", kind: str | None = None, symbol: str | None = None, topic: str | None = None,
           term: str | None = None, dtype: str | None = None, from_: str | None = None, to: str | None = None,
           sort: str = "date", limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict:
    q = (q or "").strip()
    if len(q) > MAX_Q:
        raise SearchError(422, "q_too_long", f"검색어는 {MAX_Q}자까지입니다(지금 {len(q)}자).")
    if kind and kind not in KINDS:
        raise SearchError(422, "bad_kind", f"kind 는 {' · '.join(KINDS)} 가운데 하나입니다: {kind!r}")
    if sort not in SORTS:
        raise SearchError(422, "bad_sort", f"sort 는 {' · '.join(SORTS)} 가운데 하나입니다: {sort!r}")
    if symbol and not _SYMBOL.match(symbol):
        raise SearchError(422, "bad_symbol", f"symbol 은 단축코드 6자리입니다: {symbol!r}")
    if dtype and dtype.upper() not in DTYPES:
        raise SearchError(422, "bad_dtype", f"dtype 은 공시 유형 글자 A~J 입니다: {dtype!r}")
    if not (1 <= limit <= MAX_LIMIT) or not (0 <= offset <= MAX_OFFSET):
        raise SearchError(422, "bad_page", f"limit 은 1~{MAX_LIMIT} · offset 은 0~{MAX_OFFSET} 입니다.")
    d_from, d_to = _day(from_, "from"), _day(to, "to")
    if d_from and d_to and d_from > d_to:
        raise SearchError(422, "bad_range", f"from({d_from}) 이 to({d_to}) 보다 늦습니다.")

    path = search_db_path()
    if path is None:
        raise SearchError(503, "no_index", "검색 색인이 아직 없습니다.",
                          "수집기에서 python -m collector.disclosure daily → python -m collector.search_index build 를 돌린다"
                          "(매일 12:30 러너의 search 단계가 만든다).")
    expr = match_expr(q)
    if q and not expr:
        raise SearchError(422, "no_terms", "검색어에서 찾을 낱말을 만들지 못했습니다(한글 두 글자 이상 또는 영문 · 숫자).")

    where, args = [], []
    if expr:
        where.append("d.rid IN (SELECT rowid FROM doc_fts WHERE doc_fts MATCH ?)")
        args.append(expr)
    if kind:
        where.append("d.kind = ?")
        args.append(kind)
    for tag_type, value in (("symbol", symbol), ("topic", topic), ("term", term),
                            ("dtype", dtype.upper() if dtype else None)):
        if value:
            where.append("d.rid IN (SELECT rid FROM doc_tag WHERE tag_type = ? AND tag = ?)")
            args += [tag_type, value]
    if d_from:
        where.append("d.published >= ?")
        args.append(d_from)
    if d_to:
        where.append("d.published < ?")
        args.append(_next_day(d_to))
    cond = (" WHERE " + " AND ".join(where)) if where else ""

    conn = _open_ro(path)
    try:
        if sort == "relevance" and expr:
            sql = ("SELECT d.*, bm25(doc_fts) AS score FROM doc d JOIN doc_fts ON doc_fts.rowid = d.rid"
                   + cond + " AND doc_fts MATCH ? ORDER BY score, d.published DESC LIMIT ? OFFSET ?")
            rows = conn.execute(sql, args + [expr, limit, offset]).fetchall()
        else:
            rows = conn.execute(f"SELECT d.* FROM doc d{cond} ORDER BY d.published DESC, d.rid DESC LIMIT ? OFFSET ?",
                                args + [limit, offset]).fetchall()
        n = conn.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM doc d{cond} LIMIT ?)", args + [COUNT_CAP + 1]).fetchone()[0]
        tags: dict[int, dict[str, list[str]]] = {}
        rids = [r["rid"] for r in rows]
        if rids:
            for t in conn.execute(f"SELECT rid, tag_type, tag FROM doc_tag WHERE rid IN ({','.join('?' * len(rids))})"
                                  " ORDER BY rid, tag_type, tag", rids):
                tags.setdefault(t["rid"], {}).setdefault(t["tag_type"], []).append(t["tag"])
        meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    except sqlite3.OperationalError as e:
        raise SearchError(503, "index_unreadable", f"검색 색인을 읽지 못했습니다: {e}",
                          "python -m collector.search_index build --full 로 다시 만든다") from None
    finally:
        conn.close()

    items = []
    for r in rows:
        extra = json.loads(r["extra"] or "{}")
        items.append({
            "doc_id": r["doc_id"], "kind": r["kind"], "title": r["title"], "summary": r["summary"],
            "url": r["url"], "published": r["published"], "source": r["source"],
            "corp_name": r["corp_name"], "stock_code": r["stock_code"],
            "tags": tags.get(r["rid"], {}), "extra": extra,
        })
    _attach_key_numbers(items)
    return {
        "items": items,
        "total": min(n, COUNT_CAP),
        "total_capped": n > COUNT_CAP,
        "query": {"q": q, "match": expr, "kind": kind, "symbol": symbol, "topic": topic, "term": term,
                  "dtype": dtype, "from": d_from, "to": d_to, "sort": sort, "limit": limit, "offset": offset},
        "index_built_at": meta.get("built_at"),
        "source": "전자공시(DART) 공시 목록 · 뉴스 검색 API(제목 · 요약만) — 수집기 검색 색인",
        "note": "본문은 저장하지 않는다. 원문은 url 로 연다. 이름표는 규칙으로 붙였다(정밀도 표본 판정 전).",
    }


# ── 공시 요약의 핵심 숫자 — 수집 DB 읽기 전용 ─────────────────────────────────
_PERIODIC = {"사업보고서": ("11011",), "반기보고서": ("11012",), "분기보고서": ("11013", "11014")}


def _attach_key_numbers(items: list[dict]) -> None:
    disc = [it for it in items if it["kind"] == "disclosure"]
    if not disc:
        return
    path = collector_db.db_path()
    if path is None:
        return
    try:
        conn = _open_ro(path)
    except sqlite3.Error:
        return
    try:
        has_fin = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='financial_statement'").fetchone()
        for it in disc:
            ex = it["extra"]
            title, period, corp = ex.get("title", ""), ex.get("period", ""), ex.get("corp_code", "")
            if has_fin and title in _PERIODIC and period and corp:
                it["key_numbers"] = _fin_numbers(conn, corp, _PERIODIC[title], period, ex.get("rcept_no", ""))
            elif "배당" in it["title"]:
                row = conn.execute("SELECT dps, record_dt, div_kind FROM dividend WHERE rcept_no = ? LIMIT 1",
                                   (ex.get("rcept_no", ""),)).fetchone()
                if row:
                    it["key_numbers"] = {"dps": row["dps"], "record_date": _iso(row["record_dt"]),
                                         "div_kind": row["div_kind"], "unit": "원"}
    except sqlite3.Error:
        return
    finally:
        conn.close()


def _iso(v: str | None) -> str | None:
    s = str(v or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else (s or None)


def _fin_numbers(conn: sqlite3.Connection, corp: str, reprt_codes: tuple, period: str, rcept_no: str) -> dict | None:
    """그 기간 보고서의 핵심 숫자 — 같은 접수번호 판이 있으면 그것, 없으면 그 기간의 가장 최근 판."""
    end_prefix = period.replace(".", "-")  # 2025.12 → 2025-12
    marks = ",".join("?" * len(reprt_codes))
    vers = conn.execute(
        f"SELECT DISTINCT rcept_no, known_at, fs_div FROM financial_statement WHERE corp_code = ? AND reprt_code IN ({marks})"
        " AND substr(period_end, 1, 7) = ? ORDER BY (rcept_no = ?) DESC, (fs_div = 'CFS') DESC, known_at DESC",
        (corp, *reprt_codes, end_prefix, rcept_no)).fetchall()
    if not vers:
        return None
    v = vers[0]
    out: dict = {"fs_div": v["fs_div"], "rcept_no": v["rcept_no"], "same_filing": v["rcept_no"] == rcept_no,
                 "unit": "원"}
    for key, names in KEY_ACCOUNTS:
        marks2 = ",".join("?" * len(names))
        row = conn.execute(
            f"SELECT thstrm_amount, thstrm_add_amount FROM financial_statement WHERE rcept_no = ? AND fs_div = ? "
            f"AND corp_code = ? AND sj_div = 'IS' AND account_nm IN ({marks2}) ORDER BY ord LIMIT 1",
            (v["rcept_no"], v["fs_div"], corp, *names)).fetchone()
        if row:
            out[key] = row["thstrm_amount"]
            if row["thstrm_add_amount"] is not None:
                out[key + "_cumulative"] = row["thstrm_add_amount"]
    return out


def status() -> dict:
    """색인 파일 상태(관제 화면 · 시험)."""
    path = search_db_path()
    if path is None:
        return {"ready": False}
    conn = _open_ro(path)
    try:
        meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
        kinds = {r[0]: r[1] for r in conn.execute("SELECT kind, COUNT(*) FROM doc GROUP BY kind")}
    finally:
        conn.close()
    return {"ready": True, "built_at": meta.get("built_at"), "docs": kinds}


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")
