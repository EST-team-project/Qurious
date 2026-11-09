"""#612 — 외부 현금흐름은 성과에서 제외하고 배당은 수익에 포함한다."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.paper_performance import cashflow_adjusted_return


UTC = timezone.utc
START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
END = START + timedelta(hours=24)


def _flow(kind, amount, *, at, epoch=1):
    return SimpleNamespace(kind=kind, amount=amount, created_at=at, epoch=epoch)


def test_deposit_is_not_counted_as_investment_return():
    # 90 시작 + 중간 입금 9 = 99 종료. 투자손익은 0이어야 한다.
    result, valid = cashflow_adjusted_return(
        90, 99, START, END,
        [_flow("DEPOSIT", 9, at=START + timedelta(hours=12))],
        epoch=1,
    )
    assert valid
    assert result == pytest.approx(0.0)


def test_withdrawal_is_not_counted_as_investment_loss():
    # 100 시작, 중간 출금 10, 90 종료. 투자손익은 0이어야 한다.
    result, valid = cashflow_adjusted_return(
        100, 90, START, END,
        [_flow("WITHDRAW", 10, at=START + timedelta(hours=12))],
        epoch=1,
    )
    assert valid
    assert result == pytest.approx(0.0)


def test_weighted_external_flow_preserves_return_on_deployed_capital():
    # 기간 시작 직후 20을 입금하고, 총 운용자금 120이 10% 수익을 냄.
    result, valid = cashflow_adjusted_return(
        100, 132, START, END,
        [_flow("DEPOSIT", 20, at=START + timedelta(seconds=1))],
        epoch=1,
    )
    assert valid
    assert result == pytest.approx(0.10, abs=1e-6)


def test_dividend_remains_in_investment_return():
    result, valid = cashflow_adjusted_return(
        100, 105, START, END,
        [_flow("DIVIDEND", 5, at=START + timedelta(hours=12))],
        epoch=1,
    )
    assert valid
    assert result == pytest.approx(0.05)


def test_other_epoch_cashflow_does_not_adjust_current_epoch():
    result, valid = cashflow_adjusted_return(
        100, 110, START, END,
        [_flow("DEPOSIT", 50, at=START + timedelta(hours=12), epoch=2)],
        epoch=1,
    )
    assert valid
    assert result == pytest.approx(0.10)


def test_unclassified_legacy_cashflow_invalidates_only_that_interval():
    result, valid = cashflow_adjusted_return(
        100, 120, START, END,
        [_flow("DEPOSIT", 20, at=START + timedelta(hours=12), epoch=None)],
        epoch=1,
    )
    assert not valid
    assert result == 0.0


def test_invalid_time_or_non_positive_dietz_denominator_is_rejected():
    result, valid = cashflow_adjusted_return(100, 90, END, START, [], epoch=1)
    assert not valid and result == 0.0

    result, valid = cashflow_adjusted_return(
        100, 0, START, END,
        [_flow("WITHDRAW", 200, at=START + timedelta(seconds=1))],
        epoch=1,
    )
    assert not valid and result == 0.0
