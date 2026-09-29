"""수집 DB 시세 어댑터 — 화면·분석이 수집기가 모은 일봉을 읽는 다리 (DF-08 · 옛 `#61` P1-1).

왜 필요한가
-----------
수집기는 2020-01-02 부터 전 종목 일봉을 `data/collector/market.sqlite3` 에 모았다(446만 행).
그런데 앱의 차트 · 지표 · 백테스트 · ML 은 이 DB 를 한 번도 읽지 않고 외부 차트 API 를
불렀다(ERD v1.0 §1 「두 DB 는 이어져 있지 않다」). 팀은 그 외부 API 를 약관 근거로 배제했다
(옛 `#23` · `#31`). 이 모듈은 `stock.get_candles` 가 **먼저** 부르는 읽기 전용 어댑터다.

무엇을 돌려주나 — `get_candles` 와 **같은 모양**에 두 칸을 더한다
    {"symbol", "interval", "period",
     "candles": [{"time", "open", "high", "low", "close", "volume"}, ...],
     "source": "collector", "as_of": "YYYY-MM-DD"}

- 값은 **수정주가**(`price_adjusted`)다. 분할 · 권리락 날에 차트가 끊기지 않고, 수익률 ·
  변동성 · 지표가 분할을 폭락으로 읽지 않는다. 가장 최근 날의 계수가 1 이라 마지막 봉은 원래 값과 같다.
- `time` 은 그날 00:00 UTC(= 09:00 KST 장 시작)의 유닉스 초다.
- 거래가 없던 날(거래정지 등 · 시가 0)은 **시가 = 고가 = 저가 = 종가**인 평평한 봉이다.
  그날 종가는 전일 종가 그대로라 사실과 같고, 고가 · 저가를 실수로 쓰는 분석
  (`quant_pipeline` 의 ATR 등)이 빈 값을 만나 멈추지 않는다.
- 거래량은 **원래 거래량 ÷ 계수**를 반올림한 정수다(분할 전 거래량을 분할 뒤 주식 수로 맞춘다).
  권리락 계수(0.98 안팎)도 같이 나누므로 그날 앞의 거래량이 2% 안팎 커진다 — 분석에 영향이 없는 크기다.
- `as_of` 는 돌려준 마지막 봉의 날짜다. 수집기는 공공데이터포털이 **다음 날 낮**에 주는 값을 받으므로
  (collector/README §7) 오늘 봉은 없다. 화면은 이 칸으로 기준일을 보여 줄 수 있다.

None 을 돌려주는 때 — 호출자(`get_candles`)가 옛 경로로 넘어간다
- 국내 주식 기호(`123456.KS` · `123456.KQ`)가 아닐 때 — 지수 · 환율 · 해외 · ETF 는 이 DB 에 없다
- 일봉(`1d`)이 아닐 때 · 모르는 기간일 때
- DB 파일이 없거나 열리지 않을 때 · 그 종목 행이 기간 안에 하나도 없을 때

**예외를 올리지 않는다.** 어댑터가 죽어서 화면이 비는 것보다 옛 경로로 넘어가는 쪽이 낫다.
대신 DB 를 못 연 이유는 로그에 남긴다.

다리 앞에 캐시를 두지 않는다 — 라우트 · 캐시 데우기는 `handles()` 가 참이면 캐시를 건너뛴다(DF-17).
캐시가 앞에 있으면 12:30 일일 갱신 뒤에도 캐시가 살아 있는 동안 옛 `as_of` 가 나간다.

DB 는 어디서 찾나
-----------------
1. 환경 변수 `COLLECTOR_DB_PATH` 가 있으면 그 파일만 본다(시험 · 다른 배치).
2. 없으면 `<저장소>/data/collector/market.sqlite3` — 로컬에서 앱을 돌릴 때.
3. 그다음 `<저장소>/data/csv/collector/market.sqlite3` — 도커. compose 가 호스트의 `./data` 를
   앱 컨테이너의 `/app/data/csv` 에 읽기 전용으로 이미 붙이고 있어, compose 를 고치지 않아도 보인다.

앱 이미지에는 `collector/` 패키지가 들어가지 않는다(Dockerfile 이 복사하지 않는다). 그래서 이 모듈은
`collector` 를 import 하지 않고 경로 · 표 이름을 스스로 안다. 표 모양이 바뀌면 `collector/db.py` 와
함께 고친다 — `tests/test_collector_candles_df08.py` 가 수집기의 실제 스키마로 픽스처 DB 를 만들어 이 어긋남을 잡는다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_DB_PATH = "COLLECTOR_DB_PATH"
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CANDIDATES = (
    _ROOT / "data" / "collector" / "market.sqlite3",         # 로컬 실행
    _ROOT / "data" / "csv" / "collector" / "market.sqlite3",  # 도커 — ./data 가 /app/data/csv 에 읽기 전용으로 붙는다
)

KST = timezone(timedelta(hours=9))

# 국내 주식 기호만 받는다. 뒤의 .KS(코스피) · .KQ(코스닥)는 옛 경로의 표기다 —
# 단축코드는 시장을 가리지 않고 하나뿐이라 시장 구분은 보지 않는다.
_SYMBOL = re.compile(r"^(\d{6})\.(KS|KQ)$")

# 화면이 쓰는 기간 8개(IA v0.2 · app.html 선택지) + 전체. 모르는 기간은 None → 옛 경로.
_PERIOD_MONTHS: dict[str, int | None] = {
    "1mo": 1, "3mo": 3, "6mo": 6,
    "1y": 12, "2y": 24, "3y": 36, "5y": 60, "10y": 120,
    "max": None,
}

_QUERY = """
SELECT a.bas_dt, a.adj_clpr, a.adj_mkp, a.adj_hipr, a.adj_lopr, a.cum_factor,
       d.mkp, d.trqu
  FROM price_adjusted AS a
  JOIN price_daily    AS d ON d.bas_dt = a.bas_dt AND d.srtn_cd = a.srtn_cd
 WHERE a.srtn_cd = ? AND a.bas_dt >= ? AND a.bas_dt <= ?
 ORDER BY a.bas_dt
