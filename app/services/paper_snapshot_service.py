# app/services/paper_snapshot_service.py
"""
모의계좌 일별 스냅샷 기록 & QFRS 지표용 수익률 시계열 조회.

- record_daily_snapshot: 오늘 자산을 스냅샷으로 저장 (idempotent upsert)
- get_daily_returns: QFRS 지표 계산용 일별 수익률 numpy 배열
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper import PaperAccount
from app.models.paper_snapshot import PaperAccountSnapshot     # ← import만!
from app.services.paper_trading import account_snapshot

KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)


async def _get_current_epoch(db: AsyncSession, user_id: uuid.UUID) -> int:
    """현재 모의계좌 회차 번호 (없으면 1)."""
    val = (await db.execute(
        select(PaperAccount.epoch).where(PaperAccount.user_id == user_id)
    )).scalar_one_or_none()
    return int(val or 1)


async def record_daily_snapshot(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    snap_date: Optional[date] = None,
) -> PaperAccountSnapshot:
    """
    오늘(또는 지정일)의 모의계좌 총자산을 스냅샷으로 저장.

    - 같은 날짜에 이미 스냅샷이 있으면 덮어씀
    - 불완전한 시세 스냅샷은 daily_return = 0.0
    - 직전 스냅샷이 불완전하거나 출처가 다르면 수익률 연결을 초기화
    - 연속된 완전한 일일 스냅샷만 수익률 계산에 사용
    """
    if snap_date is None:
        snap_date = datetime.now(KST).date()

    snap = await account_snapshot(db, user_id)

    cash = float(snap["cash"])
    stock_eval = float(snap["stockEval"])
    crypto_eval = float(snap["cryptoEval"])
    alt_eval = float(snap["alternativeEval"])
    position_value = stock_eval + crypto_eval + alt_eval
    total_equity = float(snap["totalAsset"])
    position_count = sum(snap["counts"].values())

    completeness = (
        "complete" if snap["price_complete"] else "incomplete"
    )
    origin = "daily"

    current_epoch = await _get_current_epoch(db, user_id)

    prev_row = (await db.execute(
        select(PaperAccountSnapshot)
        .where(
            PaperAccountSnapshot.user_id == user_id,
            PaperAccountSnapshot.snap_date < snap_date,
        )
        .order_by(PaperAccountSnapshot.snap_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    if (
        completeness == "complete"
        and prev_row is not None
        and prev_row.completeness == "complete"
        and prev_row.origin == "daily"
        and prev_row.total_equity > 0
        and prev_row.epoch == current_epoch
    ):
        daily_return = (total_equity / prev_row.total_equity) - 1.0
    else:
        daily_return = 0.0

    stmt = pg_insert(PaperAccountSnapshot).values(
        id=uuid.uuid4(),
        user_id=user_id,
        snap_date=snap_date,
        cash=cash,
        position_value=position_value,
        total_equity=total_equity,
        daily_return=daily_return,
        position_count=position_count,
        stock_value=stock_eval,
        crypto_value=crypto_eval,
        alt_value=alt_eval,
        epoch=current_epoch,
        snapshot_at=datetime.now(KST),
        completeness=completeness,
        origin=origin,
    )

    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "snap_date"],
        set_={
            "cash": stmt.excluded.cash,
            "position_value": stmt.excluded.position_value,
            "total_equity": stmt.excluded.total_equity,
            "daily_return": stmt.excluded.daily_return,
            "position_count": stmt.excluded.position_count,
            "stock_value": stmt.excluded.stock_value,
            "crypto_value": stmt.excluded.crypto_value,
            "alt_value": stmt.excluded.alt_value,
            "epoch": stmt.excluded.epoch,
            "snapshot_at": stmt.excluded.snapshot_at,
            "completeness": stmt.excluded.completeness,
            "origin": stmt.excluded.origin,
        },
    )

    await db.execute(stmt)
    await db.commit()

    logger.info(
        "snapshot recorded: user=%s date=%s epoch=%d equity=%.2f "
        "return=%.4f completeness=%s origin=%s",
        user_id,
        snap_date,
        current_epoch,
        total_equity,
        daily_return,
        completeness,
        origin,
    )

    row = (await db.execute(
        select(PaperAccountSnapshot).where(
            PaperAccountSnapshot.user_id == user_id,
            PaperAccountSnapshot.snap_date == snap_date,
        )
    )).scalar_one()

    return row


async def get_daily_returns(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    since: Optional[date] = None,
    limit: Optional[int] = None,
    with_dates: bool = False,
):
    """완전한 일일 스냅샷만 사용하는 QFRS 수익률 및 총자산 시계열."""
    stmt = (
        select(PaperAccountSnapshot)
        .where(PaperAccountSnapshot.user_id == user_id)
        .order_by(PaperAccountSnapshot.snap_date.asc())
    )

    if since is not None:
        stmt = stmt.where(PaperAccountSnapshot.snap_date >= since)

    rows = (await db.execute(stmt)).scalars().all()

    # 실제 일일 스냅샷 중 가격 완전성이 확인된 데이터만 사용
    rows = [
        row for row in rows
        if row.completeness == "complete"
        and row.origin == "daily"
    ]

    if not rows:
        if with_dates:
            return [], np.array([]), np.array([])
        return np.array([]), np.array([])

    dates_all = [row.snap_date.isoformat() for row in rows]
    equity = np.array([row.total_equity for row in rows], dtype=float)
    returns = np.array([row.daily_return for row in rows], dtype=float)

    # 첫 번째 정상 스냅샷은 비교 기준점이므로 수익률에서 제외
    returns_dates = dates_all[1:]
    returns = returns[1:]

    if limit is not None:
        returns = returns[-limit:]
        returns_dates = returns_dates[-limit:]
        equity = equity[-limit:]

    if with_dates:
        return returns_dates, returns, equity

    return returns, equity


async def snapshot_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """저장된 스냅샷 개수 (디버깅/진단용)."""
    from sqlalchemy import func
    cnt = (await db.execute(
        select(func.count()).select_from(PaperAccountSnapshot)
        .where(PaperAccountSnapshot.user_id == user_id)
    )).scalar_one()
    return int(cnt or 0)