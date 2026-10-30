"""XAI: LightGBM SHAP 기여도 설명이 일관된 구조와 문장을 만들어야 한다."""
import numpy as np
import pytest

lgb = pytest.importorskip("lightgbm")

from app.services import xai
from app.services.quant_pipeline import feature_engineer, preprocess, train_lgb, FEATURE_COLS
from tests.conftest import make_candles


def test_explain_signal_structure_and_consistency():
    df = feature_engineer(preprocess(make_candles(500)))
    model, _ = train_lgb(df)
    x = df[FEATURE_COLS].iloc[-1]
    probs = model.predict(x.values.reshape(1, -1))[0]
    ex = xai.explain_signal(model, x.values, FEATURE_COLS, x.to_dict(), probs)

    assert ex["signal"] in (-1, 0, 1) and ex["signal_label"] == xai.SIGNAL_LABEL[ex["signal"]]
    assert len(ex["contributions"]) == len(FEATURE_COLS)
    contribs = [abs(r["contribution"]) for r in ex["contributions"]]
    assert contribs == sorted(contribs, reverse=True)           # 기여도 절대값 내림차순
    assert all(r["label"] and "value_text" in r for r in ex["contributions"])
    assert ex["signal_label"] in ex["summary"] and "%" in ex["summary"]
    assert abs(sum(ex["class_probabilities"].values()) - 100) < 0.5
    # SHAP 기여도 + base = 예측 클래스의 raw score (TreeSHAP 가법성)
    raw = model.predict(x.values.reshape(1, -1), raw_score=True)[0]
    cls = int(np.argmax(probs))
    total = sum(r["contribution"] for r in ex["contributions"]) + ex["base_value"]
    assert total == pytest.approx(float(raw[cls]), abs=1e-2)


def test_feature_meta_covers_all_features():
    assert set(FEATURE_COLS) <= set(xai.FEATURE_META)


def _run_ai_predict_capturing_model(monkeypatch, candles):
    """ai_predict_return 을 그대로 돌리며 설명에 넘긴 모델만 잡는다(결과는 바꾸지 않음)."""
    from app.services.investment_research import ai_predict_return
    seen = {}
    real = xai.explain_signal

    def spy(model, x_row, *args, **kwargs):
        seen["model"], seen["x_row"] = model, np.asarray(x_row, dtype=float)
        return real(model, x_row, *args, **kwargs)

    monkeypatch.setattr(xai, "explain_signal", spy)
    return ai_predict_return(candles), seen


def test_ai_predict_badge_probability_is_today_row(monkeypatch):
    """배지의 판단 · 확률과 SHAP 근거가 같은 날(오늘 줄)의 예측이어야 한다."""
    candles = make_candles(500)
    ai, seen = _run_ai_predict_capturing_model(monkeypatch, candles)
    assert ai and ai["explanation"] and "model" in seen

    today = feature_engineer(preprocess(candles))[FEATURE_COLS].iloc[-1].values.astype(float)
    assert np.allclose(seen["x_row"], today)                     # SHAP 은 오늘 줄
    probs = seen["model"].predict(today.reshape(1, -1))[0]
    cls = int(np.argmax(probs))
    ex = ai["explanation"]
    assert ai["model_signal"] == cls - 1
    assert ai["model_signal_probability_pct"] == pytest.approx(round(float(probs[cls]) * 100, 1))
    assert ex.get("model_signal", ex["signal"]) == cls - 1           # 배지 확률 · 기여도가 가리키는 모델 판단
    assert ex["probability_pct"] == pytest.approx(round(float(probs[cls]) * 100, 1), abs=0.051)
    assert ex["class_probabilities"]["매수"] == pytest.approx(round(float(probs[2]) * 100, 1), abs=0.051)
    if ai["quality"]["reliable"]:
        assert ai["signal"] == cls - 1
        assert ai["signal_confidence"] == pytest.approx(float(probs[cls]), abs=1e-4)
    # 근거 기여도 합 + base = 같은 예측(오늘 줄 · 배지 클래스)의 raw score
    raw = seen["model"].predict(today.reshape(1, -1), raw_score=True)[0]
    total = sum(r["contribution"] for r in ex["contributions"]) + ex["base_value"]
    assert total == pytest.approx(float(raw[cls]), abs=1e-2)


def _explain_route(monkeypatch):
    from app.routes import ml
    calls = {"train": 0, "keys": []}

    async def fake_cache_get(key, max_age_hours=None):
        calls["keys"].append(key)
        return {"signal": 1, "explanation": {"summary": "캐시"}}

    async def fake_cache_set(key, value, *a, **k):
        calls["keys"].append(key)

    async def fake_candles(symbol, period=None, interval=None):
        return {"candles": make_candles(100)}

    def fake_predict(candles):
        calls["train"] += 1
        return {"signal": 0, "explanation": {"summary": "새로"}}

    monkeypatch.setattr(ml, "cache_get", fake_cache_get)
    monkeypatch.setattr(ml, "cache_set", fake_cache_set)
    monkeypatch.setattr(ml, "get_candles", fake_candles)
    monkeypatch.setattr(ml, "ai_predict_return", fake_predict)
    return ml, calls


