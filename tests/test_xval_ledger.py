"""TC-XV — TradingView ↔ LEAN 줄 단위 대사표 (할 일 ①-11 · 설계서 3.4 · 3.5).

합성 고정값만 쓴다. 실제 TradingView CSV 로 교차검증하기 전이므로(#357) 여기서의 「일치」는
합성 입력이 같다는 뜻일 뿐 TradingView 와 일치한다는 뜻이 아니다.
"""
from datetime import date

import pytest

from app.services import tradingview as tv
from app.services import xval_ledger as xl


def tv_fill(event, side, day, price, qty=10):
    return {"event": event, "side": side, "date": day, "time": day, "price": price, "quantity": qty}


def lean_fill(direction, utc, price, qty=10, order_id=1, fee=0.0):
    signed = qty if direction == "buy" else -qty
    return {"order_id": order_id, "date": utc[:10], "time_utc": utc, "direction": direction,
            "quantity": qty, "signed_quantity": signed, "fill_price": price, "fee": fee}


def one_trade_pair(tv_entry="2025-03-04", lean_entry_utc="2025-03-03T16:00:00+00:00",
                   tv_entry_px=100.0, lean_entry_px=100.0, tv_qty=10, lean_qty=10):
    tv_fills = [tv_fill("entry", "buy", tv_entry, tv_entry_px, tv_qty),
                tv_fill("exit", "sell", "2025-03-10", 110.0, tv_qty)]
    lean_fills = [lean_fill("buy", lean_entry_utc, lean_entry_px, lean_qty, 1),
                  lean_fill("sell", "2025-03-10T00:00:00+00:00", 110.0, lean_qty, 2)]
    return tv_fills, lean_fills


def event_rows(table, event):
    return [r for r in table["rows"] if r["event"] == event]


# ── 거래 묶기 · 시간대 ──────────────────────────────────────────────────


def test_xv_01_lean_utc_is_converted_to_kst_trading_day():
    # UTC 3월 3일 16:00 = KST 3월 4일 01:00 → 거래일은 3월 4일
    trades = xl.lean_trades([lean_fill("buy", "2025-03-03T16:00:00+00:00", 100.0, 10, 1),
                             lean_fill("sell", "2025-03-10T00:00:00+00:00", 110.0, 10, 2)])
    assert trades[0]["entry_date"] == date(2025, 3, 4)
    assert trades[0]["exit_date"] == date(2025, 3, 10)
    assert trades[0]["return_pct"] == pytest.approx(10.0)


def test_xv_02_split_buys_and_sells_are_one_trade_with_weighted_prices():
    trades = xl.lean_trades([
        lean_fill("buy", "2025-03-03T00:00:00+00:00", 100.0, 10, 1),
        lean_fill("buy", "2025-03-04T00:00:00+00:00", 120.0, 10, 2),
        lean_fill("sell", "2025-03-10T00:00:00+00:00", 130.0, 5, 3),
        lean_fill("sell", "2025-03-11T00:00:00+00:00", 150.0, 15, 4),
    ])
    assert len(trades) == 1
    t = trades[0]
    assert t["entry_price"] == pytest.approx(110.0)       # (100·10 + 120·10) / 20
    assert t["exit_price"] == pytest.approx(145.0)        # (130·5 + 150·15) / 20
    assert t["entry_date"] == date(2025, 3, 3)
    assert t["exit_date"] == date(2025, 3, 11)            # 마지막 청산일
    assert t["open"] is False


def test_xv_03_oversell_flips_into_a_new_short_trade():
    trades = xl.lean_trades([lean_fill("buy", "2025-03-03T00:00:00+00:00", 100.0, 10, 1),
                             lean_fill("sell", "2025-03-05T00:00:00+00:00", 105.0, 15, 2)])
    assert [t["direction"] for t in trades] == ["long", "short"]
    assert trades[0]["open"] is False and trades[1]["open"] is True
    assert trades[1]["entry_qty"] == pytest.approx(5)


def test_xv_04_tv_pyramiding_and_open_trade():
    trades = xl.tv_trades([tv_fill("entry", "buy", "2025-03-03", 100.0, 10),
                           tv_fill("entry", "buy", "2025-03-04", 110.0, 10)])
    assert len(trades) == 1 and trades[0]["open"] is True
    assert trades[0]["entry_price"] == pytest.approx(105.0)
    assert trades[0]["exit_price"] is None


