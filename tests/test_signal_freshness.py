"""TC-SF · 자동매매 신호의 일봉 신선도 (2026-11-04 · 사용자 「오전엔 2일 밀린 정보로 투자하는 것 아니냐」)

app/services/signal_freshness.py — 수집 DB 일봉이 직전 거래일 확정 종가보다 낡으면 KIS 확정 일봉을 메모리로만 붙이고,
그래도 낡으면 신호 주문을 「데이터 대기」 로 보류한다(위험 매도는 막지 않는다).
  1. 있어야 할 마지막 일봉 날짜 — 거래일 15:40 이후면 오늘, 그 전이면 직전 거래일(주말 · 휴장일 건너뜀)
  2. 판정 — 수집 DB as_of 와 맞댄다 · as_of 가 없으면(수집 DB 가 아닌 출처) 판정하지 않는다
  3. 꼬리 보강 — 확정된 날만 · 겹치는 날 종가가 0.5% 안일 때만 · 실패하면 낡은 채로 판정 · 켜고 끄는 스위치
  4. 자동매매 사이클 — 낡은 신호는 주문하지 않고 「데이터 대기」 · 위험 매도는 그대로 · 신선한 신호는 그대로
"""
import asyncio
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.services import kis_market_data as kmd
from app.services import signal_freshness as sf

KST = timezone(timedelta(hours=9))


@pytest.fixture()
def calendar_db(tmp_path: Path) -> Path:
  """2026-10-26 ~ 11-06 달력 — 주말은 쉬는 날, 10-29(목)는 임시 휴장으로 둔다."""
  p = tmp_path / "cal.db"
  conn = sqlite3.connect(p)
  conn.execute("CREATE TABLE market_calendar (cal_date TEXT PRIMARY KEY, is_trading_day INTEGER)")
  d = date(2026, 10, 26)
  while d <= date(2026, 11, 6):
    conn.execute("INSERT INTO market_calendar VALUES (?, ?)", (d.isoformat(), 0 if d.weekday() >= 5 or d == date(2026, 10, 29) else 1))
    d += timedelta(days=1)
  conn.commit()
  conn.close()
  return p


def at(y, m, d, hh, mm=0):
  return datetime(y, m, d, hh, mm, tzinfo=KST)


# ── 1. 있어야 할 마지막 일봉 날짜 ───────────────────────────────────────
@pytest.mark.parametrize("now, expected", [
  (at(2026, 11, 4, 9, 10), date(2026, 11, 3)),     # 수요일 오전 — 어제(화) 종가
  (at(2026, 11, 4, 15, 39), date(2026, 11, 3)),    # 마감 직후 15:40 전은 아직 어제
  (at(2026, 11, 4, 15, 40), date(2026, 11, 4)),    # 15:40 부터 오늘 봉
  (at(2026, 11, 2, 10, 0), date(2026, 10, 30)),    # 월요일 오전 — 금요일 종가
  (at(2026, 11, 1, 12, 0), date(2026, 10, 30)),    # 일요일 — 금요일
  (at(2026, 11, 1, 18, 0), date(2026, 10, 30)),    # 일요일 저녁도 금요일(오늘이 거래일이 아니다)
  (at(2026, 10, 30, 10, 0), date(2026, 10, 28)),   # 휴장일(10-29)을 건너뛴다
])
def test_expected_bar_date(calendar_db, now, expected):
  assert sf.expected_bar_date(now, path=calendar_db) == expected


# ── 2. 판정 ─────────────────────────────────────────────────────────────
def test_judge_stale_fresh_and_unchecked(calendar_db):
  now = at(2026, 11, 4, 10, 0)   # 오전 — 11-03 종가가 있어야 한다
  stale = sf.judge("2026-11-02", now, path=calendar_db)
  assert stale["state"] == "stale" and stale["expected"] == "2026-11-03" and stale["lag_days"] == 1
  assert sf.judge("2026-11-03", now, path=calendar_db)["state"] == "fresh"
  assert sf.judge("2026-11-04", now, path=calendar_db)["state"] == "fresh", "더 새로운 봉도 낡지 않았다"
  assert sf.judge(None, now, path=calendar_db)["state"] == "unchecked", "수집 DB 가 아닌 출처는 판정하지 않는다(옛 동작)"
  assert sf.judge("not-a-date", now, path=calendar_db)["state"] == "unchecked"


