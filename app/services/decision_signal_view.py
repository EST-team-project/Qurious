"""자동매매 기록의 표시용 출처. 매매 규칙·행동·점수 원본은 바꾸지 않는다."""
from math import isfinite
from datetime import datetime, timezone


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


def signal_view(signal: dict, settings: dict, cycle_at=None) -> dict:
    basis = signal.get("basis") or {}
    strategy = settings.get("strategy") or {}
    aggressive = settings.get("aggressive")
    error = bool(signal.get("error"))
    if error:
        kind, method = "unavailable", "지표 계산 실패 · 판단 불가"
    elif aggressive is True:
        kind, method = "aggressive", "공격 모드 · 분봉 RSI·이동평균·모멘텀·거래량 및 회차별 매매 계획"
    elif aggressive is False:
        kind, method = "basic", "기본 일봉 규칙 · RSI·이동평균·볼린저"
    else:
        kind, method = "unknown", "과거 기록 · 판단 방식 미확인"
    if not error and strategy.get("applied") is True:
        method += f" · 사용자 전략 {strategy.get('id', '')} v{strategy.get('version', '?')}"
        if kind != "aggressive":
            kind = "strategy"
    score = None if error else _number(signal.get("score"))
    label = "분봉 지표 점수" if kind == "aggressive" else "기본 지표 점수" if kind in ("basic", "strategy") else "기록 점수"
    score_text = "점수 미확인" if score is None else f"{label} {score:.1f}"
    normalized = _number(basis.get("normalized_score"))
    if not error and strategy.get("applied") is True and normalized is not None:
        score_text += f" · 전략 정규화 점수 {normalized:+.2f}"
    note = "지표 점수와 최종 판단은 사용자 전략·공격 모드·위험 정지에 따라 다를 수 있습니다. 주문·체결 결과는 실행 로그에서 확인하세요."
    return {**signal, "cycle_at": cycle_at, "decision": {
        "kind": kind, "method": method, "score_text": score_text,
        "as_of": basis.get("as_of"), "interval": basis.get("interval"), "note": note,
    }}


def cycle_timestamp(value) -> float:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc).timestamp() if stamp.tzinfo is None else stamp.timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("-inf")
