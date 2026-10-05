"""근거 문서 — 섹터별 · 연도별 법령 (목표 기능 ① · 근거 문서를 산업(섹터)별 · 연도별로 · 2026-10-05).

    python -m collector.kb_sector fetch [--sectors He,IT] [--years 2020-2026] [--max-calls 1500]
    python -m collector.kb_sector status

섹터 — 우리 섹터 분류(GICS 11섹터 꼴 · 섹터 파일 2,622종목 · 2026-09-17)와 같은 코드 · 이름에 「공통」(All)을 더했다.
법령 — `collector/kb_data/sector_laws.tsv` 한 곳. 핵심 업법(role=업법)은 시행령까지(decree=Y), 관련 법은 법만.
근거 — 조사서 docs/조사/섹터별-근거법령-조사_v0.1.md(GICS 섹터 정의 원문 · 법령 API 로 정식 이름 · 소관 부처 · 제1조 확인).

해마다 그해 시행 판
------------------
기준일 = 그해 12월 31일(올해는 오늘). 그날 시행 중인 판(시행일 ≤ 기준일 중 시행일이 가장 늦은 판)을 고르고, 고른 판보다
뒤에 공포돼 기준일까지 시행된 판이 있으면 조마다 대조해 빠진 개정을 채운다 — 근거 문서 DB(`collector/kb_law.py`)와
같은 규칙 · 같은 함수(`kb_text.select_version` · `kb_law.check_later`). 한 해 안의 중간 판은 두지 않는다(연말 판 하나).

다시 받지 않는다
----------------
판 목록은 실행마다 새로 묻고(새 개정을 알아야 한다), 본문은 판(일련번호 · 시행일)마다 한 번만 받는다 — 받은 원문은
`kb_raw`(OC 를 지운 gzip)에 있다. 고른 판과 「뒤에 공포된 판」 지문이 지난번과 같으면 그 해는 건너뛴다.

어디에 두나 — `data/collector/kb_sector.sqlite3`. 근거 문서 DB(`kb.sqlite3` · 앱이 읽는 파일)와 나눈다 — 섹터 법령은
아직 근거 답에 넣지 않았고(색인 · 임베딩은 따로 정한다), 원문이 수백 MB 라 앱 DB 를 무겁게 하지 않으려고.
HF 보관은 `scripts/hf_sector_laws.py`(섹터 · 연도 파케이 · 매주 대조).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from collector import config, kb_law
from collector.console import utf8_stdio

sys.path.insert(0, str(config.ROOT))
from app.services import kb_text  # noqa: E402

DB_PATH = config.DATA_DIR / "kb_sector.sqlite3"
MAP_PATH = Path(__file__).resolve().parent / "kb_data" / "sector_laws.tsv"
FIRST_YEAR = 2020                     # 시세 · 공시와 같은 해부터
#: 섹터 코드 → 이름 — 섹터 파일(「개별 종목 섹터」 grid_20260917 · 섹터코드 · 섹터명 칸)과 같다 + 「공통」.
SECTOR_NAMES = {"En": "에너지", "Ma": "소재", "In": "산업", "CD": "임의소비재", "CS": "필수소비재", "He": "헬스케어",
                "Fi": "금융", "IT": "정보기술", "Co": "커뮤니케이션", "Ut": "유틸리티", "Re": "부동산", "All": "공통"}
SECTOR_CODES = tuple(SECTOR_NAMES)
ROLES = ("업법", "관련")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_raw (
    source      TEXT    NOT NULL,          -- law.go.kr
    target      TEXT    NOT NULL,          -- eflaw/search/<이름> · eflaw/<일련번호>/<시행일>
    fetched_at  TEXT    NOT NULL,
    body        BLOB    NOT NULL,          -- gzip(OC 를 지운 원문)
    sha256      TEXT    NOT NULL,
    bytes       INTEGER NOT NULL,
    PRIMARY KEY (source, target, fetched_at)
);
-- 문서 하나(법률 · 시행령) — 섹터 표와 판 목록에서
CREATE TABLE IF NOT EXISTS ks_doc (
    title       TEXT PRIMARY KEY,           -- 정식 이름(법령 목록과 띄어쓰기를 빼고 같다)
    parent      TEXT NOT NULL DEFAULT '',   -- 시행령이면 그 법률 이름
    law_type    TEXT NOT NULL DEFAULT '',   -- 법률 · 대통령령
    dept        TEXT NOT NULL DEFAULT '',   -- 소관 부처(가장 최근 고른 판의 기본 정보)
    n_versions  INTEGER NOT NULL DEFAULT 0, -- 받은 시행일 판 수(연혁 · 현행 · 시행예정) — 가장 이른 기준일 판이 나오면 쪽 넘기기를 멈추므로 전체보다 적을 수 있다
    listed_at   TEXT NOT NULL DEFAULT '',   -- 판 목록을 마지막으로 물은 시각 KST
    note        TEXT NOT NULL DEFAULT ''    -- 목록에 없음 · 기준일에 시행 전 …
);
-- 해마다 고른 판
CREATE TABLE IF NOT EXISTS ks_choice (
    title           TEXT NOT NULL,
    year            INTEGER NOT NULL,
    as_of           TEXT NOT NULL,          -- 기준일 YYYY-MM-DD(그해 12-31 · 올해는 받은 날)
    source_id       TEXT NOT NULL,          -- 법령일련번호(MST)
    effective_at    TEXT NOT NULL,          -- 시행일
    promulgation_no TEXT NOT NULL DEFAULT '',
    promulgated_at  TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT '',   -- 받을 때 표시: 현행 · 연혁
    later_sig       TEXT NOT NULL DEFAULT '',   -- 고른 판보다 뒤에 공포돼 기준일까지 시행된 판들의 이름 — 같으면 다시 안 본다
    n_articles      INTEGER NOT NULL DEFAULT 0, -- 삭제 조를 뺀 조 수
    content_sha256  TEXT NOT NULL DEFAULT '',   -- 조 글 전체의 지문(kb_text.text_sha256)
    notes           TEXT NOT NULL DEFAULT '',   -- 판 점검 기록(빠진 개정을 채운 조 등)
    chosen_at       TEXT NOT NULL,
    PRIMARY KEY (title, year)
);
-- 그해 판의 조 — 삭제된 조는 두지 않는다
CREATE TABLE IF NOT EXISTS ks_article (
    title   TEXT NOT NULL,
    year    INTEGER NOT NULL,
    seq     INTEGER NOT NULL,               -- 조 차례(0부터)
    label   TEXT NOT NULL,                  -- 제2조 · 제2조의2
    heading TEXT NOT NULL DEFAULT '',       -- 조 제목
    part    TEXT NOT NULL DEFAULT '',       -- 제1편 총칙 > 제2장 …
    text    TEXT NOT NULL,                  -- 조 글(머리 줄 · 항 · 호 · 목)
    PRIMARY KEY (title, year, seq)
);
"""