# ── 3. 꼬리 보강 ────────────────────────────────────────────────────────
def utc_ts(d: date) -> int:
  return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def kst_ts(d: date) -> int:
  return int(datetime(d.year, d.month, d.day, tzinfo=KST).timestamp())


def collector_data(last: date, close=70_000.0):
  days = [last - timedelta(days=i) for i in range(30, -1, -1)]
  candles = [{"time": utc_ts(d), "open": close, "high": close, "low": close, "close": close, "volume": 1} for d in days]
  return {"symbol": "005930.KS", "candles": candles, "source": "collector", "as_of": last.isoformat()}


def kis_daily(days_and_closes):
  return {"candles": [{"time": kst_ts(d), "open": c, "high": c, "low": c, "close": c, "volume": 1} for d, c in days_and_closes], "summary": {}}


@pytest.fixture()
def kis_on(monkeypatch, calendar_db):
  sf.reset_cache()   # 캐시는 모듈 전역이라 시험마다 비운다
  monkeypatch.setattr(settings, "SIGNAL_FRESHNESS_GUARD", True)
  monkeypatch.setattr(settings, "SIGNAL_KIS_TAIL", True)
  monkeypatch.setattr(kmd, "is_enabled", lambda: True)
  # 달력은 시험용 파일로 — 앱의 수집 DB 를 읽지 않는다
  orig = sf.expected_bar_date
  monkeypatch.setattr(sf, "expected_bar_date", lambda now=None, *, path=None: orig(now, path=calendar_db))


def test_tail_appends_only_settled_days_and_keeps_utc_midnight_stamp(kis_on, monkeypatch):
  data = collector_data(date(2026, 11, 2), 70_000.0)
  # KIS: 겹치는 날(11-02)은 같은 종가 · 11-03(확정) · 11-04(오늘 장중 — 이른 오전이므로 붙이면 안 된다)
  monkeypatch.setattr(kmd, "fetch_daily", AsyncMock(return_value=kis_daily([
    (date(2026, 11, 2), 70_100.0), (date(2026, 11, 3), 71_000.0), (date(2026, 11, 4), 99_999.0)])))
  out, verdict = asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))
  assert verdict["state"] == "fresh" and verdict["tail"] == "kis+1" and verdict["as_of"] == "2026-11-03"
  assert out["as_of"] == "2026-11-03" and out["source"] == "collector+kis_tail"
  assert out["candles"][-1]["close"] == 71_000.0 and out["candles"][-1]["time"] == utc_ts(date(2026, 11, 3))
  assert len(out["candles"]) == len(data["candles"]) + 1, "오늘 장중 봉은 붙이지 않는다"
  assert data["as_of"] == "2026-11-02" and len(data["candles"]) == 31, "원본(수집 DB 에서 읽은 사전)은 건드리지 않는다"


def test_tail_after_close_adds_today(kis_on, monkeypatch):
  data = collector_data(date(2026, 11, 2))
  monkeypatch.setattr(kmd, "fetch_daily", AsyncMock(return_value=kis_daily([
    (date(2026, 11, 2), 70_000.0), (date(2026, 11, 3), 71_000.0), (date(2026, 11, 4), 72_000.0)])))
  out, verdict = asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 16, 0)))
  assert verdict["tail"] == "kis+2" and out["as_of"] == "2026-11-04" and verdict["state"] == "fresh"


def test_basis_mismatch_refuses_to_mix_adjusted_and_raw(kis_on, monkeypatch):
  data = collector_data(date(2026, 11, 2), 70_000.0)
  monkeypatch.setattr(kmd, "fetch_daily", AsyncMock(return_value=kis_daily([
    (date(2026, 11, 2), 35_000.0), (date(2026, 11, 3), 36_000.0)])))   # 액면분할 — 수정주가와 원주가가 2배 차이
  out, verdict = asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))
  assert out is data and verdict["state"] == "stale" and verdict["tail"] == "basis_mismatch"


def test_no_overlap_day_refuses(kis_on, monkeypatch):
  data = collector_data(date(2026, 10, 20))
  monkeypatch.setattr(kmd, "fetch_daily", AsyncMock(return_value=kis_daily([(date(2026, 11, 3), 71_000.0)])))
  out, verdict = asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))
  assert out is data and verdict["tail"] == "basis_mismatch"


