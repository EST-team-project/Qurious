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

# ═══════════════════════════════════════════════════════════
# 코스콤 테스트베드 스타일 — 운용 정보 API
# ═══════════════════════════════════════════════════════════

BENCHMARK_SYMBOL = "^KS11"   # KOSPI
_RF = 0.02
_PPY = 252


def _norm_date(c: dict) -> str | None:
    """캔들 항목에서 ISO 날짜 문자열(YYYY-MM-DD) 뽑기 — 필드명·형식 방어.

    - 문자열: ISO 앞 10자
    - datetime/date: isoformat 앞 10자
    - int/float: 유닉스 타임스탬프(초) → UTC 날짜 (KOSPI 일봉은 UTC 자정 기준)
    """
    # 1) 문자열/날짜 객체 필드 먼저
    for key in ("date", "datetime", "d"):
        v = c.get(key)
        if v is None:
            continue
        if isinstance(v, str):
            return v[:10]
        if hasattr(v, "isoformat"):
            return v.isoformat()[:10]

    # 2) 유닉스 타임스탬프 (time / t / timestamp)
    for key in ("time", "t", "timestamp"):
        v = c.get(key)
        if v is None:
            continue
        try:
            ts = float(v)
        except (TypeError, ValueError):
            continue
        # 밀리초 단위면 초로 환산
        if ts > 10_000_000_000:
            ts /= 1000.0
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()

    return None


async def _get_benchmark_map() -> tuple[list[str], np.ndarray]:
    """KOSPI 종가에서 (날짜[], 수익률[]) — 날짜는 두 번째 날부터 (수익률과 1:1).

    이슈 #88 지적 #10 — 이전에는 끝에서 N개 잘라 순서로 짝지어
    계좌 스냅샷이 띄엄띄엄하면 다른 날 KOSPI 수익률과 짝이 됐다.
    이제 날짜를 함께 돌려주고 호출부에서 **날짜 교집합**으로 맞춘다.
    """
    from app.services.stock import get_candles
    try:
        data = await get_candles(BENCHMARK_SYMBOL, period="2y", interval="1d")
        rows = []
        for c in data.get("candles", []):
            if not c.get("close"):
                continue
            d = _norm_date(c)
            if d:
                rows.append((d, float(c["close"])))
        if len(rows) < 2:
            return [], np.array([])
        rows.sort(key=lambda r: r[0])           # 날짜 오름차순 보장
        dates = [r[0] for r in rows[1:]]         # 수익률은 두 번째 날부터
        closes = np.array([r[1] for r in rows], dtype=float)
        rets = closes[1:] / closes[:-1] - 1
        return dates, rets
    except Exception:
        return [], np.array([])


async def get_returns_table(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """기간별 수익률 (1m/3m/6m/1y/누적)."""
    _, equity = await get_daily_returns(db, user_id)
    if len(equity) < 2:
        return {"status": "insufficient_data", "snapshot_count": len(equity)}

    def pr(days: int) -> float | None:
        if len(equity) < days + 1:
            return None
        return float(equity[-1] / equity[-days - 1] - 1)

    return {
        "status": "ok",
        "return_1m": _clean(pr(21)),
        "return_3m": _clean(pr(63)),
        "return_6m": _clean(pr(126)),
        "return_1y": _clean(pr(252)),
        "return_cumulative": _clean(float(equity[-1] / equity[0] - 1)),
        "snapshot_count": len(equity),
    }


async def get_risk_metrics(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """위험지표 (KOSPI 대비): 표준편차·베타·샤프·젠센알파·트래킹에러·정보비율.

    이슈 #88 지적 #10 — 계좌와 KOSPI 를 **날짜 교집합**으로 짝짓는다.
    """
    dates, returns, equity = await get_daily_returns(db, user_id, with_dates=True)
    if len(returns) < 5:
        return {"status": "insufficient_data", "snapshot_count": len(equity)}

    bench_dates, bench_all = await _get_benchmark_map()
    if len(bench_dates) < 5:
        return {"status": "insufficient_data", "reason": "벤치마크 없음"}

    bench_map = {d: bench_all[i] for i, d in enumerate(bench_dates) if i < len(bench_all)}

    # ── 날짜 교집합 ──
    common = [d for d in dates if d in bench_map]
    if len(common) < 5:
        return {
            "status": "insufficient_data",
            "reason": f"공통 거래일 부족 ({len(common)}일)",
        }

    idx = {d: i for i, d in enumerate(dates)}
    returns = np.array([returns[idx[d]] for d in common], dtype=float)
    bench = np.array([bench_map[d] for d in common], dtype=float)

    def mf(window: int) -> dict[str, float | None]:
        keys = ("std_dev", "beta", "sharpe", "jensen_alpha", "tracking_error", "information_ratio")
        r = returns[-window:] if len(returns) >= window else returns
        b = bench[-window:] if len(bench) >= window else bench
        n = min(len(r), len(b))
        if n < 5:
            return {k: None for k in keys}
        r, b = r[-n:], b[-n:]

        std_dev = float(np.std(r, ddof=1)) * np.sqrt(_PPY)
        var_b = float(np.var(b, ddof=1))
        cov = float(np.cov(r, b, ddof=1)[0, 1]) if var_b > 0 else 0.0
        beta = cov / var_b if var_b > 0 else 0.0
        sharpe = float((np.mean(r) * _PPY - _RF) / std_dev) if std_dev > 0 else None

        r_ann = float(np.mean(r) * _PPY)
        b_ann = float(np.mean(b) * _PPY)
        alpha = r_ann - (_RF + beta * (b_ann - _RF))
        diff = r - b
        te = float(np.std(diff, ddof=1)) * np.sqrt(_PPY)
        ir = (r_ann - b_ann) / te if te > 0 else None

        return {
            "std_dev": _clean(std_dev),
            "beta": _clean(beta),
            "sharpe": _clean(sharpe),
            "jensen_alpha": _clean(alpha),
            "tracking_error": _clean(te),
            "information_ratio": _clean(ir),
        }

    return {
        "status": "ok",
        "benchmark": "KOSPI",
        "common_days": len(common),
        "1m": mf(21), "3m": mf(63), "6m": mf(126), "1y": mf(252),
    }


async def get_turnover(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """
    매매회전율.
    회전율 = (총매수 + 총매도) / 2 / 평균자산
    연환산 = 회전율 / (기간 년수)
    """
    from sqlalchemy import func as sqlfunc
    from app.models import Order

    buy_sum = (await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(Order.price * Order.quantity), 0.0))
        .where(Order.user_id == user_id, Order.order_type == "buy")
    )).scalar_one() or 0.0
    sell_sum = (await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(Order.price * Order.quantity), 0.0))
        .where(Order.user_id == user_id, Order.order_type == "sell")
    )).scalar_one() or 0.0

    _, equity = await get_daily_returns(db, user_id)
    avg_equity = float(np.mean(equity)) if len(equity) else 0.0
    n_days = len(equity)
    years = n_days / _PPY if n_days > 0 else 0.0

    base = ((buy_sum + sell_sum) / 2) / avg_equity if avg_equity > 0 else 0.0
    annualized = base / years if years > 0 else 0.0

    return {
        "status": "ok",
        "total_buy": round(float(buy_sum), 2),
        "total_sell": round(float(sell_sum), 2),
        "avg_equity": round(avg_equity, 2),
        "turnover_ratio": round(base * 100, 4),
        "annualized_turnover_pct": round(annualized * 100, 4),
        "period_days": n_days,
        "period_years": round(years, 4),
    }