# ── 대사 · 원인 코드 ───────────────────────────────────────────────────


def test_xv_05_same_inputs_are_exact_matches_with_no_unexplained():
    tv_fills, lean_fills = one_trade_pair()
    table = xl.build_ledger(tv_fills, lean_fills)
    assert table["status"] == "compared"
    assert {r["explained"] for r in table["rows"]} == {"일치"}
    assert table["summary"]["unexplained_count"] == 0
    assert table["summary"]["paired_trade_count"] == 1
    assert event_rows(table, "entry")[0]["verdict"] == "완전 일치"
    assert table["trades"][0]["return_diff_bp"] == pytest.approx(0.0)


def test_xv_06_date_shift_is_explained_only_when_entry_mode_differs_by_declaration():
    # TV 진입 3월 4일 · LEAN 진입 3월 5일(UTC 3월 4일 16:00 → KST 5일)
    tv_fills, lean_fills = one_trade_pair(lean_entry_utc="2025-03-04T16:00:00+00:00")
    declared = {"tv": {"entry_mode": "open"}, "lean": {"entry_mode": "close"}}
    row = event_rows(xl.build_ledger(tv_fills, lean_fills, context=declared), "entry")[0]
    assert row["diff_days"] == 1
    assert row["cause"] == ["entry_mode"] and row["explained"] == "설명됨"
    # 선언이 없으면 같은 어긋남이 「미설명」 — 결함으로 올린다
    row = event_rows(xl.build_ledger(tv_fills, lean_fills), "entry")[0]
    assert row["cause"] == [] and row["explained"] == "미설명"


def test_xv_07_judge_difference_explains_exit_date_shift():
    tv_fills, lean_fills = one_trade_pair()
    lean_fills[1] = lean_fill("sell", "2025-03-11T00:00:00+00:00", 110.0, 10, 2)
    declared = {"tv": {"judge": "close"}, "lean": {"judge": "next_open"}}
    row = event_rows(xl.build_ledger(tv_fills, lean_fills, context=declared), "exit")[0]
    assert row["diff_days"] == 1 and row["cause"] == ["judge"] and row["explained"] == "설명됨"


def test_xv_08_price_gap_is_cost_only_when_sign_and_size_match_declared_slippage():
    declared = {"tv": {"slippage_bp": 10}, "lean": {"slippage_bp": 15}}
    # 매수 · LEAN 슬리피지가 5bp 더 → LEAN 가격이 높고 5bp 를 넘지 않을 때 설명됨
    tv_fills, lean_fills = one_trade_pair(lean_entry_px=100.04)
    row = event_rows(xl.build_ledger(tv_fills, lean_fills, context=declared), "entry")[0]
    assert row["cause"] == ["cost"] and row["explained"] == "설명됨"
    # 선언된 5bp 를 넘는 차이 → 미설명
    tv_fills, lean_fills = one_trade_pair(lean_entry_px=100.20)
    row = event_rows(xl.build_ledger(tv_fills, lean_fills, context=declared), "entry")[0]
    assert row["explained"] == "미설명"
    # 부호가 반대 → 미설명
    tv_fills, lean_fills = one_trade_pair(lean_entry_px=99.96)
    row = event_rows(xl.build_ledger(tv_fills, lean_fills, context=declared), "entry")[0]
    assert row["explained"] == "미설명"


def test_xv_09_quantity_gap_needs_declared_sizing_difference():
    tv_fills, lean_fills = one_trade_pair(lean_qty=20)
    declared = {"tv": {"sizing": "status"}, "lean": {"sizing": "all_in"}}
    row = event_rows(xl.build_ledger(tv_fills, lean_fills, context=declared), "entry")[0]
    assert row["diff_qty"] == pytest.approx(10) and row["cause"] == ["size"]
    row = event_rows(xl.build_ledger(tv_fills, lean_fills), "entry")[0]
    assert row["explained"] == "미설명"