def test_kis_error_stays_stale_and_does_not_raise(kis_on, monkeypatch):
  data = collector_data(date(2026, 11, 2))
  monkeypatch.setattr(kmd, "fetch_daily", AsyncMock(side_effect=RuntimeError("boom")))
  out, verdict = asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))
  assert out is data and verdict["state"] == "stale" and verdict["tail"] == "error"


def test_no_gateway_or_foreign_symbol_stays_stale(kis_on, monkeypatch):
  data = collector_data(date(2026, 11, 2))
  monkeypatch.setattr(kmd, "is_enabled", lambda: False)
  assert asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))[1]["tail"] == "unavailable"
  monkeypatch.setattr(kmd, "is_enabled", lambda: True)
  assert asyncio.run(sf.settle("AAPL", data, at(2026, 11, 4, 9, 30)))[1]["tail"] == "unavailable"


def test_switches(kis_on, monkeypatch):
  data = collector_data(date(2026, 11, 2))
  fetch = AsyncMock(return_value=kis_daily([(date(2026, 11, 2), 70_000.0), (date(2026, 11, 3), 71_000.0)]))
  monkeypatch.setattr(kmd, "fetch_daily", fetch)
  monkeypatch.setattr(settings, "SIGNAL_KIS_TAIL", False)
  out, verdict = asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))
  assert out is data and verdict["state"] == "stale" and verdict["tail"] == "off" and not fetch.await_count
  monkeypatch.setattr(settings, "SIGNAL_FRESHNESS_GUARD", False)
  assert asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))[1] == {"state": "off"}


def test_non_collector_source_is_never_judged(kis_on):
  data = {"symbol": "AAPL", "candles": [], "source": "yahoo"}
  out, verdict = asyncio.run(sf.settle("AAPL", data, at(2026, 11, 4, 9, 30)))
  assert out is data and verdict["state"] == "unchecked"


def test_tail_is_only_active_inside_for_trading():
  assert sf.trading_active() is False
  with sf.for_trading():
    assert sf.trading_active() is True
  assert sf.trading_active() is False


# ── 3b. 게이트웨이 부담 줄이기 (조사 결과 2026-11-04) ───────────────────────
def test_confirmed_days_are_fetched_once_per_expected_date(kis_on, monkeypatch):
  fetch = AsyncMock(return_value=kis_daily([(date(2026, 11, 2), 70_000.0), (date(2026, 11, 3), 71_000.0)]))
  monkeypatch.setattr(kmd, "fetch_daily", fetch)
  for _ in range(3):   # 10분마다 부르는 사이클 — 같은 날 안에서는 게이트웨이를 한 번만 부른다
    out, verdict = asyncio.run(sf.settle("005930.KS", collector_data(date(2026, 11, 2)), at(2026, 11, 4, 9, 30)))
    assert verdict["tail"] == "kis+1" and out["as_of"] == "2026-11-03"
  assert fetch.await_count == 1


def test_failure_and_unposted_day_cool_down_instead_of_hammering(kis_on, monkeypatch):
  boom = AsyncMock(side_effect=RuntimeError("boom"))
  monkeypatch.setattr(kmd, "fetch_daily", boom)
  data = collector_data(date(2026, 11, 2))
  assert asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))[1]["tail"] == "error"
  assert asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 40)))[1]["tail"] == "cooldown"
  assert boom.await_count == 1
  # 아직 확정일이 안 올라온 응답은 캐시하지 않고 잠시 쉰다
  sf.reset_cache()
  stale = AsyncMock(return_value=kis_daily([(date(2026, 11, 2), 70_000.0)]))
  monkeypatch.setattr(kmd, "fetch_daily", stale)
  assert asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))[1]["tail"] == "none"
  assert asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 41)))[1]["tail"] == "cooldown"
  assert stale.await_count == 1


def test_cache_key_changes_with_the_expected_date(kis_on, monkeypatch):
  fetch = AsyncMock(return_value=kis_daily([(date(2026, 11, 2), 70_000.0), (date(2026, 11, 3), 71_000.0), (date(2026, 11, 4), 72_000.0)]))
  monkeypatch.setattr(kmd, "fetch_daily", fetch)
  data = collector_data(date(2026, 11, 2))
  asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))    # 있어야 할 날 11-03
  out, verdict = asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 16, 0)))   # 마감 뒤 — 11-04 로 키가 바뀌어 새로 받는다
  assert fetch.await_count == 2 and verdict["tail"] == "kis+2" and out["as_of"] == "2026-11-04"


