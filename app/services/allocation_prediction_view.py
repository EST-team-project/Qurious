"""배분 결과의 표시만 정리한다. 순위·최적화 입력과 저장된 과거 결과는 변경하지 않는다."""
from copy import deepcopy
from math import isfinite

SIGNALS = {-1: "매도", 0: "관망", 1: "매수"}


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


def prediction_view(prediction: dict) -> dict:
    ai = deepcopy(prediction)
    annual = _number(ai.get("pred_ann_return_pct"))
    # 경계에 반올림된 옛 저장본도 안전하게 표시한다.
    outside = ai.get("pred_ann_return_status") == "out_of_range" or annual is not None and (annual <= -90 or annual >= 300)
    status = "out_of_range" if outside else "unavailable" if annual is None else "available"
    ai["pred_ann_return_pct"] = annual if status == "available" else None
    ai["pred_ann_return_status"] = status
    return_text = ("AI 연환산 참고값: 모델 범위 밖 — 숫자로 표시하지 않습니다." if outside else
                   "AI 연환산 참고값: 확인할 수 없습니다." if annual is None else
                   f"AI 연환산 참고값 {annual:.2f}% — 5거래일 예측을 1년으로 환산한 값입니다.")

    ex = ai.get("explanation") or {}
    model_signal = ai.get("model_signal", ex.get("model_signal", ex.get("signal")))
    probability = _number(ai.get("model_signal_probability_pct", ex.get("probability_pct")))
    if probability is not None and not 0 <= probability <= 100:
        probability = None
    quality = ai.get("quality") or {}
    accuracy, baseline = _number(quality.get("cls_val_accuracy")), _number(quality.get("baseline_accuracy"))
    unreliable = quality.get("reliable") is False
    final_signal = 0 if unreliable else ai.get("signal")
    if unreliable:
        ai["signal"] = 0
        if ex:
            if ex.get("signal") in (-1, 1):
                ex["model_signal"], ex["model_signal_label"] = ex["signal"], SIGNALS[ex["signal"]]
            ex["signal"], ex["signal_label"] = 0, "관망"
    final_label = SIGNALS.get(final_signal, "미확인")
    model_label = SIGNALS.get(model_signal)
    if probability is not None and model_label:
        signal_text = f"최종 판단 {final_label} · 모델 {model_label} 확률 {probability:.1f}%"
        probability_note = ("매도·관망·매수 중 가장 높은 분류 확률이지만 50% 미만입니다. " if probability < 50 else "") + "모델의 분류 확률이며 실제 수익이 날 확률은 아닙니다."
    else:
        signal_text = f"판단 {final_label} · 분류 확률 미확인"
        probability_note = "내부 예측 반영 점수는 확률로 표시하지 않습니다."
    if unreliable:
        quality_warning = "이 분류 모델은 검증 성능 기준을 충족하지 못해 판단을 관망으로 낮췄습니다."
        if accuracy is not None and baseline is not None:
            quality_warning += f" 검증 정확도 {accuracy * 100:.1f}% · 기준선 {baseline * 100:.1f}% (통과 기준: 기준선 + 2%p)."
    elif accuracy is None or baseline is None:
        quality_warning = "분류 모델의 검증 성능을 확인할 수 없습니다."
    else:
        quality_warning = ""
    ai["display"] = {"return_text": return_text, "signal_text": signal_text,
                     "probability_note": probability_note, "quality_warning": quality_warning}
    return ai


def allocation_view(result: dict) -> dict:
    result = deepcopy(result)
    for pick in result.get("stock_picks", []):
        if not isinstance(pick.get("ai_prediction"), dict):
            continue
        ai = prediction_view(pick["ai_prediction"])
        pick["ai_prediction"] = ai
        # 기존 저장본에 포함된 상한값·소수 신뢰도 문장도 재사용하지 않는다.
        reason = pick.get("historical_reason")
        if reason is None:
            reason = str(pick.get("reason", "")).split(", AI 예측 수익률", 1)[0]
        pick["historical_reason"] = reason
        pick["reason"] = ", ".join(filter(None, [reason, *ai["display"].values()]))
    return result
