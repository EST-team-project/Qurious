# app/services/performance_service.py
"""모의계좌 성과 지표(QFRS) 통합 서비스."""

from __future__ import annotations

import math
import uuid
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.evaluation_risk import calculate_all_metrics
from app.services.paper_snapshot_service import (
    get_daily_returns,
    record_daily_snapshot,
    snapshot_count,
)

from sqlalchemy import select
from app.models.paper_snapshot import PaperAccountSnapshot


def _clean(v):
    """NaN/inf → None (JSON 직렬화 가능하게)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _nan_metrics() -> dict[str, float | None]:
    """데이터 부족 시 반환할 빈 지표."""
    return {
        "mdd": None,
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "sterling_ratio": None,
        "calmar_ratio": None,
        "dsr": None,
    }


async def get_robo_metrics(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    risk_free_rate: float = 0.02,
    target_return: float = 0.0,
    periods_per_year: int = 252,
    n_trials: int = 50,
    sterling_top_k: int = 3,
) -> dict[str, Any]:
    """
    현재 모의계좌의 QFRS 지표 일괄 반환.

    스냅샷이 부족하면 (2개 미만) 자동으로 오늘 스냅샷을 기록하고
    부족 상태를 알려준다.
    """
    returns, equity = await get_daily_returns(db, user_id)

    # 날짜 배열 (X축 라벨용)
    _snap_rows = (await db.execute(
        select(PaperAccountSnapshot.snap_date)
        .where(PaperAccountSnapshot.user_id == user_id)
        .order_by(PaperAccountSnapshot.snap_date.asc())
    )).scalars().all()
    snap_dates = [d.isoformat() for d in _snap_rows]  # ["2026-09-17", ...]

    # 스냅샷이 2개 미만 → 지표 계산 불가
    if len(returns) < 2:
        await record_daily_snapshot(db, user_id)
        return {
            "status": "insufficient_data",
            "message": "스냅샷이 2개 미만입니다. 매일 조회 시 자동으로 쌓입니다.",
            "snapshot_count": len(equity),
            "metrics": _nan_metrics(),
            "equity_curve": [_clean(v) for v in equity.tolist()],
            "snap_dates": snap_dates,
        }

    # QFRS 지표 계산
    metrics = calculate_all_metrics(
        returns=returns,
        risk_free_rate=risk_free_rate,
        target_return=target_return,
        periods_per_year=periods_per_year,
        n_trials=n_trials,
        sterling_top_k=sterling_top_k,
    )

    # 누적 수익률 (첫 스냅샷 대비)
    total_return = float(equity[-1] / equity[0] - 1) if len(equity) > 0 else 0.0

    # Drawdown curve (차트용)
    if len(equity) > 0:
        running_max = np.maximum.accumulate(equity)
        drawdown_curve = (equity / running_max - 1).tolist()
    else:
        drawdown_curve = []

    return {
        "status": "ok",
        "snapshot_count": len(equity),
        "total_return": _clean(total_return),
        "metrics": {
            "mdd": _clean(metrics["MDD"]),
            "sharpe_ratio": _clean(metrics["Sharpe Ratio"]),
            "sortino_ratio": _clean(metrics["Sortino Ratio"]),
            "sterling_ratio": _clean(metrics["Sterling Ratio"]),
            "calmar_ratio": _clean(metrics["Calmar Ratio"]),
            "dsr": _clean(metrics["Deflated Sharpe Ratio"]),
        },
        "equity_curve": [_clean(v) for v in equity.tolist()],
        "drawdown_curve": [_clean(v) for v in drawdown_curve],
        "snap_dates": snap_dates,
        "params": {
            "risk_free_rate": risk_free_rate,
            "n_trials": n_trials,
            "periods_per_year": periods_per_year,
        },
    }