# ── 3c. 사용자 자기 KIS 키로 꼬리 받기 (조사 결과 2026-11-04 — 게이트웨이가 꺼져 있어도 동작) ──────────────
def user_bars(days_and_closes):
  return [{"date": d.strftime("%Y%m%d"), "open": c, "high": c, "low": c, "close": c, "volume": 1} for d, c in days_and_closes]


def test_user_kis_fetcher_works_even_when_gateway_is_off(kis_on, monkeypatch):
  monkeypatch.setattr(kmd, "is_enabled", lambda: False)   # 게이트웨이 주소가 비어 있는 실제 상태
  gateway = AsyncMock()
  monkeypatch.setattr(kmd, "fetch_daily", gateway)
  user = AsyncMock(return_value=user_bars([(date(2026, 11, 2), 70_100.0), (date(2026, 11, 3), 71_000.0), (date(2026, 11, 4), 99_999.0)]))
  with sf.for_trading(user, "user-1"):
    out, verdict = asyncio.run(sf.settle("005930.KS", collector_data(date(2026, 11, 2)), at(2026, 11, 4, 9, 30)))
  assert verdict["state"] == "fresh" and verdict["tail"] == "kis+1" and out["as_of"] == "2026-11-03"
  assert out["candles"][-1]["time"] == utc_ts(date(2026, 11, 3)), "수집 DB 와 같은 시간표시(UTC 자정)로 붙인다"
  assert user.await_count == 1 and not gateway.await_count, "자기 키가 있으면 게이트웨이를 부르지 않는다"


def test_user_tail_cache_is_scoped_per_user(kis_on, monkeypatch):
  monkeypatch.setattr(kmd, "is_enabled", lambda: False)
  fetch_a = AsyncMock(return_value=user_bars([(date(2026, 11, 2), 70_000.0), (date(2026, 11, 3), 71_000.0)]))
  fetch_b = AsyncMock(return_value=user_bars([(date(2026, 11, 2), 70_000.0), (date(2026, 11, 3), 71_000.0)]))
  for scope, fetch in (("a", fetch_a), ("a", fetch_a), ("b", fetch_b)):
    with sf.for_trading(fetch, scope):
      assert asyncio.run(sf.settle("005930.KS", collector_data(date(2026, 11, 2)), at(2026, 11, 4, 9, 30)))[1]["tail"] == "kis+1"
  assert fetch_a.await_count == 1, "같은 사용자는 하루 한 번"
  assert fetch_b.await_count == 1, "다른 사용자의 시세를 이 사용자 사이클이 대신 쓰지 않는다(제3자 제공 금지)"


def test_user_fetch_error_stays_stale_and_cools_down(kis_on, monkeypatch):
  monkeypatch.setattr(kmd, "is_enabled", lambda: False)
  boom = AsyncMock(side_effect=ValueError("KIS 일봉 가격·거래량이 유효하지 않습니다."))
  data = collector_data(date(2026, 11, 2))
  with sf.for_trading(boom, "u"):
    assert asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 30)))[1]["tail"] == "error"
    assert asyncio.run(sf.settle("005930.KS", data, at(2026, 11, 4, 9, 40)))[1]["tail"] == "cooldown"
  assert boom.await_count == 1


def test_user_fetcher_throttles_and_asks_for_recent_window():
  calls = []

  class Client:
    async def get_daily_ohlcv(self, symbol, start, end):
      calls.append((symbol, start, end))
      return []

  fetch = sf.user_kis_fetcher(Client(), interval_sec=0.05, days=21)

  async def run():
    t0 = asyncio.get_event_loop().time()
    await fetch("005930.KS")
    await fetch("000660.KS")
    return asyncio.get_event_loop().time() - t0

  elapsed = asyncio.run(run())
  assert len(calls) == 2 and elapsed >= 0.05, "호출 사이에 간격을 둔다(모의 계좌 초당 2건 한도)"
  symbol, start, end = calls[0]
  assert (date.fromisoformat(f"{end[:4]}-{end[4:6]}-{end[6:]}") - date.fromisoformat(f"{start[:4]}-{start[4:6]}-{start[6:]}")).days == 21