def test_xv_10_unpaired_first_trade_is_rule_def_only_when_declared_and_first():
    # LEAN 에는 3월 4일 진입이 없고 4월 진입만 있다 → TV 첫 거래가 짝 없음
    tv_fills = [tv_fill("entry", "buy", "2025-03-04", 100.0), tv_fill("exit", "sell", "2025-03-10", 110.0),
                tv_fill("entry", "buy", "2025-04-01", 100.0), tv_fill("exit", "sell", "2025-04-08", 105.0)]
    lean_fills = [lean_fill("buy", "2025-03-31T15:00:00+00:00", 100.0, 10, 1),
                  lean_fill("sell", "2025-04-08T00:00:00+00:00", 105.0, 10, 2)]
    table = xl.build_ledger(tv_fills, lean_fills, context={"rule_def_first_bar_differs": True})
    first = [r for r in table["rows"] if r["trade_seq"] == 1 and r["event"] == "entry"][0]
    assert first["cause"] == ["rule_def"] and first["explained"] == "설명됨"
    assert table["summary"]["tradingview_only_trade_count"] == 1
    # 선언이 없으면 미설명
    table = xl.build_ledger(tv_fills, lean_fills)
    assert table["summary"]["unexplained_count"] >= 1
    assert table["summary"]["unexplained_is_defect"] is True


def test_xv_11_pairing_ignores_far_apart_or_opposite_direction_trades():
    tv_fills = [tv_fill("entry", "buy", "2025-03-04", 100.0), tv_fill("exit", "sell", "2025-03-10", 110.0)]
    far = [lean_fill("buy", "2025-05-01T00:00:00+00:00", 100.0, 10, 1),
           lean_fill("sell", "2025-05-08T00:00:00+00:00", 110.0, 10, 2)]
    table = xl.build_ledger(tv_fills, far)
    assert table["summary"]["paired_trade_count"] == 0
    assert table["summary"]["tradingview_only_trade_count"] == 1 and table["summary"]["lean_only_trade_count"] == 1


def test_xv_12_one_side_still_open_is_kept_as_unexplained_not_as_a_match():
    tv_fills = [tv_fill("entry", "buy", "2025-03-04", 100.0)]  # TV 는 아직 보유 중
    lean_fills = [lean_fill("buy", "2025-03-03T16:00:00+00:00", 100.0, 10, 1),
                  lean_fill("sell", "2025-03-10T00:00:00+00:00", 110.0, 10, 2)]
    table = xl.build_ledger(tv_fills, lean_fills)
    exit_row = event_rows(table, "exit")[0]
    assert exit_row["explained"] == "미설명"


# ── 허용 오차 · 층 순서 ────────────────────────────────────────────────


def test_xv_13_without_tolerance_nothing_is_judged_inside_or_outside():
    tv_fills, lean_fills = one_trade_pair(lean_entry_px=100.5)
    table = xl.build_ledger(tv_fills, lean_fills)
    assert event_rows(table, "entry")[0]["verdict"] == "기록만(허용 오차 미정)"
    assert "미정" in table["header"]["tolerance_source"]
    assert all(v is None for v in table["header"]["tolerance"].values())
    assert [l["status"] for l in table["layers"]][2] == "recorded"


def test_xv_14_tolerance_marks_inside_and_outside():
    tv_fills, lean_fills = one_trade_pair(lean_entry_px=100.5)  # +50bp
    inside = xl.build_ledger(tv_fills, lean_fills, tolerance={"layer2_price_bp": 60})
    outside = xl.build_ledger(tv_fills, lean_fills, tolerance={"layer2_price_bp": 10})
    assert event_rows(inside, "entry")[0]["verdict"] == "허용 오차 안"
    assert event_rows(inside, "entry")[0]["explained"] == "일치"
    assert event_rows(outside, "entry")[0]["verdict"] == "허용 오차 밖"
    assert outside["layers"][2]["status"] == "outside"


def test_xv_15_upper_layer_outside_invalidates_the_lower_layers():
    tv_fills, lean_fills = one_trade_pair()
    closes = {"tv": {"2025-03-04": 100.0, "2025-03-05": 101.0},
              "lean": {"2025-03-04": 100.0, "2025-03-05": 103.0}}   # 5일째 약 198bp 차
    table = xl.build_ledger(tv_fills, lean_fills, closes=closes, tolerance={"layer0_close_bp": 50})
    statuses = {l["layer"]: l["status"] for l in table["layers"]}
    assert statuses[0] == "outside"
    assert statuses[1] == "unavailable"          # 입력이 없는 층은 무효가 아니라 unavailable
    assert statuses[2] == "invalid"
    assert all(r["verdict"].startswith("무효") for r in table["rows"])