def test_explain_refresh_is_admin_only(monkeypatch):
    import asyncio
    ml, calls = _explain_route(monkeypatch)
    out = asyncio.run(ml.ml_explain(symbol="005930.KS", refresh=1, user={"roles": ["user"]}))
    assert calls["train"] == 0 and out["explanation"]["summary"] == "캐시"   # 관리자 아니면 refresh 무시
    out = asyncio.run(ml.ml_explain(symbol="005930.KS", refresh=1, user={"roles": ["admin"]}))
    assert calls["train"] == 1 and out["explanation"]["summary"] == "새로"


def test_explain_cache_key_is_v5(monkeypatch):
    """교차검증 간격(#363)을 넣은 뒤 옛(v4) 캐시를 읽지 않는다 — 스크리닝 요약도 같은 키."""
    import asyncio, inspect
    from app.routes import stocks
    ml, calls = _explain_route(monkeypatch)
    asyncio.run(ml.ml_explain(symbol="005930.KS", refresh=0, user={"roles": []}))
    assert calls["keys"] == ["ai_predict:v5:005930.KS"]
    src = inspect.getsource(stocks)
    assert 'f"ai_predict:v5:{stock' in src and "ai_predict:v4" not in src


@pytest.mark.parametrize("seed", [44, 136])  # 합성 시세에서 품질 관문에 걸리면서 모델 판단이 매수(44) · 매도(136) — 간격(#363) 뒤 다시 고름
def test_quality_gate_badge_shows_lowered_signal(monkeypatch, seed):
    """관문이 판단을 관망으로 낮추면 배지(설명)도 관망 — 경고 · 응답 판단과 같은 말. 확률이 가리키는 모델 판단은 따로 남는다."""
    ai, seen = _run_ai_predict_capturing_model(monkeypatch, make_candles(500, seed=seed))
    ex = ai["explanation"]
    assert ai["quality"]["reliable"] is False and ex["quality_warning"]
    assert ai["signal"] == ex["signal"] == 0 and ex["signal_label"] == "관망"
    probs = seen["model"].predict(seen["x_row"].reshape(1, -1))[0]
    cls = int(np.argmax(probs))
    assert cls != 1 and ex["model_signal"] == cls - 1 and ex["model_signal_label"] == xai.SIGNAL_LABEL[cls - 1]
    assert ex["probability_pct"] == pytest.approx(round(float(probs[cls]) * 100, 1), abs=0.051)


def test_screen_badge_text_uses_lowered_signal():
    """스크리닝 패널 · 추천 종목 카드 · 표 요약 줄이 같은 배지 글자를 쓰고, 기여도는 반올림 뒤 부호(「-0.00」 없음)."""
    import pathlib, re
    js = pathlib.Path("public/js/robo.js").read_text(encoding="utf-8")
    block = js[js.index("function renderXaiBlock"):js.index("function renderAllocation")]
    assert "${escHtml(xaiBadgeText(ex))}" in block and "${ptSigned(r.contribution)}" in block
    assert "toFixed(2)" not in block
    assert "xaiBadgeText(s.xai))} — ${" in js                          # 요약 줄 「— 」 뒤 띄어쓰기(#205 에서 빠졌던 것)
    from app.routes import stocks                                     # 표 요약 줄이 쓸 모델 판단 칸을 서버가 넘긴다
    import inspect
    assert '"model_signal_label": ex.get("model_signal_label")' in inspect.getsource(stocks)
    assert not re.search(r"signal_label\)\} \$\{[^}]*probability_pct\}%", js)   # 옛 꼴(판단 + 확률 그대로) 남지 않음


def test_ai_predict_carries_last_daily_bar_date():
    """XAI 판단 한 줄의 기준일 — 학습 · 예측에 쓴 마지막 일봉 날(#213 「무엇으로 냈나 · 기준일」)."""
    import pathlib
    from app.services.investment_research import ai_predict_return
    from app.services.pattern_view import candle_day
    candles = make_candles(500)
    assert ai_predict_return(candles)["as_of"] == candle_day(candles)
    js = pathlib.Path("public/js/robo.js").read_text(encoding="utf-8")
    assert "기준일 ${escHtml(pr.as_of" in js


def test_ai_predict_cv_leaves_label_horizon_gap(monkeypatch):
    """라벨이 5일 뒤 값이라 학습 끝과 검증 처음 사이를 5행 비운다 — 겹 나누기 · LightGBM 80/20 둘 다(#363)."""
    import lightgbm as lgb
    import sklearn.model_selection as ms
    from app.services.investment_research import ai_predict_return
    folds, sizes = [], []
    real_split, real_ds = ms.TimeSeriesSplit.split, lgb.Dataset

    def spy_split(self, X, *a, **k):
        for tr, va in real_split(self, X, *a, **k):
            folds.append((int(tr.max()), int(va.min())))
            yield tr, va

    def spy_ds(data, *a, **k):
        sizes.append(len(data))
        return real_ds(data, *a, **k)

    monkeypatch.setattr(ms.TimeSeriesSplit, "split", spy_split)
    monkeypatch.setattr(lgb, "Dataset", spy_ds)
    assert ai_predict_return(make_candles(500)) is not None
    assert folds and all(va_first - tr_last - 1 == 5 for tr_last, va_first in folds)
    n_tr, n_va = sizes[0], sizes[1]
    total = n_tr + 5 + n_va
    assert n_tr + 5 == int(total * 0.8)