def test_auto_trade_prefers_the_users_own_kis_key():
  src = (Path(__file__).resolve().parents[1] / "app" / "services" / "auto_trade.py").read_text(encoding="utf-8")
  assert "signal_freshness.user_kis_fetcher(tail_client)" in src and src.count("for_trading(tail_fetch, str(uid))") == 2


# ── 4. 자동매매 사이클 ──────────────────────────────────────────────────
def _cycle():
  from tests import test_quant_cycle_integration as tq
  return tq


@pytest.fixture()
def cycle_env(monkeypatch):
  """사이클 시험 환경 — test_quant_cycle_integration 의 autouse env 와 같은 설정(그 파일 밖에서는 적용되지 않는다)."""
  from app.services.brokers import stock_coin_trade_gateway as gw
  monkeypatch.setattr(settings, "QUANT_AGGRESSIVE_MODE", False)
  monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "https://sct.test")
  monkeypatch.setattr(settings, "STOCK_COIN_TRADE_API_KEY", "key")
  monkeypatch.setattr(settings, "STOCK_COIN_TRADE_KIS_ENVIRONMENT", "paper")
  yield
  gw.set_transport(None)


def test_stale_signal_places_no_order_and_logs_wait(monkeypatch, cycle_env):
  tq = _cycle()
  original = tq.indicators   # 갈아 끼우기 전의 함수 — 이름으로 다시 부르면 자기 자신을 부른다
  async def stale_indicators(symbol, period="2y"):
    out = await original(symbol, period)
    if symbol == "005930.KS":
      out["freshness"] = {"state": "stale", "as_of": "2026-11-02", "expected": "2026-11-03", "lag_days": 1, "tail": "unavailable"}
    return out
  monkeypatch.setattr(tq, "indicators", stale_indicators)
  tq.fake_gateway()
  db, log = tq.run_cycle(tq.broker("live"))
  assert [t for t in log["trades"] if t.get("type") == "auto"] == [], "낡은 신호로는 주문하지 않는다"
  wait = [s for s in log["signals"] if s.get("symbol") == "005930.KS"]
  assert wait and wait[0]["action"] == "데이터 대기" and wait[0]["basis"]["expected"] == "2026-11-03"
  assert "보류" in wait[0]["reasons"][0] and "unavailable" in wait[0]["reasons"][0]


def test_fresh_signal_still_orders(monkeypatch, cycle_env):
  tq = _cycle()
  original = tq.indicators
  async def fresh_indicators(symbol, period="2y"):
    out = await original(symbol, period)
    if symbol == "005930.KS":
      out["freshness"] = {"state": "fresh", "as_of": "2026-11-03", "expected": "2026-11-03", "lag_days": 0, "tail": "kis+1"}
    return out
  monkeypatch.setattr(tq, "indicators", fresh_indicators)
  tq.fake_gateway()
  db, log = tq.run_cycle(tq.broker("live"))
  assert len([t for t in log["trades"] if t.get("type") == "auto"]) == 1


def test_auto_trade_wires_for_trading_and_exempts_risk_stops():
  src = (Path(__file__).resolve().parents[1] / "app" / "services" / "auto_trade.py").read_text(encoding="utf-8")
  assert src.count("signal_freshness.for_trading(tail_fetch, str(uid))") == 2, "일봉 지표를 받는 두 곳 모두 자동매매 안에서만 꼬리를 붙인다"
  assert 'fresh.get("state") == "stale" and symbol not in risk_stops' in src, "위험 매도는 낡은 일봉과 무관하게 막지 않는다"


def test_large_gap_between_signal_and_order_price_warns_but_still_orders(cycle_env):
  tq = _cycle()
  tq.fake_gateway()
  db, log = tq.run_cycle(tq.broker("live"), quote_price=75_000)   # 판단가 70,000 → 주문 직전 75,000 (+7.1%)
  trade = [t for t in log["trades"] if t.get("type") == "auto"]
  assert len(trade) == 1, "경고만 하고 막지는 않는다"
  assert "⚠ 판단가와 주문 직전 가격 차이 +7.14%" in trade[0]["reason"]


def test_small_gap_has_no_warning(cycle_env):
  tq = _cycle()
  tq.fake_gateway()
  db, log = tq.run_cycle(tq.broker("live"), quote_price=70_500)
  trade = [t for t in log["trades"] if t.get("type") == "auto"]
  assert len(trade) == 1 and "⚠" not in trade[0]["reason"]
