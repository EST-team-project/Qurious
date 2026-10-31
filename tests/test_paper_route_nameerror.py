"""TC-PRN — 모의투자 성과 API 두 곳의 NameError 재발 방지 (이슈 #460 · 2026-10-31)

모의계좌 현황 화면을 열면 `GET /api/paper/performance/backtest-100d/exists`(Order 미 import) 와
`GET /api/paper/performance/benchmark`(`limit` 미정의)가 NameError 로 500 이었다.
두 곳을 **가짜 DB 로 직접 불러** 이름 오류 없이 값이 나오는지 지킨다(일회용 PG 가 필요 없다).
정적으로는 `ruff check --select F821 app scripts` 가 같은 종류를 잡는다.

무엇을 지키나
1. 백테스트 100일 원장이 없으면 exists=False · count=0, 있으면 True · 개수. (TC-PRN-01)
2. 기준 지수(KOSPI) 시계열이 날짜 교집합으로 정규화된다 — 스냅샷 개수 상한 없이. (TC-PRN-02)
3. 스냅샷이 2건 미만이면 insufficient_data 로 답한다(예외 없음). (TC-PRN-03)
"""
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routes import paper as paper_route
from app.services import performance_service as perf


class _Result:
    """db.execute(...) 가 돌려주는 가짜 결과 — scalar() / scalars().all() 만 흉내."""

    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


def _db(result):
    return SimpleNamespace(execute=AsyncMock(return_value=result))


def _snap(day, equity):
    return SimpleNamespace(snap_date=date.fromisoformat(day), total_equity=equity)


USER = {"id": str(uuid.uuid4())}


@pytest.mark.asyncio
@pytest.mark.parametrize("count,exists", [(0, False), (3, True)])
async def test_backtest_100d_exists_does_not_raise_nameerror(count, exists):
    out = await paper_route.backtest_100d_exists(user=USER, db=_db(_Result(scalar=count)))
    assert out == {"exists": exists, "count": count}


@pytest.mark.asyncio
async def test_benchmark_series_has_no_limit_name_error(monkeypatch):
    rows = [_snap("2026-10-27", 100.0), _snap("2026-10-28", 110.0), _snap("2026-10-29", 121.0)]
    candles = {"candles": [
        {"date": "2026-10-27", "close": 2000.0},
        {"date": "2026-10-28", "close": 2100.0},
        {"date": "2026-10-29", "close": 2200.0},
    ]}
    monkeypatch.setattr("app.services.stock.get_candles", AsyncMock(return_value=candles))

    out = await perf.get_benchmark_series(_db(_Result(rows=rows)), uuid.uuid4())

    assert out["status"] == "ok"
    assert out["dates"] == ["2026-10-27", "2026-10-28", "2026-10-29"]
    assert out["our_series"] == [100.0, 110.0, 121.0]
    assert out["benchmark_series"][0] == 100.0 and out["benchmark_name"] == "KOSPI"


@pytest.mark.asyncio
async def test_benchmark_series_insufficient_when_under_two_snapshots():
    out = await perf.get_benchmark_series(_db(_Result(rows=[_snap("2026-10-29", 100.0)])), uuid.uuid4())
    assert out == {"status": "insufficient_data"}
