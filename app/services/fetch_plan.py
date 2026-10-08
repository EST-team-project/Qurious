"""받을 범위 — 「자료 직접 받기」 화면(데이터 수집 화면 설계 2 · 2026-10-08).

무엇을 보이나
-------------
고른 자료 종류 · 기간에서 **이미 받은 것 · 받을 것 · 받지 않아도 되는 것(휴장 · 아직 공개 전)** 을 센다. 단위는 수집기가
실제로 받는 단위를 따른다(2026-10-08 결정 ② — 실제 수집 단위):

  시세      날 — 공공데이터포털 주식시세정보는 하루 한 번 부르면 그날 **전 종목**을 준다(`ingest_day` source=portal).
            기준일 다음 영업일 13시 뒤에 공개된다고 하므로 그 전의 받지 않은 거래일은 「아직 공개 전」, 거래일이 아닌 날은 「휴장」.
            이미 받은 날은 13시 전이어도 받은 날이다 — 출처가 일찍 내주기도 한다(2026-10-08 12:30 회차가 10-07 을 받았다).
  공시      날 — 공시 목록은 분기 창(과거분) · 최근 사흘 창(매일) × 유형 × 시장 **조합**으로 받는다(source=dart_list).
            그날을 덮는 받은 창이 모든 조합에 있으면 받은 날, 일부만이면 「일부」.
  정책뉴스  날 — 사흘 창으로 받는다(원문 보관 `raw_response` 의 `window/…`(과거분) · `daily/…`(매일)). 오늘은 아직.
  재무      해 — 연도 × 보고서 넷 × 100개사 묶음(source=dart_fin). 「자료 없음」 만 남은 해는 마감 전이라 아직 공개 전.

받은 날의 규칙(공시 · 정책뉴스) — 매일 수집의 창은 끝이 늘 오늘이라 수집기가 「끝나지 않은 창」 으로 남긴다. 그 창을 받은 날
(기록 시각)보다 **앞선 날**은 그날이 끝난 뒤에 받았으니 받은 날이고, 받은 그날만 덮였으면 「일부」(뒤에 올라온 것이 빠질 수 있다).
처음 판(2026-10-08 오전)은 끝난 창만 받은 날로 세어, 매일 잘 돌던 10월 공시가 모두 「일부 · 조합 0 / 30」 으로 보였다.

출처는 고르지 않는다 — 종류가 정한다. 종목 칸도 없다 — 받는 단위가 종목이 아니다.

왜 기록으로 세나 (SSoT)
----------------------
앱 컨테이너에는 수집기 코드(`collector/`)가 없다(Dockerfile 은 app · public · prompts · alembic 만 담는다). 공시 유형 열 · 시장
셋 · 재무 묶음 수 같은 수집기 상수를 여기 베끼면 수집기가 바뀔 때 화면이 거짓말을 한다 → 수집기가 남긴 열쇠만 읽고,
「조합 전부」 는 그 출처의 기록에 한 번이라도 나온 조합으로 센다.

받기는 화면이 하지 않는다 (2026-10-08 결정 ①)
--------------------------------------------
앱은 수집 폴더를 읽기만 하게 붙어 있다(`./data:/app/data/csv:ro`). 받을 것이 있으면 PC 에서 돌릴 명령(받을 것의 처음 ~ 끝)을
돌려준다. 수집기는 이미 받은 것을 건너뛰므로 그 구간 안의 받은 날까지 다시 받지 않는다(같은 명령을 두 번 돌려도 같다 · 멱등).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone

from app.services import collector_db

KST = timezone(timedelta(hours=9))
_WEEKDAYS = "월화수목금토일"
MAX_DAYS = 400            # 날 단위 한 번에 — 화면이 날마다 한 칸을 그린다
MAX_YEARS = 10            # 해 단위 한 번에
PRICE_PUBLISH_AT = time(13, 0)   # 주식시세정보 — 기준일 다음 영업일 13시 뒤 공개(공공데이터포털 원문 · 2026-10-07 확인)

#: 종류 — 화면의 「자료 종류」 단추와 「출처 · 이용 조건」 표가 이것을 그대로 쓴다(앱 안의 한 곳).
KINDS: dict[str, dict] = {
    "price": {
        "label": "시세", "unit": "day",
        "origin": "공공데이터포털 금융위원회_주식시세정보",
        "terms": "인증키 · 공공누리 제4유형(출처표시 · 비상업 · 변경금지) · 기준일 다음 영업일 13시 뒤 공개",
        "how": "하루 한 번 부르면 그날 전 종목을 받는다 · 거래일이 아닌 날은 받지 않는다",
        "command": "python -m collector.backfill backfill --from {from} --to {to}",
    },
    "disclosure": {
        "label": "공시", "unit": "day",
        "origin": "전자공시 DART OpenAPI — 공시 목록",
        "terms": "인증키 · 하루 호출 한도",
        "how": "분기 · 최근 사흘 창 × 유형 × 시장 조합으로 받는다 · 그날 공시는 그날 안에 늘어난다",
        "command": "python -m collector.disclosure backfill --from {from} --to {to}",
    },
    "policy_news": {
        "label": "정책뉴스", "unit": "day",
        "origin": "정책브리핑 정책뉴스(공공데이터포털)",
        "terms": "기사마다 공공누리 유형 확인 — 제1유형만 본문 · 출처 표시",
        "how": "사흘 창으로 받는다 · 매일 수집은 어제까지",
        "command": "python -m collector.policy_news backfill --from {from} --to {to}",
    },
    "financial": {
        "label": "재무", "unit": "year",
        "origin": "전자공시 DART OpenAPI — 재무 주요계정",
        "terms": "인증키 · 하루 호출 한도",
        "how": "연도 × 보고서 넷 × 100개사 묶음으로 받는다 · 마감 전 보고서는 다음에 다시 본다",
        "command": "python -m collector.financials backfill --from-year {from} --to-year {to}",
    },
}

#: 출처 표에만 있는 줄 — 받는 길이 화면에 없는 자료(언론사 기사는 매일 수집만 · 본문을 받지 않는다)
EXTRA_SOURCES = [
    {"label": "언론사 기사", "origin": "GDELT 메타데이터", "terms": "제목 · 원문 링크 · 시각만 — 본문 받지 않음"},
]

#: 상태 — 화면 색 · 글자는 이 열쇠로 고른다. 받을 것 = missing · error · partial
STATES = {
    "done": "받음", "partial": "일부", "missing": "빈 날", "error": "실패",
    "closed": "휴장", "pending": "아직 공개 전",
}
TODO_STATES = ("missing", "error", "partial")


class FetchPlanError(Exception):
    """고칠 수 있는 잘못 — 라우트가 상태 번호와 문구를 그대로 돌려준다."""

    def __init__(self, detail: str, status: int = 422):
        super().__init__(detail)
        self.detail, self.status = detail, status


def _now() -> datetime:
    return datetime.now(KST)


def _connect() -> sqlite3.Connection:
    path = collector_db.db_path()
    if path is None:
        raise FetchPlanError("수집 DB 를 찾지 못했다 — 수집기를 먼저 돌린다", 503)
    try:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e:
        raise FetchPlanError(f"수집 DB 를 열지 못했다({type(e).__name__})", 503) from None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _parse_date(s: str | None, what: str) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise FetchPlanError(f"{what} 날짜 꼴이 아니다 — YYYY-MM-DD") from None


def _days(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


# ── 날 단위 — 종류마다 「그날을 받았나」 ──────────────────────────────────────
def _price_states(conn: sqlite3.Connection, days: list[date], now: datetime) -> dict[date, tuple[str, str]]:
    a, b = days[0], days[-1]
    if not _has_table(conn, "market_calendar"):
        raise FetchPlanError("거래일 달력이 아직 없다 — 수집 일정의 「시장 달력」 단계가 만든다", 503)
    # 공개 시각을 보려면 끝날 뒤의 다음 거래일까지 필요하다 → 달력을 열흘 더 읽는다
    cal = {date.fromisoformat(d): (bool(t), reason) for d, t, reason in conn.execute(
        "SELECT cal_date, is_trading_day, reason FROM market_calendar WHERE cal_date BETWEEN ? AND ?",
        (a.isoformat(), (b + timedelta(days=10)).isoformat()))}
    ing = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT bas_dt, status, message FROM ingest_day WHERE source='portal' AND bas_dt BETWEEN ? AND ?",
        (_ymd(a), _ymd(b)))}
    trading = sorted(d for d, (t, _r) in cal.items() if t)
    out: dict[date, tuple[str, str]] = {}
    for d in days:
        if d not in cal:
            out[d] = ("pending", "달력 밖 — 그해 공휴일이 발표되면 늘어난다")
            continue
        is_trading, reason = cal[d]
        if not is_trading:
            out[d] = ("closed", reason or "휴장")
            continue
        status, msg = ing.get(_ymd(d), (None, ""))
        if status == "done":                       # 받은 기록이 먼저 — 출처가 약속(13시)보다 일찍 내주기도 한다(2026-10-08 12:30 회차가 10-07 을 받음)
            out[d] = ("done", "")
            continue
        nxt = next((t for t in trading if t > d), None)
        if nxt is None or now < datetime.combine(nxt, PRICE_PUBLISH_AT, tzinfo=KST):
            when = f"{nxt.month}-{nxt.day} 13시 뒤" if nxt else "다음 거래일 13시 뒤"
            out[d] = ("pending", f"출처 공개 {when}")
            continue
        if status == "error":
            out[d] = ("error", (msg or "")[:120])
        elif status == "holiday":
            out[d] = ("closed", "수집기가 휴장으로 확정")
        elif status == "empty":
            out[d] = ("missing", "출처가 빈 응답을 줬다 — 다시 받는다")
        else:
            out[d] = ("missing", "")
    return out


_DART_KEY = re.compile(r"^(\d{8})-(\d{8}):(.+)$")


def _day_of(ts: str | None) -> date | None:
    """기록 시각(KST ISO — 수집기가 쓴 꼴)의 날짜. 읽지 못하면 None."""
    try:
        return date.fromisoformat((ts or "")[:10])
    except ValueError:
        return None


def _disclosure_states(conn: sqlite3.Connection, days: list[date], now: datetime) -> dict[date, tuple[str, str]]:
    """공시 — 날마다 「그날을 덮는 받은 창」 이 기록에 나온 모든 조합에 있나.

    수집기는 끝이 오늘인 창(매일 수집의 최근 사흘 창)을 「끝나지 않은 창」 이라 `partial` 로 남긴다. 그러나 그 창을 받은 날
    (기록 시각)보다 **앞선 날**은 그날이 끝난 뒤에 받았으므로 받은 날이고, 받은 그날만 「일부」 다(뒤에 올라온 공시가 빠질 수 있다).
    """
    a, b = days[0], days[-1]
    combos_all: set[str] = set()
    done: dict[date, set[str]] = {d: set() for d in days}
    part: dict[date, set[str]] = {d: set() for d in days}
    err: dict[date, set[str]] = {d: set() for d in days}
    for key, status, updated in conn.execute(
            "SELECT bas_dt, status, updated_at FROM ingest_day WHERE source='dart_list'"):
        m = _DART_KEY.match(key)
        if not m:
            continue
        combos_all.add(m.group(3))
        w0 = datetime.strptime(m.group(1), "%Y%m%d").date()
        w1 = datetime.strptime(m.group(2), "%Y%m%d").date()
        lo, hi = max(w0, a), min(w1, b)
        if lo > hi:
            continue
        got = _day_of(updated)
        for d in _days(lo, hi):
            if status == "done" or (status == "partial" and got is not None and d < got):
                done[d].add(m.group(3))
            elif status == "partial":
                part[d].add(m.group(3))
            elif status == "error":
                err[d].add(m.group(3))
    today = now.date()
    out: dict[date, tuple[str, str]] = {}
    n = len(combos_all)
    for d in days:
        if d >= today:
            out[d] = ("pending", "그날 공시는 그날 안에 늘어난다")
        elif n and len(done[d]) == n:
            out[d] = ("done", "")
        elif done[d] or part[d]:
            out[d] = ("partial", f"조합 {len(done[d])} / {n} 끝남")
        elif err[d]:
            out[d] = ("error", f"조합 {len(err[d])}개 실패")
        else:
            out[d] = ("missing", "")
    return out


#: 정책뉴스 원문 열쇠 — 과거분 `window/<시작>-<끝>`(고정 사흘 창) · 매일 수집 `daily/<시작>-<끝>`(끝 = 받은 날)
_WINDOW = re.compile(r"^(?:window|daily)/(\d{8})-(\d{8})$")


def _policy_states(conn: sqlite3.Connection, days: list[date], now: datetime) -> dict[date, tuple[str, str]]:
    """정책뉴스 — 받은 창(원문 보관)이 그날을 덮었나. 받은 날보다 앞선 날은 받은 날, 받은 그날만 덮였으면 「일부」."""
    a, b = days[0], days[-1]
    done: set[date] = set()
    part: set[date] = set()
    if _has_table(conn, "raw_response"):
        for target, fetched in conn.execute(
                "SELECT target, MAX(fetched_at) FROM raw_response WHERE source='policy_news' "
                "AND (target LIKE 'window/%' OR target LIKE 'daily/%') GROUP BY target"):
            m = _WINDOW.match(target)
            if not m:
                continue
            lo = max(datetime.strptime(m.group(1), "%Y%m%d").date(), a)
            hi = min(datetime.strptime(m.group(2), "%Y%m%d").date(), b)
            got = _day_of(fetched)
            for d in (_days(lo, hi) if lo <= hi else []):
                (done if got is not None and d < got else part).add(d)
    today = now.date()
    out: dict[date, tuple[str, str]] = {}
    for d in days:
        if d >= today:
            out[d] = ("pending", "매일 수집은 어제까지")
        elif d in done:
            out[d] = ("done", "")
        elif d in part:
            out[d] = ("partial", "그날 안에 받아 뒤에 올라온 기사가 빠졌을 수 있다")
        else:
            out[d] = ("missing", "")
    return out


# ── 해 단위 — 재무 ─────────────────────────────────────────────────────────
_FIN_KEY = re.compile(r"^(\d{4})-(\d{5})-b(\d+)$")


def _financial_years(conn: sqlite3.Connection, years: list[int]) -> list[dict]:
    rows = [(m.group(1), m.group(2), m.group(3), status) for key, status in
            conn.execute("SELECT bas_dt, status FROM ingest_day WHERE source='dart_fin'")
            if (m := _FIN_KEY.match(key))]
    expected = {(rc, bi) for _y, rc, bi, _s in rows}      # 기록에 한 번이라도 나온 보고서 × 묶음
    by_year: dict[str, dict[tuple, str]] = {}
    for y, rc, bi, s in rows:
        by_year.setdefault(y, {})[(rc, bi)] = s
    out = []
    for y in years:
        got = by_year.get(str(y), {})
        n_done = sum(1 for s in got.values() if s == "done")
        n_empty = sum(1 for s in got.values() if s == "empty")
        n_err = sum(1 for s in got.values() if s == "error")
        n_missing = len(expected - set(got))
        # 받을 것 = 실패 · 아직 부르지 않은 묶음. 「자료 없음」 만 남은 해는 마감 전 보고서라 지금 받을 것이 아니다 —
        # 수집기의 매일 재무 단계가 다시 본다(아직 공개 전).
        if n_err:
            state, note = "error", f"묶음 {n_err}개 실패"
        elif n_missing:
            state, note = ("partial" if n_done else "missing"), f"부르지 않은 묶음 {n_missing}"
        elif n_empty:
            state, note = "pending", "남은 묶음은 자료 없음 — 마감 전 보고서일 수 있다 · 매일 수집이 다시 본다"
        else:
            state, note = "done", ""
        if n_empty and state != "pending":
            note += f" · 자료 없음 {n_empty}(마감 전일 수 있다)"
        out.append({"year": y, "state": state, "state_label": STATES[state], "note": note,
                    "done": n_done, "expected": len(expected), "empty": n_empty, "error": n_err, "missing": n_missing})
    return out


_DAY_STATES = {"price": _price_states, "disclosure": _disclosure_states, "policy_news": _policy_states}


def plan(kind: str, start: str | None, end: str | None, now: datetime | None = None) -> dict:
    """받을 범위 — {kind, label, unit, from, to, counts, todo, days|years, todo_range, command, source, …}."""
    if kind not in KINDS:
        raise FetchPlanError(f"모르는 자료 종류 — {kind} (가능: {' · '.join(KINDS)})")
    spec = KINDS[kind]
    now = now or _now()
    today = now.date()
    a = _parse_date(start, "시작")
    b = _parse_date(end, "끝") or today
    if a is None:
        raise FetchPlanError("시작 날짜를 넣는다 — YYYY-MM-DD")
    clipped = b > today
    b = min(b, today)
    if b < a:
        raise FetchPlanError("끝 날짜가 시작 날짜보다 앞이다")
    out = {"kind": kind, "label": spec["label"], "unit": spec["unit"], "from": a.isoformat(), "to": b.isoformat(),
           "clipped_to_today": clipped,
           "source": {"origin": spec["origin"], "terms": spec["terms"], "how": spec["how"]},
           "checked_at": now.isoformat(timespec="seconds")}
    conn = _connect()
    try:
        if not _has_table(conn, "ingest_day"):
            raise FetchPlanError("수집 기록 표가 아직 없다 — 수집기를 먼저 돌린다", 503)
        if spec["unit"] == "year":
            years = list(range(a.year, b.year + 1))
            if len(years) > MAX_YEARS:
                raise FetchPlanError(f"한 번에 {MAX_YEARS}년까지 — 구간을 나눠 본다")
            items = _financial_years(conn, years)
            out["years"] = items
            todo = [it["year"] for it in items if it["state"] in TODO_STATES]
            fmt = str
        else:
            days = _days(a, b)
            if len(days) > MAX_DAYS:
                raise FetchPlanError(f"한 번에 {MAX_DAYS}일까지 — 구간을 나눠 본다")
            states = _DAY_STATES[kind](conn, days, now)
            out["days"] = [{"date": d.isoformat(), "weekday": _WEEKDAYS[d.weekday()], "state": states[d][0],
                            "state_label": STATES[states[d][0]], "note": states[d][1]} for d in days]
            items = out["days"]
            todo = [d for d in days if states[d][0] in TODO_STATES]
            fmt = _ymd
    finally:
        conn.close()
    counts = {k: 0 for k in STATES}
    for it in items:
        counts[it["state"]] += 1
    out["counts"] = counts
    out["todo"] = len(todo)
    if todo:
        lo, hi = min(todo), max(todo)
        out["todo_range"] = {"from": str(lo) if isinstance(lo, int) else lo.isoformat(),
                             "to": str(hi) if isinstance(hi, int) else hi.isoformat()}
        out["command"] = spec["command"].format(**{"from": fmt(lo), "to": fmt(hi)})
        out["note"] = "받을 것의 처음 ~ 끝을 한 번에 받는다 — 그 사이의 이미 받은 것은 수집기가 건너뛴다"
    else:
        out["todo_range"] = None
        out["command"] = None
        out["note"] = "받을 것이 없습니다 — 이 기간은 이미 있습니다"
    return out


def sources() -> dict:
    """화면의 「출처 · 이용 조건」 표 — 종류 넷 + 받는 길이 화면에 없는 자료."""
    return {"kinds": [{"kind": k, "label": v["label"], "unit": v["unit"], "origin": v["origin"],
                       "terms": v["terms"], "how": v["how"]} for k, v in KINDS.items()],
            "extra": EXTRA_SOURCES, "states": STATES}
