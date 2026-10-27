"""LEAN 주문 이벤트에서 실제 체결만 추출하는 테스트."""
from datetime import date

from app.services.lean_backtest import service


def test_normalize_order_events_keeps_filled_events_only():
    events = [
        {
            "orderId": 1, "time": 1704258000.0, "status": "submitted",
            "fillPrice": 0, "fillQuantity": 0, "direction": "buy",
        },
        {
            "orderId": 1, "time": 1704258000.0, "status": "filled",
            "fillPrice": 76106.13, "fillQuantity": 13.0, "direction": "buy",
            "orderFeeAmount": 176.45, "orderFeeCurrency": "KRW",
        },
        {
            "orderId": 2, "time": 1705035600.0, "status": "filled",
            "fillPrice": 69847.23, "fillQuantity": -13.0, "direction": "sell",
            "orderFeeAmount": 1813.11, "orderFeeCurrency": "KRW",
        },
    ]
    fills = service._normalize_order_events(events)
    assert len(fills) == 2
    assert [x["direction"] for x in fills] == ["buy", "sell"]
    assert fills[0]["date"] == "2024-01-03"
    assert fills[0]["quantity"] == 13.0
    assert fills[1]["signed_quantity"] == -13.0
    assert fills[1]["fee_currency"] == "KRW"


def test_parse_signal_csv_text_reads_boolean_states():
    content = (
        "date,entry_state,exit_state\n"
        "2025-01-02,1,0\n"
        "2025-01-03,0,1\n"
    )
    signals = service._parse_signal_csv_text(content)
    assert signals == [
        {"date": "2025-01-02", "entry_state": True, "exit_state": False},
        {"date": "2025-01-03", "entry_state": False, "exit_state": True},
    ]


def test_read_signal_events_reads_results_csv(tmp_path):
    path = tmp_path / "qurious-signals.csv"
    path.write_text(
        "date,entry_state,exit_state\n"
        "2025-01-02,1,0\n"
        "2025-01-03,0,1\n",
        encoding="utf-8",
    )

    signals = service._read_signal_events(tmp_path)

    assert signals == [
        {"date": "2025-01-02", "entry_state": True, "exit_state": False},
        {"date": "2025-01-03", "entry_state": False, "exit_state": True},
    ]


def test_ma_cross_algorithm_contains_signal_recording():
    source = service._algorithm_source(
        "005930.KS",
        "ma_cross",
        date(2025, 1, 1),
        date(2025, 12, 31),
        10_000_000,
        20,
        60,
        21,
        20,
    )

    assert "qurious-signals.csv" in source
    assert "entry_state = short_ma > long_ma" in source
    assert "exit_state = short_ma < long_ma" in source
    assert "on_end_of_algorithm" in source
