"""pytest 공통 설정.

이 저장소의 첫 테스트 묶음이다. 여기서 하는 일은 둘뿐이다.

1. 저장소 루트를 ``sys.path`` 에 얹어 ``app`` · ``collector`` 를 임포트할 수 있게 한다.
   (루트에서 ``pytest`` 를 돌리면 대개 되지만, CI 의 작업 디렉터리에 기대지 않는다.)
2. **실거래 승인 환경변수를 테스트마다 지운다.** 개발자 셸에
   ``QURIOUS_ALLOW_LIVE_TRADING=1`` 이 남아 있으면 차단 테스트가 조용히 통과해 버린다.
   그런 통과는 통과가 아니다.
3. (강사님 원본 2026-09-29) 합성 OHLCV 캔들(랜덤워크) — 외부 시세 · DB 없이 순수 계산 로직만 재는
   시험이 ``from tests.conftest import make_candles`` 로 쓴다. ``DATABASE_URL`` · ``REDIS_URL`` 은
   비어 있을 때만 가짜 주소로 채운다(설정 import 용 · 접속하지 않는다). 실제 DB 시험은
   ``QURIOUS_TEST_DATABASE_URL`` 을 따로 본다.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.brokers.factory import LIVE_TRADING_ENV  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_live_trading_env(monkeypatch):
    """모든 테스트를 '실거래 미승인' 상태에서 시작한다."""
    monkeypatch.delenv(LIVE_TRADING_ENV, raising=False)


@pytest.fixture
def allow_live_trading(monkeypatch):
    """실거래를 승인한 상태를 만든다. 이 픽스처를 **요청한** 테스트에서만 열린다."""
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")
    return LIVE_TRADING_ENV


def make_candles(n: int = 400, seed: int = 42, start: float = 10_000.0) -> list[dict]:
    """합성 일봉(랜덤워크 · 강사님 원본). 같은 seed 면 같은 캔들이 나온다."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, 0.015, n)
    close = start * np.cumprod(1 + rets)
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = np.concatenate([[start], close[:-1]])
    vol = rng.integers(50_000, 500_000, n)
    t0 = 1_600_000_000
    return [{"time": t0 + i * 86_400, "open": float(open_[i]), "high": float(high[i]), "low": float(low[i]),
             "close": float(close[i]), "volume": int(vol[i])} for i in range(n)]


@pytest.fixture
def candles() -> list[dict]:
    return make_candles()


@pytest.fixture(scope="module")
def rebalance_db_schema():
    """DF-73: 리밸런싱 각 시험 묶음이 일회용 DB의 표를 준비하고 정리한다.

    계정 시험이 표를 지운 뒤에도, 정책·일별 점검·예약 정산을 각각 단독 실행해도
    동작해야 한다. 끝에 표를 남기면 일부 표만 만드는 장부 시험의 FK와 충돌한다.
    """
    import asyncio

    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    import app.models  # noqa: F401 — 모든 모델을 metadata에 등록
    from app.models.base import Base

    db_url = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
    if not db_url:
        yield
        return
    url = make_url(db_url)
    assert "test" in db_url and url.database != "fin_ai" and url.port != 15432, "일회용 시험 DB만 사용"

    async def run(operation):
        # setup/teardown은 별도 asyncio.run이므로 루프 사이에 연결을 재사용하지 않는다.
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(operation)
        finally:
            await engine.dispose()

    asyncio.run(run(Base.metadata.create_all))
    try:
        yield
    finally:
        asyncio.run(run(Base.metadata.drop_all))


@pytest.fixture
def rebalance_calendar(tmp_path, monkeypatch):
    """실제 수집기 스키마·공휴일 픽스처 → 달력 읽기 서비스까지 검증한다."""
    import json
    import sqlite3
    from datetime import date
    from collector import db, market_calendar
    source = Path(__file__).parent / "fixtures" / "kasi_holidays_2020_2027.json"
    years = json.loads(source.read_text(encoding="utf-8"))["years"]
    holidays = {date.fromisoformat(row["locdate"]): row["date_name"]
                for rows in years.values() for row in rows if row["is_holiday"] == "Y"}
    path = tmp_path / "calendar.sqlite3"
    conn = sqlite3.connect(path, isolation_level=None)
    conn.executescript(db.SCHEMA)
    days, _ = market_calendar.build_days(holidays, date(2027, 12, 31), [])
    market_calendar.write_calendar(conn, days)
    conn.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(path))
    return path
