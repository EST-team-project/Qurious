"""모의계좌 일별 스냅샷 자동 기록 — Celery Beat.

배경 (Issue #88 지적 #6):
    스냅샷이 계좌 조회(GET /api/paper/account) 시에만 기록되는 구조라,
    사용자가 그날 계좌를 열지 않으면 그날 줄이 없다.
    그리고 다음에 열었을 때 daily_return 이 "직전 줄과의 비율"이라
    이틀·사흘치가 하루 수익률 한 칸에 들어간다 → QFRS 지표(샤프·변동성) 왜곡.

해결:
    매일 장 마감 뒤(15:40 KST) 모든 사용자의 줄을 자동 기록.
    단, 거래일(주말·공휴일 제외)에만 기록 — 이슈 #88 지적 #9.
    거래일이 아닌 날 daily_return=0 줄이 쌓이면
    「1개월」=21거래일, 「1년」=252거래일 창이 실제로는 3주·8개월이 된다.
    KOSPI 지수와 순서로 짝지을 때도 다른 날끼리 짝이 되었다(지적 #10).

거래일 판정:
    app/services/market_calendar.trading_days(start, end) 를 쓴다.
    달력이 없으면(CalendarUnavailable) fail-open — 주중이면 기록한다.
    스냅샷 누락이 주말 중복보다 위험하다.

참고:
    celery_app.conf.timezone = "Asia/Seoul" 이라 crontab 은 KST 로 해석된다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.celery_app import celery_app
from app.database.postgres import get_session_factory
from app.models.user import User
from app.services import market_calendar
from app.services.paper_snapshot_service import record_daily_snapshot

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


def _is_trading_day(today) -> tuple[bool, str]:
    """오늘이 거래일인지 판정.

    Returns:
        (is_trading, reason) — reason 은 로그·응답에 실을 짧은 표시.

    달력을 못 읽으면 fail-open (주중이면 True). 스냅샷 누락이 주말 중복보다 위험.
    """
    try:
        resp = market_calendar.trading_days(today, today)
        rows = resp.get("days") or []
        if not rows:
            raise market_calendar.CalendarUnavailable("빈 응답")
        row = rows[0]
        return bool(row.get("is_trading_day")), f"calendar:{row.get('date')}"
    except (market_calendar.CalendarUnavailable, Exception) as e:
        # 달력 없음 · 요청 범위 초과 · sqlite 오류 — 주중 폴백
        fallback = today.weekday() < 5
        logger.warning("거래일 달력 확인 실패(%s) — 주중 폴백=%s", e, fallback)
        return fallback, f"fallback:weekday={today.weekday()}"


async def _record_all_async() -> dict:
    from app.database import postgres as pg

    # 워커 프로세스는 FastAPI startup 을 거치지 않아 _session_factory 가 None 이다.
    # 그리고 asyncio.run() 이 매번 새 이벤트 루프를 만드는데 asyncpg 연결은
    # 이벤트 루프에 묶이므로, 매 실행 안에서 만들고 닫는다 (배치라 하루 1회).
    await pg.connect_postgres()
    try:
        today_kst = datetime.now(KST).date()

        # ── 이슈 #88 지적 #9 — 주말·공휴일 스킵 ──
        is_trading, reason = _is_trading_day(today_kst)
        if not is_trading:
            logger.info("휴장일(%s · %s) — 스냅샷 배치 건너뜀", today_kst, reason)
            return {
                "skipped": "non_trading_day",
                "date": today_kst.isoformat(),
                "reason": reason,
            }

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
                    # ── 이슈 #88 지적 #11 — 한 명 실패가 다음 사람을 막지 않도록 ──
                    await db.rollback()
                    logger.warning("스냅샷 실패 user=%s: %s", u.email, e)
            return {
                "total": len(users),
                "ok": ok,
                "fail": fail,
                "date": today_kst.isoformat(),
                "reason": reason,
            }
    finally:
        await pg.close_postgres()


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