@dataclass(frozen=True)
class SectorLaw:
    sector_code: str
    sector: str
    title: str
    role: str
    decree: bool
    why: str


def load_map(path: Path = MAP_PATH) -> List[SectorLaw]:
    """섹터 표를 읽는다 — 칸 · 코드 · 역할이 틀리면 멈춘다(조용히 빠지는 줄이 없게)."""
    out: List[SectorLaw] = []
    with open(path, encoding="utf-8", newline="") as f:
        for i, r in enumerate(csv.DictReader(f, delimiter="\t"), 2):
            code, title, role, dec = (r.get("sector_code") or "").strip(), (r.get("title") or "").strip(), \
                (r.get("role") or "").strip(), (r.get("decree") or "").strip()
            if code not in SECTOR_CODES or not title or role not in ROLES or dec not in ("Y", "N") \
                    or (r.get("sector") or "").strip() != SECTOR_NAMES.get(code):
                raise ValueError(f"{path.name} {i}줄이 규칙에 맞지 않는다: {dict(r)}")
            out.append(SectorLaw(code, (r.get("sector") or "").strip(), title, role, dec == "Y",
                                 (r.get("why") or "").strip()))
    seen = set()
    for s in out:
        if (s.sector_code, s.title) in seen:
            raise ValueError(f"{path.name} 에 같은 섹터 · 법령이 두 번: {s.sector_code} {s.title}")
        seen.add((s.sector_code, s.title))
    return out


