"""첫 거래일 예약 · 기존 예약 보정 · 달력 부족/변경 시 TIME 보류."""
import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import rebalance as rb, rebalance_schedule as schedule


def test_calendar_fixture_reads_utf8_with_cp949_default(monkeypatch, request):
    """DF-75: 한국어 Windows의 기본 인코딩에서도 휴일 이름을 온전히 읽는다."""
    read_text = Path.read_text

    def windows_read_text(path, *args, **kwargs):
        if path.name == "kasi_holidays_2020_2027.json" and not args and not kwargs.get("encoding"):
            kwargs["encoding"] = "cp949"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", windows_read_text)
    calendar = request.getfixturevalue("rebalance_calendar")
    with sqlite3.connect(calendar) as db:
        row = db.execute("SELECT is_trading_day, reason FROM market_calendar WHERE cal_date='2026-10-09'").fetchone()
    assert row[0] == 0 and "한글날" in row[1]


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("now,due", [
    ("2026-11-01T01:00", False),  # 일요일의 옛 1일 예약
    ("2026-11-01T23:59", False),  # 첫 거래일 한국시간 08:59
    ("2026-11-02T00:00", True),
    ("2026-11-07T01:00", False),  # 놓친 예약도 토요일에는 실행하지 않음
    ("2026-11-09T00:00", True),  # 놓친 예약은 이후 거래일에 한 번 점검
])
def test_legacy_first_day_reservation_is_repaired(rebalance_calendar, now, due):
    plan = SimpleNamespace(time_period="monthly", next_run_at=utc("2026-11-01T00:00"))
    result = asyncio.run(rb.refresh_time_schedule(plan, utc(now)))
    assert plan.next_run_at == utc("2026-11-02T00:00")
    assert result["time_due"] is due
    assert result["error"] is None


def test_missing_calendar_waits_then_recovers(rebalance_calendar, monkeypatch, tmp_path):
    plan = SimpleNamespace(time_period="monthly", next_run_at=utc("2026-11-01T00:00"))
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "missing.sqlite3"))
    result = asyncio.run(rb.refresh_time_schedule(plan, utc("2026-11-02T01:00")))
    assert result["error"] and not result["time_due"]
    assert plan.next_run_at == utc("2026-11-01T00:00")  # retry anchor retained
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(rebalance_calendar))
    result = asyncio.run(rb.refresh_time_schedule(plan, utc("2026-11-02T01:00")))
    assert result["time_due"] and not plan.time_schedule_error
    assert plan.next_run_at == utc("2026-11-02T00:00")


def test_calendar_range_end_does_not_rollback_schedule_advance(rebalance_calendar):
    plan = SimpleNamespace(time_period="yearly", next_run_at=utc("2027-01-04T00:00"))
    asyncio.run(rb.advance_time_schedule(plan, utc("2027-01-04T01:00")))
    assert plan.next_run_at == utc("2028-01-01T00:00")
    assert plan.time_schedule_error


@pytest.mark.parametrize("mutation", [
    "DELETE FROM market_calendar WHERE cal_date = '2026-11-01'",
    "DELETE FROM market_calendar WHERE cal_date >= '2026-11-20'",
    "UPDATE market_calendar SET is_trading_day=0 WHERE cal_date LIKE '2026-11-%'",
])
def test_missing_day_partial_month_or_no_trading_day_waits(rebalance_calendar, mutation):
    with sqlite3.connect(rebalance_calendar) as db:
        db.execute(mutation)
    result = schedule.resolve("monthly", utc("2026-11-01T00:00"), utc("2026-11-02T01:00"))
    assert result["error"] and not result["time_due"]


def test_calendar_correction_moves_existing_reservation(rebalance_calendar):
    with sqlite3.connect(rebalance_calendar) as db:
        db.execute("UPDATE market_calendar SET is_trading_day=0, reason='임시공휴일' WHERE cal_date='2026-11-02'")
    result = schedule.resolve("monthly", utc("2026-11-02T00:00"), utc("2026-11-02T01:00"))
    assert result["next_run_at"] == utc("2026-11-03T00:00")
    assert not result["time_due"]


def test_disabled_schedule_never_requires_calendar(monkeypatch, tmp_path):
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "missing.sqlite3"))
    result = schedule.resolve("none", utc("2026-11-01T00:00"), utc("2026-11-02T01:00"))
    assert result == dict(next_run_at=None, time_due=False, trading_today=False, error=None)
