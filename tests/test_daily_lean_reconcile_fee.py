from types import SimpleNamespace

from scripts.daily_lean_reconcile import judge_fee, pull_failure_text


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

def test_pull_failure_text_shows_stdout_too(): # 이슈 #377 — 예외 메시지가 stdout 에 있어도 보인다
    res = SimpleNamespace(returncode=1, stderr="", stdout="ValueError: 원장 파일이 지문 목록과 다르다 — rows/a.parquet")
    msg = pull_failure_text(res)
    assert "종료코드 1" in msg and "[stdout]" in msg and "rows/a.parquet" in msg and "[stderr]" not in msg
    both = pull_failure_text(SimpleNamespace(returncode=2, stderr="Traceback x", stdout="진행 중"))
    assert "[stderr] Traceback x" in both and "[stdout] 진행 중" in both
    assert "출력 없음" in pull_failure_text(SimpleNamespace(returncode=3, stderr=None, stdout=""))
