"""가격 없는 목표 저장: 실제 수집기 스키마와 기존 미확인 종목 검증 경계."""
import asyncio
from datetime import date
import sqlite3

import pytest

from collector.db import SCHEMA
from app.services import rebalance as rb, rebalance_prices as prices


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    path = tmp_path/'market.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.executemany('INSERT INTO price_daily (bas_dt,srtn_cd,itms_nm,mrkt_ctg,clpr,mkp,trqu,halted) VALUES (?,?,?,?,0,0,0,1)', [
            ('20261001','005930','옛 이름','KOSPI'),
            ('20261002','005930','삼성전자','KOSPI'),
            ('20261002','035900','코스닥 종목','KOSDAQ'),
            ('20261002','0009K0','영문 코드 종목','KOSPI'),
            ('20261002','123456','코넥스 종목','KONEX'),
            ('20261002','123457','확인 불가 시장','UNKNOWN'),
            ('20990101','999999','미래 종목','KOSPI'),
        ])
        db.execute("INSERT INTO etf_daily (bas_dt,srtn_cd,itms_nm,clpr) VALUES ('20261002','069500','KODEX 200',0)")
    monkeypatch.setenv('COLLECTOR_DB_PATH', str(path))
    return path


@pytest.mark.parametrize('symbol,expected', [
    ('005930','005930.KS'), ('005930.ks','005930.KS'), ('035900.KS','035900.KQ'),
    ('0009K0','0009K0.KS'), ('123456','123456.KN'), ('069500','069500.KS'),
])
def test_metadata_uses_collector_market_without_a_tradable_price(catalog, symbol, expected):
    before = catalog.read_bytes()
    result = prices.target_metadata([symbol], as_of=date(2026,10,2))
    assert result[symbol]['symbol'] == expected
    assert result[symbol]['name']
    assert 'price' not in result[symbol]
    assert catalog.read_bytes() == before


def test_unverified_symbols_and_future_rows_are_not_invented(catalog):
    assert prices.target_metadata(['999999','123457','AAPL','005930.US','000000'], as_of=date(2026,10,2)) == {}
    assert prices.target_metadata(['005930'], as_of=date(2026,10,2))['005930']['name'] == '삼성전자'


def test_saving_known_targets_does_not_need_external_quotes(catalog, monkeypatch):
    async def forbidden(*a, **k):
        raise AssertionError('목표 저장에서 외부 현재가를 요청하면 안 된다')
    monkeypatch.setattr(rb.pt, 'resolve_stock', forbidden)
    result = asyncio.run(rb.resolve_targets([
        {'symbol':'005930','name':'임의 입력명','weight_pct':20},
        {'symbol':'005930.KS','weight_pct':10},
        {'symbol':'069500','weight_pct':15},
    ]))
    assert {t['symbol']: t['weight_pct'] for t in result} == {'005930.KS':30, '069500.KS':15}
    assert next(t for t in result if t['symbol']=='005930.KS')['name'] == '삼성전자'


@pytest.mark.parametrize('available', [True, False])
def test_unconfirmed_target_keeps_existing_validation(catalog, monkeypatch, available):
    if not available:
        monkeypatch.setenv('COLLECTOR_DB_PATH', str(catalog.parent/'absent.sqlite3'))
    calls = []
    async def rejected(symbol):
        calls.append(symbol)
        raise rb.pt.PaperTradeError('종목을 확인할 수 없습니다')
    monkeypatch.setattr(rb.pt,'resolve_stock',rejected)
    with pytest.raises(rb.RebalanceError, match='종목을 확인'):
        asyncio.run(rb.resolve_targets([{'symbol':'000000','weight_pct':30}]))
    assert calls == ['000000']
