"""TradingView 연동: 알림 파싱 · 거래 목록 CSV 성과 계산 · LEAN 비교 판정."""
import pytest

from app.services import tradingview as tv


@pytest.mark.parametrize("raw,expected", [
    ("KRX:005930", "005930"), ("NASDAQ:AAPL", "AAPL"), ("005930.KS", "005930.KS"), (" aapl ", "AAPL"),
])
def test_normalize_ticker(raw, expected):
    assert tv.normalize_ticker(raw) == expected


def test_parse_alert_buy_sell_alert():
    a = tv.parse_alert({"ticker": "KRX:005930", "action": "buy", "contracts": "3", "price": "274,500", "strategy": "MA"})
    assert (a["symbol"], a["side"], a["quantity"], a["price"]) == ("005930", "BUY", 3, 274500.0)
    assert tv.parse_alert({"ticker": "AAPL", "action": "sell", "qty": 2})["side"] == "SELL"
    assert tv.parse_alert({"ticker": "AAPL"})["side"] == "ALERT"
    assert tv.parse_alert({"ticker": "AAPL", "action": "buy", "contracts": 1, "dry_run": "true"})["dry_run"]


CSV = """Trade #,Type,Signal,Date/Time,Price,Contracts,Profit,Profit %,Cum. Profit,Cum. Profit %
1,Entry Long,L,2025-01-10,55000,1,,,
1,Exit Long,S,2025-02-10,58000,1,3000,10.00,3000,10.00
2,Entry Long,L,2025-03-01,57000,1,,,
2,Exit Long,S,2025-04-01,54000,1,-3000,-10.00,0,0
3,Entry Long,L,2025-05-01,57000,1,,,
3,Exit Long,S,2025-06-01,60000,1,3000,5.00,3000,5.00
"""


def test_parse_trade_list_csv_metrics():
    m = tv.parse_trade_list_csv(CSV)
    assert m["total_trades"] == 3
    assert m["win_rate_pct"] == pytest.approx(66.67, abs=0.01)
    # 1.10 * 0.90 * 1.05 - 1 = 3.95%
    assert m["net_profit_pct"] == pytest.approx(3.95, abs=0.01)
    assert m["max_drawdown_pct"] == pytest.approx(-10.0, abs=0.01)


def test_parse_trade_list_csv_errors():
    with pytest.raises(ValueError):
        tv.parse_trade_list_csv("")
    with pytest.raises(ValueError):
        tv.parse_trade_list_csv("a,b,c\n1,2,3\n")


def test_compare_metrics_verdicts():
    lean = {"net_profit_pct": 10.0, "max_drawdown_pct": -8.0, "total_trades": 5, "win_rate_pct": 60, "sharpe_ratio": 1.0, "lean_ok": True}
    assert tv.compare_metrics({"net_profit_pct": 11.0, "max_drawdown_pct": -9.0, "total_trades": 5}, lean)["verdict"] == "일치"
    assert tv.compare_metrics({"net_profit_pct": 17.0, "max_drawdown_pct": -8.0, "total_trades": 5}, lean)["verdict"] == "부분 일치"
    r = tv.compare_metrics({"net_profit_pct": 40.0, "max_drawdown_pct": -8.0, "total_trades": 9}, lean)
    assert r["verdict"] == "불일치"
    assert any("수수료" in c for c in r["causes"]) and any("거래 횟수" in c for c in r["causes"])
    assert tv.compare_metrics({}, {})["verdict"] == "비교 불가"


def test_parse_trade_list_csv_preserves_entry_exit_fills():
    metrics = tv.parse_trade_list_csv(CSV)
    fills = metrics["fills"]
    assert len(fills) == 6
    assert fills[0]["event"] == "entry"
    assert fills[0]["side"] == "buy"
    assert fills[0]["date"] == "2025-01-10"
    assert fills[0]["price"] == pytest.approx(55000)
    assert fills[1]["event"] == "exit"
    assert fills[1]["side"] == "sell"
    assert fills[1]["date"] == "2025-02-10"


