"""LEAN 주문 이벤트에서 실제 체결만 추출하는 테스트."""
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
