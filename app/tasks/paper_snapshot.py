"""모의계좌 일별 스냅샷 자동 기록 — Celery Beat.

배경 (Issue #88 지적 #6):
    스냅샷이 계좌 조회(GET /api/paper/account) 시에만 기록되는 구조라,
    사용자가 그날 계좌를 열지 않으면 그날 줄이 없다.
    그리고 다음에 열었을 때 daily_return 이 "직전 줄과의 비율"이라
    이틀·사흘치가 하루 수익률 한 칸에 들어간다 → QFRS 지표(샤프·변동성) 왜곡.

해결:
    매일 장 마감 뒤(15:40 KST) 모든 사용자의 줄을 자동 기록.

참고:
    celery_app.conf.timezone = "Asia/Seoul" 이라 crontab 은 KST 로 해석된다.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.celery_app import celery_app
from app.database.postgres import get_session_factory
from app.models.user import User
from app.services.paper_snapshot_service import record_daily_snapshot

logger = logging.getLogger(__name__)


async def _record_all_async() -> dict:
    factory = get_session_factory()
    async with factory() as db:
        users = (await db.execute(select(User))).scalars().all()
        ok, fail = 0, 0
        for u in users:
            try:
                await record_daily_snapshot(db, u.id)
                ok += 1
            except Exception as e:
                fail += 1
                logger.warning("스냅샷 실패 user=%s: %s", u.email, e)
        return {"total": len(users), "ok": ok, "fail": fail}


@celery_app.task(name="paper.record_daily_snapshots")
def record_all_snapshots() -> dict:
    """Celery Beat 진입점 — 모든 사용자의 오늘 스냅샷을 기록."""
    try:
        result = asyncio.run(_record_all_async())
        logger.info("paper 스냅샷 배치 완료: %s", result)
        return result
    except Exception as e:
        logger.exception("paper 스냅샷 배치 실패")
        return {"error": str(e)}