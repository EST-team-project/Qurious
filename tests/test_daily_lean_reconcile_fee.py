from scripts.daily_lean_reconcile import judge_fee


def test_judge_fee_uses_top_level_lean_fills_and_compares_rates():
    journal_rows = [{
        "fills": [{
            "fill_price": 100,
            "qty_filled": 10,
            "cost": {"total_cost": 10, "gross_amount": 1000},
        }]
    }]
    lean_stats = {"Total Fees": "₩20.00"}
    lean_fills = [
        {"quantity": 10, "fill_price": 100, "fee": 10},
        {"quantity": 10, "fill_price": 100, "fee": 10},
    ]

    result = judge_fee(journal_rows, lean_stats, lean_fills)

    assert result["verdict"] == "참고용(요율)"
    assert result["j_bp"] == 100
    assert result["l_bp"] == 100
    assert result["delta_bp"] == 0
    assert result["j_gross"] == 1000
    assert result["l_gross"] == 2000


def test_judge_fee_fails_closed_without_lean_fills():
    journal_rows = [{
        "fills": [{
            "fill_price": 100,
            "qty_filled": 10,
            "cost": {"total_cost": 10, "gross_amount": 1000},
        }]
    }]

    result = judge_fee(journal_rows, {"Total Fees": "₩20.00"}, [])

    assert result["verdict"] == "판정 불가"
    assert "LEAN 체결 목록 없음" in result["reason"]


def test_judge_fee_fails_closed_on_invalid_lean_fill():
    journal_rows = [{
        "fills": [{
            "fill_price": 100,
            "qty_filled": 10,
            "cost": {"total_cost": 10, "gross_amount": 1000},
        }]
    }]

    result = judge_fee(
        journal_rows,
        {"Total Fees": "₩20.00"},
        [{"quantity": 0, "fill_price": 100}],
    )

    assert result["verdict"] == "판정 불가"
    assert "LEAN 체결 파싱 실패" in result["reason"]
