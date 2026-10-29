"""운영 감시가 부분 실패를 Celery 성공으로 오인하지 않아야 한다 (#371)."""
from unittest.mock import AsyncMock

import pytest

from app.tasks import paper_snapshot as task


@pytest.mark.parametrize("outcome", [
    {"total": 3, "ok": 3, "fail": 0, "date": "2026-10-29"},
    {"skipped": "non_trading_day", "date": "2026-10-31"},
])
def test_snapshot_success_and_calendar_skip(monkeypatch, outcome):
    operation = AsyncMock(return_value=outcome)
    monkeypatch.setattr(task, "_record_all_async", operation)
    result = task.record_all_snapshots.apply(throw=False)
    assert result.state == "SUCCESS" and result.result == outcome
    operation.assert_awaited_once()


@pytest.mark.parametrize("partial", [False, True])
def test_snapshot_failure_reaches_celery_without_automatic_retry(monkeypatch, partial):
    operation = AsyncMock(return_value={"total": 3, "ok": 2, "fail": 1, "date": "2026-10-29"})
    if not partial:
        operation.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(task, "_record_all_async", operation)
    result = task.record_all_snapshots.apply(throw=False)
    assert result.state == "FAILURE" and isinstance(result.result, RuntimeError)
    if partial:
        assert "ok=2 fail=1 total=3" in str(result.result)
    operation.assert_awaited_once()
