# app/services/performance_service.py
"""모의계좌 성과 지표(QFRS) 통합 서비스."""

from __future__ import annotations

import math
import uuid
from datetime import timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.evaluation_risk import calculate_all_metrics
from app.services.paper_snapshot_service import (
    get_daily_returns,
    valid_daily_row, _get_current_epoch,
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


# 성과 화면 공통 표본 정책. QFRS와 테스트베드 위험지표가 같은 최소 기준을 사용한다.
MIN_METRIC_OBSERVATIONS = 21
MIN_DAILY_STD_DEV = 0.005
RISK_PERIOD_OBSERVATIONS = {"1m": 21, "3m": 63, "6m": 126, "1y": 252}
RETURN_BASIS = "modified_dietz_external_cashflows_excluded"

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

    완전한 일일 스냅샷이 부족하면 부족 상태를 알려준다. 조회로 기록을 변경하지 않는다.
    """
    returns, equity = await get_daily_returns(db, user_id)

    # 날짜 배열 (X축 라벨용)
    _snap_rows = (await db.execute(
        select(PaperAccountSnapshot)
        .where(
            PaperAccountSnapshot.user_id == user_id,
            PaperAccountSnapshot.completeness == "complete",
            PaperAccountSnapshot.origin == "daily",
        )
        .order_by(PaperAccountSnapshot.snap_date.asc())
    )).scalars().all()
    epoch = await _get_current_epoch(db, user_id)
    snap_dates = [r.snap_date.isoformat() for r in _snap_rows if valid_daily_row(r, epoch)]  # ["2026-09-17", ...]

    # 스냅샷이 2개 미만 → 지표 계산 불가
    if len(returns) < 2:
        return {
            "status": "insufficient_data",
            "message": "계산 가능한 일수익률이 2개 미만입니다. 거래일 마감 후 일일 수집으로 쌓입니다.",
            "snapshot_count": len(equity),
            "metrics": _nan_metrics(),
            "equity_curve": [_clean(v) for v in equity.tolist()],
            "snap_dates": snap_dates,
            "return_basis": "modified_dietz_external_cashflows_excluded",
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

    # 이상값 방지 — 기록 부족 · 변동성 극소면 지표를 숨긴다 (이슈 #220)
    n = len(returns)
    std_dev_daily = float(np.std(returns, ddof=1)) if n >= 2 else 0.0
    too_short = n < MIN_METRIC_OBSERVATIONS
    too_flat = std_dev_daily < MIN_DAILY_STD_DEV

    def _safe(v, cap=100.0):
        """극단값은 None — |v| > cap 이면 뜻이 없음."""
        if v is None or not np.isfinite(v):
            return None
        return None if abs(v) > cap else float(v)

    if too_short or too_flat:
        # 스냅샷 부족 or 변동성 극소 → 지표 숨김
        metrics_out = {k: None for k in (
            "mdd", "sharpe_ratio", "sortino_ratio",
            "sterling_ratio", "calmar_ratio", "dsr",
        )}
        metrics_out["reason"] = (
            f"아직 판단할 만큼 기록이 없습니다 "
            f"(스냅샷 {n}개 · 일변동성 {std_dev_daily*100:.2f}%) — "
            f"모의 주문을 더 해 보세요."
        )
    else:
        metrics_out = {
            "mdd": _clean(metrics["MDD"]),
            "sharpe_ratio": _safe(metrics["Sharpe Ratio"], cap=10.0),
            "sortino_ratio": _safe(metrics["Sortino Ratio"], cap=10.0),
            "sterling_ratio": _safe(metrics["Sterling Ratio"], cap=20.0),
            "calmar_ratio": _safe(metrics["Calmar Ratio"], cap=20.0),
            "dsr": _clean(metrics["Deflated Sharpe Ratio"]),
        }

    # 계좌 총자산(equity)은 입출금에 따라 변하므로 투자성과 계산에 직접 사용하지 않는다.
    # 성과 누적곡선은 입출금 보정 일간 수익률을 복리 연결한다.
    performance_index = np.cumprod(1.0 + returns) if len(returns) else np.array([], dtype=float)
    total_return = float(performance_index[-1] - 1.0) if len(performance_index) else None

    # Drawdown curve (차트용): 외부 입출금이 아닌 투자성과 기준.
    if len(performance_index) > 0:
        running_max = np.maximum.accumulate(performance_index)
        drawdown_curve = (performance_index / running_max - 1).tolist()
    else:
        drawdown_curve = []

    return {
        "status": "ok",
        "snapshot_count": len(equity),
        "total_return": _clean(total_return),
        "metrics": metrics_out,          # ← 여기
        "equity_curve": [_clean(v) for v in equity.tolist()],
        "drawdown_curve": [_clean(v) for v in drawdown_curve],
        "return_basis": "modified_dietz_external_cashflows_excluded",
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

BENCHMARK_SYMBOL = "^KS11"   # Qurious 내부 참고용 KOSPI 가격지수
BENCHMARK_NAME = "KOSPI"
_RF = 0.02                  # Qurious 내부 고정 가정. 코스콤 공식 무위험수익률이 아님.
_PPY = 252
BENCHMARK_NOTE = (
    "Qurious 내부 참고지수는 KOSPI 가격지수(^KS11)입니다. "
    "해외주식·코인·대체자산 비중이 큰 계좌에는 적합한 비교 기준이 아닐 수 있습니다. "
    "배당을 반영하는 총수익지수가 아닌 가격지수이며, 코스콤 테스트베드의 공식 벤치마크와 동일하다고 확인된 값이 아닙니다."
)
RISK_FREE_RATE_NOTE = (
    "무위험수익률은 시장금리에 연동하지 않는 Qurious 내부 연 2.0% 고정 가정이며, "
    "코스콤 테스트베드의 공식 적용률이 아닙니다."
)
STATISTICAL_INFERENCE_NOTE = (
    "젠센 알파와 정보비율은 표본에서 계산한 기술통계 추정치입니다. "
    "표준오차·t값·통계적 유의성 검정은 제공하지 않으므로 단독으로 확정적 성과로 해석하지 마세요."
)


def _norm_date(c: dict, *, timestamp_timezone=timezone.utc) -> str | None:
    """캔들 항목에서 거래일(YYYY-MM-DD)을 읽는다.

    Yahoo 및 수집 DB의 일봉 epoch는 UTC 날짜로 정규화한다. KIS gateway는
    거래일 00:00 KST를 epoch로 반환하므로 source에 따라 시간대를 명시한다.
    명시적 date/datetime 문자열은 제공자가 붙인 거래일을 우선한다.
    """
    for key in ("date", "datetime", "d"):
        v = c.get(key)
        if v is None:
            continue
        if isinstance(v, str):
            return v[:10]
        if hasattr(v, "isoformat"):
            return v.isoformat()[:10]

    for key in ("time", "t", "timestamp"):
        v = c.get(key)
        if v is None:
            continue
        try:
            ts = float(v)
        except (TypeError, ValueError):
            continue
        if ts > 10_000_000_000:
            ts /= 1000.0
        from datetime import datetime
        return datetime.fromtimestamp(ts, tz=timestamp_timezone).date().isoformat()
    return None


def _candle_timestamp_timezone(source: str | None):
    """epoch 날짜 해석에 사용할 시세 공급자 시간대."""
    if str(source or "").strip().lower() == "kis":
        return ZoneInfo("Asia/Seoul")
    return timezone.utc


async def _get_benchmark_map() -> tuple[list[str], np.ndarray]:
    """KOSPI 종가에서 날짜별 일수익률을 만든다."""
    from app.services.stock import get_candles
    try:
        data = await get_candles(BENCHMARK_SYMBOL, period="2y", interval="1d")
        timestamp_timezone = _candle_timestamp_timezone(data.get("source"))
        rows = []
        for c in data.get("candles", []):
            if not c.get("close"):
                continue
            d = _norm_date(c, timestamp_timezone=timestamp_timezone)
            if d:
                rows.append((d, float(c["close"])))
        if len(rows) < 2:
            return [], np.array([])
        rows.sort(key=lambda r: r[0])
        dates = [r[0] for r in rows[1:]]
        closes = np.array([r[1] for r in rows], dtype=float)
        rets = closes[1:] / closes[:-1] - 1
        return dates, rets
    except Exception:
        return [], np.array([])


async def get_returns_table(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """기간별 수익률. 각 기간은 달력 월이 아니라 공통 일수익률 관측치 기준이다."""
    returns, equity = await get_daily_returns(db, user_id)
    if len(equity) < 2 or len(returns) < 1:
        return {
            "status": "insufficient_data",
            "snapshot_count": len(equity),
            "return_observation_count": len(returns),
            "period_observations": {
                key: {
                    "available": len(returns),
                    "required": days,
                    "status": "insufficient_data",
                }
                for key, days in RISK_PERIOD_OBSERVATIONS.items()
            },
            "return_basis": RETURN_BASIS,
        }

    def pr(days: int) -> float | None:
        if len(returns) < days:
            return None
        return float(np.prod(1.0 + returns[-days:]) - 1.0)

    period_observations = {
        key: {
            "available": min(len(returns), days),
            "required": days,
            "status": "ok" if len(returns) >= days else "insufficient_data",
        }
        for key, days in RISK_PERIOD_OBSERVATIONS.items()
    }
    return {
        "status": "ok",
        "return_1m": _clean(pr(RISK_PERIOD_OBSERVATIONS["1m"])),
        "return_3m": _clean(pr(RISK_PERIOD_OBSERVATIONS["3m"])),
        "return_6m": _clean(pr(RISK_PERIOD_OBSERVATIONS["6m"])),
        "return_1y": _clean(pr(RISK_PERIOD_OBSERVATIONS["1y"])),
        "return_cumulative": _clean(float(np.prod(1.0 + returns) - 1.0)),
        "snapshot_count": len(equity),
        "return_observation_count": len(returns),
        "period_observations": period_observations,
        "period_basis": "common_daily_return_observations",
        "period_note": (
            "1개월=21개, 3개월=63개, 6개월=126개, 1년=252개 일수익률 관측치입니다. "
            "결측 거래일이 있으면 달력 기간은 더 길어질 수 있습니다."
        ),
        "return_basis": RETURN_BASIS,
    }


async def get_risk_metrics(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Qurious 내부 KOSPI 참고지수 대비 위험지표. 각 기간의 전체 표본을 요구한다."""
    dates, account_returns, equity = await get_daily_returns(
        db, user_id, with_dates=True
    )
    base = {
        "benchmark": "KOSPI",
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "benchmark_type": "price_index",
        "benchmark_note": BENCHMARK_NOTE,
        "risk_free_rate_annual": _RF,
        "risk_free_rate_note": RISK_FREE_RATE_NOTE,
        "period_basis": "common_daily_return_observations",
        "period_observations_required": dict(RISK_PERIOD_OBSERVATIONS),
        "inference_available": False,
        "inference_note": STATISTICAL_INFERENCE_NOTE,
        "return_basis": RETURN_BASIS,
    }
    if len(account_returns) == 0:
        return {
            **base,
            "status": "insufficient_data",
            "snapshot_count": len(equity),
            "common_days": 0,
            "reason": "계산 가능한 일수익률이 없습니다.",
        }

    bench_dates, bench_all = await _get_benchmark_map()
    if len(bench_dates) < 2:
        return {
            **base,
            "status": "insufficient_data",
            "snapshot_count": len(equity),
            "common_days": 0,
            "reason": "벤치마크 데이터가 부족합니다.",
        }

    bench_map = {
        d: float(bench_all[i])
        for i, d in enumerate(bench_dates)
        if i < len(bench_all)
    }
    account_map = {
        d: float(account_returns[i])
        for i, d in enumerate(dates)
        if i < len(account_returns)
    }
    common = [d for d in dates if d in bench_map and d in account_map]
    if not common:
        return {
            **base,
            "status": "insufficient_data",
            "snapshot_count": len(equity),
            "common_days": 0,
            "reason": "계좌와 벤치마크의 공통 거래일이 없습니다.",
        }

    returns = np.asarray([account_map[d] for d in common], dtype=float)
    bench = np.asarray([bench_map[d] for d in common], dtype=float)
    metric_keys = (
        "std_dev", "beta", "sharpe", "jensen_alpha",
        "tracking_error", "information_ratio",
    )

    def empty_period(n: int, required: int, reason: str) -> dict[str, Any]:
        return {
            **{key: None for key in metric_keys},
            "status": "insufficient_data",
            "sample_count": n,
            "required_observations": required,
            "reason": reason,
        }

    def mf(period_key: str, window: int) -> dict[str, Any]:
        n = len(returns)
        if n < window:
            return empty_period(
                n, window,
                f"이 기간은 공통 일수익률 {window}개가 필요하지만 현재 {n}개입니다.",
            )

        r = returns[-window:]
        b = bench[-window:]
        std_daily = float(np.std(r, ddof=1))
        if window < MIN_METRIC_OBSERVATIONS:
            return empty_period(
                window, window,
                f"최소 관측치 {MIN_METRIC_OBSERVATIONS}개 미만입니다.",
            )
        if not np.isfinite(std_daily) or std_daily < MIN_DAILY_STD_DEV:
            return empty_period(
                window, window,
                f"일간 표준편차가 최소 기준 {MIN_DAILY_STD_DEV * 100:.2f}%보다 낮아 지표를 숨깁니다.",
            )

        std_dev = std_daily * np.sqrt(_PPY)
        var_b = float(np.var(b, ddof=1))
        if not np.isfinite(var_b) or var_b <= np.finfo(float).eps:
            beta = None
            alpha = None
        else:
            cov = float(np.cov(r, b, ddof=1)[0, 1])
            beta = cov / var_b
            r_ann = float(np.mean(r) * _PPY)
            b_ann = float(np.mean(b) * _PPY)
            alpha = r_ann - (_RF + beta * (b_ann - _RF))

        sharpe = float((np.mean(r) * _PPY - _RF) / std_dev) if std_dev > 0 else None
        diff = r - b
        te = float(np.std(diff, ddof=1)) * np.sqrt(_PPY)
        ir = (float(np.mean(diff)) * _PPY) / te if te > 0 else None

        return {
            "status": "ok",
            "sample_count": window,
            "required_observations": window,
            "sample_quality": "short_window" if window < 63 else "window_estimate",
            "std_dev": _clean(std_dev),
            "beta": _clean(beta),
            "sharpe": _clean(sharpe),
            "jensen_alpha": _clean(alpha),
            "tracking_error": _clean(te),
            "information_ratio": _clean(ir),
            "beta_reason": (
                "벤치마크 수익률 분산이 0에 가까워 베타와 젠센 알파를 계산할 수 없습니다."
                if beta is None else None
            ),
        }

    periods = {
        key: mf(key, days)
        for key, days in RISK_PERIOD_OBSERVATIONS.items()
    }
    return {
        **base,
        "status": "ok",
        "snapshot_count": len(equity),
        "common_days": len(common),
        "sample_note": (
            "위험지표는 기간별 전체 공통 관측치가 확보된 경우에만 표시합니다. "
            "각 기간은 21/63/126/252개 일수익률 기준이며, 미달 기간은 계산하지 않습니다. "
            "특히 21개 관측은 짧은 표본이어서 추정값 변동이 클 수 있습니다. "
            "알파·정보비율은 추정치로 표준오차와 t검정을 제공하지 않습니다."
        ),
        **periods,
    }

async def get_turnover(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """
    매매회전율.
    회전율 = (총매수 + 총매도) / 2 / 평균자산
    연환산 = 회전율 / (기간 년수)
    """
    from sqlalchemy import func as sqlfunc
    from app.models import Order

    # PAPER 성과와 동일하게 현재 계좌 회차의 주문만 회전율에 반영한다.
    epoch = await _get_current_epoch(db, user_id)

    buy_sum = (await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(Order.price * Order.quantity), 0.0))
        .where(Order.user_id == user_id, Order.epoch == epoch, Order.order_type == "buy")
    )).scalar_one() or 0.0
    sell_sum = (await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(Order.price * Order.quantity), 0.0))
        .where(Order.user_id == user_id, Order.epoch == epoch, Order.order_type == "sell")
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

    stmt = (
        select(PaperAccountSnapshot)
        .where(
            PaperAccountSnapshot.user_id == user_id,
            PaperAccountSnapshot.completeness == "complete",
            PaperAccountSnapshot.origin == "daily",
        )
        .order_by(PaperAccountSnapshot.snap_date.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    epoch = await _get_current_epoch(db, user_id)
    rows = [r for r in rows if valid_daily_row(r, epoch)][-limit:]

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
    from app.services.stock import get_candles

    # 실제 총자산은 입출금이 섞이므로, 현금흐름 보정된 일간 성과를 복리 연결한다.
    our_dates, returns, _ = await get_daily_returns(db, user_id, with_dates=True)
    if len(returns) < 1:
        return {"status": "insufficient_data", "return_basis": RETURN_BASIS}
    performance_index = np.cumprod(1.0 + returns) * 100.0
    our_map = {day: float(value) for day, value in zip(our_dates, performance_index)}

    try:
        bench_data = await get_candles(BENCHMARK_SYMBOL, period="2y", interval="1d")
        timestamp_timezone = _candle_timestamp_timezone(bench_data.get("source"))
        bench_map: dict[str, float] = {}
        for c in bench_data.get("candles", []):
            if not c.get("close"):
                continue
            d = _norm_date(c)
            if d:
                bench_map[d] = float(c["close"])
    except Exception as e:
        return {"status": "insufficient_data", "reason": f"벤치마크 실패: {e}"}

    # 수익률이 계산된 계좌 날짜와 KOSPI 날짜의 교집합
    common = [d for d in our_dates if d in bench_map]
    if not common:
        return {"status": "insufficient_data", "reason": "벤치마크 공통 날짜 부족"}

    our_aligned = np.array([our_map[d] for d in common], dtype=float)
    bench_aligned = np.array([bench_map[d] for d in common], dtype=float)

    norm_our = (our_aligned / our_aligned[0] * 100).round(2).tolist()
    norm_bench = (bench_aligned / bench_aligned[0] * 100).round(2).tolist()

    return {
        "status": "ok",
        "dates": common,
        "our_series": norm_our,
        "benchmark_series": norm_bench,
        "benchmark_name": "KOSPI",
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "benchmark_note": BENCHMARK_NOTE,
    }
