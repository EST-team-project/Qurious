"""재무제표 주요계정 수집 — DART 다중회사 주요계정으로 상장사 재무를 100개사씩 받는다 (목표 기능 ① W7 · 설계서 5.1.5).

무엇을 하나
-----------
``fnlttMultiAcnt.json``(다중회사 주요계정)은 한 번에 회사 100개까지 받는다(개발가이드 오류 021 「최대 100건」).
한 회사 한 보고서에 연결 · 별도 × 재무상태표 · 손익계산서 약 30줄(유동자산 · 자산총계 · 부채총계 · 자본총계 ·
매출액 · 영업이익 · 당기순이익 …)이 온다. 상장사(상장폐지 포함) 3,990개사 × 2019 ~ 2026 보고서 31개를
받아도 약 1,240회라 하루 한도(20,000)의 6% 다. 전체 재무제표(``fnlttSinglAcntAll`` · 회사 하나씩)는
필요한 종목만 따로 받는다(다음 판).

★ 정정 공시 — API 는 가장 최근 정정본만 준다
---------------------------------------------
2026-10-04 실측: GS건설(006360) 2023 사업보고서는 2024-03-21 처음 제출 → 2024-03-28 · 2024-03-29 ·
2026-06-30 정정. 지금 API 를 부르면 접수번호 ``20260630000500``(2026-06-30 정정본)의 값만 온다.
그래서 날짜 둘을 남긴다.

    known_at        이 값이 실린 보고서의 접수일(접수번호 앞 8자리) — **이 값 그대로**를 알 수 있었던 첫날
    first_known_at  그 기간 보고서가 처음 나온 날(정정 전 원본) — **그 기간 숫자**가 처음 나온 날

과거분은 정정본 값뿐이라 ``first_known_at`` ≤ 날 < ``known_at`` 사이에는 「뒤에 고쳐진 값」 을 쓰게 된다.
앞으로 매일 받는 정정은 **새 접수번호로 새 행**이 되어 그날의 판이 남는다(기본 키에 접수번호).
어느 날짜로 거를지는 읽는 쪽(``GET /api/data/financials`` 의 ``pit``)이 고른다.

다섯 가지 모드
--------------
``backfill``  연도 · 보고서 · 100개사 묶음마다 받는다. 끝낸 묶음은 ``ingest_day`` 에 남겨 건너뛴다.
``daily``     최근 N일 공시 목록의 정기보고서(정정 포함) 가운데 아직 값이 없는 접수번호만 다시 받는다.
``link``      ``first_known_at`` 을 공시 목록에서 잇는다(네트워크 0회).
``reparse``   보존 원문으로 다시 정규화(네트워크 0회).
``status``    현황.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from collector import config, db, raw_store
from collector.console import utf8_stdio
from collector.ratelimit import RateLimiter
from collector.sources import dart

MULTI_URL = "https://opendart.fss.or.kr/api/fnlttMultiAcnt.json"

#: 보고서 코드 → (이름, 공시 목록의 보고서 이름). 차례는 한 해 안의 순서.
REPORTS: Dict[str, Tuple[str, str]] = {
    "11013": ("1분기", "분기보고서"),
    "11012": ("반기", "반기보고서"),
    "11014": ("3분기", "분기보고서"),
    "11011": ("사업", "사업보고서"),
}
ORDER = ("11013", "11012", "11014", "11011")

#: 한 번에 묻는 회사 수 — DART 상한.
BATCH = 100

#: 과거분 시작 연도. 2020-01 화면 · 백테스트가 2019 사업보고서를 읽어야 해서 2019 부터.
DEFAULT_FROM_YEAR = 2019

#: 일일 갱신이 되돌아보는 날 수. 정기보고서 마감일엔 API 반영이 익영업일까지 늦는다(FAQ 「데이터 반영시점」).
DAILY_DAYS = 10

#: 같은 접수번호를 이만큼 불러도 그 판 값이 안 오면 「값 없음」 으로 접는다(소액공모 · 일부 금융사 등).
MAX_ATTEMPTS = 5

_DATE = re.compile(r"(\d{4})[.\-](\d{2})[.\-](\d{2})")


def _now() -> str:
    return raw_store.now_kst_iso()


def _limiter() -> RateLimiter:
    return RateLimiter(config.DART_SLEEP, reserve=config.DART_RESERVE, name="DART")


# ==================================================
# 1. 정규화 — 네트워크 없이 시험한다(TC-FS)
# ==================================================
def parse_amount(s) -> Optional[int]:
    """「12,069,316,661,153」 → 12069316661153 · 「-1,234」 → -1234 · 빈칸 · 「-」 → None."""
    if s is None:
        return None
    t = str(s).strip().replace(",", "")
    if t in ("", "-", "–", "—"):
        return None
    try:
        return int(t)
    except ValueError:
        try:
            return int(round(float(t)))
        except ValueError:
            return None


def period_end(thstrm_dt: str) -> str:
    """「2025.12.31 현재」 · 「2025.01.01 ~ 2025.12.31」 → 2025-12-31(마지막 날짜)."""
    found = _DATE.findall(thstrm_dt or "")
    if not found:
        return ""
    y, m, d = found[-1]
    return f"{y}-{m}-{d}"


def known_at_of(rcept_no: str) -> str:
    """접수번호 앞 8자리가 접수일이다(14자리 · 예 20260630000500 → 20260630)."""
    s = (rcept_no or "").strip()
    return s[:8] if len(s) >= 8 and s[:8].isdigit() else ""


_COLS = ("corp_code", "bsns_year", "reprt_code", "fs_div", "sj_div", "ord", "account_nm", "rcept_no", "scope",
         "stock_code", "period_end", "thstrm_amount", "thstrm_add_amount", "frmtrm_amount", "frmtrm_add_amount",
         "bfefrmtrm_amount", "currency", "known_at", "first_known_at", "fetched_at", "raw_sha256")


def normalize_row(item: Dict, *, fetched_at: str, raw_sha256: str = "") -> Optional[Dict]:
    """응답 한 줄 → ``financial_statement`` 한 행. 접수번호 · 회사가 없으면 None."""
    rcept_no = str(item.get("rcept_no") or "").strip()
    corp_code = str(item.get("corp_code") or "").strip()
    if not rcept_no or not corp_code:
        return None
    try:
        ord_ = int(str(item.get("ord") or "0").strip() or 0)
    except ValueError:
        ord_ = 0
    return {
        "corp_code": corp_code,
        "bsns_year": str(item.get("bsns_year") or "").strip(),
        "reprt_code": str(item.get("reprt_code") or "").strip(),
        "fs_div": str(item.get("fs_div") or "").strip(),
        "sj_div": str(item.get("sj_div") or "").strip(),
        "ord": ord_,
        "account_nm": " ".join(str(item.get("account_nm") or "").split()),
        "rcept_no": rcept_no,
        "scope": "major",
        "stock_code": str(item.get("stock_code") or "").strip(),
        "period_end": period_end(str(item.get("thstrm_dt") or "")),
        "thstrm_amount": parse_amount(item.get("thstrm_amount")),
        "thstrm_add_amount": parse_amount(item.get("thstrm_add_amount")),
        "frmtrm_amount": parse_amount(item.get("frmtrm_amount")),
        "frmtrm_add_amount": parse_amount(item.get("frmtrm_add_amount")),
        "bfefrmtrm_amount": parse_amount(item.get("bfefrmtrm_amount")),
        "currency": str(item.get("currency") or "KRW").strip() or "KRW",
        "known_at": known_at_of(rcept_no),
        "first_known_at": "",
        "fetched_at": fetched_at,
        "raw_sha256": raw_sha256,
    }


#: 같은 판(접수번호)을 다시 받으면 값만 고친다 — first_known_at 은 link 가 채운 값을 지키고 fetched_at 은 처음 것.
_UPSERT = (
    f"INSERT INTO financial_statement ({', '.join(_COLS)}) VALUES ({', '.join('?' * len(_COLS))}) "
    "ON CONFLICT(corp_code, bsns_year, reprt_code, fs_div, sj_div, ord, account_nm, rcept_no) DO UPDATE SET "
    "stock_code=excluded.stock_code, period_end=excluded.period_end, thstrm_amount=excluded.thstrm_amount, "
    "thstrm_add_amount=excluded.thstrm_add_amount, frmtrm_amount=excluded.frmtrm_amount, "
    "frmtrm_add_amount=excluded.frmtrm_add_amount, bfefrmtrm_amount=excluded.bfefrmtrm_amount, "
    "currency=excluded.currency, raw_sha256=excluded.raw_sha256"
)


def upsert_rows(conn: sqlite3.Connection, rows: Iterable[Optional[Dict]]) -> int:
    n = 0
    for r in rows:
        if r is None:
            continue
        conn.execute(_UPSERT, tuple(r[c] for c in _COLS))
        n += 1
    return n


# ==================================================
# 2. 공시 목록과 잇기 — first_known_at
# ==================================================
def period_of(period_end_iso: str) -> str:
    """2025-12-31 → 2025.12 (공시 목록 ``period`` 칸 모양)."""
    return f"{period_end_iso[:4]}.{period_end_iso[5:7]}" if len(period_end_iso) >= 7 else ""


def link_first_known(conn: sqlite3.Connection) -> int:
    """``first_known_at`` = 같은 회사 · 같은 기간 · 같은 보고서 이름의 공시 가운데 가장 이른 접수일.

    정정 · 첨부추가가 따로 접수번호를 받아도 원본이 가장 이르다(GS건설 2023 사업보고서 → 20240321).
    공시 목록에 아직 그 기간 원본이 없으면 비워 둔다(읽는 쪽이 known_at 으로 대신 거른다).
    트랜잭션은 부르는 쪽이 잡는다. 고친 행 수를 돌려준다.
    """
    # 회사 · 기간 · 보고서마다 한 번만 찾는다(행마다 찾으면 수백만 번이다) — 임시 표에 모아 바뀐 행만 고친다.
    conn.execute("DROP TABLE IF EXISTS temp._first_known")
    conn.execute(
        "CREATE TEMP TABLE _first_known AS "
        "SELECT f.corp_code, f.bsns_year, f.reprt_code, f.period_end, MIN(d.rcept_dt) AS fk "
        "  FROM (SELECT DISTINCT corp_code, bsns_year, reprt_code, period_end FROM financial_statement"
        "         WHERE period_end <> '') f "
        "  JOIN disclosure d ON d.corp_code = f.corp_code "
        "   AND d.period = substr(f.period_end, 1, 4) || '.' || substr(f.period_end, 6, 2) "
        "   AND d.title = CASE f.reprt_code WHEN '11011' THEN '사업보고서' WHEN '11012' THEN '반기보고서' "
        "                 ELSE '분기보고서' END "
        " GROUP BY f.corp_code, f.bsns_year, f.reprt_code, f.period_end")
    conn.execute("CREATE INDEX temp.ix_first_known ON _first_known(corp_code, bsns_year, reprt_code, period_end)")
    before = conn.total_changes
    # 원본 접수일이 값의 접수일보다 늦을 수는 없다 — 목록이 덜 받혀 그렇게 나오면 값의 접수일(known_at)로 둔다
    conn.execute(
        "UPDATE financial_statement SET first_known_at = MIN(k.fk, financial_statement.known_at) "
        "  FROM _first_known k "
        " WHERE k.corp_code = financial_statement.corp_code AND k.bsns_year = financial_statement.bsns_year "
        "   AND k.reprt_code = financial_statement.reprt_code AND k.period_end = financial_statement.period_end "
        "   AND financial_statement.first_known_at <> MIN(k.fk, financial_statement.known_at)")
    conn.execute("DROP TABLE temp._first_known")
    return conn.total_changes - before


# ==================================================
# 3. 받기
# ==================================================
@dataclass
class Tally:
    calls: int = 0
    rows: int = 0
    versions: int = 0     # 새로 생긴 (회사 · 기간 · 접수번호) 판
    batches: int = 0
    empty: int = 0
    errors: List[str] = field(default_factory=list)
    stopped: str = ""


def corp_universe() -> List[Tuple[str, str]]:
    """(종목코드, 고유번호) — DART 고유번호 매핑의 상장사 전부(상장폐지 포함 · 3,990곳 · 2026-09-19)."""
    m = json.loads(config.DART_CORP_CODE_PATH.read_text(encoding="utf-8"))
    return sorted((stock, v[0]) for stock, v in m.items() if v and v[0])


def fetch_multi(conn: sqlite3.Connection, limiter: RateLimiter, session: requests.Session, *,
                corp_codes: Sequence[str], bsns_year: str, reprt_code: str, tally: Tally,
                max_calls: Optional[int] = None) -> List[Dict]:
    """한 묶음을 받아 넣는다. 넣은 행(정규화한 것)을 돌려준다 — 받은 접수번호를 부르는 쪽이 대조한다."""
    if max_calls is not None and limiter.calls >= max_calls:
        raise dart.DartQuotaExceeded(f"이번 실행의 호출 상한 {max_calls:,}회에 닿았다 — 다시 돌리면 이어서 간다")
    r = dart._get(limiter, MULTI_URL, {  # noqa: SLF001 — 배당 수집기와 같은 호출 · 간격 규칙
        "corp_code": ",".join(corp_codes), "bsns_year": bsns_year, "reprt_code": reprt_code,
    }, session=session)
    tally.calls += 1
    if r.status_code != 200:
        raise dart.DartError(f"주요계정 HTTP {r.status_code} ({bsns_year} {reprt_code} · {len(corp_codes)}곳)")
    body = r.content
    doc = json.loads(body.decode("utf-8"))
    status = str(doc.get("status", ""))
    dart._check_status(status, str(doc.get("message", "")),  # noqa: SLF001
                       f"주요계정 {bsns_year} {reprt_code} · {len(corp_codes)}곳")
    if status == dart.DART_NO_DATA:
        tally.empty += 1
        return []
    items = doc.get("list") or []
    fetched_at = _now()
    target = f"fin_multi/{bsns_year}-{reprt_code}/{hashlib.sha256(','.join(corp_codes).encode()).hexdigest()[:12]}"
    conn.execute("BEGIN IMMEDIATE")
    try:
        sha = raw_store.save(conn, "dart", target, body, http_status=r.status_code,
                             note=f"corps={len(corp_codes)} rows={len(items)}")
        rows = [normalize_row(i, fetched_at=fetched_at, raw_sha256=sha) for i in items]
        rows = [x for x in rows if x is not None]
        keys = {(x["corp_code"], x["bsns_year"], x["reprt_code"], x["rcept_no"]) for x in rows}
        have = 0
        for k in keys:
            have += conn.execute(
                "SELECT 1 FROM financial_statement WHERE corp_code=? AND bsns_year=? AND reprt_code=? "
                "AND rcept_no=? LIMIT 1", k).fetchone() is not None
        tally.versions += len(keys) - have
        tally.rows += upsert_rows(conn, rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return rows


def _mark(conn: sqlite3.Connection, source: str, key: str, status: str, rows: int, message: str = "") -> None:
    conn.execute(
        "INSERT INTO ingest_day (source, bas_dt, status, rows, attempts, updated_at, message) "
        "VALUES (?, ?, ?, ?, 1, ?, ?) "
        "ON CONFLICT(source, bas_dt) DO UPDATE SET status=excluded.status, rows=excluded.rows, "
        "attempts=ingest_day.attempts+1, updated_at=excluded.updated_at, message=excluded.message",
        (source, key, status, rows, _now(), message[:500]))


def run_backfill(*, from_year: int = DEFAULT_FROM_YEAR, to_year: Optional[int] = None,
                 reports: Sequence[str] = ORDER, max_calls: Optional[int] = None,
                 quiet: bool = False) -> Tally:
    """연도 × 보고서 × 100개사 묶음. 끝낸 묶음은 건너뛴다(``ingest_day`` source='dart_fin').

    「데이터 없음(013)」 인 묶음은 ``empty`` 로 남기고 다음 실행에서 다시 본다 — 아직 마감 전인 보고서가 그렇다.
    """
    to_year = to_year or datetime.now().year
    conn = db.connect()
    limiter = _limiter()
    session = requests.Session()
    tally = Tally()
    universe = corp_universe()
    batches = [universe[i:i + BATCH] for i in range(0, len(universe), BATCH)]
    done = {r[0] for r in conn.execute(
        "SELECT bas_dt FROM ingest_day WHERE source='dart_fin' AND status='done'")}
    plan = [(str(y), rc, bi) for y in range(from_year, to_year + 1) for rc in reports for bi in range(len(batches))]
    todo = [p for p in plan if f"{p[0]}-{p[1]}-b{p[2]:02d}" not in done]
    if not quiet:
        print(f"재무 주요계정 — {to_year - from_year + 1}년 × 보고서 {len(reports)} × 묶음 {len(batches)}"
              f"({len(universe):,}곳) = {len(plan)} · 이미 끝남 {len(plan) - len(todo)} · 이번 {len(todo)}")
    for i, (y, rc, bi) in enumerate(todo, 1):
        key = f"{y}-{rc}-b{bi:02d}"
        codes = [c for _, c in batches[bi]]
        try:
            rows = fetch_multi(conn, limiter, session, corp_codes=codes, bsns_year=y, reprt_code=rc,
                               tally=tally, max_calls=max_calls)
        except dart.DartQuotaExceeded as exc:
            tally.stopped = str(exc)
            break
        except (dart.DartError, requests.RequestException, ValueError) as exc:
            tally.errors.append(f"{key}: {str(exc).splitlines()[0][:200]}")
            conn.execute("BEGIN IMMEDIATE")
            _mark(conn, "dart_fin", key, "error", 0, str(exc))
            conn.execute("COMMIT")
            continue
        tally.batches += 1
        conn.execute("BEGIN IMMEDIATE")
        _mark(conn, "dart_fin", key, "done" if rows else "empty", len(rows))
        conn.execute("COMMIT")
        if not quiet and (i % 40 == 0 or i == len(todo)):
            print(f"  {i}/{len(todo)} · {key} · 호출 {tally.calls:,} · 행 {tally.rows:,}", flush=True)
    conn.execute("BEGIN IMMEDIATE")
    linked = link_first_known(conn)
    conn.execute("COMMIT")
    if not quiet:
        print(f"  처음 공개일 잇기 {linked:,}행")
    conn.close()
    return tally


def guess_reports(title: str, period: str) -> List[Tuple[str, str]]:
    """공시 목록의 (보고서 이름, 기간 YYYY.MM) → 물어볼 (사업연도, 보고서 코드) 후보 — 앞이 더 그럴듯하다.

    12월 결산이 대부분이라 그 경우를 먼저 둔다. 결산월이 다른 회사(3 · 6 · 9월)는 뒤 후보로 맞춘다.
    """
    if not period or len(period) != 7:
        return []
    y, mm = int(period[:4]), int(period[5:7])
    years = [str(y), str(y - 1)]
    if title == "사업보고서":
        return [(yy, "11011") for yy in years]
    if title == "반기보고서":
        return [(yy, "11012") for yy in years]
    if title == "분기보고서":
        first = "11013" if mm in (3, 4, 5) else "11014" if mm in (9, 10, 11) else None
        codes = [first] + [c for c in ("11013", "11014") if c != first] if first else ["11013", "11014"]
        return [(yy, c) for yy in years for c in codes]
    return []


def run_daily(*, days: int = DAILY_DAYS, max_calls: Optional[int] = None, quiet: bool = False) -> Tally:
    """최근 ``days`` 일의 정기보고서(정정 포함) 중 값이 아직 없는 접수번호를 받는다.

    접수번호마다 후보 (사업연도 · 보고서 코드)를 차례로 묻고, 응답의 접수번호가 그 공시와 같으면 끝난다.
    API 반영이 늦어 옛 판이 오면 그 판도 넣되(판이 하나 더 생길 뿐) 이 접수번호는 다음 실행에서 다시 본다.
    """
    conn = db.connect()
    limiter = _limiter()
    session = requests.Session()
    tally = Tally()
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y%m%d")
    wanted = conn.execute(
        "SELECT d.rcept_no, d.corp_code, d.title, d.period FROM disclosure d "
        " WHERE d.rcept_dt >= ? AND d.title IN ('사업보고서','반기보고서','분기보고서') AND d.period <> ''"
        "   AND NOT EXISTS (SELECT 1 FROM financial_statement f WHERE f.rcept_no = d.rcept_no)"
        "   AND NOT EXISTS (SELECT 1 FROM ingest_day g WHERE g.source='dart_fin_rcept' AND g.bas_dt=d.rcept_no"
        "                    AND (g.status='missing' OR g.status='done'))"
        " ORDER BY d.rcept_no", (since,)).fetchall()
    pending = {r["rcept_no"]: (r["corp_code"], guess_reports(r["title"], r["period"])) for r in wanted}
    if not quiet:
        print(f"재무 일일 — 최근 {days}일 정기보고서 중 값 없는 접수번호 {len(pending)}건")
    rounds = 0
    while pending and rounds < 4 and not tally.stopped:
        # 같은 (연도, 보고서) 후보끼리 100개씩 묶어 묻는다
        groups: Dict[Tuple[str, str], List[str]] = {}
        for rno, (corp, cands) in pending.items():
            if rounds < len(cands):
                groups.setdefault(cands[rounds], []).append(rno)
        if not groups:
            break
        for (y, rc), rnos in groups.items():
            corps = sorted({pending[x][0] for x in rnos})
            for i in range(0, len(corps), BATCH):
                try:
                    rows = fetch_multi(conn, limiter, session, corp_codes=corps[i:i + BATCH], bsns_year=y,
                                       reprt_code=rc, tally=tally, max_calls=max_calls)
                except dart.DartQuotaExceeded as exc:
                    tally.stopped = str(exc)
                    break
                except (dart.DartError, requests.RequestException, ValueError) as exc:
                    tally.errors.append(f"{y}-{rc}: {str(exc).splitlines()[0][:200]}")
                    continue
                got = {x["rcept_no"] for x in rows}
                for rno in [x for x in rnos if x in got]:
                    pending.pop(rno, None)
            if tally.stopped:
                break
        rounds += 1
    # 끝내 못 받은 접수번호는 시도 수를 남기고, 많이 시도한 것은 「값 없음」 으로 접는다
    conn.execute("BEGIN IMMEDIATE")
    for rno in pending:
        row = conn.execute("SELECT attempts FROM ingest_day WHERE source='dart_fin_rcept' AND bas_dt=?",
                           (rno,)).fetchone()
        n = (row[0] if row else 0) + 1
        _mark(conn, "dart_fin_rcept", rno, "missing" if n >= MAX_ATTEMPTS else "pending", 0,
              "API 가 이 접수번호의 값을 아직 주지 않았다")
    linked = link_first_known(conn)
    conn.execute("COMMIT")
    conn.close()
    if not quiet:
        print(f"  남은 접수번호 {len(pending)} · 처음 공개일 잇기 {linked:,}행")
    return tally


def run_reparse(*, quiet: bool = False) -> int:
    """보존 원문으로 다시 정규화한다(네트워크 0회)."""
    conn = db.connect()
    n = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for rec in raw_store.iter_latest(conn, "dart", prefix="fin_multi/"):
            doc = json.loads(rec["body"].decode("utf-8"))
            n += upsert_rows(conn, (normalize_row(i, fetched_at=rec["fetched_at"], raw_sha256=rec["sha256"])
                                    for i in doc.get("list") or []))
        link_first_known(conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.close()
    if not quiet:
        print(f"다시 정규화 {n:,}행(네트워크 0회)")
    return n


def print_status() -> None:
    conn = db.connect()
    t = conn.execute("SELECT COUNT(*), COUNT(DISTINCT corp_code), COUNT(DISTINCT rcept_no) FROM financial_statement").fetchone()
    print(f"재무 주요계정 {t[0]:,}행 · 회사 {t[1]:,} · 판(접수번호) {t[2]:,}")
    for r in conn.execute("SELECT bsns_year, reprt_code, COUNT(DISTINCT corp_code) c, COUNT(DISTINCT rcept_no) v "
                          "FROM financial_statement GROUP BY bsns_year, reprt_code ORDER BY bsns_year, reprt_code"):
        print(f"  {r['bsns_year']} {REPORTS.get(r['reprt_code'], ('?',))[0]:>3} · 회사 {r['c']:,} · 판 {r['v']:,}")
    r = conn.execute("SELECT SUM(first_known_at <> '') a, SUM(first_known_at <> '' AND first_known_at < known_at) b, "
                     "COUNT(*) n FROM (SELECT DISTINCT corp_code, bsns_year, reprt_code, rcept_no, known_at, first_known_at "
                     "FROM financial_statement)").fetchone()
    if r and r["n"]:
        print(f"  처음 공개일 이음 {r['a'] or 0:,}/{r['n']:,}판 · 그중 정정본 값(처음 공개일 < 값의 접수일) {r['b'] or 0:,}판")
    st = conn.execute("SELECT source, status, COUNT(*) FROM ingest_day WHERE source LIKE 'dart_fin%' "
                      "GROUP BY source, status").fetchall()
    print("  받기 기록: " + " · ".join(f"{x[0]} {x[1]} {x[2]}" for x in st))
    conn.close()


def _report(t: Tally) -> None:
    print(f"재무 — 호출 {t.calls:,}회 · 넣거나 고친 행 {t.rows:,} · 새 판 {t.versions:,} · 묶음 {t.batches:,}"
          f" · 데이터 없음 {t.empty:,}" + (f" · 오류 {len(t.errors)}" if t.errors else ""))
    for e in t.errors[:10]:
        print(f"  🟡 {e}")
    if t.stopped:
        print(f"\n멈춤: {t.stopped}")


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.financials",
                                description="DART 재무제표 주요계정 수집(상장사 · 100개사 묶음)")
    p.add_argument("mode", choices=["backfill", "daily", "link", "reparse", "status"])
    p.add_argument("--from-year", type=int, default=DEFAULT_FROM_YEAR)
    p.add_argument("--to-year", type=int)
    p.add_argument("--days", type=int, default=DAILY_DAYS, help="daily — 되돌아볼 날 수")
    p.add_argument("--max-calls", type=int, default=config.DART_DAILY_LIMIT - config.DART_RESERVE)
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)
    if a.mode == "status":
        print_status()
        return 0
    if a.mode == "reparse":
        run_reparse(quiet=a.quiet)
        return 0
    if a.mode == "link":
        conn = db.connect()
        conn.execute("BEGIN IMMEDIATE")
        n = link_first_known(conn)
        conn.execute("COMMIT")
        conn.close()
        print(f"처음 공개일 잇기 {n:,}행(네트워크 0회)")
        return 0
    if a.mode == "daily":
        t = run_daily(days=a.days, max_calls=a.max_calls, quiet=a.quiet)
    else:
        t = run_backfill(from_year=a.from_year, to_year=a.to_year, max_calls=a.max_calls, quiet=a.quiet)
    _report(t)
    if t.stopped:
        return 3
    return 1 if t.errors else 0


if __name__ == "__main__":
    sys.exit(main())
