import asyncio
import pytest
from fastapi import HTTPException
from datetime import date
from unittest.mock import AsyncMock

from app.routes import tradingview as route
from app.routes.tradingview import CompareBody


class FakeDb:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        pass

    async def refresh(self, row):
        pass


def test_compare_route_returns_separate_signal_comparison(monkeypatch):
    body = CompareBody(
        ticker="005930",
        strategy="ma_cross",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        tv_signal_csv=(
            "time,SignalState_Entry,SignalState_Exit\n"
            "2025-01-02,1,0\n"
            "2025-01-03,0,1\n"
        ),
    )

    lean_result = {
        "lean_statistics": {},
        "lean_fills": [],
        "lean_signals": [
            {
                "date": "2025-01-02",
                "entry_state": True,
                "exit_state": False,
            },
            {
                "date": "2025-01-03",
                "entry_state": False,
                "exit_state": True,
            },
        ],
        "points": [],
    }

    monkeypatch.setattr(
        route.lean_service,
        "run",
        AsyncMock(return_value=lean_result),
    )
    def fail_if_performance_comparison_called(*args):
        raise AssertionError("신호 전용 요청에서는 성과 비교를 실행하면 안 됩니다.")

    monkeypatch.setattr(
        route.tv, "compare_metrics", fail_if_performance_comparison_called
    )
    monkeypatch.setattr(
        route.tv,
        "compare_fills",
        lambda *args: {"status": "compared", "rows": []},
    )
    monkeypatch.setattr(route, "audit", AsyncMock())

    db = FakeDb()
    user = {"id": "00000000-0000-0000-0000-000000000001"}

    result = asyncio.run(route.compare(body, user=user, db=db))

    assert result["performance_comparison"]["status"] == "not_requested"
    assert result["verdict"] == "신호 비교 전용"
    assert result["fill_comparison"]["status"] == "not_requested"
    assert result["saved_to_performance_history"] is False
    assert result["id"] is None
    assert db.rows == []


def test_compare_route_rejects_signal_csv_for_unsupported_strategy(monkeypatch):
    body = CompareBody(
        ticker="005930",
        strategy="momentum",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        tv_signal_csv=(
            "time,SignalState_Entry,SignalState_Exit\n"
            "2025-01-02,1,0\n"
        ),
    )

    async def unexpected_lean_run(*args, **kwargs):
        raise AssertionError("비지원 전략에서는 LEAN을 실행하면 안 됩니다.")

    monkeypatch.setattr(route.lean_service, "run", unexpected_lean_run)
    user = {"id": "00000000-0000-0000-0000-000000000001"}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(route.compare(body, user=user, db=FakeDb()))

    assert exc_info.value.status_code == 422
    assert "ma_cross" in str(exc_info.value.detail)

def test_compare_route_accepts_trade_csv_without_manual_metrics(monkeypatch):
    body = CompareBody(
        ticker="005930",
        strategy="ma_cross",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        tv_trades_csv=(
            "Trade #,Type,Signal,Date/Time,Price,Contracts,Profit,Profit %,Cum. Profit,Cum. Profit %\n"
            "1,Entry Long,L,2025-01-10,55000,1,,,,\n"
            "1,Exit Long,S,2025-02-10,58000,1,3000,10.00,3000,10.00\n"
        ),
    )

    lean_result = {
        "lean_statistics": {},
        "lean_fills": [],
        "lean_signals": [],
        "points": [],
    }
    captured = {}

    monkeypatch.setattr(
        route.lean_service, "run", AsyncMock(return_value=lean_result)
    )
    monkeypatch.setattr(route.tv, "lean_metrics_from_result", lambda result: {})
    monkeypatch.setattr(
        route.tv,
        "compare_metrics",
        lambda tv_metrics, lean_metrics, ticker, strategy: {
            "ticker": ticker,
            "strategy": strategy,
            "verdict": "일치",
            "rows": [],
            "diff": {},
            "causes": [],
            "tradingview": tv_metrics,
            "lean": lean_metrics,
        },
    )

    def capture_fills(tv_fills, lean_fills):
        captured["tv_fills"] = tv_fills
        return {"status": "compared", "rows": []}

    monkeypatch.setattr(route.tv, "compare_fills", capture_fills)
    monkeypatch.setattr(route, "audit", AsyncMock())

    db = FakeDb()
    user = {"id": "00000000-0000-0000-0000-000000000001"}

    result = asyncio.run(route.compare(body, user=user, db=db))

    assert len(captured["tv_fills"]) == 2
    assert result["fill_comparison"]["status"] == "compared"
    assert result["performance_comparison"]["status"] == "compared"
    assert result["saved_to_performance_history"] is True
    assert len(db.rows) == 1