def documents(rows: Sequence[SectorLaw]) -> List[Tuple[str, str]]:
    """받을 문서 (이름, 부모 법률) — 법률은 한 번만, 시행령은 decree=Y 인 법률에서. 차례는 표 차례."""
    docs: Dict[str, str] = {}
    for s in rows:
        docs.setdefault(s.title, "")
    for s in rows:
        if s.decree:
            docs.setdefault(f"{s.title} 시행령", s.title)
    return list(docs.items())


def as_of_for(year: int, today: date) -> str:
    """그해 기준일 — 지난해들은 12월 31일, 올해는 오늘."""
    return today.isoformat() if year >= today.year else f"{year}-12-31"


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(path or DB_PATH, timeout=60, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    conn.executescript(SCHEMA)
    return conn


class CachedClient:
    """본문은 받아 둔 원문이 있으면 그것을, 없으면 법령 API 를 — 목록(`…/search/…`)은 늘 새로 묻는다."""

    def __init__(self, live, conn: sqlite3.Connection, max_calls: Optional[int] = None) -> None:
        self.live, self.conn, self.max_calls = live, conn, max_calls
        self.hits = 0

    @property
    def calls(self) -> int:
        return self.live.calls

    def get(self, path: str, params: Dict[str, str], target: str) -> dict:
        if "/search/" not in target:
            row = self.conn.execute("SELECT body FROM kb_raw WHERE source='law.go.kr' AND target=? "
                                    "ORDER BY fetched_at DESC LIMIT 1", (target,)).fetchone()
            if row is not None:
                self.hits += 1
                return json.loads(gzip.decompress(row[0]).decode("utf-8"))
        if self.max_calls is not None and self.live.calls >= self.max_calls:
            raise kb_law.LawApiError(f"이번 실행의 호출 상한 {self.max_calls:,}회 — 다시 돌리면 받은 것은 건너뛰고 이어 간다")
        return self.live.get(path, params, target)


def _slug(title: str) -> str:
    return re.sub(r"\s+", "", title)


#: 판 목록 쪽 넘기기 상한 — 한 쪽 100줄 · 법률 · 시행령 · 시행규칙이 섞여 와도 이 안에서 끝난다(안전장치).
MAX_PAGES = 30


def law_versions_all(client, title: str, oldest_as_of: str) -> List:
    """시행일 판 목록 — 가장 이른 기준일(`oldest_as_of`)에 시행 중인 판이 나올 때까지 쪽을 넘긴다.

    `kb_law.law_versions` 는 첫 쪽(100줄)만 본다. 목록에는 이름이 비슷한 시행령 · 시행규칙 판이 섞여 와서 법률 자체는
    최근 판만 남는다(2026-10-05 실측: 자동차관리법 첫 쪽 33판 · 가장 이른 시행일 2023-06-11 · 상법 7판 · 2025-01-31).
    근거 문서 DB 는 최신 판만 쓰니 첫 쪽으로 충분하지만, 연도별은 2020년 판까지 있어야 한다.
    """
    out: List = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        data = client.get("lawSearch.do", {"target": "eflaw", "type": "JSON", "query": title, "display": "100",
                                           "nw": "1,2,3", "sort": "efdes", "page": str(page)},
                          f"eflaw/search/{title}/p{page}")
        ls = data.get("LawSearch", {}) or {}
        rows = kb_law._as_list(ls.get("law"))
        for r in rows:
            if not kb_law._same_name(r.get("법령명한글", ""), title):
                continue
            v = kb_text.Version(source_id=str(r.get("법령일련번호", "")), promulgation_no=str(r.get("공포번호", "")),
                                promulgated_at=kb_law._iso(r.get("공포일자", "")), effective_at=kb_law._iso(r.get("시행일자", "")),
                                status=r.get("현행연혁코드", ""), law_type=r.get("법령구분명", ""),
                                change_kind=r.get("제개정구분명", ""))
            if (v.source_id, v.effective_at) not in seen:
                seen.add((v.source_id, v.effective_at))
                out.append(v)
        total = int(ls.get("totalCnt") or 0)
        if not rows or page * 100 >= total:
            break
        if any(v.effective_at and v.effective_at <= oldest_as_of for v in out):
            break                                  # 가장 이른 기준일에 시행 중인 판을 찾았다 — 더 옛 판은 필요 없다
    return out


def _later_sig(versions: Sequence, chosen, as_of: str) -> str:
    return ",".join(v.label for v in kb_text.later_promulgated(versions, chosen, as_of))


def fetch(conn: sqlite3.Connection, client, docs: Sequence[Tuple[str, str]], years: Sequence[int], today: date,
          *, quiet: bool = True) -> Dict[str, int]:
    """문서마다 판 목록 → 해마다 그해 시행 판 → (바뀐 해만) 본문 · 판 점검 → 조 저장."""
    out = {"docs": 0, "missing": 0, "years_new": 0, "years_same": 0, "not_in_force": 0}
    now = kb_law.now_kst()
    oldest = as_of_for(min(years), today) if years else today.isoformat()
    for title, parent in docs:
        versions = law_versions_all(client, title, oldest)
        out["docs"] += 1
        if not versions:
            out["missing"] += 1
            conn.execute("INSERT INTO ks_doc(title, parent, listed_at, note) VALUES (?,?,?,?) "
                         "ON CONFLICT(title) DO UPDATE SET listed_at=excluded.listed_at, note=excluded.note",
                         (title, parent, now, "법령 목록에 이름이 같은 문서가 없다"))
            if not quiet:
                print(f"  ✗ {title} — 목록에 없음", flush=True)
            continue
        spec = kb_law.DocSpec(doc_id=_slug(title), title=title, kind="law", grade=1)
        dept = law_type = ""
        for y in years:
            as_of = as_of_for(y, today)
            chosen = kb_text.select_version(versions, as_of)
            if chosen is None:
                out["not_in_force"] += 1
                conn.execute("DELETE FROM ks_choice WHERE title=? AND year=?", (title, y))
                conn.execute("DELETE FROM ks_article WHERE title=? AND year=?", (title, y))
                continue
            sig = _later_sig(versions, chosen, as_of)
            prev = conn.execute("SELECT source_id, effective_at, later_sig FROM ks_choice WHERE title=? AND year=?",
                                (title, y)).fetchone()
            if prev and (prev[0], prev[1], prev[2]) == (chosen.source_id, chosen.effective_at, sig):
                out["years_same"] += 1
                conn.execute("UPDATE ks_choice SET as_of=? WHERE title=? AND year=?", (as_of, title, y))
                continue
            info, arts = kb_law.fetch_body(client, spec, chosen)
            arts, notes = kb_law.check_later(client, spec, versions, chosen, arts, as_of)
            used = [a for a in arts if not a.deleted]
            sha = kb_text.text_sha256("\n\n".join(f"{a.label}\n{a.body}" for a in used))
            d = info.get("소관부처")
            dept = kb_law._join(d.get("content") if isinstance(d, dict) else d) or dept
            law_type = chosen.law_type or law_type
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("INSERT OR REPLACE INTO ks_choice(title, year, as_of, source_id, effective_at, promulgation_no, "
                             "promulgated_at, status, later_sig, n_articles, content_sha256, notes, chosen_at) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (title, y, as_of, chosen.source_id, chosen.effective_at, chosen.promulgation_no,
                              chosen.promulgated_at, chosen.status, sig, len(used), sha, " / ".join(notes), now))
                conn.execute("DELETE FROM ks_article WHERE title=? AND year=?", (title, y))
                conn.executemany("INSERT INTO ks_article(title, year, seq, label, heading, part, text) VALUES (?,?,?,?,?,?,?)",
                                 [(title, y, i, a.label, a.title, a.part, a.body) for i, a in enumerate(used)])
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            out["years_new"] += 1
        conn.execute("INSERT INTO ks_doc(title, parent, law_type, dept, n_versions, listed_at, note) VALUES (?,?,?,?,?,?,'') "
                     "ON CONFLICT(title) DO UPDATE SET parent=excluded.parent, "
                     "law_type=CASE WHEN excluded.law_type<>'' THEN excluded.law_type ELSE ks_doc.law_type END, "
                     "dept=CASE WHEN excluded.dept<>'' THEN excluded.dept ELSE ks_doc.dept END, "
                     "n_versions=excluded.n_versions, listed_at=excluded.listed_at, note=''",
                     (title, parent, law_type, dept, len(versions), now))
        if not quiet:
            n = conn.execute("SELECT COUNT(*) FROM ks_choice WHERE title=?", (title,)).fetchone()[0]
            print(f"  ✓ {title} · 판 {len(versions)} · 해 {n} · 호출 누적 {client.calls}", flush=True)
    return out


