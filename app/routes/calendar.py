"""거래일 달력 · 금융 일정 API — /api/calendar (목표 기능 ① W4 · 설계서 5.2.4 · 7절)

- GET /api/calendar/trading-days?from=&to=               : 하루하루의 거래일 여부 · 휴장 까닭 · 근거(시세로 확인 / 예정)
- GET /api/calendar/events?from=&to=&kind=&symbol=&limit= : 휴장 · 파생 만기 · 배당 기준일 · 배당락일

로그인 없이 읽는다 — 공휴일 · 거래소 규칙 · 공시에서 나온 공개 정보이고 사용자 데이터가 없다(설계서 7절).
표는 수집기가 매일 12:30 에 다시 만든다(`collector/market_calendar.py`). 달력이 없으면 503 과 할 일을 돌려준다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services import market_calendar as mc

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

_KST = timezone(timedelta(hours=9))


def _today() -> date:
    return datetime.now(_KST).date()


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except mc.CalendarUnavailable as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.get("/trading-days", summary="거래일 달력")
def trading_days(
    start: date | None = Query(default=None, alias="from", description="시작일(YYYY-MM-DD · 기본 오늘)"),
    end: date | None = Query(default=None, alias="to", description="끝일(YYYY-MM-DD · 포함 · 기본 60일 뒤)"),
):
    s, e = mc.default_range(_today())
    return _run(mc.trading_days, start or s, end or e)


@router.get("/events", summary="금융 일정")
def events(
    start: date | None = Query(default=None, alias="from", description="시작일(YYYY-MM-DD · 기본 오늘)"),
    end: date | None = Query(default=None, alias="to", description="끝일(YYYY-MM-DD · 포함 · 기본 60일 뒤)"),
    kind: str | None = Query(default=None, description="쉼표로 여럿 — market_closure · deriv_expiry · dividend_record · dividend_ex"),
    symbol: str | None = Query(default=None, pattern=r"^[0-9A-Z]{6}$", description="종목 단축코드(배당 일정)"),
    limit: int = Query(default=500, ge=1, le=mc.MAX_EVENTS),
):
    s, e = mc.default_range(_today())
    return _run(mc.events, start or s, end or e, kind, symbol, limit)
