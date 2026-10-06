"""리밸런싱 시간 예약. 달력 API와 같은 읽기 서비스를 사용한다."""
from __future__ import annotations

import calendar
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services import market_calendar

KST = ZoneInfo("Asia/Seoul")


def next_boundary(now: datetime, period: str) -> datetime | None:
    """다음 주기의 달력상 시작. 달력 미준비 때도 재시도할 주기는 보존한다."""
    if period not in ("monthly", "quarterly", "yearly"):
        return None
    local = now.astimezone(KST)
    month = local.month
    if period == "quarterly":
        month = (month - 1) // 3 * 3 + 1
    elif period == "yearly":
        month = 1
    offset = {"monthly": 1, "quarterly": 3, "yearly": 12}[period]
    index = local.year * 12 + month - 1 + offset
    return datetime(index // 12, index % 12 + 1, 1, 9, tzinfo=KST).astimezone(timezone.utc)


def days(start: date, end: date) -> list[dict]:
    response = market_calendar.trading_days(start, end)
    rows = response["days"]
    expected = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    if response.get("partial") or [row["date"] for row in rows] != expected:
        raise market_calendar.CalendarUnavailable("요청 기간의 거래일 달력이 부족합니다. 달력을 갱신한 뒤 다시 확인합니다.")
    return rows


def first_trading_time(reserved_at: datetime, period: str) -> datetime:
    local = reserved_at.astimezone(KST)
    month = local.month
    if period == "quarterly":
        month = (month - 1) // 3 * 3 + 1
    elif period == "yearly":
        month = 1
    start = date(local.year, month, 1)
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    for row in days(start, end):
        if row["is_trading_day"]:
            return datetime.combine(date.fromisoformat(row["date"]), time(9), KST).astimezone(timezone.utc)
    raise market_calendar.CalendarUnavailable("주기 시작 월에 거래일이 없습니다. 달력을 확인해야 합니다.")


def resolve(period: str, reserved_at: datetime | None, now: datetime) -> dict:
    """기존 1일 예약도 보정. 놓친 예약은 다음 거래일 09시 이후에 점검한다.

    자료가 없으면 TIME만 대기한다. 주말 추정으로 대체하거나 다른 조건을 막지 않는다.
    """
    if period == "none":
        return dict(next_run_at=None, time_due=False, trading_today=False, error=None)
    anchor = reserved_at or next_boundary(now, period)
    result = dict(next_run_at=anchor, time_due=False, trading_today=False, error=None)
    try:
        result["next_run_at"] = first_trading_time(anchor, period)
    except (market_calendar.CalendarUnavailable, sqlite3.Error):
        result["error"] = "거래일 달력 자료가 없거나 요청 기간을 모두 확인할 수 없습니다. 달력 갱신 후 다시 확인합니다."
    # The next year's calendar may be missing while today's pending proposal is valid.
    try:
        today = now.astimezone(KST).date()
        result["trading_today"] = days(today, today)[0]["is_trading_day"]
    except (market_calendar.CalendarUnavailable, sqlite3.Error):
        result["error"] = result["error"] or "오늘의 거래일 정보를 확인할 수 없습니다. 시간 조건은 대기합니다."
    result["time_due"] = bool(not result["error"] and result["trading_today"] and result["next_run_at"] <= now
                              and now.astimezone(KST).time() >= time(9))
    return result
