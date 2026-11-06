from scripts.daily_lean_reconcile import judge_signal_verdict


def test_full_date_coverage_and_states_match():
    assert judge_signal_verdict({
        "status": "compared",
        "mismatch_date_count": 0,
        "tradingview_only_date_count": 0,
        "lean_only_date_count": 0,
    }) == "일치"


def test_missing_lean_dates_are_partial_match():
    assert judge_signal_verdict({
        "status": "compared",
        "mismatch_date_count": 0,
        "tradingview_only_date_count": 2,
        "lean_only_date_count": 0,
    }) == "겹친 날만 일치"


def test_missing_tradingview_dates_are_partial_match():
    assert judge_signal_verdict({
        "status": "compared",
        "mismatch_date_count": 0,
        "tradingview_only_date_count": 0,
        "lean_only_date_count": 1,
    }) == "겹친 날만 일치"


def test_state_mismatch_takes_priority():
    assert judge_signal_verdict({
        "status": "compared",
        "mismatch_date_count": 1,
        "tradingview_only_date_count": 2,
        "lean_only_date_count": 0,
    }) == "불일치"


def test_unavailable_is_not_a_match():
    assert judge_signal_verdict({"status": "unavailable"}) == "판정 불가"
