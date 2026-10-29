"""수정주가와 원주가 사이의 단위 변환 (#366). 현재 원주가에는 다시 적용하지 않는다."""
from __future__ import annotations

import math
import sqlite3
from datetime import date

from app.services import collector_db


def positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label}을 확인하지 못했습니다.")
    return float(value)


def adjusted_to_raw(value: float, factor: float) -> float:
    """수정 = 원래 × 판단 날 누적계수. ATR도 같은 가격 거리이므로 계수로 나눈다."""
    result = positive(value, "수정 가격·거리") / positive(factor, "누적 조정계수")
    return positive(result, "원래 가격·거리")


def adjustment_changed(before: float, after: float) -> bool:
    return not math.isclose(positive(before, "이전 계수") / positive(after, "이후 계수"), 1.0,
                            rel_tol=1e-9, abs_tol=1e-9)


def load_day(symbol: str, on: date, *, path=None) -> dict:
    """지정 거래일만 읽는다. 다른 날 값이나 마지막 계수로 대체하지 않는다."""
    path = path or collector_db.db_path()
    if path is None:
        raise ValueError("가격 단위 확인용 수집 DB가 없습니다.")
    code = symbol.split('.')[0]
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
        row = conn.execute(
            "SELECT p.clpr, a.adj_clpr, a.cum_factor FROM price_daily p "
            "JOIN price_adjusted a USING (bas_dt, srtn_cd) WHERE p.srtn_cd=? AND p.bas_dt=?",
            (code, on.strftime('%Y%m%d'))).fetchone()
    if row is None:
        raise ValueError("해당 거래일의 원주가·수정주가·계수가 없습니다.")
    raw, adjusted, factor = (positive(v, label) for v, label in zip(row, ('원주가', '수정주가', '계수')))
    # 공급 자료의 원 단위 반올림은 허용하되 다른 가격 계열은 거부한다.
    if not math.isclose(raw * factor, adjusted, rel_tol=1e-6, abs_tol=1.0):
        raise ValueError("원주가·수정주가·계수의 단위가 일치하지 않습니다.")
    return {'as_of': on.isoformat(), 'raw_close': raw, 'adjusted_close': adjusted, 'factor': factor}