def test_compare_fills_reports_date_side_and_price_differences():
    tv_fills = tv.parse_trade_list_csv(CSV)["fills"][:2]
    lean_fills = [
        {
            "order_id": 1, "date": "2025-01-10",
            "direction": "buy", "fill_price": 55000,
        },
        {
            "order_id": 2, "date": "2025-02-10",
            "direction": "sell", "fill_price": 58100,
        },
    ]
    result = tv.compare_fills(tv_fills, lean_fills)
    assert result["status"] == "compared"
    assert result["paired_event_count"] == 2
    assert result["date_match_count"] == 2
    assert result["side_match_count"] == 2
    assert result["date_and_side_match_count"] == 2
    assert result["avg_abs_price_diff_pct"] == pytest.approx(0.0862, abs=0.0001)


def test_compare_fills_without_real_csv_is_unavailable():
    result = tv.compare_fills([], [{"date": "2025-01-10", "direction": "buy"}])
    assert result["status"] == "unavailable"
    assert result["lean_fill_count"] == 1
    assert result["tradingview_fill_count"] == 0


def test_compare_fills_converts_lean_utc_to_kst_and_reports_bps():
    tv_fills = [{
        "trade_id": "1",
        "event": "entry",
        "side": "buy",
        "date": "2025-01-11",
        "time": "2025-01-11",
        "price": 100.0,
    }]
    lean_fills = [{
        "order_id": 1,
        "date": "2025-01-10",
        "time_utc": "2025-01-10T16:00:00+00:00",
        "direction": "buy",
        "fill_price": 100.1,
    }]

    result = tv.compare_fills(tv_fills, lean_fills)

    assert result["date_match_count"] == 1
    assert result["avg_abs_price_diff_bps"] == pytest.approx(10.0, abs=0.01)
    assert result["rows"][0]["lean_vs_tradingview_price_diff_bps"] == pytest.approx(
        10.0, abs=0.01
    )


def test_compare_fills_keeps_alignment_after_missing_middle_event():
    tv_fills = [
        {"date": "2025-01-01", "time": "2025-01-01", "side": "buy", "price": 100},
        {"date": "2025-01-02", "time": "2025-01-02", "side": "sell", "price": 110},
        {"date": "2025-01-03", "time": "2025-01-03", "side": "buy", "price": 105},
    ]
    lean_fills = [
        {"date": "2025-01-01", "direction": "buy", "fill_price": 100},
        {"date": "2025-01-03", "direction": "buy", "fill_price": 105},
    ]

    result = tv.compare_fills(tv_fills, lean_fills)

    assert result["paired_event_count"] == 2
    assert result["unmatched_tradingview_events"] == 1
    assert result["unmatched_lean_events"] == 0
    assert [
        row["match_status"]
        for row in result["rows"]
    ] == ["paired", "unmatched_tradingview", "paired"]


SIGNAL_CSV = """time,SignalState_Entry,SignalState_Exit
2025-01-01,1,0
2025-01-02,0,1
2025-01-03,1,0
"""


def test_parse_signal_csv_reads_daily_entry_exit_states():
    signals = tv.parse_signal_csv(SIGNAL_CSV)
    assert len(signals) == 3
    assert signals[0] == {
        "date": "2025-01-01",
        "entry_state": True,
        "exit_state": False,
    }
    assert signals[1]["entry_state"] is False
    assert signals[1]["exit_state"] is True


def test_compare_signals_is_separate_from_fill_comparison():
    tv_signals = tv.parse_signal_csv(SIGNAL_CSV)
    lean_signals = [
        {"date": "2025-01-01", "entry_state": True, "exit_state": False},
        {"date": "2025-01-02", "entry_state": False, "exit_state": False},
        {"date": "2025-01-03", "entry_state": True, "exit_state": False},
    ]

    result = tv.compare_signals(tv_signals, lean_signals)

    assert result["status"] == "compared"
    assert result["matched_date_count"] == 3
    assert result["entry_match_rate_pct"] == 100.0
    assert result["exit_match_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert result["mismatch_date_count"] == 1
    assert result["mismatch_dates"][0]["date"] == "2025-01-02"


def test_compare_signals_without_both_sources_is_unavailable():
    result = tv.compare_signals([], [{"date": "2025-01-01", "entry_state": True}])
    assert result["status"] == "unavailable"


def test_parse_signal_csv_rejects_missing_state_columns():
    with pytest.raises(ValueError):
        tv.parse_signal_csv("time,close\n2025-01-01,100\n")
