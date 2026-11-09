"""#614 regression tests."""
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock
import numpy as np
import pytest
from app.services import performance_service as perf

def series(n, low=False, flat=False):
    x=np.arange(n,dtype=float)
    r=.001*np.sin(x*1.17) if low else .009*np.sin(x*1.17)+.003*np.cos(x*.43)
    b=np.zeros(n) if flat else .008*np.sin(x*.73+.2)+.002*np.cos(x*.31)
    return [f"2026-{i//28+1:02d}-{i%28+1:02d}" for i in range(n)],r,b

@pytest.mark.asyncio
async def test_returns_short_sample_is_not_reused_for_long_windows(monkeypatch):
    r=np.linspace(-.01,.012,12)
    async def daily(*args): return r,np.ones(13)*100
    monkeypatch.setattr(perf,'get_daily_returns',daily)
    out=await perf.get_returns_table(None,uuid4())
    assert all(out[f'return_{k}'] is None for k in ('1m','3m','6m','1y'))
    assert out['period_observations']['1m']=={'available':12,'required':21,'status':'insufficient_data'}

@pytest.mark.asyncio
@pytest.mark.parametrize('n',[5,12,20])
async def test_risk_windows_require_full_observations(monkeypatch,n):
    ds,r,b=series(n)
    async def daily(*args,**kwargs): return ds,r,np.ones(n+1)*100
    async def bench(): return ds,b
    monkeypatch.setattr(perf,'get_daily_returns',daily); monkeypatch.setattr(perf,'_get_benchmark_map',bench)
    out=await perf.get_risk_metrics(None,uuid4())
    for k,w in [('1m',21),('3m',63),('6m',126),('1y',252)]:
        assert out[k]['status']=='insufficient_data' and out[k]['sample_count']==n and out[k]['required_observations']==w

@pytest.mark.asyncio
async def test_full_window_metrics_match_sample_formulas(monkeypatch):
    ds,r,b=series(21)
    async def daily(*args,**kwargs): return ds,r,np.ones(22)*100
    async def bench(): return ds,b
    monkeypatch.setattr(perf,'get_daily_returns',daily); monkeypatch.setattr(perf,'_get_benchmark_map',bench)
    out=await perf.get_risk_metrics(None,uuid4()); m=out['1m']
    beta=np.cov(r,b,ddof=1)[0,1]/np.var(b,ddof=1)
    assert m['status']=='ok' and m['sample_count']==21
    assert m['beta']==pytest.approx(beta)
    assert m['tracking_error']==pytest.approx(np.std(r-b,ddof=1)*np.sqrt(252))
    assert out['3m']['status']=='insufficient_data' and out['inference_available'] is False

@pytest.mark.asyncio
async def test_zero_benchmark_variance_does_not_return_zero_beta(monkeypatch):
    ds,r,b=series(21,flat=True)
    async def daily(*args,**kwargs): return ds,r,np.ones(22)*100
    async def bench(): return ds,b
    monkeypatch.setattr(perf,'get_daily_returns',daily); monkeypatch.setattr(perf,'_get_benchmark_map',bench)
    m=(await perf.get_risk_metrics(None,uuid4()))['1m']
    assert m['beta'] is None and m['jensen_alpha'] is None and m['tracking_error'] is not None

@pytest.mark.asyncio
async def test_low_vol_guard_matches_qfrs(monkeypatch):
    ds,r,b=series(21,low=True)
    async def daily(*args,**kwargs): return ds,r,np.ones(22)*100
    async def bench(): return ds,b
    monkeypatch.setattr(perf,'get_daily_returns',daily); monkeypatch.setattr(perf,'_get_benchmark_map',bench)
    m=(await perf.get_risk_metrics(None,uuid4()))['1m']
    assert m['status']=='insufficient_data' and '표준편차' in m['reason']

def test_kis_midnight_epoch_is_not_shifted_to_previous_kst_day():
    epoch=datetime(2026,10,27,tzinfo=ZoneInfo('Asia/Seoul')).timestamp()
    assert perf._norm_date({'time':epoch},timestamp_timezone=ZoneInfo('Asia/Seoul'))=='2026-10-27'
    assert perf._norm_date({'time':epoch},timestamp_timezone=timezone.utc)=='2026-10-26'

@pytest.mark.asyncio
@pytest.mark.parametrize('source,zone',[('kis',ZoneInfo('Asia/Seoul')),('yahoo',timezone.utc)])
async def test_benchmark_map_uses_provider_timezone(monkeypatch,source,zone):
    a=datetime(2026,10,27,tzinfo=zone).timestamp()
    b=datetime(2026,10,28,tzinfo=zone).timestamp()
    data={'source':source,'candles':[{'time':a,'close':100.0},{'time':b,'close':101.0}]}
    monkeypatch.setattr('app.services.stock.get_candles',AsyncMock(return_value=data))
    dates,rets=await perf._get_benchmark_map()
    assert dates==['2026-10-28'] and rets.tolist()==pytest.approx([.01])

def test_benchmark_and_rf_are_labelled_qurious_assumptions():
    assert perf.BENCHMARK_SYMBOL=='^KS11' and perf._RF==pytest.approx(.02)
    assert '공식 벤치마크' in perf.BENCHMARK_NOTE and '공식 적용률' in perf.RISK_FREE_RATE_NOTE
