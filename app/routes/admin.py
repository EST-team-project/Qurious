from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.models import (
    AuditEvent, BankProduct, BrokerSettings, Chat, CorporateCbStat,
    CrawledDoc, FundProduct, Order, PersonalCbStat, Portfolio,
)

router = APIRouter(prefix="/api/admin")

FINANCIAL_MODELS = [PersonalCbStat, CorporateCbStat, BankProduct, FundProduct]
USER_MODELS = [Chat, Portfolio, Order, BrokerSettings, CrawledDoc, AuditEvent]


def _require_admin(user=Depends(get_current_user)):
    if "admin" not in user.get("roles", []):
        raise HTTPException(403, "관리자 권한이 필요합니다.")
    return user


# (Qurious 2026-10-08 · DF-78) 「DB 초기화」 `POST /api/admin/reset` 을 없앴다 — 신용평가 참조 표 넷만이 아니라
# 모든 사용자의 주문 · 포트폴리오 · 증권사 설정 · 채팅 · 크롤링 문서 · 감사 로그(USER_MODELS)까지 지웠다.
# 개발용 초기화는 일회용 시험 DB(scripts/personal/test.ps1) · alembic 으로 한다(크롤링 세 화면 결정 ② A · 2026-10-07).


@router.get("/stats")
async def db_stats(
    user=Depends(_require_admin),
    db: AsyncSession = Depends(get_pg_session),
):
    stats: dict = {}
    for model in FINANCIAL_MODELS + USER_MODELS:
        count = await db.scalar(select(func.count()).select_from(model))
        stats[f"postgres.{model.__tablename__}"] = count
    return {"stats": stats}


@router.get("/audit-log")
async def audit_log(
    event_type: str = Query("", description="이벤트 유형 부분 일치 필터 (예: order, broker, auto_trade)"),
    user_id:    str = Query("", description="사용자 ID 필터"),
    limit:      int = Query(100, ge=1, le=500),
    user=Depends(_require_admin),
    db: AsyncSession = Depends(get_pg_session),
):
    """감사 로그 조회 (관리자 전용). 최신순, 이벤트 유형/사용자로 필터링."""
    from app.services.audit import _resolve_user_id

    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type.ilike(f"%{event_type}%"))
    if user_id:
        stmt = stmt.where(AuditEvent.user_id == _resolve_user_id(user_id))

    result = await db.execute(stmt)
    events = [{
        "id": str(ev.id),
        "user_id": str(ev.user_id) if ev.user_id else "",
        "client_id": ev.client_id,
        "event_type": ev.event_type,
        "payload": ev.payload,
        "created_at": ev.created_at.isoformat(),
    } for ev in result.scalars().all()]
    return {"events": events, "count": len(events)}
