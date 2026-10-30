"""시장 데이터 주기 동기화 Celery Beat 태스크.

기존 sync_scheduler.py 의 asyncio 기반 루프를 Celery Beat으로 보완한다.
- FastAPI 이벤트 루프와 완전히 분리되어 독립적으로 실행
- 워커 재시작·장애 시에도 Beat 스케줄에 따라 자동 재실행
- celery_app.py beat_schedule 에서 주기 설정 (1h / 24h)
"""
import asyncio
import logging

from app.celery_app import celery_app
from app.config import settings

logger = logging.getLogger(__name__)


@celery_app.task(name="sync.market_data", time_limit=300)
def sync_market_data() -> dict:
    """시장 지수·매크로·섹터 ETF·미국 주식 데이터를 캐싱한다 (1시간 주기)."""

    async def _async() -> dict:
        from app.database.postgres import connect_postgres, close_postgres
        from app.lib.redis_cache import connect_redis, close_redis
        from app.services.sync_scheduler import sync_all

        await connect_redis()
        await connect_postgres()
        try:
            # force=True: 오프라인 체크 없이 항상 실행
            return await sync_all(force=True)
        finally:
            await close_redis()
            await close_postgres()

    result = asyncio.run(_async())
    logger.info("[beat] sync_market_data 완료: %s", result)
    return result


@celery_app.task(name="sync.stock_candles", time_limit=600)
def sync_stock_candles() -> dict:
    """주요 종목 캔들 데이터와 퀀트 지표를 일 1회 캐싱한다."""

    async def _async() -> dict:
        from app.database.postgres import connect_postgres, close_postgres
        from app.lib.redis_cache import connect_redis, close_redis
        from app.services.sync_scheduler import _sync_stock_candles

        await connect_redis()
        await connect_postgres()
        try:
            await _sync_stock_candles()
            return {"ok": True}
        finally:
            await close_redis()
            await close_postgres()

    result = asyncio.run(_async())
    logger.info("[beat] sync_stock_candles 완료")
    return result


@celery_app.task(name="sync.prune_external_cache", time_limit=120)
def prune_external_cache() -> dict:
    """나이 지난 외부 시세 캐시(`data_cache` 의 허용 목록 키)를 하루 한 번 지운다 — 상태 · 결과 키는 건드리지 않는다(할 일 ①-29)."""

    async def _async() -> dict:
        from app.database.postgres import connect_postgres, close_postgres
        from app.services.data_cache import prune_external

        await connect_postgres()
        try:
            return await prune_external()
        finally:
            await close_postgres()

    result = asyncio.run(_async())
    logger.info("[beat] prune_external_cache 완료 %s", result)
    return result


@celery_app.task(name="rebalance.check_triggers", time_limit=600)
def rebalance_check_triggers() -> dict:
    """갱신 완료를 5분마다 확인하고 준비된 거래일에 플랜별로 한 번 판정한다."""

    async def _async() -> dict:
        from app.database.postgres import connect_postgres, close_postgres, get_session_factory
        from app.lib.redis_cache import connect_redis, close_redis
        from app.services.rebalance import check_all_due

        await connect_redis()
        await connect_postgres()
        try:
            return await check_all_due(get_session_factory())
        finally:
            await close_redis()
            await close_postgres()

    result = asyncio.run(_async())
    logger.info("[beat] rebalance_check_triggers 완료: %s", result)
    return result


@celery_app.task(name="quant.reconcile", time_limit=120)
def quant_reconcile() -> dict:
    """로그(가상 장부·live_orders·사이클) vs 실거래(KIS 잔고) 정합성 점검 (Celery Beat, RECONCILE_INTERVAL_SEC)."""

    async def _async() -> dict:
        from app.database.postgres import connect_postgres, close_postgres, get_session_factory
        from app.lib.redis_cache import connect_redis, close_redis
        from app.services.reconciliation import run_reconciliation

        await connect_redis()
        await connect_postgres()
        try:
            async with get_session_factory()() as db:
                return await run_reconciliation(db)
        finally:
            await close_redis()
            await close_postgres()

    result = asyncio.run(_async())
    logger.info("[beat] quant_reconcile 완료: ok=%s issues=%d", result.get("ok"), len(result.get("issues") or []))
    return result


@celery_app.task(name="beat.heartbeat", time_limit=20, ignore_result=True)
def beat_heartbeat() -> str:
    """beat→worker 경로 생존 신호 (app/tasks/beat_health.py). Docker healthcheck 가 이 키의 나이를 본다."""
    from app.tasks.beat_health import write_heartbeat
    return write_heartbeat()


@celery_app.task(name="quant.auto_trade_cycle", time_limit=max(60, int(settings.QUANT_CYCLE_SEC) - 15))
def quant_auto_trade_cycle() -> dict:
    """자동매매 활성 사용자 전원의 사이클 (Celery Beat, QUANT_CYCLE_SEC 기본 3분). time_limit 은 주기 안에 끝나도록 주기-15초."""

    async def _async() -> dict:
        from app.database.postgres import connect_postgres, close_postgres
        from app.lib.redis_cache import connect_redis, close_redis
        from app.services.auto_trade import run_cycle_for_enabled_users

        await connect_redis()
        await connect_postgres()
        try:
            return await run_cycle_for_enabled_users()
        finally:
            await close_redis()
            await close_postgres()

    result = asyncio.run(_async())
    logger.info("[beat] quant_auto_trade_cycle 완료: %s", result)
    return result


@celery_app.task(name="quant.confirm_fills", time_limit=100)
def quant_confirm_fills() -> dict:
    """게이트웨이 경유 KIS 실주문(live_orders)의 열린 상태를 체결 조회로 갱신한다 (Celery Beat 2분)."""

    async def _async() -> dict:
        from app.database.postgres import connect_postgres, close_postgres
        from app.lib.redis_cache import connect_redis, close_redis
        from app.services.auto_trade import confirm_live_fills
        from app.services.order_retry import retry_cancelled_orders

        await connect_redis()
        await connect_postgres()
        try:
            result = await confirm_live_fills()
            result["retry"] = await retry_cancelled_orders()
            return result
        finally:
            await close_redis()
            await close_postgres()

    result = asyncio.run(_async())
    logger.info("[beat] quant_confirm_fills 완료: %s", result)
    return result


@celery_app.task(name="quant.check_stop_orders", time_limit=60)
def quant_check_stop_orders() -> dict:
    """B5 — pending 스탑 주문 순회 → 시세 도달 시 시장가 발동 (1분마다)."""

    async def _async() -> dict:
        from app.database.postgres import close_postgres, connect_postgres, get_session_factory
        from app.lib.redis_cache import close_redis, connect_redis
        from app.services import paper_trading as pt

        await connect_redis()
        await connect_postgres()
        try:
            factory = get_session_factory()
            async with factory() as db:
                fired = await pt.check_stop_orders(db)
                await db.commit()
                return {"fired": len(fired), "orders": fired}
        finally:
            await close_redis()
            await close_postgres()

    result = asyncio.run(_async())
    logger.info("[beat] quant_check_stop_orders 완료: %s", result)
    return result