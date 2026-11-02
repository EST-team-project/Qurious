"""KIS 공식 기간 일봉 계약과 100봉 페이지 경계. 모든 HTTP는 합성이다."""
import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.brokers import kis


def bar(day, **changes):
    return {'stck_bsop_date': day.strftime('%Y%m%d'), 'stck_oprc': '100',
        'stck_hgpr': '110', 'stck_lwpr': '90', 'stck_clpr': '101', 'acml_vol': '3', **changes}


def client(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(kis.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(kis.asyncio, 'sleep', AsyncMock())
    instance = kis.KISClient('synthetic', 'synthetic')
    monkeypatch.setattr(instance, '_ensure_token', AsyncMock())
    return instance


def test_adjusted_period_api_paginates_and_respects_dates(monkeypatch):
    end = date(2026, 11, 2)
    seen = []
    def handler(request):
        params = dict(request.url.params)
        seen.append(params)
        assert request.url.path.endswith('/inquire-daily-itemchartprice')
        assert request.headers['tr_id'] == 'FHKST03010100'
        assert params['FID_ORG_ADJ_PRC'] == '0' and params['FID_INPUT_ISCD'] == '005930'
        rows = [bar(end-timedelta(days=i)) for i in range(100)] if len(seen)==1 else [
            bar(end-timedelta(days=i)) for i in range(100, 103)]
        return httpx.Response(200, json={'rt_cd':'0','output2':rows})
    c = client(monkeypatch, handler)
    start = (end-timedelta(days=101)).strftime('%Y%m%d')
    result = asyncio.run(c.get_daily_ohlcv('005930.KS',start,'20261102'))
    assert len(result)==102 and result[0]['date']==start and result[-1]['date']=='20261102'
    assert seen[1]['FID_INPUT_DATE_2']==(end-timedelta(days=100)).strftime('%Y%m%d')
    assert seen[1]['FID_INPUT_DATE_1']==start


@pytest.mark.parametrize('rows', [None, [bar(date(2026,11,3))],
    [bar(date(2026,11,2), stck_clpr='nan')], [bar(date(2026,11,2), stck_lwpr='102')],
    [bar(date(2026,11,2), acml_vol='-1')], [bar(date(2026,11,2)),bar(date(2026,11,2),stck_clpr='102')]])
def test_invalid_or_future_bars_are_rejected(monkeypatch, rows):
    c = client(monkeypatch, lambda r: httpx.Response(200,json={'rt_cd':'0','output2':rows}))
    with pytest.raises(ValueError):
        asyncio.run(c.get_daily_ohlcv('005930.KS','20261001','20261102'))


def test_bad_range_fails_before_request(monkeypatch):
    c = client(monkeypatch, lambda r: pytest.fail('invalid range must not request'))
    with pytest.raises(ValueError):
        asyncio.run(c.get_daily_ohlcv('005930.KS','20261102','20261001'))
