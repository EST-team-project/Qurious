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
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
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
        snap_date = datetime.now(KST).date()

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
        snapshot_at=datetime.now(KST),
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
    with_dates: bool = False,
):
    """
    QFRS 지표 계산용 일별 수익률 & 총자산 시계열.

    Parameters
    ----------
    with_dates : bool
        True 면 (날짜[], returns, equity) 3-튜플 반환.
        날짜는 **returns 와 1:1 정렬** (첫 스냅샷은 daily_return=0 이라 제외).
        기본 False — 기존 호출자(returns, equity) 2-튜플 그대로.

    Returns
    -------
    with_dates=False : (returns, equity)
    with_dates=True  : (dates, returns, equity)
        - dates   : list[str] ISO 날짜 (returns 와 같은 길이)
        - returns : daily_return 배열 (첫 값 제외)
        - equity  : total_equity 배열 (전체)
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
        if with_dates:
            return [], np.array([]), np.array([])
        return np.array([]), np.array([])

    dates_all = [r.snap_date.isoformat() for r in rows]
    equity = np.array([r.total_equity for r in rows], dtype=float)
    returns = np.array([r.daily_return for r in rows], dtype=float)

    # 첫 스냅샷은 daily_return=0 이므로 지표 계산 시 제외 — 날짜도 같이 제외
    returns_dates = dates_all[1:] if len(dates_all) > 1 else []
    if len(returns) > 0:
        returns = returns[1:]

    if limit is not None:
        returns = returns[-limit:]
        returns_dates = returns_dates[-limit:] if returns_dates else []
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