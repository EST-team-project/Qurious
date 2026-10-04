"""거래일 달력 · 금융 일정 읽기 — 수집 DB 의 `market_calendar` · `market_event` (목표 기능 ① W4 · 설계서 5.2.4).

표는 수집기(`collector/market_calendar.py`)가 매일 12:30 러너의 `calendar` 단계에서 다시 만든다.
앱은 **읽기만** 한다 — 수집 DB 는 컨테이너에 읽기 전용으로 붙는다(`collector_db` 머리말).
앱 이미지에는 `collector` 패키지가 없어서 표 이름 · 칸을 여기서 스스로 안다. 표 모양이 바뀌면 함께 고친다 —
`tests/test_market_calendar.py` 가 수집기의 실제 스키마로 픽스처 DB 를 만들어 어긋남을 잡는다.

달력이 없을 때(수집기 `build` 를 한 번도 안 돌린 PC)는 503 과 할 일을 돌려준다. 시세가 쌓인 날로
거래일을 흉내 내지 않는다 — 그 달력에는 앞날이 없어 「다음 거래일」 을 물으면 틀린 답을 준다
(그 때문에 배당락일 3행이 틀렸었다 — 2026-10-02).

모든 응답은 `source` · `as_of`(달력을 만든 날)를 싣는다(기능 설계서 공통 부품 C1).
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from app.services import collector_db

#: 한 번에 돌려주는 날 수 · 일정 수의 상한 — 화면 · 계산이 쓰는 범위(1~3년)보다 넉넉하게.
MAX_DAYS = 3700
MAX_EVENTS = 5000

EVENT_KINDS = {
    "market_closure": "휴장",
    "deriv_expiry": "파생 만기",
    "dividend_record": "배당 기준일",
    "dividend_ex": "배당락일",
    # 2026-10-04 · W7 — 실적 · 정기보고서 법정 기한 · 금통위 · FOMC(collector/event_sources.py)
    "earnings": "실적 발표",
    "report_deadline": "보고서 기한",
    "policy_rate": "금통위",
    "fomc": "FOMC",
}
#: `kind` 를 비우면 주는 종류 — 일정 화면이 결정 ③ 의 넷만 그린다(새 종류를 화면에 올리는 것은 Figma 결정 뒤).
#: 새 종류는 `kind=earnings,policy_rate` 처럼 이름으로, 또는 `kind=all` 로 묻는다.
DEFAULT_KINDS = ("market_closure", "deriv_expiry", "dividend_record", "dividend_ex")
CONFIDENCE = {"confirmed": "확정", "scheduled": "예정", "computed": "규칙으로 계산"}
BASIS = {"observed": "시세로 확인", "rule": "규칙 · 공휴일 표로 예정"}
_WEEKDAYS = "월화수목금토일"


class CalendarUnavailable(Exception):
    """달력을 읽을 수 없다 — 라우트가 이 상태 번호 · 문구를 그대로 돌려준다."""

    def __init__(self, detail: str, status_code: int = 503):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _connect() -> sqlite3.Connection:
    path = collector_db.db_path()
    if path is None:
        raise CalendarUnavailable("수집 DB 를 찾지 못했다 — 수집기를 먼저 돌린다(collector/README.md)")
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e:
        raise CalendarUnavailable(f"수집 DB 를 열지 못했다({type(e).__name__})") from None
    has = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                       "AND name IN ('market_calendar', 'market_event')").fetchone()[0]
    if has < 2:
        conn.close()
        raise CalendarUnavailable("거래일 달력이 아직 없다 — `python -m collector.market_calendar build` 를 한 번 돌린다")
    return conn


def _meta(conn: sqlite3.Connection) -> dict:
    lo, hi, updated = conn.execute(
        "SELECT MIN(cal_date), MAX(cal_date), MAX(updated_at) FROM market_calendar").fetchone()
    if not lo:
        raise CalendarUnavailable("거래일 달력이 비어 있다 — `python -m collector.market_calendar build` 를 돌린다")
    last_obs = conn.execute(
        "SELECT MAX(cal_date) FROM market_calendar WHERE basis = 'observed'").fetchone()[0]
    return {"start": lo, "end": hi, "updated_at": updated, "observed_until": last_obs}


def _check_range(start: date, end: date, limit_days: int) -> None:
    if end < start:
        raise CalendarUnavailable("끝 날짜가 시작 날짜보다 앞이다", 422)
    if (end - start).days > limit_days:
        raise CalendarUnavailable(f"한 번에 {limit_days:,}일까지 — 구간을 나눠 부른다", 422)


def trading_days(start: date, end: date) -> dict:
    """구간의 하루하루 — 거래일 여부 · 휴장 까닭 · 근거(시세로 확인 / 예정)."""
    _check_range(start, end, MAX_DAYS)
    conn = _connect()
    try:
        meta = _meta(conn)
        rows = conn.execute(
            "SELECT cal_date, is_trading_day, reason, basis, note FROM market_calendar "
            "WHERE cal_date BETWEEN ? AND ? ORDER BY cal_date", (start.isoformat(), end.isoformat())).fetchall()
    finally:
        conn.close()
    days = [{
        "date": d,
        "weekday": _WEEKDAYS[date.fromisoformat(d).weekday()],
        "is_trading_day": bool(t),
        "reason": reason,
        "basis": basis,
        "basis_label": BASIS.get(basis, basis),
        "note": note,
    } for d, t, reason, basis, note in rows]
    n_trading = sum(1 for x in days if x["is_trading_day"])
    out = {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": days,
        "trading_days": n_trading,
        "closed_days": len(days) - n_trading,
        "calendar": meta,
        "source": "collector",
        "as_of": (meta["updated_at"] or "")[:10],
    }
    # 달력 밖을 물으면 숨기지 않고 알린다 — 빈칸을 「거래일 없음」 으로 읽으면 안 된다.
    gaps = []
    if start.isoformat() < meta["start"]:
        gaps.append(f"{meta['start']} 앞은 달력에 없다(시세가 2020-01-02 부터다)")
    if end.isoformat() > meta["end"]:
        gaps.append(f"{meta['end']} 뒤는 아직 없다 — 그해 공휴일이 발표되면 늘어난다")
    if gaps:
        out["partial"] = True
        out["partial_reason"] = " · ".join(gaps)
    return out


def events(start: date, end: date, kind: str | None = None, symbol: str | None = None,
           limit: int = 500) -> dict:
    """구간의 금융 일정 — 휴장 · 파생 만기 · 배당 기준일 · 배당락일(기본) · 실적 · 보고서 기한 · 금통위 · FOMC(이름 · all 로)."""
    _check_range(start, end, MAX_DAYS)
    kinds = [k for k in (kind or "").split(",") if k]
    if kinds == ["all"]:
        kinds = list(EVENT_KINDS)
    elif not kinds:
        kinds = list(DEFAULT_KINDS)
    unknown = [k for k in kinds if k not in EVENT_KINDS]
    if unknown:
        raise CalendarUnavailable(f"모르는 일정 종류: {', '.join(unknown)} — {', '.join(EVENT_KINDS)} 중에서", 422)
    limit = max(1, min(int(limit), MAX_EVENTS))
    sql = ("SELECT event_id, kind, event_date, event_time, market, symbol, title, detail, confidence, source, "
           "source_ref FROM market_event WHERE event_date BETWEEN ? AND ?")
    args: list = [start.isoformat(), end.isoformat()]
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        args += kinds
    if symbol:
        sql += " AND symbol = ?"
        args.append(symbol)
    conn = _connect()
    try:
        meta = _meta(conn)
        total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
        rows = conn.execute(sql + " ORDER BY event_date, kind, symbol LIMIT ?", [*args, limit]).fetchall()
    finally:
        conn.close()
    items = [{
        "id": eid,
        "kind": k,
        "kind_label": EVENT_KINDS.get(k, k),
        "date": d,
        "weekday": _WEEKDAYS[date.fromisoformat(d).weekday()],
        "time": t,
        "market": market,
        "symbol": sym,
        "title": title,
        "detail": detail,
        "confidence": conf,
        "confidence_label": CONFIDENCE.get(conf, conf),
        "source_ref": ref,
    } for eid, k, d, t, market, sym, title, detail, conf, _src, ref in rows]
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "kind": kinds,
        "symbol": symbol or "",
        "events": items,
        "total": total,
        "truncated": total > len(items),
        "calendar": meta,
        "source": "collector",
        "as_of": (meta["updated_at"] or "")[:10],
    }


def trading_days_between(conn: sqlite3.Connection, after: str, before: str) -> list[str]:
    """`after` 보다 뒤 · `before` 보다 앞인 거래일(YYYY-MM-DD) — 데이터 상태가 「몇 거래일 늦었나」 를 셀 때 쓴다."""
    return [r[0] for r in conn.execute(
        "SELECT cal_date FROM market_calendar WHERE is_trading_day = 1 AND cal_date > ? AND cal_date < ? "
        "ORDER BY cal_date", (after, before))]


def default_range(today: date) -> tuple[date, date]:
    """화면이 구간 없이 부를 때 — 오늘부터 60일."""
    return today, today + timedelta(days=60)