"""

_warned_missing = False


def db_path() -> Path | None:
    """수집 DB 파일 위치. 없으면 None."""
    env = os.environ.get(ENV_DB_PATH)
    if env:
        p = Path(env)
        return p if p.is_file() else None
    for p in _DEFAULT_CANDIDATES:
        if p.is_file():
            return p
    return None


def _match(symbol: str, period: str, interval: str) -> re.Match | None:
    """다리가 받는 요청 모양이면 기호 일치 결과, 아니면 None — 국내 주식 기호 · 일봉 · 아는 기간."""
    m = _SYMBOL.match(symbol or "")
    return m if m and interval == "1d" and period in _PERIOD_MONTHS else None


def handles(symbol: str, period: str = "1y", interval: str = "1d") -> bool:
    """이 요청을 다리가 **먼저** 받는가 — 요청 모양이 맞고 DB 파일이 있다 (DF-17).

    다리 위에 캐시를 두는 쪽(일봉 · 지표 라우트, `sync_scheduler` 의 캐시 데우기)이 캐시를 건너뛸지 정할 때 쓴다.
    그 종목 행이 있는지는 보지 않는다(파일을 열어야 안다). 행이 없으면(ETF 등) `get_candles` 가 옛 경로로
    넘어가고, 옛 경로는 같은 키로 스스로 캐시하므로 외부 호출은 늘지 않는다.
    """
    return _match(symbol, period, interval) is not None and db_path() is not None


def _months_before(d: date, months: int) -> date:
    """`d` 에서 `months` 달 전. 그 달에 같은 날이 없으면 말일로(3-31 의 한 달 전 = 2-28)."""
    y, m = divmod(d.year * 12 + (d.month - 1) - months, 12)
    m += 1
    day = d.day
    while True:
        try:
            return date(y, m, day)
        except ValueError:
            day -= 1


def _epoch(bas_dt: str) -> int:
    return int(datetime(int(bas_dt[:4]), int(bas_dt[4:6]), int(bas_dt[6:8]), tzinfo=timezone.utc).timestamp())


def _candle(row: tuple) -> dict | None:
    bas_dt, close, o, h, l, factor, mkp, trqu = row
    if close is None or close <= 0:
        return None
    if not mkp or o is None or h is None or l is None:
        # 거래가 없던 날 — 시가 · 고가 · 저가가 0 으로 온다. 평평한 봉으로.
        o = h = l = close
    volume = round(trqu / factor) if trqu and factor else 0
    return {
        "time": _epoch(bas_dt),
        "open": round(o, 2),
        "high": round(h, 2),
        "low": round(l, 2),
        "close": round(close, 2),
        "volume": volume,
    }


def read_daily_candles(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    *,
    today: date | None = None,
    path: Path | None = None,
) -> dict | None:
    """수집 DB 에서 일봉을 읽는다. 쓸 수 없으면 None(예외 없음) — 머리말 참고."""
    global _warned_missing
    m = _match(symbol, period, interval)
    if m is None:
        return None

    path = path or db_path()
    if path is None:
        if not _warned_missing:
            logger.warning("수집 DB 를 찾지 못했다(%s 또는 data/collector) — 일봉은 옛 경로로 간다", ENV_DB_PATH)
            _warned_missing = True
        return None

    today = today or datetime.now(KST).date()
    months = _PERIOD_MONTHS[period]
    start = "00000000" if months is None else _months_before(today, months).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    try:
        # 읽기 전용으로 연다 — 앱이 수집 DB 에 쓰는 일은 없어야 한다.
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            rows = conn.execute(_QUERY, (m.group(1), start, end)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("수집 DB 를 읽지 못했다(%s) — %s 일봉은 옛 경로로 간다", e, symbol)
        return None

    candles = [c for c in map(_candle, rows) if c is not None]
    if not candles:
        return None
    # 마지막 행이 버려졌을 수 있으니(종가 없음) as_of 는 남은 마지막 봉에서 읽는다.
    last = datetime.fromtimestamp(candles[-1]["time"], tz=timezone.utc).strftime("%Y-%m-%d")
    return {
        "symbol": symbol,
        "interval": interval,
        "period": period,
        "candles": candles,
        "source": "collector",
        "as_of": last,
    }


async def get_daily_candles(symbol: str, period: str = "1y", interval: str = "1d") -> dict | None:
    """`read_daily_candles` 의 비동기 판 — 파일 읽기가 이벤트 루프를 막지 않게 스레드에서 돈다."""
    return await asyncio.to_thread(read_daily_candles, symbol, period, interval)
