"""P01-④-2 — T2 신호 · 신뢰도 · 보유 여부 → 매수 · 매도 · 보유 의견.

설계서 4.4절 (docs/설계/기능설계.md:393).

규칙 표(판 고정) — 입력 = T2 신호 · 신뢰도 · 보유 여부 · 목표 비중(T3)
    매수  : 미보유 + 매수 신호 + 신뢰도 >= θ
    매도  : 보유 + 매도 신호 + 신뢰도 >= θ  또는 위험 관문 한도
    보유  : 그 밖 (관망도 기록)
상충 신호 = 보유.

이유(opinion_rule) 는 규칙 줄 키 — 화면(P01-①-5)이 그날 값과 함께 풀어 쓴다.
"""
from __future__ import annotations

BUY, SELL, HOLD, SKIP = "매수", "매도", "보유", "관망"

#: 신뢰도 문턱 θ — 설계서 값이 정해지면 바꾼다
CONFIDENCE_MIN = 0.6


def decide(
    signal: str,
    confidence: float,
    held: bool,
    *,
    risk_gate: bool = False,
) -> tuple[str, str]:
    """(의견, 규칙 키).

    signal     : T2 신호 — "매수" · "매도" · "관망"
    confidence : T2 신뢰도 0~1
    held       : 그 종목 보유 여부
    risk_gate  : 위험 관문 한도에 걸렸나 (예: 손실 한도 초과)
    """
    if held and risk_gate:
        return SELL, "sell_risk_gate"

    if signal == "매수" and not held:
        if confidence >= CONFIDENCE_MIN:
            return BUY, "buy_new"
        return SKIP, "skip_low_conf"

    if signal == "매도" and held:
        if confidence >= CONFIDENCE_MIN:
            return SELL, "sell_held"
        return HOLD, "hold_low_conf"

    if held:
        return HOLD, "hold_held"

    return SKIP, "skip_neutral"