def parse_years(text: str, today: date) -> List[int]:
    if not text:
        return list(range(FIRST_YEAR, today.year + 1))
    a, _, b = text.partition("-")
    return list(range(int(a), int(b or a) + 1))


def cmd_fetch(a) -> int:
    rows = load_map()
    if a.sectors:
        want = set(a.sectors.split(","))
        rows = [r for r in rows if r.sector_code in want]
    docs = documents(rows)
    today = date.today()
    years = parse_years(a.years, today)
    conn = connect()
    client = CachedClient(kb_law.LawClient(conn=conn), conn, max_calls=a.max_calls)
    try:
        r = fetch(conn, client, docs, years, today, quiet=a.quiet)
    finally:
        conn.close()
    print(f"  문서 {r['docs']}(목록에 없음 {r['missing']}) · 해 새로 {r['years_new']} · 그대로 {r['years_same']} · "
          f"시행 전 {r['not_in_force']} · 호출 {client.calls} · 받아 둔 원문 씀 {client.hits}")
    return 0


def cmd_status(_a) -> int:
    conn = connect()
    try:
        docs = conn.execute("SELECT COUNT(*), SUM(note<>'') FROM ks_doc").fetchone()
        ch = conn.execute("SELECT COUNT(*), COUNT(DISTINCT title), MIN(year), MAX(year) FROM ks_choice").fetchone()
        arts = conn.execute("SELECT COUNT(*), SUM(LENGTH(text)) FROM ks_article").fetchone()
        raw = conn.execute("SELECT COUNT(*), SUM(LENGTH(body)) FROM kb_raw").fetchone()
        print(f"  문서 {docs[0]}(메모 있음 {docs[1] or 0}) · 해마다 고른 판 {ch[0]}(문서 {ch[1]} · {ch[2]}~{ch[3]}) · "
              f"조 {arts[0]:,}({(arts[1] or 0) / 1e6:,.1f}M자) · 원문 {raw[0]}({(raw[1] or 0) / 1e6:,.1f}MB)")
        for r in conn.execute("SELECT title, note FROM ks_doc WHERE note<>''"):
            print(f"    ✗ {r[0]} — {r[1]}")
    finally:
        conn.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.kb_sector", description="섹터별 · 연도별 근거 법령")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--sectors", default="", help="En,He 처럼 섹터 코드만(빈칸이면 전부)")
    f.add_argument("--years", default="", help="2020-2026 (빈칸이면 2020 ~ 올해)")
    f.add_argument("--max-calls", type=int, default=None)
    f.add_argument("--quiet", action="store_true")
    sub.add_parser("status")
    a = p.parse_args(argv)
    return cmd_fetch(a) if a.cmd == "fetch" else cmd_status(a)


if __name__ == "__main__":
    sys.exit(main())
