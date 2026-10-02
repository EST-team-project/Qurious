# app/services/paper_snapshot_service.py
"""
모의계좌 일별 스냅샷 기록 & QFRS 지표용 수익률 시계열 조회.

- record_daily_snapshot: 오늘 자산을 스냅샷으로 저장 (idempotent upsert)
- get_daily_returns: QFRS 지표 계산용 일별 수익률 numpy 배열
- backfill_from_now: 과거 데이터가 없으면 오늘부터 시작
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper_snapshot import PaperAccountSnapshot
from app.services.paper_trading import account_snapshot

logger = logging.getLogger(__name__)


async def record_daily_snapshot(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    snap_date: Optional[date] = None,
) -> PaperAccountSnapshot:
    """
    오늘(또는 지정일)의 모의계좌 총자산을 스냅샷으로 저장.

    - 같은 날짜에 이미 스냅샷이 있으면 덮어씀 (upsert)
    - daily_return은 **직전 스냅샷의 total_equity 대비** 계산
    - 첫 스냅샷은 daily_return = 0.0
    """
    if snap_date is None:
        snap_date = datetime.now(timezone.utc).date()

    # 1. 현재 계좌 상태 (기존 함수 재사용)
    snap = await account_snapshot(db, user_id)
    cash = float(snap["cash"])
    stock_eval = float(snap["stockEval"])
    crypto_eval = float(snap["cryptoEval"])
    alt_eval = float(snap["alternativeEval"])
    position_value = stock_eval + crypto_eval + alt_eval
    total_equity = float(snap["totalAsset"])
    position_count = sum(snap["counts"].values())

    # 2. 직전 스냅샷 조회 (오늘 이전)
    prev_row = (await db.execute(
        select(PaperAccountSnapshot)
        .where(
            PaperAccountSnapshot.user_id == user_id,
            PaperAccountSnapshot.snap_date < snap_date,
        )
        .order_by(PaperAccountSnapshot.snap_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    if prev_row and prev_row.total_equity > 0:
        daily_return = (total_equity / prev_row.total_equity) - 1.0
    else:
        daily_return = 0.0

    # 3. UPSERT (동일 user_id + snap_date면 덮어쓰기)
    # 자산군별 평가액
    stock_eval = float(snap["stockEval"])
    crypto_eval = float(snap["cryptoEval"])
    alt_eval = float(snap["alternativeEval"])

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
        snapshot_at=datetime.now(timezone.utc),
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
            "snapshot_at": stmt.excluded.snapshot_at,
        },
    )
    await db.execute(stmt)
    await db.commit()

    logger.info(
        "snapshot recorded: user=%s date=%s equity=%.2f return=%.4f",
        user_id, snap_date, total_equity, daily_return,
    )

    # 4. 저장된 행 반환
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
) -> tuple[np.ndarray, np.ndarray]:
    """
    QFRS 지표 계산용 일별 수익률 & 총자산 시계열.

    Returns
    -------
    (returns, equity) : tuple[np.ndarray, np.ndarray]
        - returns: daily_return 배열 (첫 값 제외한 순수익률)
        - equity : total_equity 배열 (지표 계산과 별개로 차트용)
    """
    stmt = (
        select(PaperAccountSnapshot)
        .where(PaperAccountSnapshot.user_id == user_id)
        .order_by(PaperAccountSnapshot.snap_date.asc())
    )
    if since is not None:
        stmt = stmt.where(PaperAccountSnapshot.snap_date >= since)

    rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        return np.array([]), np.array([])

    equity = np.array([r.total_equity for r in rows], dtype=float)
    returns = np.array([r.daily_return for r in rows], dtype=float)

    # 첫 스냅샷은 daily_return=0이므로 지표 계산 시엔 제외하는 게 정석
    if len(returns) > 0:
        returns = returns[1:]  # 첫 값(0) 제거
        # equity는 그대로 유지 (차트용)

    if limit is not None:
        returns = returns[-limit:]
        equity = equity[-limit:]

    return returns, equity


async def snapshot_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """저장된 스냅샷 개수 (디버깅/진단용)."""
    from sqlalchemy import func
    cnt = (await db.execute(
        select(func.count()).select_from(PaperAccountSnapshot)
        .where(PaperAccountSnapshot.user_id == user_id)
    )).scalar_one()
    return int(cnt or 0)