def test_xv_16_layer0_and_layer1_are_unavailable_without_inputs_and_never_invented():
    tv_fills, lean_fills = one_trade_pair()
    table = xl.build_ledger(tv_fills, lean_fills)
    assert table["layers"][0]["status"] == "unavailable"
    assert table["layers"][1]["status"] == "unavailable"
    signal = {"status": "compared", "entry_match_rate_pct": 100.0, "exit_match_rate_pct": 80.0,
              "mismatch_date_count": 3}
    table = xl.build_ledger(tv_fills, lean_fills, signal_result=signal, tolerance={"layer1_min_match_pct": 90})
    assert table["layers"][1]["status"] == "outside"
    assert table["layers"][2]["status"] == "invalid"


# ── 비용 층 ───────────────────────────────────────────────────────────


def test_xv_17_cost_row_compares_lean_fee_with_declared_tv_cost():
    tv_fills = [tv_fill("entry", "buy", "2025-03-04", 100.0), tv_fill("exit", "sell", "2025-03-10", 110.0)]
    lean_fills = [lean_fill("buy", "2025-03-03T16:00:00+00:00", 100.0, 10, 1, fee=0.0),
                  lean_fill("sell", "2025-03-10T00:00:00+00:00", 110.0, 10, 2, fee=2.1)]  # 2.1 / 1000 = 21bp
    declared = {"tv": {"roundtrip_cost_bp": 21.0}}
    table = xl.build_ledger(tv_fills, lean_fills, context=declared, tolerance={"layer3_cost_bp": 1})
    cost = event_rows(table, "cost")[0]
    assert cost["layer"] == 3 and cost["lean_cost_bp"] == pytest.approx(21.0)
    assert cost["diff_cost_bp"] == pytest.approx(0.0) and cost["explained"] == "일치"
    # 비용이 다르면: 근사 방식(cost_note)을 선언했을 때만 설명됨 · 슬리피지 선언 차이로는 설명되지 않는다
    lean_off = [lean_fills[0], lean_fill("sell", "2025-03-10T00:00:00+00:00", 110.0, 10, 2, fee=3.0)]  # 30bp
    slip_only = {"tv": {"roundtrip_cost_bp": 21.0, "slippage_bp": 10}, "lean": {"slippage_bp": 15}}
    assert event_rows(xl.build_ledger(tv_fills, lean_off, context=slip_only), "cost")[0]["explained"] == "미설명"
    noted = {"tv": {"roundtrip_cost_bp": 21.0, "cost_note": "매도세 편도 근사"}}
    row = event_rows(xl.build_ledger(tv_fills, lean_off, context=noted), "cost")[0]
    assert row["explained"] == "설명됨" and row["cause"] == ["cost"]
    # TradingView 선언이 없으면 비용 줄을 만들지 않는다(값을 지어내지 않음)
    assert event_rows(xl.build_ledger(tv_fills, lean_fills), "cost") == []


# ── 입력 부족 · 세 엔진 설정 ───────────────────────────────────────────


def test_xv_18_missing_side_is_unavailable_with_reason():
    table = xl.build_ledger([], [lean_fill("buy", "2025-03-03T00:00:00+00:00", 100.0)])
    assert table["status"] == "unavailable" and table["rows"] == []
    assert "TradingView" in table["reason"]


def test_xv_19_engine_settings_flag_the_old_ten_thousand_default():
    report = xl.engine_settings_report(lean_initial_cash=10_000, paper_initial_cash=10_000_000, when=date(2026, 10, 1))
    items = {m["item"] for m in report["mismatches"]}
    assert "initial_cash" in items and report["all_same"] is False
    same = xl.engine_settings_report(lean_initial_cash=10_000_000, paper_initial_cash=10_000_000, when=date(2026, 10, 1))
    assert "initial_cash" not in {m["item"] for m in same["mismatches"]}
    assert "currency" not in {m["item"] for m in same["mismatches"]}
    # LEAN 과 모의는 같은 요율표를 읽는다
    e = same["engines"]
    assert e["lean"]["fee_tax_roundtrip_bp"] == e["paper"]["fee_tax_roundtrip_bp"]
    assert e["tradingview"]["slippage_bps"] == e["lean"]["slippage_bps"] == 10.0


