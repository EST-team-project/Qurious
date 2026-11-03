"""배분 계산의 최종 비중과 실제 공통 수익률 표본을 검증한다."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from app.services.investment_research import optimize_portfolio


def candles(seed, *, volatility=.01, offset=0, count=121):
    rng = np.random.default_rng(seed)
    prices = 100 * np.cumprod(1 + rng.normal(.0003, volatility, count))
    start = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset)
    return [dict(time=int((start + timedelta(days=i)).timestamp()), open=float(p),
                 high=float(p * 1.01), low=float(p * .99), close=float(p), volume=1000)
            for i, p in enumerate(prices)]


@pytest.mark.parametrize('risk', ['conservative', 'moderate', 'aggressive'])
@pytest.mark.parametrize('count', [2, 3, 8, 20])
def test_final_weights_keep_bounds_and_exact_percent_total(risk, count):
    data = [dict(symbol=f'S{i}', candles=candles(17 + i, volatility=.001 if i == 0 else .03))
            for i in range(count)]
    result = optimize_portfolio(data, risk)
    assert 'error' not in result
    weights = result['weights']
    assert set(weights) == {item['symbol'] for item in data}
    assert all(5 <= w <= 60 for w in weights.values())
    assert sum(Decimal(str(w)) for w in weights.values()) == Decimal('100')
    assert result == optimize_portfolio(data, risk)


@pytest.mark.parametrize('overlap', [0, 1, 59])
def test_not_enough_common_returns_is_a_controlled_error(overlap):
    data = [dict(symbol='A', candles=candles(1)),
            dict(symbol='B', candles=candles(2, offset=120 - overlap))]
    result = optimize_portfolio(data, 'moderate')
    assert 'error' in result
    assert '공통' in result['error']


def test_sixty_common_returns_are_sufficient():
    data = [dict(symbol='A', candles=candles(1)),
            dict(symbol='B', candles=candles(2, offset=60))]
    assert 'error' not in optimize_portfolio(data, 'moderate')


def test_duplicate_symbols_do_not_silently_drop_weight():
    data = [dict(symbol='A', candles=candles(1)), dict(symbol='A', candles=candles(2))]
    assert 'error' in optimize_portfolio(data, 'moderate')


def test_infeasible_five_percent_floor_is_rejected():
    data = [dict(symbol=f'S{i}', candles=candles(i)) for i in range(21)]
    assert 'error' in optimize_portfolio(data, 'moderate')


def test_covariance_failure_does_not_escape_as_server_error(monkeypatch):
    def failed(_):
        raise np.linalg.LinAlgError('synthetic failure')
    monkeypatch.setattr(np.linalg, 'pinv', failed)
    data = [dict(symbol='A', candles=candles(1)), dict(symbol='B', candles=candles(2))]
    assert 'error' in optimize_portfolio(data, 'moderate')
