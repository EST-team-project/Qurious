"""자동매매 신호의 일봉 신선도 — 낡은 종가로 주문하지 않게 (2026-11-04 · 사용자 「오전엔 2일 밀린 정보로 투자하는 것 아니냐」)

문제
----
자동매매 신호는 수집 DB 일봉(`collector_db`)으로 계산한다. 일봉 정본(공공데이터포털 주식시세정보)은 거래일 **다음 영업일
낮**에야 올라와서 수집 회차가 12:30 이다. 그래서 오전 판단은 직전 거래일이 아니라 **그 전 거래일 종가**까지만 본다
(예: 11-04 오전의 마지막 봉은 11-02). 주문 직전 가격만 KIS 현재가로 새로 읽으니, 가격은 새것이고 판단은 낡은 모양이 된다.

이 모듈이 하는 일 (세 가지, 모두 자동매매 사이클에서만)
---------------------------------------------------------
1. **판정**(`judge`) — 지금 있어야 할 마지막 확정 일봉 날짜(`expected_bar_date`)와 수집 DB 의 `as_of` 를 맞대어
   fresh / stale 을 가른다. 거래일 15:40 이후면 오늘 봉, 그 전이면 직전 거래일 봉이 있어야 한다.
2. **꼬리 보강**(`settle`) — 낡았으면 KIS 일봉(`kis_market_data.fetch_daily`)에서 **확정된 날만** 가져와 **메모리에서만**
   붙인다. 수집 DB · HF 에는 쓰지 않는다(KIS 약관: 시세는 개인 업무에 한해 쓰고 제3자에게 주지 않는다 · collector/sources/kis.py).
   받는 곳은 ① **그 사용자 자기 KIS 키**(`brokers/kis.py` get_daily_ohlcv · 수정주가 일봉 · 약관상 개인 업무에 가장 가깝고 게이트웨이가 꺼져 있어도 동작)
   ② 키가 없으면 강사님 st 게이트웨이(`STOCK_COIN_TRADE_BASE_URL` · 공유 서버 — 「개인 업무」 해당 여부는 사용자가 약관으로 판단 · 조사 2026-11-04)
   ③ 둘 다 없으면 받지 않고 낡은 채로 판정한다. 확정일 캐시는 **사용자별**(다른 사용자의 사이클이 남의 시세를 쓰지 않게)이고 실패 · 미게시는 5분 쉰다.
3. **보류**(auto_trade.py) — 그래도 낡았으면 그 종목의 신호 주문을 내지 않고 「데이터 대기」 로 기록한다.
   손절·익절 같은 위험 매도(risk_stops)는 실시간 시세로 판단하므로 막지 않는다.

켜기·끄기: `SIGNAL_FRESHNESS_GUARD`(False 면 옛 동작) · `SIGNAL_KIS_TAIL`(False 면 보강 없이 가드만).
수집 DB 가 아닌 출처(KIS · 야후 직접)의 일봉은 `as_of` 가 없어 판정하지 않는다(`unchecked`) — 이전 동작 그대로다.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import time as _time
from datetime import date, datetime, time, timedelta, timezone

from app.config import settings

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
#: 장 마감(15:30) 뒤 KIS 가 오늘 일봉을 확정해 주는 시각의 여유 — 모의 계좌 일별 스냅샷(15:40)과 같은 시각
SETTLE_TIME = time(15, 40)
#: 겹치는 날 종가 차이 허용 비율 — 수정주가·원주가가 섞였는지 가린다
BASIS_TOLERANCE = 0.005

#: 확정된 날의 KIS 일봉 캐시 — 키 (범위: 사용자 id 또는 gateway, 기호, 있어야 할 날짜). 확정된 과거 봉은 바뀌지 않으므로 하루(키가 바뀔 때까지) 한 번만 받는다.
#: KIS 호출은 강사님 공유 게이트웨이(STOCK_COIN_TRADE_BASE_URL)를 거치므로 10분 주기 사이클마다 종목 수만큼 부르지 않게 한다(조사 결과 2026-11-04).
_TAIL_CACHE: dict[tuple[str, str, str], dict[date, dict]] = {}
#: 받지 못했거나 아직 확정일이 안 올라온 기호는 잠시 다시 부르지 않는다 — 「범위:기호」 별 다시 부를 수 있는 시각(monotonic 초)
_RETRY_AT: dict[str, float] = {}
RETRY_COOLDOWN_SEC = 300


def reset_cache() -> None:
    """시험·재시작용 — 캐시와 쉬는 시간을 비운다."""
    _TAIL_CACHE.clear()
    _RETRY_AT.clear()


#: 자동매매 사이클 안에서만 꼬리 보강을 켠다(화면 · 다른 분석은 읽기 전용 그대로)
_trading: contextvars.ContextVar[bool] = contextvars.ContextVar("signal_freshness_trading", default=False)
#: 이번 사이클의 사용자별 KIS 일봉 받기 — (캐시 범위 이름, async fetch(symbol) -> [{date: YYYYMMDD, close, ...}]). 없으면 게이트웨이를 쓴다.
_user_tail: contextvars.ContextVar[tuple[str, object] | None] = contextvars.ContextVar("signal_freshness_user_tail", default=None)


@contextlib.contextmanager
def for_trading(user_fetch=None, scope: str = ""):
    """`with signal_freshness.for_trading():` 안에서 부른 `get_quant_indicators` 만 KIS 꼬리를 붙인다.

    user_fetch: 그 사용자 **자기 KIS 키**로 일봉을 받는 함수(약관상 개인 업무에 가장 가깝다 · 게이트웨이가 꺼져 있어도 동작).
    scope: 캐시를 가르는 이름(사용자 id) — 한 사용자가 받은 시세를 다른 사용자의 사이클이 쓰지 않게 한다.
    """
    token = _trading.set(True)
    token2 = _user_tail.set((scope or "user", user_fetch) if user_fetch else None)
    try:
        yield
    finally:
        _user_tail.reset(token2)
        _trading.reset(token)


def user_kis_fetcher(client, *, interval_sec: float = 1.1, days: int = 21):
    """사용자 자기 KIS 클라이언트(`brokers/kis.py` get_daily_ohlcv · 수정주가 일봉)로 최근 일봉을 받는 함수를 만든다.

    모의 서버는 호출이 빠르면 HTTP 500(유량 초과)을 낸다 — 2026-11-04 실측: 0.6초 간격에서 둘째 호출이 500, 1.2초 간격 네 종목은 모두 성공 →
    기본 1.1초. 확정일 캐시 덕에 사용자당 하루 종목 수만큼(31곳이면 약 35초) 한 번만 부른다.
    돌려주는 값은 [{date: YYYYMMDD, open, high, low, close, volume}] — 오래된 → 최신.
    """
    state = {"last": 0.0}
    lock = asyncio.Lock()

    async def fetch(symbol: str) -> list[dict]:
        async with lock:
            wait = state["last"] + interval_sec - _time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                end = datetime.now(KST).date()
                return await client.get_daily_ohlcv(symbol, (end - timedelta(days=days)).strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            finally:
                state["last"] = _time.monotonic()

    return fetch


def trading_active() -> bool:
    return _trading.get()


def expected_bar_date(now: datetime | None = None, *, path=None) -> date:
    """지금 시점에 수집돼 있어야 할 마지막 **확정** 일봉의 날짜 (거래일 달력은 수집 DB 의 market_calendar)."""
    from app.services import paper_journal as pj   # 거래일 달력 읽기 — 달력이 없으면 평일로 본다
    k = (now or datetime.now(KST)).astimezone(KST)
    d = k.date()
    if k.time() >= SETTLE_TIME and pj.is_trading_day(d, pj._calendar(d, d, path=path)):
        return d
    return pj.prev_trading_day(d, path=path)


def judge(as_of: str | None, now: datetime | None = None, *, path=None) -> dict:
    """수집 DB `as_of`(YYYY-MM-DD)와 있어야 할 날짜를 맞댄다. as_of 가 없으면 판정하지 않는다(unchecked)."""
    if not as_of:
        return {"state": "unchecked", "as_of": None, "expected": None, "lag_days": None}
    expected = expected_bar_date(now, path=path)
    try:
        last = date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return {"state": "unchecked", "as_of": str(as_of), "expected": expected.isoformat(), "lag_days": None}
    return {"state": "fresh" if last >= expected else "stale", "as_of": last.isoformat(),
            "expected": expected.isoformat(), "lag_days": max(0, (expected - last).days)}


def _utc_date(ts: int | float) -> date:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date()


def _kst_date(ts: int | float) -> date:
    return datetime.fromtimestamp(ts, tz=KST).date()


def _utc_midnight(d: date) -> int:
    """수집 DB 일봉과 같은 시간표시 — 그 날짜의 UTC 자정."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


