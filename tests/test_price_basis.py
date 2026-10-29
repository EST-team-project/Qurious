from pathlib import Path
from datetime import date
import sqlite3
import pytest

from app.services.price_basis import adjusted_to_raw, adjustment_changed, load_day


@pytest.mark.parametrize('factor', [1., .5, 2., .519])
def test_distance_conversion_preserves_risk_unit(factor):
    assert adjusted_to_raw(100 * factor, factor) == pytest.approx(100)
    assert adjustment_changed(factor, factor) is False


@pytest.mark.parametrize('bad', [None, True, 0, -1, float('nan'), float('inf')])
def test_missing_factor_never_means_one(bad):
    with pytest.raises(ValueError):
        adjusted_to_raw(100, bad)


def test_both_directions_of_corporate_action_are_detected():
    assert adjustment_changed(.5, 1)
    assert adjustment_changed(2, 1)


def test_date_lookup_never_substitutes_latest_factor(tmp_path):
    p = tmp_path / 'prices.sqlite3'
    with sqlite3.connect(p) as db:
        db.execute('CREATE TABLE price_daily (bas_dt TEXT, srtn_cd TEXT, clpr REAL)')
        db.execute('CREATE TABLE price_adjusted (bas_dt TEXT, srtn_cd TEXT, adj_clpr REAL, cum_factor REAL)')
        db.executemany('INSERT INTO price_daily VALUES (?,?,?)', [('20260302','005930',100), ('20260303','005930',50)])
        db.executemany('INSERT INTO price_adjusted VALUES (?,?,?,?)', [('20260302','005930',50,.5), ('20260303','005930',50,1)])
    first = load_day('005930.KS', date(2026,3,2), path=p)
    assert first['factor'] == .5 and adjusted_to_raw(5, first['factor']) == 10
    with pytest.raises(ValueError, match='해당 거래일'):
        load_day('005930.KS', date(2026,3,4), path=p)
