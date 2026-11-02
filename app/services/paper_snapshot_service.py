# app/services/paper_snapshot_service.py
"""
모의계좌 일별 스냅샷 기록 & QFRS 지표용 수익률 시계열 조회.

- record_daily_snapshot: 오늘 자산을 스냅샷으로 저장 (idempotent upsert)
- get_daily_returns: QFRS 지표 계산용 일별 수익률 numpy 배열
"""

from __future__ import annotations

import inspect
import logging
import uuid
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper import PaperAccount
from app.models.paper_snapshot import PaperAccountSnapshot
from app.models.paper_snapshot_price_audit import PaperSnapshotPriceAudit
from app.services.paper_trading import account_snapshot
from app.services.snapshot_pricing import daily_complete, consecutive

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
    origin: str = "daily",
) -> PaperAccountSnapshot:
    """
    오늘(또는 지정일)의 모의계좌 총자산을 스냅샷으로 저장.

    - 같은 날짜에 이미 스냅샷이 있으면 덮어씀
    - 불완전한 시세 스냅샷은 daily_return = 0.0, return_valid = false (성과 계산 제외)
    - 직전 스냅샷이 불완전하거나 출처가 다르면 수익률 연결을 초기화
    - 연속된 완전한 일일 스냅샷만 수익률 계산에 사용
    """
    if snap_date is None:
        snap_date = datetime.now(KST).date()

    # 기존 2인자 mock 및 호출부 호환성을 유지하면서 감사 데이터만 선택적으로 요청한다.
    params = inspect.signature(account_snapshot).parameters
    supports_audits = (
        "include_price_audits" in params
        or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    )
    if supports_audits:
        snap = await account_snapshot(db, user_id, include_price_audits=True)
    else:
        snap = await account_snapshot(db, user_id)

    price_audits = snap.get("_price_audits", [])
    if origin not in ("daily", "manual"):
        raise ValueError("잘못된 스냅샷 출처입니다.")
    snap = await account_snapshot(db, user_id, valuation_date=snap_date)

    cash = float(snap["cash"])
    stock_eval = float(snap["stockEval"])
    crypto_eval = float(snap["cryptoEval"])
    alt_eval = float(snap["alternativeEval"])
    position_value = stock_eval + crypto_eval + alt_eval
    total_equity = float(snap["totalAsset"])
    position_count = sum(snap["counts"].values())

    captured_at = datetime.now(KST)
    metadata = []
    for item in snap.get("price_metadata", []):
        complete = daily_complete(item, snap_date, at=captured_at)
        fallback = list(item.get("fallback", []))
        if not complete and not fallback:
            fallback.append("daily_close_or_time_unverified")
        # 평가 결과와 근거만 보존한다. 시세 자체를 저장하는 표로 확장하지 않는다.
        provenance = {key: value for key, value in item.items() if key != "price"}
        metadata.append({**provenance, "complete": complete, "fallback": fallback})
    verified = (snap["price_complete"] and len(metadata) == position_count
                and all(daily_complete(p, snap_date, at=captured_at) for p in metadata))
    completeness = "complete" if verified else "incomplete"

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

    return_valid = (
        origin == "daily"
        and completeness == "complete"
        and prev_row is not None
        and prev_row.completeness == "complete"
        and prev_row.origin == "daily"
        and prev_row.total_equity > 0
        and prev_row.epoch == current_epoch
        and valid_daily_row(prev_row, current_epoch)
        and consecutive(prev_row.snap_date, snap_date)
    )
    if return_valid:
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
        snapshot_at=captured_at,
        completeness=completeness,
        origin=origin,
        price_metadata=metadata,
        return_valid=return_valid,
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
            "price_metadata": stmt.excluded.price_metadata,
            "return_valid": stmt.excluded.return_valid,
        },
        where=(PaperAccountSnapshot.origin != "daily") if origin == "manual" else None,
    )

    stmt = stmt.returning(PaperAccountSnapshot.id)
    snapshot_id = (await db.execute(stmt)).scalar_one()

    # 같은 날짜 스냅샷을 재기록하면 해당 스냅샷의 감사 행만 교체한다.
    await db.execute(
        delete(PaperSnapshotPriceAudit).where(
            PaperSnapshotPriceAudit.snapshot_id == snapshot_id
        )
    )
    if price_audits:
        audit_rows = [
            {**item, "snapshot_id": snapshot_id}
            for item in price_audits
        ]
        await db.execute(
            PaperSnapshotPriceAudit.__table__.insert(),
            audit_rows,
        )

    # 스냅샷 upsert와 감사 행 교체를 하나의 트랜잭션으로 확정한다.
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
        ).execution_options(populate_existing=True)
    )).scalar_one()

    return row


def valid_daily_row(row, epoch):
    return (row.completeness == "complete" and row.origin == "daily" and row.epoch == epoch
            and len(row.price_metadata or []) == row.position_count
            and all(daily_complete(p, row.snap_date, at=row.snapshot_at) for p in (row.price_metadata or [])))


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

    rows = (await db.execute(stmt)).scalars().all()
    epoch = await _get_current_epoch(db, user_id)
    # 누락·불완전·회차 경계를 0% 수익으로 만들지 않는다. 재수집한 과거 행의
    # 다음 날도 저장된 옛 비율 대신 실제 이웃 두 행으로 다시 계산한다.
    dates, returns, equity = [], [], []
    previous = None
    for row in rows:
        if valid_daily_row(row, epoch) and (since is None or row.snap_date >= since):
            equity.append(row.total_equity)
            if (previous is not None and valid_daily_row(previous, epoch)
                    and previous.total_equity > 0 and consecutive(previous.snap_date, row.snap_date)):
                dates.append(row.snap_date.isoformat())
                returns.append(row.total_equity / previous.total_equity - 1)
        previous = row
    if limit is not None:
        if limit < 1:
            raise ValueError("조회 개수는 1 이상이어야 합니다.")
        dates, returns, equity = dates[-limit:], returns[-limit:], equity[-limit:]
    result = (np.array(returns, dtype=float), np.array(equity, dtype=float))
    return (dates, *result) if with_dates else result


async def snapshot_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """저장된 스냅샷 개수 (디버깅/진단용)."""
    from sqlalchemy import func
    cnt = (await db.execute(
        select(func.count()).select_from(PaperAccountSnapshot)
        .where(PaperAccountSnapshot.user_id == user_id)
    )).scalar_one()
    return int(cnt or 0)