async def settle(symbol: str, data: dict, now: datetime | None = None, *, path=None) -> tuple[dict, dict]:
    """(필요하면 꼬리를 붙인 일봉 data, 신선도 판정). data 는 `stock.get_candles` 의 돌려주는 사전."""
    if not settings.SIGNAL_FRESHNESS_GUARD:
        return data, {"state": "off"}
    now = now or datetime.now(KST)
    verdict = judge(data.get("as_of") if data.get("source") == "collector" else None, now, path=path)
    if verdict["state"] != "stale":
        return data, verdict
    if not settings.SIGNAL_KIS_TAIL:
        return data, {**verdict, "tail": "off"}

    from app.services import kis_market_data as kmd
    user = _user_tail.get()
    is_krx = kmd.is_krx(symbol)
    if not is_krx or (user is None and not kmd.is_enabled()):
        return data, {**verdict, "tail": "unavailable"}   # 자기 KIS 키도 게이트웨이도 없다 — 낡은 채로 판정만
    candles = list(data.get("candles") or [])
    if not candles:
        return data, {**verdict, "tail": "none"}
    expected = date.fromisoformat(verdict["expected"])
    scope, source = (user[0], "user") if user else ("gateway", "gateway")
    key = (scope, symbol, verdict["expected"])
    by_day = _TAIL_CACHE.get(key)
    if by_day is None:
        retry_key = f"{scope}:{symbol}"
        if _time.monotonic() < _RETRY_AT.get(retry_key, 0.0):
            return data, {**verdict, "tail": "cooldown"}   # 방금 실패했다 — 증권사를 다시 두드리지 않는다
        try:
            if user:
                bars = await user[1](symbol)
                days = [(datetime.strptime(str(b["date"]), "%Y%m%d").date(), b) for b in bars or [] if b.get("close")]
            else:
                raw = await kmd.fetch_daily(symbol, 20)
                days = [(_kst_date(c["time"]), c) for c in raw.get("candles") or [] if c.get("close")]
        except Exception as exc:   # 보강은 덤이다 — 실패해도 사이클은 가드로 안전하게 보류한다
            logger.warning("신호 꼬리 보강 실패 %s(%s): %s", symbol, source, exc)
            _RETRY_AT[retry_key] = _time.monotonic() + RETRY_COOLDOWN_SEC
            return data, {**verdict, "tail": "error"}
        # 확정된 날(있어야 할 날짜 이하)만 쓴다 — 오늘 장중의 진행 중 봉은 버린다
        by_day = {d: c for d, c in days if d <= expected}
        if expected in by_day:
            for k in [k for k in _TAIL_CACHE if k[2] != verdict["expected"]]:
                del _TAIL_CACHE[k]   # 지난 날짜 키는 지운다
            _TAIL_CACHE[key] = by_day
            _RETRY_AT.pop(retry_key, None)
        else:
            _RETRY_AT[retry_key] = _time.monotonic() + RETRY_COOLDOWN_SEC   # 아직 확정일이 안 올라왔다 — 잠시 뒤 다시
    last_day = _utc_date(candles[-1]["time"])
    base = by_day.get(last_day)
    last_close = candles[-1].get("close")
    if base is None or not last_close or abs(float(base["close"]) / float(last_close) - 1) > BASIS_TOLERANCE:
        # 겹치는 날이 없거나 종가가 다르다 — 수정주가·원주가가 섞일 수 있어 붙이지 않는다
        return data, {**verdict, "tail": "basis_mismatch"}
    added = [{**c, "time": _utc_midnight(d)} for d, c in sorted(by_day.items()) if last_day < d <= expected]
    if not added:
        return data, {**verdict, "tail": "none"}
    patched = {**data, "candles": candles + added, "as_of": _utc_date(added[-1]["time"]).isoformat(),
               "source": f"{data.get('source')}+kis_tail"}
    out = judge(patched["as_of"], now, path=path)
    out["tail"] = f"kis+{len(added)}"
    return patched, out
