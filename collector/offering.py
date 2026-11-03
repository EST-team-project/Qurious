"""공모 청약 · 납입 일정 — OpenDART 증권신고서(지분증권) 주요정보 (할 일 ①-23 F-lite · 2026-11-03 S195).

범위(사용자 결정 2026-11-03): **이미 수집 범위에 있는 상장사**(공시 목록 `disclosure` 에 종목코드가 있는 회사)의 지분증권
증권신고서 — 대부분 유상증자다. 상장일 · 비상장 IPO 는 만들지 않는다(다음 판).

받는 길
-------
`estkRs.json`(apiId 2020054) 은 `corp_code` 가 필수이고 구간(`bgn_de` · `end_de`)은 **최초접수일** 기준이다(2026-11-03 실측 —
정정 신고서의 접수일로 물으면 013 「조회된 데이타가 없습니다」). 그래서
  1. 공시 목록에서 최근 `WINDOW_DAYS` 일 안에 「증권신고서(지분증권)」(정정 · 발행조건확정 포함)을 낸 회사를 고르고,
  2. 그 회사의 마지막 신고서 뒤로 아직 받지 않았으면(마지막 신고서 접수일 + 2일까지는 하루 한 번 더 받는다 — API 반영이
     늦을 수 있어서) 회사마다 한 번, 최근 `LOOKBACK_DAYS` 일(최초접수일)을 묻는다.
  3. 응답 원문(JSON)은 `raw_response`(dart · `estk/<corp_code>`)에 남기고, 읽기는 회사마다 **가장 최근 원문**에서 한다 —
     응답은 신고서 묶음마다 마지막 정정본 한 줄(접수번호 = 마지막 정정본)을 준다.
호출은 매일 단계(`corp_schedule daily`)의 DART 몫 안에서 센다 — 새 신고서가 없는 날은 0회.

응답 모양(2026-11-03 실측 3건 · 뷰노 · 상지건설 · 한솔아이원스)
-----------------------------------------------------------------
- `일반사항` 의 `sbd`(청약기일)는 「2026년 12월 18일 ~ 2026년 12월 21일」 꼴의 **기간**, `pymd`(납입기일)는 「2026년 12월 29일」.
- `증권의종류` 의 `slprc`(모집가액) · `slta`(모집총액)는 「4,980」 · 「31,374,000,000」 꼴 글자.
- 발행조건확정 신고서를 낸 뒤에도 응답의 접수번호가 그 앞 정정본인 경우가 있었다(상지건설) — 가격 · 날짜는
  **증권신고서 기준이며 정정될 수 있다**고 화면에 적는다.

지키는 것
--------
- 날짜를 못 읽으면 일정을 만들지 않는다(행은 빈 날짜로 남겨 센다 — `corp_schedule` 원칙). 청약은 시작일에 한 줄(기간은 설명에).
- 같은 회사가 그 신고서보다 뒤에 「철회신고서」 를 냈으면 달력에 올리지 않는다(열리지 않을 청약을 예정으로 보이지 않게 —
  주총 철회와 같은 원칙). 철회신고서는 어느 신고서를 물리는지 번호가 없어 「같은 회사 · 더 늦은 접수번호」 로 판정한다.
- 표는 `corp_schedule`(kind offer_sub · offer_pay)에 둔다 — 원문에서 언제든 다시 만든다(`build` 는 두 종류를 비우고 다시 읽는다).
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from collector import config, raw_store

ESTK_URL = "https://opendart.fss.or.kr/api/estkRs.json"
EQUITY_TITLE = "증권신고서(지분증권)"
WITHDRAW_TITLE = "철회신고서"
#: 대상 회사 — 최근 이 날 수 안에 지분증권 신고서(정정 포함)를 낸 상장사.
WINDOW_DAYS = 90
#: 묻는 구간(최초접수일) — 정정이 몇 달 뒤에 와도 원 신고서가 들어오게(상지건설은 원 신고서 뒤 5개월 넘게 정정이 이어졌다).
LOOKBACK_DAYS = 365
#: 마지막 신고서 접수일 뒤 이 날 수까지는 하루 한 번 다시 받는다(API 반영이 늦을 수 있다).
REFETCH_DAYS = 2

#: 받는 도중 안전장치(코드 검수 · 2026-11-03) — DART 가 느리거나 막힌 날 회차(일정 단계 15분 한도)를 붙잡지 않게.
#: 연속 실패가 이만큼이면 멈추고 남은 회사는 다음 회차로 · 공모 받기 전체가 이 초를 넘기면 멈춘다.
MAX_CONSECUTIVE_ERRORS = 3
MAX_FETCH_SECONDS = 300
KINDS = ("offer_sub", "offer_pay")
RAW_PREFIX = "estk"

_DATE = re.compile(r"(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ==================================================
# 1. 읽기 — 네트워크 없이 시험한다(TC-EV)
# ==================================================
def dates_in(text: str) -> List[str]:
    """글 안의 날짜(YYYY-MM-DD) 차례대로 — 없는 날짜(2월 30일)는 버린다. 추측해 채우지 않는다."""
    out = []
    for y, m, d in _DATE.findall(text or ""):
        try:
            out.append(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            continue
    return out


def _won(s: str) -> Optional[int]:
    t = re.sub(r"[,\s원]", "", s or "")
    return int(t) if t.isdigit() else None


def _money(n: int) -> str:
    """모집총액을 쉬운 말로 — 1억 이상은 억 원(소수 한 자리), 그 아래는 원."""
    return f"{n / 1e8:,.1f}억 원" if n >= 100_000_000 else f"{n:,}원"


def parse_estk(body: bytes) -> List[Dict[str, object]]:
    """estkRs 응답 원문 → 신고서 묶음마다 한 줄 — 접수번호 · 회사 · 청약 시작 · 끝 · 납입 · 원문 칸 글 · 증권(종류 · 가액 · 총액 · 방법).

    정상이 아니면(013 데이터 없음 포함) 빈 목록. 모양이 다르면 예외 — 부르는 쪽이 그 회사만 건너뛴다.
    """
    doc = json.loads(body.decode("utf-8"))
    if str(doc.get("status", "")) != "000":
        return []
    groups = {g.get("title"): g.get("list") or [] for g in doc.get("group") or []}
    secs: Dict[str, List[Dict[str, object]]] = {}
    for it in groups.get("증권의종류", []):
        secs.setdefault(str(it.get("rcept_no", "")), []).append({
            "kind": str(it.get("stksen") or "").strip(), "price": _won(str(it.get("slprc") or "")),
            "total": _won(str(it.get("slta") or "")), "method": str(it.get("slmthn") or "").strip()})
    out = []
    for it in groups.get("일반사항", []):
        rno = str(it.get("rcept_no") or "")
        if not re.fullmatch(r"\d{14}", rno):
            continue
        sbd, pymd = str(it.get("sbd") or "").strip(), str(it.get("pymd") or "").strip()
        sub = dates_in(sbd)
        pay = dates_in(pymd)
        out.append({
            "rcept_no": rno, "corp_code": str(it.get("corp_code") or ""), "corp_name": str(it.get("corp_name") or ""),
            "sub_start": sub[0] if sub else "", "sub_end": sub[-1] if sub else "", "pay": pay[0] if pay else "",
            "sub_text": sbd, "pay_text": pymd, "securities": secs.get(rno, []),
        })
    return out


def _detail(o: Dict[str, object], kind: str) -> str:
    parts = []
    if kind == "offer_sub":
        parts.append(f"청약 {o['sub_start']} ~ {o['sub_end']}" if o["sub_start"] else f"청약기일 칸: {o['sub_text'] or '비어 있음'}")
        if o["pay"]:
            parts.append(f"납입 {o['pay']}")
    else:
        parts.append(f"납입 {o['pay']}" if o["pay"] else f"납입기일 칸: {o['pay_text'] or '비어 있음'}")
        if o["sub_start"]:
            parts.append(f"청약 {o['sub_start']} ~ {o['sub_end']}")
    secs = o.get("securities") or []
    methods = sorted({str(s["method"]) for s in secs if s.get("method")})
    if methods:
        parts.append(" · ".join(methods))
    for s in secs:
        if s.get("price"):
            parts.append(f"{s['kind'] or '증권'} 1주 {int(s['price']):,}원")
    total = sum(int(s["total"]) for s in secs if s.get("total"))
    if total:
        parts.append(f"모집총액 {_money(total)}")
    parts.append("증권신고서 기준 — 정정될 수 있음")
    return " · ".join(parts)


# ==================================================
# 2. 받기 — 매일 단계(corp_schedule daily)의 DART 몫 안에서
# ==================================================
def _fetched(conn: sqlite3.Connection) -> Dict[str, str]:
    """회사(corp_code) → 마지막으로 받은 날(YYYYMMDD · KST)."""
    out = {}
    for target, at in conn.execute(
            "SELECT target, MAX(fetched_at) FROM raw_response WHERE source='dart' AND target LIKE ? GROUP BY target",
            (RAW_PREFIX + "/%",)):
        out[target.split("/", 1)[1]] = str(at)[:10].replace("-", "")
    return out


def targets(conn: sqlite3.Connection, today: date, *, days: int = WINDOW_DAYS) -> List[Tuple[str, str]]:
    """받을 회사 — [(corp_code, 마지막 지분증권 신고서 접수일 YYYYMMDD)]. 오늘 이미 받았거나, 마지막 신고서 + 2일 뒤에 받았으면 뺀다."""
    since = (today - timedelta(days=days)).strftime("%Y%m%d")
    iso_today = today.strftime("%Y%m%d")
    have = _fetched(conn)
    out = []
    for corp, last in conn.execute(
            "SELECT corp_code, MAX(rcept_dt) FROM disclosure WHERE title = ? AND stock_code <> '' AND rcept_dt >= ? "
            "GROUP BY corp_code ORDER BY MAX(rcept_dt) DESC, corp_code", (EQUITY_TITLE, since)):
        got = have.get(corp)
        if got:
            if got >= iso_today:
                continue                     # 오늘 이미 받았다
            until = (datetime.strptime(last, "%Y%m%d").date() + timedelta(days=REFETCH_DAYS)).strftime("%Y%m%d")
            if got > until:
                continue                     # 마지막 신고서 뒤로 넉넉히 받았다
        out.append((corp, last))
    return out


def _status_of(body: bytes) -> str:
    """estkRs 응답의 status(000 정상 · 013 데이터 없음). 읽을 수 없으면 빈 글."""
    try:
        return str(json.loads(body).get("status", ""))
    except Exception:  # noqa: BLE001
        return ""


def _call_dart(corp_code: str, bgn_de: str, end_de: str, limiter, session) -> bytes:
    from collector.sources import dart

    r = dart._get(limiter, ESTK_URL, {"corp_code": corp_code, "bgn_de": bgn_de, "end_de": end_de}, session=session)
    if r.status_code != 200:
        raise dart.DartError(f"증권신고서(지분증권) 조회 HTTP {r.status_code} (corp_code={corp_code})")
    doc = r.json()
    dart._check_status(str(doc.get("status", "")), str(doc.get("message", "")), f"증권신고서(지분증권) {corp_code}")
    return r.content


def fetch_recent(conn: sqlite3.Connection, today: date, *, max_calls: int, quiet: bool = True,
                 call: Optional[Callable[[str, str, str], bytes]] = None) -> Dict[str, object]:
    """대상 회사마다 estkRs 를 한 번 — 원문을 남긴다. 한 회사의 오류는 세고 넘어가고, 하루 한도면 멈춘다.

    `call(corp_code, bgn_de, end_de) -> 응답 바이트` 를 넘기면 그것을 쓴다(시험). 기본은 DART(키는 기존 수집기의 환경변수).
    """
    todo = targets(conn, today)
    out: Dict[str, object] = {"todo": len(todo), "fetched": 0, "errors": 0, "calls": 0, "quota": False}
    if not todo or max_calls <= 0:
        out["left"] = len(todo)
        return out
    if call is None:
        import requests

        from collector.ratelimit import RateLimiter

        limiter = RateLimiter(config.DART_SLEEP, reserve=config.DART_RESERVE, name="DART")
        session = requests.Session()

        def call(corp: str, bgn: str, end: str) -> bytes:  # noqa: E306 — 기본 호출(DART)
            return _call_dart(corp, bgn, end, limiter, session)

    bgn = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    done = 0
    started = time.monotonic()
    streak = 0                               # 연속 실패 수 — 성공하면 0
    out["kept"] = 0                          # 정정 반영이 늦어 013(데이터 없음)이 와서, 있던 좋은 원문을 그대로 둔 회사 수
    for corp, _last in todo:
        if int(out["calls"]) >= max_calls:
            break
        if time.monotonic() - started > MAX_FETCH_SECONDS:
            out["timed_out"] = True
            break
        out["calls"] = int(out["calls"]) + 1
        try:
            body = call(corp, bgn, end)
        except Exception as e:  # noqa: BLE001 — 한 회사 오류가 일정 단계를 멈추지 않게(하루 한도만 멈춘다)
            if type(e).__name__ == "DartQuotaExceeded":
                out["quota"] = True
                break
            out["errors"] = int(out["errors"]) + 1
            if not quiet:
                print(f"  ⚠️ 증권신고서(지분증권) {corp} 건너뜀 — {type(e).__name__}: {str(e)[:120]}")
            done += 1
            streak += 1
            if streak >= MAX_CONSECUTIVE_ERRORS:      # DART 가 막혔거나 느리다 — 더 불러도 같다
                out["stopped_on_errors"] = True
                break
            continue
        streak = 0
        if _status_of(body) != "000":
            prev = raw_store.load(conn, "dart", f"{RAW_PREFIX}/{corp}")
            if prev is not None and _status_of(prev["body"]) == "000":
                out["kept"] = int(out["kept"]) + 1    # 있던 공모 일정을 013 이 지우지 않게(빈 응답이면 지우지 않기)
                done += 1
                continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            raw_store.save(conn, "dart", f"{RAW_PREFIX}/{corp}", body, http_status=200,
                           note=f"bgn_de={bgn} end_de={end}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        out["fetched"] = int(out["fetched"]) + 1
        done += 1
    out["left"] = len(todo) - done
    return out


# ==================================================
# 3. 표 만들기 · 달력 일정
# ==================================================
def build(conn: sqlite3.Connection, *, at: Optional[str] = None) -> Dict[str, int]:
    """회사마다 가장 최근 원문을 읽어 `corp_schedule` 의 offer_sub · offer_pay 를 다시 만든다(호출 없음 · 두 종류는 비우고 다시)."""
    at = at or _now_iso()
    has_disc = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='disclosure'").fetchone()
    stock = {}
    withdrawn: Dict[str, str] = {}
    if has_disc:
        for corp, code in conn.execute(
                "SELECT corp_code, stock_code FROM disclosure WHERE title = ? AND stock_code <> '' ORDER BY rcept_no",
                (EQUITY_TITLE,)):
            stock[corp] = code
        for corp, rno in conn.execute(
                "SELECT corp_code, MAX(rcept_no) FROM disclosure WHERE title = ? GROUP BY corp_code", (WITHDRAW_TITLE,)):
            withdrawn[corp] = rno
    rows: List[tuple] = []
    out = {"offers": 0, "dated": 0, "withdrawn": 0, "unreadable": 0}
    for kept in raw_store.iter_latest(conn, "dart", prefix=RAW_PREFIX + "/"):
        corp = kept["target"].split("/", 1)[1]
        try:
            offers = parse_estk(kept["body"])
        except Exception:                    # 깨진 원문 한 건이 전체를 멈추지 않게
            out["unreadable"] += 1
            continue
        for o in offers:
            code = stock.get(str(o["corp_code"]) or corp) or stock.get(corp, "")
            if not code:
                continue                     # 수집 범위(상장사) 밖
            if withdrawn.get(corp, "") > str(o["rcept_no"]):
                out["withdrawn"] += 1
                continue
            out["offers"] += 1
            out["dated"] += bool(o["sub_start"])
            for kind, d in (("offer_sub", o["sub_start"]), ("offer_pay", o["pay"])):
                rows.append((o["rcept_no"], kind, code, o["corp_name"], d, "", "공모", _detail(o, kind), "",
                             kept["sha256"], at))
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"DELETE FROM corp_schedule WHERE kind IN ({','.join('?' * len(KINDS))})", KINDS)
        conn.executemany("INSERT OR REPLACE INTO corp_schedule (rcept_no, kind, stock_code, corp_name, event_date, "
                         "event_time, label, detail, orig_filed, raw_sha256, parsed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return out


def offer_events(conn: sqlite3.Connection, today: date, at: str) -> List[tuple]:
    """`corp_schedule`(offer_sub · offer_pay) → `market_event` 줄. 날짜 없는 행은 올리지 않는다 · 같은 종목 같은 날 같은 종류는 하나
    (접수번호가 큰 것) · 지난 날 confirmed · 오늘부터 scheduled."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='corp_schedule'").fetchone():
        return []
    best: Dict[Tuple[str, str, str], tuple] = {}
    for rno, kind, code, name, d, detail in conn.execute(
            f"SELECT rcept_no, kind, stock_code, corp_name, event_date, detail FROM corp_schedule "
            f"WHERE kind IN ({','.join('?' * len(KINDS))}) AND event_date <> '' AND stock_code <> ''", KINDS):
        k = (kind, code, d)
        if k not in best or rno > best[k][0]:
            best[k] = (rno, kind, code, name, d, detail)
    iso_today = today.isoformat()
    ev = []
    for rno, kind, code, name, d, detail in sorted(best.values(), key=lambda r: (r[4], r[1], r[2])):
        conf = "confirmed" if d < iso_today else "scheduled"
        title = f"{name} 공모 " + ("청약" if kind == "offer_sub" else "납입")
        ev.append((f"{kind}:{d}:{code}", kind, d, "", "", code, title, detail, conf, "dart", rno, at))
    return ev


def counts(conn: sqlite3.Connection, kinds: Sequence[str] = KINDS) -> Dict[str, int]:
    """종류마다 행 수(날짜 있는 것) — 명령 출력용."""
    return {k: conn.execute("SELECT COUNT(*) FROM corp_schedule WHERE kind=? AND event_date <> ''", (k,)).fetchone()[0]
            for k in kinds}