def test_xv_20_ledger_works_with_real_parser_output():
    csv_text = (
        "Trade #,Type,Signal,Date/Time,Price,Contracts,Profit,Profit %\n"
        "1,Entry Long,L,2025-03-04,100,10,,\n"
        "1,Exit Long,S,2025-03-10,110,10,100,10.00\n"
    )
    fills = tv.parse_trade_list_fills(csv_text)
    lean_fills = [lean_fill("buy", "2025-03-03T16:00:00+00:00", 100.0, 10, 1),
                  lean_fill("sell", "2025-03-10T00:00:00+00:00", 110.0, 10, 2)]
    table = xl.build_ledger(fills, lean_fills)
    assert table["summary"]["paired_trade_count"] == 1 and table["summary"]["unexplained_count"] == 0
    assert table["trades"][0]["tradingview"]["return_pct"] == pytest.approx(10.0)


# ── 라우트 ────────────────────────────────────────────────────────────


def _route_call(monkeypatch, body, lean_fills):
    import asyncio
    from unittest.mock import AsyncMock

    from app.routes import tradingview as route

    lean_result = {"lean_statistics": {}, "lean_fills": lean_fills, "lean_signals": [], "points": []}
    monkeypatch.setattr(route.lean_service, "run", AsyncMock(return_value=lean_result))
    monkeypatch.setattr(route, "audit", AsyncMock())

    class _Db:
        def add(self, row): pass
        async def commit(self): pass
        async def refresh(self, row): pass

    user = {"id": "00000000-0000-0000-0000-000000000001"}
    return asyncio.run(route.compare(body, user=user, db=_Db()))


def test_xv_21_route_adds_reconcile_table_and_keeps_fill_comparison(monkeypatch):
    from app.routes.tradingview import CompareBody, LedgerContext, LedgerTolerance

    csv_text = (
        "Trade #,Type,Signal,Date/Time,Price,Contracts,Profit,Profit %\n"
        "1,Entry Long,L,2025-03-04,100,10,,\n"
        "1,Exit Long,S,2025-03-10,110,10,100,10.00\n"
    )
    body = CompareBody(
        ticker="005930", strategy="ma_cross", start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
        tv_trades_csv=csv_text,
        tolerance=LedgerTolerance(layer2_price_bp=5, source="테스트 합성"),
        ledger_context=LedgerContext(),
        repro={"card_sha256": "abc123"},
    )
    lean_fills = [lean_fill("buy", "2025-03-03T16:00:00+00:00", 100.0, 10, 1),
                  lean_fill("sell", "2025-03-10T00:00:00+00:00", 110.0, 10, 2)]
    result = _route_call(monkeypatch, body, lean_fills)
    # 기존 키는 그대로, 새 키가 더해진다
    assert result["fill_comparison"]["status"] == "compared"
    table = result["reconcile_table"]
    assert table["status"] == "compared"
    assert table["header"]["repro"] == {"card_sha256": "abc123"}
    assert table["header"]["tolerance"]["layer2_price_bp"] == 5
    assert table["header"]["tolerance_source"] == "테스트 합성"
    assert table["summary"]["unexplained_count"] == 0
    # 세 엔진 시작 금액이 모두 1,000만 원이라 어긋남 목록에 시작 금액이 없다
    settings = table["header"]["engine_settings"]
    assert "initial_cash" not in {m["item"] for m in settings["mismatches"]}


def test_xv_22_route_without_trades_csv_says_not_requested_and_default_cash_is_ten_million(monkeypatch):
    from app.routes.tradingview import CompareBody

    body = CompareBody(
        ticker="005930", strategy="ma_cross", start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
        tv_signal_csv="time,SignalState_Entry,SignalState_Exit\n2025-01-02,1,0\n",
    )
    assert body.initial_cash == 10_000_000
    result = _route_call(monkeypatch, body, [])
    assert result["reconcile_table"]["status"] == "not_requested"
