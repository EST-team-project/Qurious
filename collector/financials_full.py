"""전체 재무제표 — DART 단일회사 전체 재무제표(fnlttSinglAcntAll)를 분봉 유니버스 351곳에 대해 매일 더한다 (할 일 ①-05 · G3 · 2026-10-24).

    python -m collector.financials_full daily [--quiet] [--max-calls 1500]          러너 단계 — 새 정기보고서 · 분기 대조 · 새로 든 회사
    python -m collector.financials_full backfill --years 2015-2020 [--max-calls 15000] [--sleep 0.6]   지난 해 채우기(회차 밖에서만)
    python -m collector.financials_full seed --raw-dir <폴더>                          10-22 일회 수집 원문(gz)을 표로 — 네트워크 0회
    python -m collector.financials_full status

무엇을 하나 — 사용자 결정 2026-10-24 「새 공시 + 분기마다 대조」
---------------------------------------------------------------
① **새 정기보고서(정정 포함)** — 공시 단계가 받은 최근 10일 목록(`disclosure`)에서 351곳의 사업 · 반기 · 분기보고서 접수번호 가운데
   전체 재무제표가 아직 없는 것. 회사가 쓰는 구분(연결 CFS · 별도 OFS — 우리 표에서 읽음 · 처음이면 연결 먼저)으로 부르고, **응답의
   접수번호가 그 공시와 같아야 끝**이다. 응답이 더 옛 판이면 API 반영이 늦은 것이라 다음 회차가 다시 묻고(다섯 번이면 「값 없음」),
   더 새 판이면 그 공시는 이미 정정본에 밀린 것이라 끝낸다(옛 판 값은 DART 가 다시 주지 않는다). 주요계정 단계와 같은 규칙이다.
② **분기마다 대조** — 분기(KST)마다 한 번, 하루 50곳씩(약 300 ~ 400회 · 7일 안에 351곳 한 바퀴) 최근 두 사업연도를 다시 받아 우리
   판과 맞춘다. 결과는 `financial_full_check` 에 한 줄씩: 같음 · 없던 판(표에 더함 — ① 이 놓친 정정) · **조용한 고침**(같은 접수번호인데
   값이 다름 — 우리 줄은 처음 받은 그대로 두고 그때 응답 원문을 남긴다) · 사라짐(우리엔 있는데 API 가 안 줌) · 둘 다 없음.
③ **유니버스에 새로 든 회사** — 줄도 받은 기록도 없는 회사는 지난 해(2015 ~ )를 하루 300회 안에서 채운다(남으면 다음 회차).

지난 해 채우기(backfill)는 러너 단계가 아니다 — 회차가 끝난 뒤에만 돈다(사용자 결정 2026-10-24 「고정 몫 + 회차 뒤에만」): 시작할 때와
부르기 전마다 회차 잠금 · 12:20 ~ 13:20 을 보고 걸리면 멈춘다(같은 명령으로 이어 받음) · 하루 15,000회까지(= 20,000 − 예비 1,000 −
회차 몫 3,000 − 사람 확인 1,000) · 간격 0.6초(분당 100회 안 — 공식 숫자는 없고 약관 제10조⑥ 「과도한 네트워크 접속」 제한을 따름).

같은 표에 넣지 않는 까닭 · 날짜 둘
----------------------------------
주요계정 표(`financial_statement`)와 기본 키가 겹친다 — 그 키(…ord · account_nm · rcept_no)로는 전체 재무제표 줄이 서로도 겹친다
(2024년 27만 6천 줄에서 겹치지 않는 열쇠는 ord · account_id · account_detail 을 함께 써야 했다 · 2026-10-24 실측). 그래서 표를 따로
두고(`financial_statement_full`), 날짜 둘(known_at = 접수번호 앞 8자리 · first_known_at = 그 기간 원본 보고서 접수일)은 주요계정
표와 같은 뜻으로 둔다 — 백테스트가 「그날 알 수 있었던 값」 만 읽게.

원문 · 이어 받기
---------------
값이 온 응답(000)은 원문을 `raw_response`(source dart · target `fin_full/<고유번호>/<연도>-<보고서>-<구분>`)에 남긴다 — 다시 정규화하는
재료이자 감사 근거(대조에서 「같음」 이면 같은 원문을 또 남기지 않는다). 부른 조합은 `ingest_day` 에 남겨(값 있음 done · 없음 empty)
다시 부르지 않는다. 10-22 일회 수집 원문 8,329건은 `seed` 로 옮겨 담는다(받은 시각 = 파일 시각 · 네트워크 0회).

종료코드 — 0 끝 · 1 일부 실패(받은 것은 저장) · 3 한도 · 상한 · 회차 시간에 멈춤(다음에 이어서) · 78 키 없음
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from collector import config, db, raw_store
from collector.console import utf8_stdio
from collector.dart_company import universe
from collector.financials import guess_reports, known_at_of, parse_amount
from collector.ratelimit import RateLimiter
from collector.sources import dart

URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
#: 보고서 코드 — 한 해 안에서 늦은 것부터(지난 해 채우기 차례 · 일회 수집과 같음).
REPORTS: Tuple[str, ...] = ("11011", "11014", "11012", "11013")
#: 12월 결산 기준 법정 제출 마감(월, 일 · 사업보고서는 다음 해) — 아직 나올 수 없는 보고서를 부르지 않는다.
DEADLINE: Dict[str, Tuple[int, int, int]] = {"11013": (0, 5, 15), "11012": (0, 8, 14), "11014": (0, 11, 14), "11011": (1, 3, 31)}
FIRST_YEAR = 2015                 # 전체 재무제표 API 의 첫 사업연도(XBRL 재무제표 · 2015 1분기 ~)
DAILY_DAYS = 10                   # 공시 목록을 되돌아보는 날 수(주요계정 단계와 같음 — 마감일 반영이 익영업일까지 늦다)
MAX_ATTEMPTS = 5                  # 같은 접수번호를 이만큼 물어도 그 판이 안 오면 「값 없음」
CHECK_CORPS_PER_DAY = 50          # 분기 대조 — 하루에 보는 회사 수(약 300 ~ 400회)
NEW_CORP_MAX_CALLS = 300          # 새로 든 회사 채우기 — 하루 상한
BACKFILL_SLEEP = 0.6              # 지난 해 채우기 간격(초) — 분당 100회 안
ROUND_GUARD = ((12, 20), (13, 20))  # 지난 해 채우기를 시작하지 않고 · 돌다가도 멈추는 시간(회차 12:30 ~ 약 13:20)
EX_STOPPED = 3
EX_CONFIG = 78

#: 응답 칸(줄) — 값 칸은 정수로 바꾼다.
_NAME_COLS = ("sj_nm", "thstrm_nm", "frmtrm_nm", "frmtrm_q_nm", "bfefrmtrm_nm")
_AMOUNT_COLS = ("thstrm_amount", "thstrm_add_amount", "frmtrm_amount", "frmtrm_q_amount", "frmtrm_add_amount",
                "bfefrmtrm_amount")
COLS: Tuple[str, ...] = ("corp_code", "bsns_year", "reprt_code", "fs_div", "sj_div", "sj_nm", "ord", "account_id",
                         "account_nm", "account_detail", "rcept_no", "stock_code", "thstrm_nm", "thstrm_amount",
                         "thstrm_add_amount", "frmtrm_nm", "frmtrm_amount", "frmtrm_q_nm", "frmtrm_q_amount",
                         "frmtrm_add_amount", "bfefrmtrm_nm", "bfefrmtrm_amount", "currency", "known_at", "first_known_at",
                         "fetched_at", "raw_sha256")
#: 대조에서 「같은 줄」 의 열쇠와 비교하는 값.
_ROW_KEY = ("sj_div", "ord", "account_id", "account_detail")
_ROW_VAL = ("account_nm",) + _AMOUNT_COLS + ("currency",)

SRC_RCEPT = "dart_full_rcept"     # ingest_day — 공시 접수번호마다(pending · done · missing · superseded)
SRC_CALL = "dart_full_bf"         # ingest_day — (회사:연도:보고서:구분) 부른 조합(done 값 있음 · empty 없음)
SRC_CHECK = "dart_full_check"     # ingest_day — (분기:회사) 대조를 끝낸 회사


def _now() -> str:
    return raw_store.now_kst_iso()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ==================================================
# 1. 정규화 — 네트워크 없이 시험한다(TC-FF)
# ==================================================
def normalize(item: Dict, *, fs_div: str, stock_code: str, fetched_at: str, raw_sha256: str) -> Optional[Dict]:
    """응답 한 줄 → 표 한 행. 접수번호 · 회사 · 계정 ID 가 없으면 None. 계정 이름의 공백은 하나로 접는다(주요계정과 같게)."""
    rcept_no = str(item.get("rcept_no") or "").strip()
    corp_code = str(item.get("corp_code") or "").strip()
    account_id = str(item.get("account_id") or "").strip()
    if not rcept_no or not corp_code or not account_id:
        return None
    try:
        ord_ = int(str(item.get("ord") or "0").strip() or 0)
    except ValueError:
        ord_ = 0
    row = {
        "corp_code": corp_code,
        "bsns_year": str(item.get("bsns_year") or "").strip(),
        "reprt_code": str(item.get("reprt_code") or "").strip(),
        "fs_div": fs_div,
        "sj_div": str(item.get("sj_div") or "").strip(),
        "ord": ord_,
        "account_id": account_id,
        "account_nm": " ".join(str(item.get("account_nm") or "").split()),
        "account_detail": " ".join(str(item.get("account_detail") or "").split()),
        "rcept_no": rcept_no,
        "stock_code": stock_code,
        "currency": str(item.get("currency") or "KRW").strip() or "KRW",
        "known_at": known_at_of(rcept_no),
        "first_known_at": "",
        "fetched_at": fetched_at,
        "raw_sha256": raw_sha256,
    }
    for c in _NAME_COLS:
        row[c] = " ".join(str(item.get(c) or "").split())
    for c in _AMOUNT_COLS:
        row[c] = parse_amount(item.get(c))
    return row


#: 같은 판(접수번호)을 다시 받아도 줄을 고치지 않는다 — 처음 받은 값이 「그날 알 수 있었던 값」 이다(조용한 고침은 대조 표가 적는다).
_INSERT = (f"INSERT INTO financial_statement_full ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))}) "
           "ON CONFLICT(corp_code, bsns_year, reprt_code, fs_div, sj_div, ord, account_id, account_detail, rcept_no) DO NOTHING")


def insert_rows(conn: sqlite3.Connection, rows: Iterable[Optional[Dict]]) -> int:
    n = 0
    for r in rows:
        if r is None:
            continue
        cur = conn.execute(_INSERT, tuple(r[c] for c in COLS))
        n += cur.rowcount or 0
    return n


def row_diff(ours: Sequence[Dict], theirs: Sequence[Dict]) -> int:
    """같은 판의 두 벌이 다른 줄 수 — 열쇠(표 · 순서 · 계정 ID · 상세)마다 값(이름 · 금액 · 통화)을 맞춘다. 한쪽에만 있는 줄도 센다."""
    a = {tuple(r[k] for k in _ROW_KEY): tuple(r[k] for k in _ROW_VAL) for r in ours}
    b = {tuple(r[k] for k in _ROW_KEY): tuple(r[k] for k in _ROW_VAL) for r in theirs}
    return sum(1 for k in a.keys() | b.keys() if a.get(k) != b.get(k))


def link_first_known(conn: sqlite3.Connection) -> int:
    """first_known_at = 같은 회사 · 사업연도 · 보고서 이름의 공시 가운데 가장 이른 접수일(정정 · 첨부추가가 따로 번호를 받아도 원본이
    가장 이르다). 기간 칸(YYYY.MM)은 회사 결산월을 몰라도 맞도록 「그 사업연도 판 보고서」 를 공시의 보고서 이름 · 기간 연도로 잇는다 —
    12월 결산은 기간 연도 = 사업연도. 원본 접수일이 값의 접수일보다 늦게 나오면(목록이 덜 받혔다) 값의 접수일로 둔다. 트랜잭션은 부르는 쪽."""
    conn.execute("DROP TABLE IF EXISTS temp._ff_first")
    conn.execute(
        "CREATE TEMP TABLE _ff_first AS "
        "SELECT f.corp_code, f.bsns_year, f.reprt_code, MIN(d.rcept_dt) AS fk "
        "  FROM (SELECT DISTINCT corp_code, bsns_year, reprt_code FROM financial_statement_full) f "
        "  JOIN disclosure d ON d.corp_code = f.corp_code "
        "   AND substr(d.period, 1, 4) = f.bsns_year "
        "   AND d.title = CASE f.reprt_code WHEN '11011' THEN '사업보고서' WHEN '11012' THEN '반기보고서' ELSE '분기보고서' END "
        "   AND (f.reprt_code IN ('11011', '11012') "
        "        OR (f.reprt_code = '11013' AND substr(d.period, 6, 2) IN ('03', '04', '05')) "
        "        OR (f.reprt_code = '11014' AND substr(d.period, 6, 2) IN ('09', '10', '11'))) "
        " GROUP BY f.corp_code, f.bsns_year, f.reprt_code")
    conn.execute("CREATE INDEX temp.ix_ff_first ON _ff_first(corp_code, bsns_year, reprt_code)")
    before = conn.total_changes
    conn.execute(
        "UPDATE financial_statement_full SET first_known_at = MIN(k.fk, financial_statement_full.known_at) "
        "  FROM _ff_first k "
        " WHERE k.corp_code = financial_statement_full.corp_code AND k.bsns_year = financial_statement_full.bsns_year "
        "   AND k.reprt_code = financial_statement_full.reprt_code "
        "   AND financial_statement_full.first_known_at <> MIN(k.fk, financial_statement_full.known_at)")
    conn.execute("DROP TABLE temp._ff_first")
    return conn.total_changes - before


# ==================================================
# 2. 부르기 — 한 회사 · 한 보고서 · 한 구분
# ==================================================
class Stop(Exception):
    """이번 실행은 여기까지 — 한도 · 상한 · 회차 시간(다음 실행이 이어서 받는다)."""


@dataclass
class Tally:
    calls: int = 0
    rows: int = 0
    versions: int = 0
    filings_done: int = 0
    filings_pending: int = 0
    filings_missing: int = 0
    filings_superseded: int = 0
    check: Dict[str, int] = field(default_factory=dict)
    check_corps: int = 0
    quarter: str = ""
    new_corps: int = 0
    errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    stopped: str = ""


class Caller:
    """간격 · 상한 · (지난 해 채우기라면) 회차 시간을 지키며 부른다. 받은 원문은 저장 여부를 부르는 쪽이 고른다."""

    def __init__(self, conn: sqlite3.Connection, tally: Tally, *, max_calls: Optional[int], sleep: float = 0.0,
                 session=None, limiter: Optional[RateLimiter] = None, guard=None):
        self.conn, self.t, self.max_calls = conn, tally, max_calls
        self.lim = limiter or RateLimiter(max(sleep, config.DART_SLEEP), reserve=config.DART_RESERVE, name="DART")
        self.sess = session or requests.Session()
        self.guard = guard

    def get(self, corp: str, year: str, reprt: str, fs: str) -> Tuple[str, bytes, Dict]:
        """(상태 '000' · '013', 원문, 문서). 020 · 상한 · 회차 시간이면 Stop. 그 밖의 상태는 DartError."""
        if self.max_calls is not None and self.t.calls >= self.max_calls:
            raise Stop(f"이번 실행의 호출 상한 {self.max_calls:,}회 — 다음 실행이 이어서 받는다")
        if self.guard:
            why = self.guard()
            if why:
                raise Stop(why)
        r = dart._get(self.lim, URL, {"corp_code": corp, "bsns_year": str(year), "reprt_code": reprt,  # noqa: SLF001
                                      "fs_div": fs}, session=self.sess)
        self.t.calls += 1
        if r.status_code != 200:
            raise dart.DartError(f"전체 재무제표 HTTP {r.status_code} ({corp} {year} {reprt} {fs})")
        body = r.content
        doc = json.loads(body.decode("utf-8"))
        st = str(doc.get("status", ""))
        if st == dart.DART_QUOTA_EXCEEDED:
            raise Stop("DART 하루 한도(020) — 다음 실행이 이어서 받는다")
        dart._check_status(st, str(doc.get("message", "")), f"전체 재무제표 {corp} {year} {reprt} {fs}")  # noqa: SLF001
        return st, body, doc


def _mark(conn: sqlite3.Connection, source: str, key: str, status: str, rows: int, message: str = "") -> None:
    conn.execute(
        "INSERT INTO ingest_day (source, bas_dt, status, rows, attempts, updated_at, message) VALUES (?, ?, ?, ?, 1, ?, ?) "
        "ON CONFLICT(source, bas_dt) DO UPDATE SET status=excluded.status, rows=excluded.rows, "
        "attempts=ingest_day.attempts+1, updated_at=excluded.updated_at, message=excluded.message",
        (source, key, status, rows, _now(), message[:500]))


def _call_key(corp: str, year, reprt: str, fs: str) -> str:
    return f"{corp}:{year}:{reprt}:{fs}"


def store(conn: sqlite3.Connection, corp: str, year, reprt: str, fs: str, st: str, body: bytes, doc: Dict, *,
          stock_code: str, tally: Tally, fetched_at: Optional[str] = None, save_raw: bool = True) -> Tuple[str, int]:
    """한 응답을 한 트랜잭션에 — 원문(값이 오면) · 줄 · 부른 기록. (응답의 접수번호, 새로 넣은 줄 수)를 돌려준다."""
    at = fetched_at or _now()
    rcept = ""
    added = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        if st == dart.DART_OK:
            items = doc.get("list") or []
            sha = (raw_store.save(conn, "dart", f"fin_full/{corp}/{year}-{reprt}-{fs}", body, http_status=200,
                                  note=f"rows={len(items)}", fetched_at=at) if save_raw else _sha(body))
            rows = [normalize(i, fs_div=fs, stock_code=stock_code, fetched_at=at, raw_sha256=sha) for i in items]
            rows = [x for x in rows if x is not None]
            rcepts = {x["rcept_no"] for x in rows}
            rcept = max(rcepts) if rcepts else ""
            new_version = bool(rcept) and conn.execute(
                "SELECT 1 FROM financial_statement_full WHERE rcept_no=? AND corp_code=? AND fs_div=? LIMIT 1",
                (rcept, corp, fs)).fetchone() is None
            added = insert_rows(conn, rows)
            tally.rows += added
            tally.versions += int(new_version and added > 0)
            _mark(conn, SRC_CALL, _call_key(corp, year, reprt, fs), "done", len(rows), f"rcept={rcept}")
        else:
            _mark(conn, SRC_CALL, _call_key(corp, year, reprt, fs), "empty", 0, f"status={st}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return rcept, added


def corp_fs(conn: sqlite3.Connection, corp: str) -> str:
    """그 회사가 쓰는 구분 — 우리 표에 연결 줄이 있으면 'CFS' · 별도만 있으면 'OFS' · 없으면 ''(처음 — 연결 먼저 떠 본다)."""
    got = {r[0] for r in conn.execute("SELECT DISTINCT fs_div FROM financial_statement_full WHERE corp_code=?", (corp,))}
    return "CFS" if "CFS" in got else ("OFS" if "OFS" in got else "")


def _asked(conn: sqlite3.Connection, keys: Sequence[str]) -> Dict[str, str]:
    out = {}
    for k in keys:
        r = conn.execute("SELECT status FROM ingest_day WHERE source=? AND bas_dt=?", (SRC_CALL, k)).fetchone()
        if r:
            out[k] = r[0]
    return out


def due(year: int, reprt: str, today: date) -> bool:
    """12월 결산 기준 마감이 지났나(그날 포함) — 아직 나올 수 없는 보고서는 부르지 않는다."""
    dy, m, d = DEADLINE[reprt]
    return today >= date(year + dy, m, d)


def periods(y0: int, y1: int, today: date) -> List[Tuple[int, str]]:
    """늦은 해부터 · 한 해 안에서 늦은 보고서부터 — 마감이 지난 것만."""
    return [(y, rp) for y in range(y1, y0 - 1, -1) for rp in REPORTS if due(y, rp, today)]


def fill_corp(conn: sqlite3.Connection, caller: Caller, corp: str, stock: str, plan: Sequence[Tuple[int, str]],
              tally: Tally, *, today: Optional[date] = None) -> None:
    """한 회사의 기간들 — 이미 부른 조합 · 줄이 있는 조합은 건너뛴다. 구분은 우리 표에서 · 처음이면 사업보고서로 떠 본다
    (연결 → 별도 · 2025 → 2024 — 일회 수집과 같은 규칙). 그 기간에 연결이 없으면(013) 별도를 한 번 더."""
    today = today or date.today()
    fs = corp_fs(conn, corp)
    if not fs:
        for y in (today.year - 1, today.year - 2):
            for f in ("CFS", "OFS"):
                k = _call_key(corp, y, "11011", f)
                st = _asked(conn, [k]).get(k)
                if st is None:
                    s, body, doc = caller.get(corp, str(y), "11011", f)
                    store(conn, corp, y, "11011", f, s, body, doc, stock_code=stock, tally=tally)
                    st = "done" if s == dart.DART_OK else "empty"
                if st == "done":
                    fs = f
                    break
            if fs:
                break
        if not fs:
            return              # 두 구분 모두 없는 회사(금융업 등 — 「상장회사(금융업 제외)」)
    for (y, rp) in plan:
        k = _call_key(corp, y, rp, fs)
        st = _asked(conn, [k]).get(k)
        if st is None and conn.execute("SELECT 1 FROM financial_statement_full WHERE corp_code=? AND bsns_year=? AND "
                                       "reprt_code=? AND fs_div=? LIMIT 1", (corp, str(y), rp, fs)).fetchone():
            continue
        try:
            if st is None:
                s, body, doc = caller.get(corp, str(y), rp, fs)
                store(conn, corp, y, rp, fs, s, body, doc, stock_code=stock, tally=tally)
                st = "done" if s == dart.DART_OK else "empty"
            if st == "empty" and fs == "CFS":           # 그 기간만 연결이 없을 수 있다 — 별도를 한 번 더
                k2 = _call_key(corp, y, rp, "OFS")
                if _asked(conn, [k2]).get(k2) is None:
                    s, body, doc = caller.get(corp, str(y), rp, "OFS")
                    store(conn, corp, y, rp, "OFS", s, body, doc, stock_code=stock, tally=tally)
        except (dart.DartError, requests.RequestException, ValueError) as e:
            tally.errors.append(f"{corp} {y} {rp}: {str(e).splitlines()[0][:150]}")


# ==================================================
# 3. 매일 — ① 새 정기보고서 ② 분기 대조 ③ 새로 든 회사
# ==================================================
def pending_filings(conn: sqlite3.Connection, corps: Dict[str, str], since: str) -> List[sqlite3.Row]:
    """최근 공시 목록의 정기보고서(정정 포함) 가운데 351곳 · 전체 재무제표가 없는 접수번호 · 접어 둔 것(끝 · 값 없음 · 밀림) 뺌."""
    rows = conn.execute(
        "SELECT d.rcept_no, d.corp_code, d.title, d.period FROM disclosure d "
        " WHERE d.rcept_dt >= ? AND d.title IN ('사업보고서','반기보고서','분기보고서') AND d.period <> '' "
        "   AND NOT EXISTS (SELECT 1 FROM financial_statement_full f WHERE f.rcept_no = d.rcept_no) "
        "   AND NOT EXISTS (SELECT 1 FROM ingest_day g WHERE g.source=? AND g.bas_dt=d.rcept_no "
        "                    AND g.status IN ('done','missing','superseded')) "
        " ORDER BY d.rcept_no", (since, SRC_RCEPT)).fetchall()
    return [r for r in rows if r["corp_code"] in corps]


def _supersedes(conn: sqlite3.Connection, newer: str, d: sqlite3.Row) -> bool:
    """`newer` 가 공시 d 와 같은 회사 · 같은 보고서 이름 · 같은 기간의 더 늦은 접수번호인가(= d 를 밀어낸 정정본). 공시 목록으로 확인한다 —
    접수번호만 견주면 다른 기간의 판(결산월이 12월이 아닌 회사의 틀린 후보)을 정정본으로 잘못 볼 수 있다."""
    return newer > d["rcept_no"] and conn.execute(
        "SELECT 1 FROM disclosure WHERE rcept_no=? AND corp_code=? AND title=? AND period=?",
        (newer, d["corp_code"], d["title"], d["period"])).fetchone() is not None


def run_filings(conn: sqlite3.Connection, caller: Caller, corps: Dict[str, str], tally: Tally, *, today: date) -> None:
    """공시 한 건마다 후보 (사업연도 · 보고서)를 차례로 묻는다 — 응답의 접수번호가 그 공시와 같으면 끝. 값이 온 응답은 어느 후보든
    그 기간의 한 판이라 표에 넣는다(버리지 않는다). 한 건의 오류는 그 건만 「기다림」 으로 두고 다음 건으로 간다(한도 · 상한은 멈춤)."""
    since = (today - timedelta(days=DAILY_DAYS - 1)).strftime("%Y%m%d")
    for d in pending_filings(conn, corps, since):
        rno, corp = d["rcept_no"], d["corp_code"]
        fs0 = corp_fs(conn, corp)
        order = [fs0] + [f for f in ("CFS", "OFS") if f != fs0] if fs0 else ["CFS", "OFS"]
        outcome = "pending"
        try:
            for (y, rp) in guess_reports(d["title"], d["period"]):
                for fs in order:
                    st, body, doc = caller.get(corp, y, rp, fs)
                    rcept, _added = store(conn, corp, y, rp, fs, st, body, doc, stock_code=corps[corp], tally=tally)
                    if st != dart.DART_OK:
                        continue                      # 그 구분은 없다 — 다른 구분
                    if rcept == rno:
                        outcome = "done"
                    elif _supersedes(conn, rcept, d):
                        outcome = "superseded"        # 이 공시는 이미 같은 보고서의 정정본에 밀렸다 — 옛 판 값은 다시 오지 않는다
                    break                             # 값이 온 구분이 이 후보의 구분 — 다른 구분은 묻지 않는다
                if outcome != "pending":
                    break
        except Stop:
            raise
        except (dart.DartError, requests.RequestException, ValueError) as e:
            tally.errors.append(f"{rno}: {str(e).splitlines()[0][:160]}")
        row = conn.execute("SELECT attempts FROM ingest_day WHERE source=? AND bas_dt=?", (SRC_RCEPT, rno)).fetchone()
        n = (row[0] if row else 0) + 1
        if outcome == "pending" and n >= MAX_ATTEMPTS:
            outcome = "missing"
        conn.execute("BEGIN IMMEDIATE")
        _mark(conn, SRC_RCEPT, rno, outcome, 0, {"pending": "API 가 이 접수번호의 판을 아직 주지 않았다",
                                                  "missing": f"{MAX_ATTEMPTS}번 물어도 이 판이 오지 않았다",
                                                  "superseded": "더 새 정정본이 먼저 왔다",
                                                  "done": ""}[outcome])
        conn.execute("COMMIT")
        tally.filings_done += outcome == "done"
        tally.filings_pending += outcome == "pending"
        tally.filings_missing += outcome == "missing"
        tally.filings_superseded += outcome == "superseded"


def quarter_of(d: date) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def check_corp(conn: sqlite3.Connection, caller: Caller, corp: str, stock: str, quarter: str, today: date,
               tally: Tally) -> None:
    """한 회사의 최근 두 사업연도 — 기간마다 API 지금 판과 우리 판을 맞춰 대조 표에 한 줄. 끝나면 그 회사를 「대조 끝」 으로."""
    y1 = today.year
    plan = set(periods(y1 - 1, y1, today))
    plan |= {(int(y), rp) for y, rp in conn.execute(
        "SELECT DISTINCT bsns_year, reprt_code FROM financial_statement_full WHERE corp_code=? AND bsns_year >= ?",
        (corp, str(y1 - 1)))}
    fs_default = corp_fs(conn, corp) or "CFS"
    for (y, rp) in sorted(plan, reverse=True):
        ours_fs = [r[0] for r in conn.execute(
            "SELECT DISTINCT fs_div FROM financial_statement_full WHERE corp_code=? AND bsns_year=? AND reprt_code=?",
            (corp, str(y), rp))]
        for fs in (ours_fs or [fs_default]):
            our_rcepts = [r[0] for r in conn.execute(
                "SELECT DISTINCT rcept_no FROM financial_statement_full WHERE corp_code=? AND bsns_year=? AND reprt_code=? "
                "AND fs_div=? ORDER BY rcept_no", (corp, str(y), rp, fs))]
            try:
                st, body, doc = caller.get(corp, str(y), rp, fs)
            except (dart.DartError, requests.RequestException, ValueError) as e:
                tally.errors.append(f"대조 {corp} {y} {rp} {fs}: {str(e).splitlines()[0][:140]}")
                continue
            sha = _sha(body)
            changed = 0
            api_rcept = ""
            if st != dart.DART_OK:
                result = "gone" if our_rcepts else "no_data"
            else:
                items = doc.get("list") or []
                api_rcept = max((str(i.get("rcept_no") or "") for i in items), default="")
                if api_rcept and api_rcept not in our_rcepts:
                    store(conn, corp, y, rp, fs, st, body, doc, stock_code=stock, tally=tally)
                    result = "new_version"
                else:
                    theirs = [normalize(i, fs_div=fs, stock_code=stock, fetched_at="", raw_sha256="") for i in items]
                    theirs = [x for x in theirs if x is not None]
                    ours = [dict(r) for r in conn.execute(
                        "SELECT * FROM financial_statement_full WHERE corp_code=? AND bsns_year=? AND reprt_code=? AND fs_div=? "
                        "AND rcept_no=?", (corp, str(y), rp, fs, api_rcept))]
                    changed = row_diff(ours, theirs)
                    result = "same" if changed == 0 else "silent_change"
                    if changed:
                        conn.execute("BEGIN IMMEDIATE")
                        raw_store.save(conn, "dart", f"fin_full/{corp}/{y}-{rp}-{fs}", body, http_status=200,
                                       note=f"check {quarter} silent_change rows={changed}")
                        conn.execute("COMMIT")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO financial_full_check (quarter, corp_code, bsns_year, reprt_code, fs_div, result, "
                "api_rcept_no, our_rcept_no, changed_rows, checked_at, raw_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (quarter, corp, str(y), rp, fs, result, api_rcept, our_rcepts[-1] if our_rcepts else "", changed, _now(), sha))
            conn.execute("COMMIT")
            tally.check[result] = tally.check.get(result, 0) + 1
    conn.execute("BEGIN IMMEDIATE")
    _mark(conn, SRC_CHECK, f"{quarter}:{corp}", "done", 0)
    conn.execute("COMMIT")
    tally.check_corps += 1


def run_check(conn: sqlite3.Connection, caller: Caller, pairs: Sequence[Tuple[str, str]], tally: Tally, *, today: date,
              per_day: int = CHECK_CORPS_PER_DAY) -> None:
    q = quarter_of(today)
    tally.quarter = q
    done = {r[0].split(":", 1)[1] for r in conn.execute(
        "SELECT bas_dt FROM ingest_day WHERE source=? AND bas_dt LIKE ? AND status='done'", (SRC_CHECK, f"{q}:%"))}
    todo = [(s, c) for s, c in pairs if c not in done][:per_day]
    for stock, corp in todo:
        check_corp(conn, caller, corp, stock, q, today, tally)


def run_new_corps(conn: sqlite3.Connection, caller: Caller, pairs: Sequence[Tuple[str, str]], tally: Tally, *,
                  today: date, max_calls: int = NEW_CORP_MAX_CALLS) -> None:
    """줄도 부른 기록도 없는 회사 — 지난 해(2015 ~ )를 하루 상한 안에서. 남으면 다음 회차가 이어서."""
    asked = {r[0].split(":", 1)[0] for r in conn.execute("SELECT bas_dt FROM ingest_day WHERE source=?", (SRC_CALL,))}
    have = {r[0] for r in conn.execute("SELECT DISTINCT corp_code FROM financial_statement_full")}
    new = [(s, c) for s, c in pairs if c not in asked and c not in have]
    if not new or max_calls <= 0:
        return
    cap = tally.calls + max_calls
    sub = Caller(conn, tally, max_calls=min(cap, caller.max_calls) if caller.max_calls is not None else cap,
                 limiter=caller.lim, session=caller.sess)
    plan = periods(FIRST_YEAR, today.year, today)
    for stock, corp in new:
        try:
            fill_corp(conn, sub, corp, stock, plan, tally, today=today)
        except Stop:
            if caller.max_calls is not None and tally.calls >= caller.max_calls:
                raise                                   # 회차 상한 — 멈춤 그대로
            tally.notes.append(f"새로 든 회사 채우기는 하루 {max_calls}회까지 — 남은 것은 다음 회차가 이어서")
            return
        tally.new_corps += 1


def run_daily(conn: sqlite3.Connection, *, today: Optional[date] = None, max_calls: Optional[int] = None, session=None,
              limiter: Optional[RateLimiter] = None, corp_map: Optional[Dict] = None,
              check_per_day: int = CHECK_CORPS_PER_DAY, new_corp_calls: int = NEW_CORP_MAX_CALLS) -> Tally:
    today = today or date.today()
    tally = Tally()
    _ver, pairs, _missing = universe(conn, corp_map)
    corps = {c: s for s, c in pairs}
    caller = Caller(conn, tally, max_calls=max_calls, session=session, limiter=limiter)
    try:
        run_filings(conn, caller, corps, tally, today=today)
        run_check(conn, caller, pairs, tally, today=today, per_day=check_per_day)
        run_new_corps(conn, caller, pairs, tally, today=today, max_calls=new_corp_calls)
    except Stop as e:
        tally.stopped = str(e)
    except (dart.DartError, requests.RequestException, ValueError) as e:
        tally.errors.append(str(e).splitlines()[0][:200])
    conn.execute("BEGIN IMMEDIATE")
    link_first_known(conn)
    conn.execute("COMMIT")
    return tally


# ==================================================
# 4. 지난 해 채우기 — 회차 밖에서만
# ==================================================
def round_busy(now: Optional[datetime] = None) -> Optional[str]:
    """지금 지난 해 채우기를 하면 안 되는 까닭 한 줄 — 회차가 돌고 있음(잠금) · 12:20 ~ 13:20. 없으면 None."""
    now = now or datetime.now()
    (h0, m0), (h1, m1) = ROUND_GUARD
    hm = (now.hour, now.minute)
    if (h0, m0) <= hm < (h1, m1):
        return f"회차 시간({h0:02d}:{m0:02d} ~ {h1:02d}:{m1:02d})이라 멈춤 — {h1:02d}:{m1:02d} 뒤 같은 명령으로 이어 받는다"
    try:
        from scripts import daily_update as du      # 늦게 부른다 — 수집기 모듈이 러너를 읽지 않게(시험 · 다른 단계는 안 씀)
    except Exception:  # noqa: BLE001 — 러너를 못 읽으면 잠금은 모른다(시간 칸만 지킨다)
        return None
    held = du.lock_holder(du.LOCK_PATH)
    return f"정기 회차가 돌고 있어 멈춤 — {held}" if held else None


def run_backfill(conn: sqlite3.Connection, *, years: Tuple[int, int], max_calls: Optional[int], sleep: float = BACKFILL_SLEEP,
                 today: Optional[date] = None, session=None, limiter: Optional[RateLimiter] = None, guard=round_busy,
                 corp_map: Optional[Dict] = None) -> Tally:
    today = today or date.today()
    tally = Tally()
    _ver, pairs, _missing = universe(conn, corp_map)
    caller = Caller(conn, tally, max_calls=max_calls, sleep=sleep, session=session, limiter=limiter, guard=guard)
    plan = periods(years[0], years[1], today)
    try:
        for stock, corp in pairs:
            fill_corp(conn, caller, corp, stock, plan, tally, today=today)
    except Stop as e:
        tally.stopped = str(e)
    except (dart.DartError, requests.RequestException, ValueError) as e:
        tally.errors.append(str(e).splitlines()[0][:200])
    conn.execute("BEGIN IMMEDIATE")
    link_first_known(conn)
    conn.execute("COMMIT")
    return tally


# ==================================================
# 5. 일회 수집본 옮겨 담기(네트워크 0회)
# ==================================================
def seed(conn: sqlite3.Connection, raw_dir: Path, *, corp_map: Optional[Dict] = None) -> Dict[str, int]:
    """`raw_fs/<고유번호>/<연도>_<보고서>_<CFS|OFS>.json.gz` → 원문 · 줄 · 부른 기록. 받은 시각은 파일 시각(일회 수집 그때).
    값이 없던 응답(013)은 부른 기록만(원문은 남기지 않는다 — 주요계정 단계와 같음). 다시 돌려도 같은 줄(원문은 같은 열쇠로 바뀜)."""
    _ver, pairs, _missing = universe(conn, corp_map)
    stock_of = {c: s for s, c in pairs}
    out = {"files": 0, "with_data": 0, "empty": 0, "rows": 0, "outside": 0}
    tally = Tally()
    for f in sorted(Path(raw_dir).rglob("*.json.gz")):
        corp = f.parent.name
        y, rp, fs = f.name.split(".")[0].split("_")
        body = gzip.decompress(f.read_bytes())
        doc = json.loads(body.decode("utf-8"))
        st = str(doc.get("status", ""))
        out["files"] += 1
        if corp not in stock_of:
            out["outside"] += 1
        at = datetime.fromtimestamp(f.stat().st_mtime).astimezone().isoformat(timespec="seconds")
        _rcept, added = store(conn, corp, y, rp, fs, st if st == dart.DART_OK else dart.DART_NO_DATA, body, doc,
                              stock_code=stock_of.get(corp, ""), tally=tally, fetched_at=at)
        out["rows"] += added
        out["with_data" if st == dart.DART_OK else "empty"] += 1
    conn.execute("BEGIN IMMEDIATE")
    out["linked"] = link_first_known(conn)
    conn.execute("COMMIT")
    return out


# ==================================================
# 6. 상태 · 명령
# ==================================================
def status_lines(conn: sqlite3.Connection) -> List[str]:
    n, corps, versions = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT corp_code), COUNT(DISTINCT rcept_no) FROM financial_statement_full").fetchone()
    out = [f"  전체 재무제표 {n:,}줄 · 회사 {corps:,} · 판(접수번호) {versions:,}"]
    for r in conn.execute("SELECT bsns_year, COUNT(DISTINCT corp_code) c, COUNT(DISTINCT rcept_no) v FROM financial_statement_full "
                          "GROUP BY bsns_year ORDER BY bsns_year"):
        out.append(f"    {r['bsns_year']} · 회사 {r['c']:,} · 판 {r['v']:,}")
    st = conn.execute("SELECT source, status, COUNT(*) FROM ingest_day WHERE source IN (?,?,?) GROUP BY source, status",
                      (SRC_RCEPT, SRC_CALL, SRC_CHECK)).fetchall()
    out.append("  받기 기록: " + (" · ".join(f"{x[0]} {x[1]} {x[2]:,}" for x in st) or "없음"))
    q = quarter_of(date.today())
    ck = dict(conn.execute("SELECT result, COUNT(*) FROM financial_full_check WHERE quarter=? GROUP BY result", (q,)).fetchall())
    done = conn.execute("SELECT COUNT(*) FROM ingest_day WHERE source=? AND bas_dt LIKE ?", (SRC_CHECK, f"{q}:%")).fetchone()[0]
    out.append(f"  분기 대조 {q} — 회사 {done:,}곳 끝 · " + (" · ".join(f"{k} {v:,}" for k, v in sorted(ck.items())) or "아직 없음"))
    return out


def _report(t: Tally, what: str) -> None:
    print(f"{what} — 호출 {t.calls:,}회 · 새 줄 {t.rows:,} · 새 판 {t.versions:,}"
          + (f" · 새 보고서 끝 {t.filings_done} · 기다림 {t.filings_pending} · 값 없음 {t.filings_missing} · 밀림 {t.filings_superseded}"
             if what.startswith("전체 재무제표 매일") else "")
          + (f" · 대조 {t.quarter} {t.check_corps}곳(" + " · ".join(f"{k} {v}" for k, v in sorted(t.check.items())) + ")"
             if t.check_corps else "")
          + (f" · 새로 든 회사 {t.new_corps}" if t.new_corps else ""))
    for e in t.errors[:10]:
        print(f"  🟡 {e}")
    for n in t.notes:
        print(f"  · {n}")
    if t.check.get("silent_change"):
        print(f"🟡 조용한 고침 {t.check['silent_change']}건 — 같은 접수번호인데 API 값이 바뀌었다(우리 줄은 처음 받은 그대로 · "
              "원문은 raw_response 에 · financial_full_check 에서 본다)")
    if t.stopped:
        print(f"\n멈춤: {t.stopped}")


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.financials_full",
                                description="DART 전체 재무제표(분봉 유니버스 351곳) — 매일 · 지난 해 채우기 · 옮겨 담기")
    p.add_argument("mode", choices=["daily", "backfill", "seed", "status"])
    p.add_argument("--max-calls", type=int, default=None, help="이번 실행 호출 상한(매일 1,500 · 지난 해 15,000)")
    p.add_argument("--years", default="2015-2020", help="backfill — 사업연도 범위")
    p.add_argument("--sleep", type=float, default=BACKFILL_SLEEP, help="backfill — 호출 간격(초)")
    p.add_argument("--raw-dir", default="", help="seed — 일회 수집 raw_fs 폴더")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--db", default="", help="(시험용) 수집 DB 대신 쓸 SQLite 파일")
    a = p.parse_args(argv)
    conn = db.connect(Path(a.db) if a.db else None)
    try:
        if a.mode == "status":
            for ln in status_lines(conn):
                print(ln)
            return 0
        if a.mode == "seed":
            if not a.raw_dir:
                print("멈춤: seed 에는 --raw-dir(일회 수집 raw_fs 폴더)가 있어야 한다")
                return 2
            out = seed(conn, Path(a.raw_dir))
            print(f"전체 재무제표 옮겨 담기 — 원문 {out['files']:,}(값 있음 {out['with_data']:,} · 없음 {out['empty']:,}) · "
                  f"새 줄 {out['rows']:,} · 유니버스 밖 {out['outside']} · 처음 공개일 잇기 {out['linked']:,}(네트워크 0회)")
            return 0
        try:
            config.dart_key()
        except config.MissingKey as e:
            print(f"🔴 DART 인증키가 없어 받지 않는다 — {e}")
            return EX_CONFIG
        if a.mode == "daily":
            t = run_daily(conn, max_calls=a.max_calls if a.max_calls is not None else 1500)
            _report(t, "전체 재무제표 매일")
        else:
            busy = round_busy()
            if busy:
                print(f"멈춤: {busy}")
                return EX_STOPPED
            # 회차 밖에서 도는 큰 일이라 러너가 장부 경로를 넘겨 주지 않는다 — 스스로 적어 「오늘 DART 몇 번」 에 들어가게(기록만)
            import os
            os.environ.setdefault(dart.LEDGER_ENV, str(config.STATE_DIR / "dart_calls.jsonl"))
            y0, y1 = (int(x) for x in a.years.split("-"))
            t = run_backfill(conn, years=(y0, y1), max_calls=a.max_calls if a.max_calls is not None else 15_000,
                             sleep=a.sleep)
            _report(t, f"전체 재무제표 지난 해 {y0} ~ {y1}")
        if t.stopped:
            return EX_STOPPED
        return 1 if t.errors else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
