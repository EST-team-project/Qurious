"""유니버스와 자동매매 주기의 정합성 — 강사님 10-07 판 시험을 Qurious 값에 맞게 손봤다(2026-10-08).

강사님 판은 3섹터(반도체 · IT · K뷰티) 31종목 · 3분 주기를 값으로 단언한다. Qurious 는 유니버스와 주기를 우리
값으로 둔다(사용자 10-08 · 받을지는 팀 이슈). 그래서 여기서는 값이 아니라 「설정 하나가 예약 · 만료 · 시간 한도 ·
빠른 시작 · 헬스 표시를 모두 정한다」 는 구조를 본다. 값 자체는 tests/test_base_code_merge_guard.py(TC-BM)가 지킨다.
"""
import re

from app.celery_app import celery_app
from app.config import settings
from app.services import auto_trade, kis_quickstart
from app.services.brokers.stock_coin_trade_gateway import normalize_symbol
from app.services.stock import QUANT_SECTORS, QUANT_STOCKS


def test_universe_size_and_sectors_follow_the_list():
    assert 28 <= len(QUANT_STOCKS) <= 35
    assert list(QUANT_SECTORS) == list(dict.fromkeys(s["sector"] for s in QUANT_STOCKS))


def test_universe_symbols_unique_and_krx_format():
    symbols = [s["symbol"] for s in QUANT_STOCKS]
    assert len(symbols) == len(set(symbols))
    for sym in symbols:
        assert re.fullmatch(r"\d{6}\.(KS|KQ)", sym), sym
        assert normalize_symbol(sym) == sym[:6]     # 게이트웨이는 6자리 코드로 보낸다
    assert all(s["name"] for s in QUANT_STOCKS)


def test_universe_contains_core_names():
    names = {s["name"] for s in QUANT_STOCKS}
    assert {"삼성전자", "SK하이닉스", "NAVER", "카카오", "아모레퍼시픽"} <= names


def test_auto_trade_cycle_follows_one_setting():
    """예약 주기 · 만료 · `_INTERVAL_SEC` 가 QUANT_CYCLE_SEC 하나를 따른다(Qurious 기본 600 · 강사님 판 180)."""
    sec = int(settings.QUANT_CYCLE_SEC)
    entry = celery_app.conf.beat_schedule["quant-auto-trade-cycle"]
    assert entry["task"] == "quant.auto_trade_cycle" and entry["schedule"] == float(sec)
    assert entry["options"]["expires"] < sec
    assert auto_trade._INTERVAL_SEC == sec
    assert "quant-auto-trade-5min" not in celery_app.conf.beat_schedule
    assert "quant-auto-trade-10min" not in celery_app.conf.beat_schedule


def test_cycle_task_time_limit_fits_in_period():
    import app.tasks.sync_tasks  # noqa: F401  태스크 등록
    task = celery_app.tasks["quant.auto_trade_cycle"]
    assert task.time_limit is not None and 60 <= task.time_limit < int(settings.QUANT_CYCLE_SEC)


def test_quickstart_reports_interval_from_setting():
    assert kis_quickstart.interval_min() == max(1, int(settings.QUANT_CYCLE_SEC) // 60)
    assert "interval_min()" in __import__("inspect").getsource(kis_quickstart.start)


def test_health_reports_cycle_sec():
    import asyncio
    from app.routes.health import health
    assert asyncio.run(health())["quant"]["cycle_sec"] == int(settings.QUANT_CYCLE_SEC)
