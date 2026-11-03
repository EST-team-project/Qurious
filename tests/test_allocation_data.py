from datetime import date
import sqlite3

import pytest

from app.services.allocation_data import read_proxy_candles


def test_etf_history_uses_collector_and_does_not_change_database(tmp_path):
    path = tmp_path / "market.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE etf_daily (bas_dt TEXT,srtn_cd TEXT,clpr REAL,mkp REAL,hipr REAL,lopr REAL,trqu INTEGER)")
        db.executemany("INSERT INTO etf_daily VALUES (?,?,?,?,?,?,?)", [
            ("20200101", "069500", 100, 100, 101, 99, 30),
            ("20261029", "069500", 200, 198, 202, 195, 500),
            ("20261030", "069500", 201, 200, 203, 198, 510),
            ("20261103", "069500", 999, 999, 999, 999, 10),
            ("20261030", "999999", 123, 123, 123, 123, 10),
        ])
    before = path.read_bytes()
    result = read_proxy_candles("069500.KS", path=path, today=date(2026, 11, 2))
    assert result["source"] == "collector_etf"
    assert [c["close"] for c in result["candles"]] == [200, 201]
    assert result["candles"][1]["volume"] == 510
    assert path.read_bytes() == before
    assert read_proxy_candles("114260.KS", path=path, today=date(2026, 11, 2)) is None


def test_unavailable_collector_allows_existing_market_data_fallback(tmp_path):
    assert read_proxy_candles("069500.KS", path=tmp_path / "missing.sqlite3") is None
    assert not (tmp_path / "missing.sqlite3").exists()


def test_only_declared_proxy_symbols_can_be_read(tmp_path):
    with pytest.raises(ValueError):
        read_proxy_candles("005930.KS", path=tmp_path / "missing.sqlite3")
