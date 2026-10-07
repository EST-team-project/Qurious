"""공시 목록 수집 — 상장사 공시를 유형(A~J)별로 받아 ``disclosure`` 표에 쌓는다 (목표 기능 ① W7 · 설계서 5.1.5).

무엇을 하나
-----------
전자공시(DART) ``list.json`` 을 시장(유가 Y · 코스닥 K · 코넥스 N) × 공시 유형(A~J)으로 나눠 부른다.
응답에는 유형 칸이 없어서(2026-10-04 실측 — 칸은 corp_code · corp_name · stock_code · corp_cls · report_nm ·
rcept_no · flr_nm · rcept_dt · rm 아홉뿐) **유형별로 불러야** 그 공시가 정기공시인지 거래소공시인지 안다.

네 가지 모드
------------
``daily``     최근 N일(기본 3일)을 유형 · 시장마다 다시 받는다. 12:30 러너의 ``disclosure`` 단계.
              평일 하루 상장사 공시는 약 700건(2026-09-30 유가 299 · 코스닥 374 · 코넥스 8)이라 30여 회면 된다.
``backfill``  지정 구간을 석 달 창으로 받는다. 끝낸 (창 · 유형 · 시장)은 ``ingest_day`` 에 남겨 다음 실행이
              건너뛴다 — 한도에 닿아 멈추면 그 자리부터 이어 간다.
``reparse``   보존한 목록 원문으로 다시 정규화한다(네트워크 0회).
``status``    현황.

이용 조건 (2026-10-04 원문 확인 · 조사서 ``docs/조사/지난판/공시-재무-뉴스-이용조건-조사_v0.1.md``)
- 개인 인증키는 **하루 20,000건**(83종 서비스 합계)이다(FAQ 「오픈API 이용한도」). 분당 1,000회 이상이면
  그 IP 를 1시간 막는다(FAQ 「IP 차단 문의」) → 호출 간격 ``config.DART_SLEEP`` 0.25초 = 분당 240회 이하.
- 이용약관 제19조② — 인증키를 제3자가 쓰게 하면 안 된다. 팀원은 각자 키로 돌린다(키는 ``.env`` 에만).
- FAQ 「상업적 사용」 — 공공데이터법의 공공데이터라 공개 · 활용은 제한되지 않고, 재배포 · 재가공 책임은 이용자.

정정 공시를 어떻게 다루나
-------------------------
정정본은 **새 접수번호**로 따로 온다(「[기재정정]사업보고서 (2025.12)」). 원본을 덮지 않고 둘 다 남긴다.
머리의 ``[...]`` 는 ``revision`` 칸으로, 정기보고서의 ``(YYYY.MM)`` 은 ``period`` 칸으로 떼어 둔다 —
재무제표의 「그 기간 보고서가 처음 나온 날(first_known_at)」 을 이 두 칸으로 찾는다(``collector/financials.py``).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from collector import config, db, raw_store
from collector.console import utf8_stdio
from collector.ratelimit import RateLimiter
from collector.sources import dart

#: 공시 유형(DART pblntf_ty). 이름은 DART 개발가이드 「공시검색」 의 값 설명 그대로.
TYPES: Dict[str, str] = {
    "A": "정기공시", "B": "주요사항보고", "C": "발행공시", "D": "지분공시", "E": "기타공시",
    "F": "외부감사관련", "G": "펀드공시", "H": "자산유동화", "I": "거래소공시", "J": "공정위공시",
}

#: 시장 구분(DART corp_cls). 기타법인(E)은 받지 않는다 — 종목 코드가 없어 이름표 · 시세와 잇지 못한다.
MARKETS: Dict[str, str] = {"Y": "유가증권", "K": "코스닥", "N": "코넥스"}

#: 과거분을 받는 시작. 시세 · 배당이 2020-01-02 부터라 맞춘다.
DEFAULT_FROM = "20200101"

#: 일일 갱신이 다시 받는 날 수. 정기보고서 마감일에는 API 반영이 익영업일까지 늦을 수 있어
#: (FAQ 「데이터 반영시점」) 하루치만 보면 늦게 올라온 공시를 놓친다.
DAILY_DAYS = 3

#: 한 번에 받는 줄 수 — DART 상한(1~100).
PAGE_COUNT = 100

#: 원문 보존 대상 이름의 머리. ``list/<유형><시장>/<시작>-<끝>/p<쪽>``
RAW_PREFIX = "list/"

#: 「보고서 이름 (YYYY.MM)」 — 정기보고서 기간.
_PERIOD = re.compile(r"\((\d{4})\.(\d{2})\)\s*$")
#: 머리의 [기재정정] · [첨부추가] … (여럿이 붙을 수 있다)
_REVISION = re.compile(r"^\s*((?:\[[^\]]*\]\s*)+)")
#: 이름과 꼬리 설명 사이의 긴 공백(응답은 이름 뒤에 공백 여럿 + 「(설명)」 을 붙인다 · 실측 2026-10-04)
_GAP = re.compile(r"\s{2,}")


def _now() -> str:
    return raw_store.now_kst_iso()


# ==================================================
# 1. 이름 나누기 — 네트워크 없이 시험한다(TC-DC)
# ==================================================
@dataclass
class ReportName:
    report_nm: str       # 공백만 접은 원문
    title: str           # 머리 [..] · 꼬리 설명 · 정기보고서 기간을 뗀 이름
    revision: str        # 머리 [..] 안 글 — 여럿이면 「·」 로 잇는다
    period: str          # 정기보고서 기간 YYYY.MM — 없으면 빈칸


def split_report_nm(raw: str) -> ReportName:
    """``report_nm`` 원문을 칸으로 나눈다.

    예) ``"[기재정정]주주총회소집결의              (임시주주총회)"``
        → title ``주주총회소집결의`` · revision ``기재정정`` · report_nm ``[기재정정]주주총회소집결의 (임시주주총회)``
        ``"사업보고서 (2025.12)"`` → title ``사업보고서`` · period ``2025.12``
    ⚠️ 꼬리 설명은 **공백 둘 이상** 뒤에 온다. 정기보고서의 ``(2025.12)`` 는 공백 하나 뒤라 꼬리가 아니다 —
       그래서 공백을 먼저 접으면 둘을 가를 수 없다(접기 전에 나눈다).
    """
    raw = raw or ""
    revision = ""
    m = _REVISION.match(raw)
    body = raw
    if m:
        revision = "·".join(x.strip("[] ") for x in re.findall(r"\[[^\]]*\]", m.group(1)) if x.strip("[] "))
        body = raw[m.end():]
    base = _GAP.split(body.strip(), maxsplit=1)[0].strip()
    period = ""
    pm = _PERIOD.search(base)
    if pm:
        period = f"{pm.group(1)}.{pm.group(2)}"
        base = base[:pm.start()].strip()
    return ReportName(report_nm=" ".join(raw.split()), title=base, revision=revision, period=period)


def normalize_item(item: Dict, pblntf_ty: str, *, fetched_at: str, raw_sha256: str = "") -> Dict:
    """목록 한 줄 → ``disclosure`` 한 행."""
    nm = split_report_nm(str(item.get("report_nm") or ""))
    rcept_no = str(item.get("rcept_no") or "").strip()
    return {
        "rcept_no": rcept_no,
        "rcept_dt": str(item.get("rcept_dt") or rcept_no[:8]).strip(),
        "corp_code": str(item.get("corp_code") or "").strip(),
        "corp_name": str(item.get("corp_name") or "").strip(),
        "stock_code": str(item.get("stock_code") or "").strip(),
        "corp_cls": str(item.get("corp_cls") or "").strip(),
        "pblntf_ty": pblntf_ty,
        "report_nm": nm.report_nm,
        "title": nm.title,
        "revision": nm.revision,
        "period": nm.period,
        "flr_nm": str(item.get("flr_nm") or "").strip(),
        "rm": str(item.get("rm") or "").strip(),
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
        "raw_sha256": raw_sha256,
    }


_COLS = ("rcept_no", "rcept_dt", "corp_code", "corp_name", "stock_code", "corp_cls", "pblntf_ty",
         "report_nm", "title", "revision", "period", "flr_nm", "rm", "fetched_at", "updated_at", "raw_sha256")

#: 다시 받으면 fetched_at(처음 받은 시각)은 그대로 · 나머지는 새 값. 유형은 빈칸으로 덮지 않는다.
_UPSERT = (
    f"INSERT INTO disclosure ({', '.join(_COLS)}) VALUES ({', '.join('?' * len(_COLS))}) "
    "ON CONFLICT(rcept_no) DO UPDATE SET "
    "rcept_dt=excluded.rcept_dt, corp_code=excluded.corp_code, corp_name=excluded.corp_name, "
    "stock_code=excluded.stock_code, corp_cls=excluded.corp_cls, "
    "pblntf_ty=CASE WHEN excluded.pblntf_ty <> '' THEN excluded.pblntf_ty ELSE disclosure.pblntf_ty END, "
    "report_nm=excluded.report_nm, title=excluded.title, revision=excluded.revision, period=excluded.period, "
    "flr_nm=excluded.flr_nm, rm=excluded.rm, updated_at=excluded.updated_at, raw_sha256=excluded.raw_sha256"
)


def upsert_rows(conn: sqlite3.Connection, rows: Iterable[Dict]) -> int:
    """행을 넣거나 고친다. 넣은 줄 수(접수번호가 빈 줄은 버린다)를 돌려준다. 트랜잭션은 부르는 쪽이 잡는다."""
    n = 0
    for r in rows:
        if not r["rcept_no"] or not r["corp_code"]:
            continue
        conn.execute(_UPSERT, tuple(r[c] for c in _COLS))
        n += 1
    return n


# ==================================================
# 2. 받기
# ==================================================
def _limiter() -> RateLimiter:
    return RateLimiter(config.DART_SLEEP, reserve=config.DART_RESERVE, name="DART")


def raw_target(pblntf_ty: str, corp_cls: str, bgn: str, end: str, page: int) -> str:
    return f"{RAW_PREFIX}{pblntf_ty}{corp_cls}/{bgn}-{end}/p{page}"


def parse_raw_target(target: str) -> Optional[Tuple[str, str, str, str, int]]:
    """``list/AY/20260101-20260331/p2`` → (A, Y, 20260101, 20260331, 2)."""
    m = re.match(r"^list/([A-J])([YKN])/(\d{8})-(\d{8})/p(\d+)$", target or "")
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3), m.group(4), int(m.group(5))


def _save_raw_if_changed(conn: sqlite3.Connection, target: str, body: bytes, status: int) -> str:
    """원문을 남긴다 — 가장 최근 보존본과 같으면 새로 쌓지 않는다(매일 같은 사흘을 다시 받으므로)."""
    import hashlib
    digest = hashlib.sha256(body).hexdigest()
    row = conn.execute(
        "SELECT sha256 FROM raw_response WHERE source='dart' AND target=? ORDER BY fetched_at DESC LIMIT 1",
        (target,)).fetchone()
    if row and row[0] == digest:
        return digest
    return raw_store.save(conn, "dart", target, body, http_status=status, note=f"bytes={len(body)}")


@dataclass
class Tally:
    calls: int = 0
    rows: int = 0
    new: int = 0
    combos: int = 0
    errors: List[str] = field(default_factory=list)
    stopped: str = ""


def fetch_combo(conn: sqlite3.Connection, limiter: RateLimiter, session: requests.Session, *,
                pblntf_ty: str, corp_cls: str, bgn: str, end: str, tally: Tally,
                max_calls: Optional[int] = None) -> int:
    """(유형 · 시장 · 기간) 하나를 끝 쪽까지 받는다. 넣은 줄 수.

    ⚠️ 기간이 3개월을 넘으면 DART 가 ``status=100`` 으로 거부한다(#33 실측) — 부르는 쪽이 석 달 창으로 자른다.
    """
    page, total_page, got = 1, 1, 0
    while page <= total_page:
        if max_calls is not None and limiter.calls >= max_calls:
            raise dart.DartQuotaExceeded(f"이번 실행의 호출 상한 {max_calls:,}회에 닿았다 — 다시 돌리면 이어서 간다")
        r = dart._get(limiter, config.DART_LIST_URL, {  # noqa: SLF001 — 배당 수집기와 같은 호출 · 간격 규칙
            "bgn_de": bgn, "end_de": end, "corp_cls": corp_cls, "pblntf_ty": pblntf_ty,
            "page_no": page, "page_count": PAGE_COUNT,
        }, session=session)
        tally.calls += 1
        if r.status_code != 200:
            raise dart.DartError(f"목록 HTTP {r.status_code} ({pblntf_ty}{corp_cls} {bgn}~{end} p{page})")
        body = r.content
        doc = json.loads(body.decode("utf-8"))
        status = str(doc.get("status", ""))
        dart._check_status(status, str(doc.get("message", "")),  # noqa: SLF001
                           f"목록 {pblntf_ty}{corp_cls} {bgn}~{end} p{page}")
        if status == dart.DART_NO_DATA:
            return got
        total_page = int(doc.get("total_page") or 1)
        fetched_at = _now()
        conn.execute("BEGIN IMMEDIATE")
        try:
            sha = _save_raw_if_changed(conn, raw_target(pblntf_ty, corp_cls, bgn, end, page), body, r.status_code)
            items = doc.get("list") or []
            known = {x[0] for x in conn.execute(
                f"SELECT rcept_no FROM disclosure WHERE rcept_no IN ({','.join('?' * len(items))})",
                [str(i.get("rcept_no") or "") for i in items]).fetchall()} if items else set()
            n = upsert_rows(conn, (normalize_item(i, pblntf_ty, fetched_at=fetched_at, raw_sha256=sha)
                                   for i in items))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        got += n
        tally.rows += n
        tally.new += sum(1 for i in items if str(i.get("rcept_no") or "") not in known)
        page += 1
    return got


def quarter_windows(bgn: str, end: str) -> List[Tuple[str, str]]:
    """[bgn, end] 를 달력 분기로 자른 창 목록. 끝 창은 end 에서 끊는다."""
    b = datetime.strptime(bgn, "%Y%m%d").date()
    e = datetime.strptime(end, "%Y%m%d").date()
    out: List[Tuple[str, str]] = []
    cur = b
    while cur <= e:
        q_end_month = ((cur.month - 1) // 3) * 3 + 3
        nxt = date(cur.year + (1 if q_end_month == 12 else 0), 1 if q_end_month == 12 else q_end_month + 1, 1)
        stop = min(nxt - timedelta(days=1), e)
        out.append((cur.strftime("%Y%m%d"), stop.strftime("%Y%m%d")))
        cur = nxt
    return out


def _mark(conn: sqlite3.Connection, key: str, status: str, rows: int, message: str = "") -> None:
    conn.execute(
        "INSERT INTO ingest_day (source, bas_dt, status, rows, attempts, updated_at, message) "
        "VALUES ('dart_list', ?, ?, ?, 1, ?, ?) "
        "ON CONFLICT(source, bas_dt) DO UPDATE SET status=excluded.status, rows=excluded.rows, "
        "attempts=ingest_day.attempts+1, updated_at=excluded.updated_at, message=excluded.message",
        (key, status, rows, _now(), message[:500]))


def combo_key(bgn: str, end: str, pblntf_ty: str, corp_cls: str) -> str:
    return f"{bgn}-{end}:{pblntf_ty}{corp_cls}"


def run(*, bgn: str, end: str, types: Sequence[str], markets: Sequence[str], resume: bool,
        max_calls: Optional[int], quiet: bool = False) -> Tally:
    """창 · 유형 · 시장을 차례로 받는다. ``resume=True`` 면 ``ingest_day`` 에 done 인 조합은 건너뛴다.

    끝나지 않은 창(오늘이 든 분기)은 done 으로 남기지 않는다 — 다음 실행이 다시 받아야 새 공시가 들어온다.
    """
    conn = db.connect()
    limiter = _limiter()
    session = requests.Session()
    tally = Tally()
    today = datetime.now().strftime("%Y%m%d")
    done = {r[0] for r in conn.execute(
        "SELECT bas_dt FROM ingest_day WHERE source='dart_list' AND status='done'")} if resume else set()
    windows = quarter_windows(bgn, min(end, today))
    plan = [(w, t, m) for w in windows for t in types for m in markets]
    todo = [(w, t, m) for (w, t, m) in plan if combo_key(w[0], w[1], t, m) not in done]
    if not quiet:
        print(f"공시 목록 — 창 {len(windows)}개 × 유형 {len(types)} × 시장 {len(markets)} = {len(plan)}조합 "
              f"· 이미 끝남 {len(plan) - len(todo)} · 이번 {len(todo)}")
    for i, ((wb, we), t, m) in enumerate(todo, 1):
        key = combo_key(wb, we, t, m)
        try:
            n = fetch_combo(conn, limiter, session, pblntf_ty=t, corp_cls=m, bgn=wb, end=we,
                            tally=tally, max_calls=max_calls)
        except dart.DartQuotaExceeded as exc:
            tally.stopped = str(exc)
            break
        except (dart.DartError, requests.RequestException, ValueError) as exc:
            tally.errors.append(f"{key}: {str(exc).splitlines()[0][:200]}")
            conn.execute("BEGIN IMMEDIATE")
            _mark(conn, key, "error", 0, str(exc))
            conn.execute("COMMIT")
            continue
        tally.combos += 1
        closed = we < today
        conn.execute("BEGIN IMMEDIATE")
        _mark(conn, key, "done" if closed else "partial", n)
        conn.execute("COMMIT")
        if not quiet and (i % 30 == 0 or i == len(todo)):
            print(f"  {i}/{len(todo)} · {key} · 이번 실행 호출 {tally.calls:,} · 넣은 줄 {tally.rows:,}", flush=True)
    conn.close()
    return tally


def run_daily(*, days: int = DAILY_DAYS, quiet: bool = False,
              max_calls: Optional[int] = None) -> Tally:
    """최근 ``days`` 일을 유형 · 시장마다 다시 받는다(진행 기록 없이 늘 다시)."""
    end = datetime.now()
    bgn = end - timedelta(days=days - 1)
    return run(bgn=bgn.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"), types=list(TYPES),
               markets=list(MARKETS), resume=False, max_calls=max_calls, quiet=quiet)


def run_reparse(*, quiet: bool = False) -> int:
    """보존한 목록 원문으로 다시 정규화한다. **네트워크 0회.** 처음 받은 시각은 원문을 받은 시각으로 둔다."""
    conn = db.connect()
    n = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for rec in raw_store.iter_latest(conn, "dart", prefix=RAW_PREFIX):
            parsed = parse_raw_target(rec["target"])
            if not parsed:
                continue
            doc = json.loads(rec["body"].decode("utf-8"))
            items = doc.get("list") or []
            n += upsert_rows(conn, (normalize_item(i, parsed[0], fetched_at=rec["fetched_at"],
                                                   raw_sha256=rec["sha256"]) for i in items))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.close()
    if not quiet:
        print(f"다시 정규화 {n:,}줄(네트워크 0회)")
    return n


def print_status() -> None:
    conn = db.connect()
    tot = conn.execute("SELECT COUNT(*), MIN(rcept_dt), MAX(rcept_dt) FROM disclosure").fetchone()
    print(f"공시 {tot[0]:,}건 · {tot[1]} ~ {tot[2]}")
    for r in conn.execute("SELECT substr(rcept_dt,1,4) y, COUNT(*) n FROM disclosure GROUP BY y ORDER BY y"):
        print(f"  {r['y']} {r['n']:,}건")
    by_ty = conn.execute("SELECT pblntf_ty, COUNT(*) n FROM disclosure GROUP BY pblntf_ty ORDER BY pblntf_ty").fetchall()
    print("  유형: " + " · ".join(f"{r['pblntf_ty'] or '?'} {TYPES.get(r['pblntf_ty'], '')} {r['n']:,}" for r in by_ty))
    st = conn.execute("SELECT status, COUNT(*) FROM ingest_day WHERE source='dart_list' GROUP BY status").fetchall()
    print("  받기 기록: " + " · ".join(f"{r[0]} {r[1]}" for r in st))
    conn.close()


def _report(t: Tally, quiet: bool) -> None:
    print(f"공시 목록 — 호출 {t.calls:,}회 · 넣거나 고친 줄 {t.rows:,} · 새 공시 {t.new:,} · 끝낸 조합 {t.combos:,}"
          + (f" · 오류 {len(t.errors)}" if t.errors else ""))
    for e in t.errors[:10]:
        print(f"  🟡 {e}")
    if t.stopped:
        print(f"\n멈춤: {t.stopped}")


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.disclosure",
                                description="DART 공시 목록 수집(상장사 · 유형 A~J)")
    p.add_argument("mode", choices=["daily", "backfill", "reparse", "status"])
    p.add_argument("--days", type=int, default=DAILY_DAYS, help="daily — 다시 받을 최근 날 수")
    p.add_argument("--from", dest="bgn", default=DEFAULT_FROM, help="backfill 시작 YYYYMMDD")
    p.add_argument("--to", dest="end", default=datetime.now().strftime("%Y%m%d"), help="backfill 끝 YYYYMMDD")
    p.add_argument("--types", default="".join(TYPES), help="받을 유형 글자(기본 ABCDEFGHIJ)")
    p.add_argument("--markets", default="".join(MARKETS), help="받을 시장 글자(기본 YKN)")
    p.add_argument("--max-calls", type=int, default=config.DART_DAILY_LIMIT - config.DART_RESERVE,
                   help="이번 실행의 호출 상한 — DART 는 남은 횟수를 알려 주지 않아 직접 센다")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)
    if a.mode == "status":
        print_status()
        return 0
    if a.mode == "reparse":
        run_reparse(quiet=a.quiet)
        return 0
    if a.mode == "daily":
        t = run_daily(days=a.days, quiet=a.quiet, max_calls=a.max_calls)
    else:
        types = [x for x in a.types.upper() if x in TYPES]
        markets = [x for x in a.markets.upper() if x in MARKETS]
        t = run(bgn=a.bgn, end=a.end, types=types, markets=markets, resume=True,
                max_calls=a.max_calls, quiet=a.quiet)
    _report(t, a.quiet)
    # 한도에 닿아 멈췄으면 3(다시 돌리면 이어 간다) · 오류가 있으면 1 — 러너가 🟡 로 보인다
    if t.stopped:
        return 3
    return 1 if t.errors else 0


if __name__ == "__main__":
    sys.exit(main())
