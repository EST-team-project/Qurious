"""수동 현금흐름을 제외한 PAPER 계좌 투자성과 계산 유틸리티."""
from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any


EXTERNAL_CASHFLOW_KINDS = ("DEPOSIT", "WITHDRAW")


def _as_utc(value: datetime | None) -> datetime | None:
    """DB 드라이버·테스트 더블이 반환한 시각을 비교 가능한 UTC로 정규화한다."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def cashflow_adjusted_return(
    start_equity: float,
    end_equity: float,
    start_at: datetime | None,
    end_at: datetime | None,
    cashflows: Iterable[Any],
    epoch: int,
) -> tuple[float, bool]:
    """외부 입출금을 제외한 Modified Dietz 수익률을 계산한다.

    DEPOSIT은 양(+)의 외부 현금흐름, WITHDRAW는 음(-)의 외부 현금흐름이다.
    각 흐름의 기간 말까지 남은 시간을 가중치로 사용한다. DIVIDEND는 투자소득이므로
    외부 현금흐름에서 제외해 수익률에 포함한다.

    회차를 확인할 수 없는 과거 이벤트(epoch=NULL)가 구간에 있으면 수익률을 추정하지
    않는다. 해당 구간만 성과 시계열에서 제외하고, 다음 유효 스냅샷부터 다시 연결한다.
    """
    start_time = _as_utc(start_at)
    end_time = _as_utc(end_at)
    try:
        beginning = float(start_equity)
        ending = float(end_equity)
    except (TypeError, ValueError):
        return 0.0, False

    if (
        start_time is None
        or end_time is None
        or end_time <= start_time
        or not math.isfinite(beginning)
        or not math.isfinite(ending)
        or beginning <= 0
    ):
        return 0.0, False

    period_seconds = (end_time - start_time).total_seconds()
    net_external_flow = 0.0
    weighted_external_flow = 0.0

    for event in cashflows:
        kind = str(getattr(event, "kind", "") or "").upper()
        if kind not in EXTERNAL_CASHFLOW_KINDS:
            continue

        event_time = _as_utc(getattr(event, "created_at", None))
        if event_time is None or not (start_time < event_time <= end_time):
            continue

        event_epoch = getattr(event, "epoch", None)
        if event_epoch is None:
            # 기존 이벤트는 어느 회차의 현금흐름인지 알 수 없어 현재 회차로 간주하지 않는다.
            return 0.0, False
        try:
            if int(event_epoch) != int(epoch):
                continue
            amount = float(event.amount)
        except (TypeError, ValueError, AttributeError):
            return 0.0, False
        if not math.isfinite(amount) or amount <= 0:
            return 0.0, False

        signed_flow = amount if kind == "DEPOSIT" else -amount
        weight = (end_time - event_time).total_seconds() / period_seconds
        net_external_flow += signed_flow
        weighted_external_flow += signed_flow * weight

    denominator = beginning + weighted_external_flow
    if not math.isfinite(denominator) or denominator <= 0:
        return 0.0, False

    result = (ending - beginning - net_external_flow) / denominator
    if not math.isfinite(result):
        return 0.0, False
    return float(result), True