async def get_allocation_history(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 60,
) -> dict[str, Any]:
    """시점별 자산 비중 (스택바 차트용)."""
    from app.models.paper_snapshot import PaperAccountSnapshot

    rows = (await db.execute(
        select(PaperAccountSnapshot)
        .where(PaperAccountSnapshot.user_id == user_id)
        .order_by(PaperAccountSnapshot.snap_date.asc())
        .limit(limit)
    )).scalars().all()

    if not rows:
        return {"status": "insufficient_data"}

    series = []
    for r in rows:
        total = float(r.total_equity) or 1.0
        series.append({
            "date": r.snap_date.isoformat(),
            "cash_pct": round(float(r.cash) / total * 100, 2),
            "stock_pct": round(float(getattr(r, "stock_value", 0) or 0) / total * 100, 2),
            "crypto_pct": round(float(getattr(r, "crypto_value", 0) or 0) / total * 100, 2),
            "alt_pct": round(float(getattr(r, "alt_value", 0) or 0) / total * 100, 2),
        })

    return {"status": "ok", "series": series}


async def get_benchmark_series(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """우리 자산 + KOSPI 정규화 시계열 (기간선택 차트용).

    이슈 #88 지적 #10 — 이전엔 `bench_closes[-len(equity):]` 로 끝에서 N개를 잘라
    계좌 스냅샷이 띄엄띄엄하면 엉뚱한 날 KOSPI 를 그렸다. 이제 **날짜 기준**으로 맞춘다.
    """
    from app.models.paper_snapshot import PaperAccountSnapshot
    from app.services.stock import get_candles

    rows = (await db.execute(
        select(PaperAccountSnapshot)
        .where(PaperAccountSnapshot.user_id == user_id)
        .order_by(PaperAccountSnapshot.snap_date.asc())
    )).scalars().all()

    if len(rows) < 2:
        return {"status": "insufficient_data"}

    our_dates = [r.snap_date.isoformat() for r in rows]
    equity = np.array([float(r.total_equity) for r in rows], dtype=float)

    try:
        bench_data = await get_candles(BENCHMARK_SYMBOL, period="2y", interval="1d")
        bench_map: dict[str, float] = {}
        for c in bench_data.get("candles", []):
            if not c.get("close"):
                continue
            d = _norm_date(c)
            if d:
                bench_map[d] = float(c["close"])
    except Exception as e:
        return {"status": "insufficient_data", "reason": f"벤치마크 실패: {e}"}

    # 계좌 스냅샷 날짜 기준으로 KOSPI 있는 날만 교집합
    common = [d for d in our_dates if d in bench_map]
    if len(common) < 2:
        return {"status": "insufficient_data", "reason": "벤치마크 공통 날짜 부족"}

    idx = {d: i for i, d in enumerate(our_dates)}
    our_aligned = np.array([equity[idx[d]] for d in common], dtype=float)
    bench_aligned = np.array([bench_map[d] for d in common], dtype=float)

    norm_our = (our_aligned / our_aligned[0] * 100).round(2).tolist()
    norm_bench = (bench_aligned / bench_aligned[0] * 100).round(2).tolist()

    return {
        "status": "ok",
        "dates": common,
        "our_series": norm_our,
        "benchmark_series": norm_bench,
        "benchmark_name": "KOSPI",
    }