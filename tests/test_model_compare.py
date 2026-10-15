"""모델 비교 시험 (TC-MV) — `app/services/model_compare.py` · `app/routes/model_compare.py` (ML·딥러닝 › 모델 비교 · 2026-10-15).

여기서 지키는 것 —
1. 시간 순서 — 시험 겹은 늘 학습 겹 뒤 · 사이에 간격(라벨 기간) · 앞날이 없는 마지막 행은 라벨을 만들지 않음 · 스케일러는 학습 겹에서만.
2. 판정 — 정보 없는 자료(무작위 걸음)에서 「뚜렷」 이 나오지 않고(음성 대조), 신호를 심은 자료에서는 나온다(양성 대조) ·
   기준선 셋 모두와 같은 쪽일 때만 · 시험 행이 적으면 판정하지 않음 · 판정 글은 한 곳 · 홀름은 계절성 서비스와 같은 함수.
3. 사용자 결정(2026-10-15) — 계층 균형 가중을 받을 수 있는 모델 모두에 · 반복 한도(SVM · MLP) · LightGBM 고정 100회 ·
   겹 수 · 간격은 관리자만(403) · 자료는 수집 DB 일봉만(없으면 503 · 종목 없으면 404 · 다른 출처로 넘어가지 않음 · mode=ro).

실제 수집 DB 는 열지 않는다 — 그 밖의 시험은 없는 경로(autouse), 읽기 시험은 임시 SQLite 를 COLLECTOR_DB_PATH 로 가리킨다.
8개 모델을 다 도는 시험은 모듈 고정물(`full_run`) 하나를 나눠 본다(이 PC 약 17초).
"""
from __future__ import annotations

import asyncio
import pathlib
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.services import collector_db
from app.services import model_compare as mc
from app.services import seasonality
from app.services.quant_pipeline import feature_engineer, preprocess

SRC = pathlib.Path(mc.__file__)


@pytest.fixture(autouse=True)
def _no_real_db(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없는-수집DB.sqlite3"))


# ── 합성 자료 ─────────────────────────────────────────────────────

def make_candles(n: int = 500, seed: int = 0, vol: float = 0.02, start: str = "2023-01-02",
                 tail_jump: float = 0.0) -> list[dict]:
    """무작위 걸음 일봉(앞날을 맞힐 정보가 없다). tail_jump 를 주면 마지막 10일을 날마다 그만큼 오르게 한다."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0, vol, n)
    if tail_jump:
        r[-10:] = tail_jump
    close = 50_000 * np.exp(np.cumsum(r))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    volume = rng.integers(100_000, 1_000_000, n)
    days = pd.bdate_range(start, periods=n).tz_localize("Asia/Seoul")   # 장 날짜 00:00 KST
    return [{"time": int(d.timestamp()), "open": float(o), "high": float(h), "low": float(lo),
             "close": float(c), "volume": int(v)}
            for d, o, h, lo, c, v in zip(days, open_, high, low, close, volume)]


def small_models() -> dict:
    """빠른 시험용 두 모델 — 판정 · 누수 규칙은 모델 종류와 상관없다."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    return {"Logistic": lambda: LogisticRegression(max_iter=1000),
            "RF-small": lambda: RandomForestClassifier(n_estimators=30, max_depth=4, random_state=0, n_jobs=1)}


def synthetic_dataset(n: int = 600, seed: int = 1, signal: float = 1.0, imbalance: bool = False) -> mc.Dataset:
    """엔진 시험용 자료 — 라벨이 첫 특징에 달려 있다(signal=0 이면 정보 없음). 기준선 입력은 정보 없는 무작위."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, len(mc.FEATURE_COLS)))
    latent = signal * X[:, 0] + rng.normal(scale=0.5, size=n)
    if imbalance:
        y = np.where(latent > 1.6, 1, np.where(latent < -1.6, -1, 0))     # 관망이 70% 넘게
    else:
        y = np.where(latent > 0.45, 1, np.where(latent < -0.45, -1, 0))
    return mc.Dataset(X=X, y=y.astype(int), dates=[f"d{i:04d}" for i in range(n)], fwd_ret=latent * 0.02,
                      persist=rng.choice([-1, 0, 1], size=n), ma_trend=rng.choice([-1, 1], size=n),
                      horizon=5, threshold=0.02, dropped_tail=5)


@pytest.fixture(scope="module")
def full_run():
    """강사님 8개 모델 전체 · 2년치 무작위 걸음 — 한 번만 돌려 여러 시험이 나눠 본다."""
    t0 = time.perf_counter()
    out = mc.compare_models_v2(make_candles(500, seed=7), symbol="TEST", data_source="synthetic",
                               data_as_of="2024-11-29")
    out["_wall_s"] = time.perf_counter() - t0
    return out


# ── TC-MV-01 · 02 시간 순서 · 간격 ─────────────────────────────────

def test_mv01_test_fold_always_after_train_with_gap(full_run):
    """시험 겹은 늘 학습 겹 뒤 · 그 사이에 정확히 gap 행을 비운다 · 시험 겹끼리 겹치지 않고 이어진다."""
    gap = full_run["cv"]["gap"]
    assert gap == mc.HORIZON
    folds = full_run["cv"]["folds"]
    assert len(folds) == mc.N_SPLITS
    for f in folds:
        assert f["test_start_idx"] - f["train_end_idx"] - 1 == gap
        assert f["train_to"] < f["test_from"]
    for a, b in zip(folds, folds[1:]):
        assert b["train_rows"] > a["train_rows"]                     # 확장 창
        assert a["test_to"] < b["test_from"]


def test_mv02_gap_bounds_are_rejected_with_reason():
    ds = synthetic_dataset()
    with pytest.raises(mc.ModelCompareError) as e:
        mc.make_splits(len(ds.y), 5, gap=ds.horizon - 2, horizon=ds.horizon)
    assert e.value.status == 422 and "간격" in e.value.message
    mc.make_splits(len(ds.y), 5, gap=ds.horizon - 1, horizon=ds.horizon)   # 경계값은 된다
    with pytest.raises(mc.ModelCompareError) as e:
        mc.make_splits(len(ds.y), 5, gap=mc.GAP_MAX + 1, horizon=ds.horizon)
    assert e.value.status == 422
    with pytest.raises(mc.ModelCompareError) as e:
        mc.make_splits(len(ds.y), mc.N_SPLITS_RANGE[1] + 1, gap=ds.horizon, horizon=ds.horizon)
    assert e.value.status == 422 and "겹 수" in e.value.message


# ── TC-MV-03 마지막 행 라벨 ───────────────────────────────────────

def test_mv03_tail_rows_without_future_get_no_label():
    """앞날이 없는 마지막 horizon 행은 뺀다. 강사님 코드는 그 행들을 「관망(0)」 으로 남긴다(재현 — 결함대장 후보)."""
    candles = make_candles(300, seed=3, tail_jump=0.05)                 # 마지막 10일 날마다 +5%
    ds = mc.build_dataset(candles)
    last_known = pd.Timestamp(candles[-1 - mc.HORIZON]["time"], unit="s", tz="UTC").tz_convert("Asia/Seoul")
    assert ds.dates[-1] == last_known.strftime("%Y-%m-%d")
    assert ds.dropped_tail == mc.HORIZON
    assert ds.y[-1] == 1                                                # 앞날이 다 있는 마지막 행은 「오름」
    old = feature_engineer(preprocess(candles))
    assert len(old) == len(ds.y) + mc.HORIZON
    assert (old["target"].iloc[-mc.HORIZON:] == 0).all()                # 강사님: 앞날을 모르는데 「관망」


# ── TC-MV-04 · 05 누수 ────────────────────────────────────────────

def test_mv04_scaler_is_fit_on_train_rows_only():
    """미래(시험 겹부터 끝까지) 자료를 바꿔도 학습 결과(스케일러 · 예측)가 같다. 강사님 방식(전체에 맞춤)은 달라진다."""
    from sklearn.preprocessing import StandardScaler

    ds = mc.build_dataset(make_candles(400, seed=4))
    splits = mc.make_splits(len(ds.y), 5, mc.HORIZON, mc.HORIZON)
    tr, te = splits[1]
    X2 = ds.X.copy()
    X2[te[0]:] *= 100.0
    factory = small_models()["Logistic"]
    a, b = mc.fit_fold(factory, ds.X, ds.y, tr), mc.fit_fold(factory, X2, ds.y, tr)
    np.testing.assert_allclose(a[0].mean_, b[0].mean_)
    np.testing.assert_allclose(a[0].scale_, b[0].scale_)
    np.testing.assert_array_equal(a.predict(ds.X[tr]), b.predict(ds.X[tr]))
    assert not np.allclose(StandardScaler().fit(ds.X).mean_, StandardScaler().fit(X2).mean_)


def test_mv05_future_prices_do_not_change_earlier_folds():
    """둘째 겹 시험 끝 + 라벨 기간 뒤의 가격을 바꿔도 첫째 · 둘째 겹 점수(모델 · 기준선)는 그대로다."""
    candles = make_candles(450, seed=5)
    base = mc.compare_models_v2(candles, models=small_models(), n_boot=200)
    fold2_end = base["cv"]["folds"][1]["test_to"]
    pos = next(i for i, c in enumerate(candles)
               if pd.Timestamp(c["time"], unit="s", tz="UTC").tz_convert("Asia/Seoul").strftime("%Y-%m-%d") == fold2_end)
    cut = pos + mc.HORIZON + 1
    changed = [dict(c, **{k: c[k] * (1.5 if i >= cut else 1.0) for k in ("open", "high", "low", "close")})
               for i, c in enumerate(candles)]
    other = mc.compare_models_v2(changed, models=small_models(), n_boot=200)
    for r_a, r_b in zip(sorted(base["models"] + base["baselines"], key=lambda r: r["key"]),
                        sorted(other["models"] + other["baselines"], key=lambda r: r["key"])):
        assert r_a["fold_scores"][:2] == r_b["fold_scores"][:2], r_a["key"]
    assert any(r_a["fold_scores"][2:] != r_b["fold_scores"][2:]
               for r_a, r_b in zip(base["models"], other["models"]))  # 뒤 겹은 실제로 바뀌었다(시험이 헛돌지 않음)


# ── TC-MV-06 · 07 판정 — 음성 대조 · 양성 대조 ──────────────────────

@pytest.mark.parametrize("seed", [11, 12, 13])
def test_mv06_random_walk_models_do_not_clearly_beat_baseline(seed):
    out = mc.compare_models_v2(make_candles(520, seed=seed), models=small_models())
    assert out["samples"]["judged"] is True
    assert all(r["verdict"] != "better" for r in out["models"]), [(r["key"], r["vs_baselines"]) for r in out["models"]]


def test_mv06b_full_eight_models_on_random_walk(full_run):
    """정보 없는 자료에서는 「뚜렷이 낫다」 도 「뚜렷이 못하다」 도 나오지 않아야 한다(둘 다 거짓 판정)."""
    assert all(r["verdict"] == "no_difference" for r in full_run["models"]), \
        [(r["key"], r["vs_baselines"]) for r in full_run["models"]]
    assert next(r for r in full_run["baselines"] if r["key"] == "random")["role"] == "chance_band"
    assert full_run["strongest_baseline"] in mc.JUDGE_BASELINES


def test_mv07_planted_signal_is_detected():
    """양성 대조 — 라벨이 특징에 달려 있으면 「뚜렷이 나았다」 가 나와야 판정이 늘 「차이 없음」 만 내는 게 아님을 안다."""
    out = mc.evaluate(synthetic_dataset(signal=1.0), models=small_models())
    assert {r["verdict"] for r in out["models"]} == {"better"}
    assert all(c["ci95"][0] > 0 for r in out["models"] for c in r["vs_baselines"])
    assert all(len(r["vs_baselines"]) == len(mc.JUDGE_BASELINES) for r in out["models"])
    noise = mc.evaluate(synthetic_dataset(signal=0.0, seed=2), models=small_models())
    assert all(r["verdict"] != "better" for r in noise["models"])


# ── TC-MV-08 판정 글은 한 곳 · 홀름은 계절성 서비스와 같은 함수 ──────

def test_mv08_verdict_texts_come_from_one_place(full_run):
    for r in full_run["models"]:
        assert r["verdict_text"] == mc.VERDICT_TEXT[r["verdict"]]
    assert full_run["verdict_texts"] == mc.VERDICT_TEXT
    src = SRC.read_text(encoding="utf-8")
    for text in mc.VERDICT_TEXT.values():
        assert src.count(text) == 1, text                               # 같은 글을 다른 곳에 또 적지 않는다
    assert full_run["headline"].startswith("모델 8개")


def test_mv08b_holm_is_the_seasonality_function():
    """홀름 보정은 한 벌 — 모델 비교가 따로 쓰지 않는다(같은 규칙 두 벌 금지)."""
    assert mc.holm is seasonality.holm
    assert "def holm" not in SRC.read_text(encoding="utf-8")


def test_mv08c_holm_is_applied_per_baseline_over_all_models(full_run):
    """판정에 쓴 p 는 기준선마다 모델 8개의 p 를 함께 홀름 보정한 값이다(깨 보기 V6 — 보정을 건너뛰어도 통과하던 빈틈).

    응답의 p 는 소수 넷째 자리로 반올림돼 있어, 반올림한 p 로 다시 보정한 값과 0.001 안에서 같으면 된다.
    """
    for b in mc.JUDGE_BASELINES:
        raw = [next(c for c in m["vs_baselines"] if c["baseline"] == b)["p_two"] for m in full_run["models"]]
        got = [next(c for c in m["vs_baselines"] if c["baseline"] == b)["p_holm"] for m in full_run["models"]]
        want = mc.holm(raw)
        assert all(abs(g - w) <= 1e-3 for g, w in zip(got, want)), (b, got, want)
        assert all(g >= r - 1e-9 for g, r in zip(got, raw))              # 보정한 p 는 원래 p 보다 작지 않다


# ── TC-MV-09 표본이 적으면 판정하지 않음 · 너무 짧으면 거절 ──────────

def test_mv09_small_sample_is_not_judged():
    out = mc.compare_models_v2(make_candles(260, seed=9), models=small_models(), n_boot=200)
    assert out["samples"]["test_rows"] < mc.MIN_JUDGE_ROWS
    assert out["samples"]["judged"] is False
    assert {r["verdict"] for r in out["models"]} == {"insufficient"}
    assert "판정하지 않습니다" in out["headline"]


def test_mv09b_too_short_is_rejected():
    with pytest.raises(mc.ModelCompareError) as e:
        mc.compare_models_v2(make_candles(120, seed=9), models=small_models())
    assert e.value.status == 422
    assert "admin_hint" not in e.value.detail(admin=False)
    assert "admin_hint" in e.value.detail(admin=True)


# ── TC-MV-10 응답 칸 · 모델 수 ────────────────────────────────────

def test_mv10_response_contract(full_run):
    keys = {"contract", "symbol", "data_source", "data_as_of", "period", "target", "features", "primary_metric",
            "cv", "samples", "weighting", "baselines", "strongest_baseline", "models", "headline", "model_count",
            "baseline_count", "skipped", "definitions", "verdict_texts", "verdict_labels", "insights", "limits",
            "notice", "elapsed_ms"}
    assert keys <= set(full_run)
    assert full_run["contract"] == "ml-compare-v2"
    assert full_run["data_source"] == "synthetic" and full_run["data_as_of"] == "2024-11-29"
    assert {r["name"] for r in full_run["models"]} == set(mc.MODEL_NAMES)
    assert full_run["model_count"] == 8 and full_run["baseline_count"] == 4
    assert sum(r["strongest"] for r in full_run["baselines"]) == 1
    for r in full_run["models"] + full_run["baselines"]:
        assert len(r["fold_scores"]) == mc.N_SPLITS
        assert r["fold_min"] <= r["fold_mean"] <= r["fold_max"]
    assert [r["rank"] for r in full_run["models"]] == list(range(1, 9))
    assert full_run["models"][0]["top_group"] is True
    assert len(full_run["limits"]) >= 4 and full_run["notice"]
    assert {"train_score", "weighting"} <= set(full_run["definitions"])


# ── TC-MV-11 같은 입력 → 같은 답 ─────────────────────────────────

def test_mv11_deterministic():
    candles = make_candles(450, seed=21)
    a = mc.compare_models_v2(candles, models=small_models(), n_boot=300)
    b = mc.compare_models_v2(candles, models=small_models(), n_boot=300)
    a.pop("elapsed_ms"), b.pop("elapsed_ms")
    assert a == b


# ── TC-MV-12 정확도의 함정 ───────────────────────────────────────

def test_mv12_majority_baseline_shows_accuracy_trap():
    """관망이 70% 넘는 자료 — 「늘 관망」 은 정확도가 높지만 균형 정확도는 정확히 1/3 이다."""
    out = mc.evaluate(synthetic_dataset(signal=1.0, imbalance=True, seed=3), models=small_models(), n_boot=200)
    maj = next(r for r in out["baselines"] if r["key"] == "majority")
    assert maj["accuracy"] > 0.65
    assert maj["balanced_accuracy"] == pytest.approx(1 / 3, abs=1e-4)


# ── TC-MV-13 평가 엔진은 DB · 네트워크를 쓰지 않는다 ─────────────

def test_mv13_engine_does_not_touch_db_or_network(monkeypatch):
    """읽기는 `read_model_compare` 한 곳 — 엔진(1 ~ 4절)에는 DB · 네트워크 이름이 없고, 다리를 막아도 엔진은 돈다."""
    src = SRC.read_text(encoding="utf-8")
    engine = src.split('"""', 2)[2].split("# 5. 읽기")[0]
    for bad in ("collector_db", "sqlite3", "get_candles", "requests", "httpx", "urllib", "socket", "database"):
        assert bad not in engine, bad

    def boom(*a, **k):
        raise AssertionError("엔진이 수집 DB 를 불렀다")

    monkeypatch.setattr(collector_db, "read_daily_candles", boom)
    monkeypatch.setattr(collector_db, "db_path", boom)
    out = mc.compare_models_v2(make_candles(300, seed=31), models=small_models(), n_boot=100)
    assert out["model_count"] == 2


# ── TC-MV-14 걸린 시간(2년치 · 8개 모델) ─────────────────────────

def test_mv14_runtime_budget(full_run):
    """강사님 화면 안내 「10~30초」 — 같은 범위 안이어야 한다(로컬 CPU · 넉넉히 60초)."""
    assert full_run["elapsed_ms"] < 60_000
    print(f"\n[TC-MV-14] rows={full_run['samples']['rows']} test_rows={full_run['samples']['test_rows']} "
          f"elapsed_ms={full_run['elapsed_ms']} wall_s={full_run['_wall_s']:.1f}")


# ── TC-MV-15 계층 균형 가중 — 받을 수 있는 모델 모두에 같은 방식 ─────

from sklearn.base import BaseEstimator, ClassifierMixin  # noqa: E402


class _Spy(ClassifierMixin, BaseEstimator):
    """fit 이 받은 sample_weight 를 기록하는 가짜 모델(늘 가장 많은 계층을 말한다)."""
    seen: list = []

    def fit(self, X, y, sample_weight=None):
        _Spy.seen.append(None if sample_weight is None else np.asarray(sample_weight, dtype=float))
        vals, cnt = np.unique(y, return_counts=True)
        self.c_ = int(vals[np.argmax(cnt)])
        return self

    def predict(self, X):
        return np.full(len(X), self.c_)


class _NoWeight(_Spy):
    def fit(self, X, y):                                                # sample_weight 를 받지 않는 모델
        return super().fit(X, y)


def test_mv15_balanced_weights_reach_every_model_that_accepts_them(full_run):
    ds = synthetic_dataset(imbalance=True, seed=5)
    tr = np.arange(300)
    _Spy.seen = []
    pipe = mc.fit_fold(lambda: _Spy(), ds.X, ds.y, tr)
    assert pipe.weighted_ is True
    w = _Spy.seen[-1]
    y = ds.y[tr]
    for c in np.unique(y):                                              # 계층 수에 반비례 · 계층마다 무게 합이 같다
        np.testing.assert_allclose(w[y == c], len(y) / (len(np.unique(y)) * np.sum(y == c)))
    assert w.sum() == pytest.approx(len(y))
    # 받지 않는 모델 — 가중 없이 맞추고 경고 칸 · weighting.unweighted 에 적는다(말없이 넘기지 않는다)
    out = mc.evaluate(ds, models={"NoWeight": lambda: _NoWeight(), "Spy": lambda: _Spy()}, n_boot=100)
    rows = {r["key"]: r for r in out["models"]}
    assert out["weighting"] == {"method": "balanced", "unweighted": ["NoWeight"]}
    assert any("가중 없음" in n for n in rows["NoWeight"]["warnings"])
    assert not any("가중 없음" in n for n in rows["Spy"]["warnings"])
    # 강사님 8개는 이 판 sklearn 에서 모두 가중을 받는다(양상블은 안쪽 모델에 그대로 넘긴다)
    assert full_run["weighting"] == {"method": "balanced", "unweighted": []}


def test_mv15b_weighting_changes_the_ensemble_fit():
    """양상블에 넘긴 가중이 실제로 안쪽 모델에 닿는다 — 가중 유무로 예측이 달라진다(헛돌지 않음)."""
    ds = synthetic_dataset(imbalance=True, seed=8)
    tr = np.arange(400)
    factory = mc.default_models()["Ensemble(Voting)"]
    a = mc.fit_fold(factory, ds.X, ds.y, tr, weighted=True)
    b = mc.fit_fold(factory, ds.X, ds.y, tr, weighted=False)
    assert a.weighted_ is True and b.weighted_ is False
    assert (a.predict(ds.X) != b.predict(ds.X)).sum() > 0


# ── TC-MV-16 반복 한도 · LightGBM 고정 횟수 ──────────────────────

def test_mv16_iteration_limits_and_fixed_lightgbm(full_run):
    models = mc.default_models()
    for name in ("LinearSVM", "RBF SVM"):
        assert models[name]().max_iter == mc.SVM_MAX_ITER > 500        # 강사님 값 500 보다 크게
    assert models["MLP"]().max_iter == mc.MLP_MAX_ITER
    inner = dict(models["Ensemble(Voting)"]().estimators)["mlp"]
    assert inner.max_iter == mc.MLP_MAX_ITER > 200                      # 양상블 안 MLP — 강사님 값 200
    if "LightGBM" in models:
        lgbm = models["LightGBM"]()
        assert lgbm.n_estimators == 100                                 # 고정 100회 — 평가 구간으로 멈출 때를 고르지 않음
    for r in full_run["models"]:                                        # 합성 2년치에서는 「덜 학습」 경고가 없다
        assert not any("반복 한도" in n for n in r["warnings"]), (r["key"], r["warnings"])


def test_mv16b_stacking_low_train_score_is_shown_with_reason(full_run):
    """Stacking 학습 점수는 그대로 보이되(사용자 결정) 찍기보다 낮으면 까닭을 붙인다 — 다른 모델에는 붙이지 않는다."""
    st = next(r for r in full_run["models"] if r["key"] == "Ensemble(Stacking)")
    assert st["train_fold_mean"] < 1 / 3                                # 합성 2년치 실측 0.229 — 값은 숨기지 않는다
    assert any("뒤집" in n for n in st["warnings"])
    assert all(not any("뒤집" in n for n in r["warnings"]) for r in full_run["models"] if r is not st)
    assert "거꾸로" in full_run["definitions"]["train_score"]


# ── TC-MV-17 인자 검사 · 관리자 손잡이 ───────────────────────────

def _fake_loaded(code="005930", period="2y", n=500, seed=7):
    candles = make_candles(n, seed=seed)
    return {"code": code, "period": period, "candles": candles, "as_of": "2026-10-13", "from": "2024-10-14",
            "market": "KOSPI", "basis": mc.DATA_BASIS, "fingerprint": mc.data_fingerprint(candles)}


def test_mv17_arguments_and_admin_only_knobs(monkeypatch):
    got = {}

    def fake_compare(candles, **kw):
        got.update(kw)
        return {"ok": True}

    monkeypatch.setattr(mc, "compare_models_v2", fake_compare)
    monkeypatch.setattr(mc, "load_daily", lambda code, period: _fake_loaded(code, period))
    for bad in ("6mo", "10y", ""):
        with pytest.raises(mc.ModelCompareError) as e:
            mc.read_model_compare("005930", bad)
        assert e.value.status == 422 and e.value.code == "bad_period" and "기간" in e.value.message
    for kw in ({"n_splits": 3}, {"gap": 10}):
        with pytest.raises(mc.ModelCompareError) as e:
            mc.read_model_compare("005930", "2y", admin=False, **kw)
        assert e.value.status == 403 and e.value.code == "admin_only" and "관리자" in e.value.message
    for bad in ("5930", "AAPL", "005930.KX", "00593O", "0000D0"):
        with pytest.raises(mc.ModelCompareError) as e:
            mc.read_model_compare(bad, "2y")
        assert e.value.status == 422 and e.value.code == "bad_symbol"
    out = mc.read_model_compare("005930.KQ", "3y", n_splits=4, gap=8, admin=True)
    assert got["n_splits"] == 4 and got["gap"] == 8 and got["symbol"] == "005930"
    assert got["data_source"] == "collector" and got["data_as_of"] == "2026-10-13"
    assert out["data"]["basis"] == mc.DATA_BASIS and out["request"]["period_label"] == "3년"
    assert (out["data"]["label"], out["data"]["attribution"]) == (mc.SOURCE_LABEL, mc.ATTRIBUTION)   # 출처 글은 서버 한 곳
    mc.read_model_compare(" 005930 ", "2y")                             # 일반 사용자 · 기본값
    assert got["n_splits"] == mc.N_SPLITS and got["gap"] is None
    ch = mc.choices()                                                   # 화면이 고르는 값은 서버 한 곳
    assert [p["key"] for p in ch["periods"]] == list(mc.PERIODS)
    assert {p["key"]: p["judged"] for p in ch["periods"]}["1y"] is False
    assert ch["gap"]["min"] == mc.HORIZON - 1 and ch["n_splits"]["max"] == mc.N_SPLITS_RANGE[1]


# ── TC-MV-18 · 19 데이터 관문 — 못 읽음 503 · 없음 404 · ETF 422 · 읽기 전용 · 기준일 기간 창 ──

def _collector_db(path: pathlib.Path, code: str = "005930", days: int = 560, end: date | None = None,
                  etf: str | None = None) -> list[str]:
    """임시 수집 DB(수집기 표 정의) — 주식 한 종목(일봉 · 수정주가 · 시장 칸) · 고르면 ETF 한 종목."""
    from collector import db as CDB

    c = sqlite3.connect(path)
    c.executescript(CDB.SCHEMA)
    end = end or (datetime.now(timezone(timedelta(hours=9))).date() - timedelta(days=1))
    ds: list[date] = []
    d = end
    while len(ds) < days:
        if d.weekday() < 5:
            ds.append(d)
        d -= timedelta(days=1)
    ds.sort()
    rng = np.random.default_rng(1)
    close = 60_000 * np.exp(np.cumsum(rng.normal(0, 0.02, days)))
    rows_d, rows_a = [], []
    for day, px in zip(ds, close):
        k = day.strftime("%Y%m%d")
        hi, lo = px * 1.01, px * 0.99
        rows_d.append((k, code, "KOSPI", int(px), int(px), int(hi), int(lo), 1_000_000))
        rows_a.append((k, code, float(px), float(px), float(hi), float(lo), 1.0))
    c.executemany("INSERT INTO price_daily (bas_dt, srtn_cd, mrkt_ctg, clpr, mkp, hipr, lopr, trqu) VALUES (?,?,?,?,?,?,?,?)", rows_d)
    c.executemany("INSERT INTO price_adjusted (bas_dt, srtn_cd, adj_clpr, adj_mkp, adj_hipr, adj_lopr, cum_factor) "
                  "VALUES (?,?,?,?,?,?,?)", rows_a)
    if etf:
        c.executemany("INSERT INTO etf_daily (bas_dt, srtn_cd, clpr, mkp, hipr, lopr, trqu) VALUES (?,?,?,?,?,?,?)",
                      [(r[0], etf, r[3], r[4], r[5], r[6], r[7]) for r in rows_d])
    c.commit()
    c.close()
    return [x.strftime("%Y-%m-%d") for x in ds]


def test_mv18_unavailable_503_not_found_404_etf_422(tmp_path, monkeypatch):
    with pytest.raises(mc.ModelCompareError) as e:                     # autouse — 없는 경로
        mc.read_model_compare("005930", "2y")
    assert e.value.status == 503 and e.value.code == "db_unavailable" and e.value.message == mc.TEXT_UNAVAILABLE
    assert "admin_hint" not in e.value.detail(False) and "admin_hint" in e.value.detail(True)
    assert "COLLECTOR_DB_PATH" not in e.value.message
    p = tmp_path / "market.sqlite3"
    _collector_db(p, etf="069500")
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    with pytest.raises(mc.ModelCompareError) as e:
        mc.read_model_compare("000660", "2y")
    assert e.value.status == 404 and e.value.code == "symbol_not_found" and "000660" in e.value.message
    assert "ETF" in e.value.message and "admin_hint" not in e.value.detail(False)   # 까닭은 사람 글에
    with pytest.raises(mc.ModelCompareError) as e:
        mc.read_model_compare("069500", "2y")
    assert e.value.status == 422 and e.value.code == "etf_not_supported"
    bad = tmp_path / "broken.sqlite3"
    bad.write_bytes(b"not a sqlite database at all")
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(bad))
    with pytest.raises(mc.ModelCompareError) as e:                     # 읽기 실패는 「없음」 이 아니라 503
        mc.read_model_compare("005930", "2y")
    assert e.value.status == 503 and e.value.code == "db_unavailable"


def test_mv19_reads_through_gateway_read_only_and_reports_source(tmp_path, monkeypatch):
    from app.services import data_ohlcv

    p = tmp_path / "market.sqlite3"
    dates = _collector_db(p)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    monkeypatch.setattr(mc, "default_models", small_models)            # 8개는 TC-MV-10 이 본다 — 여기서는 읽기 길만
    seen, real = [], sqlite3.connect

    def spy(target, *a, **k):
        seen.append(str(target))
        return real(target, *a, **k)

    monkeypatch.setattr(data_ohlcv.sqlite3, "connect", spy)
    out = mc.read_model_compare("005930", "2y")
    assert seen and all("mode=ro" in t for t in seen)                  # 수집 DB 는 읽기 전용으로만
    assert out["data_source"] == "collector" and out["symbol"] == "005930"
    assert out["data_as_of"] == dates[-1] == out["data"]["as_of"]      # 마지막 봉 날짜
    assert out["data"]["basis"] == "adj_base" and len(out["data"]["fingerprint"]) == 64
    assert out["period"]["to"] < dates[-1]                             # 앞날이 없는 마지막 행은 라벨을 만들지 않음
    assert out["samples"]["judged"] is True and out["samples"]["test_rows"] >= mc.MIN_JUDGE_ROWS


def test_mv19b_window_counts_back_from_data_as_of_not_today(tmp_path, monkeypatch):
    """기간 창은 자료 기준일에서 거꾸로 — 오늘이 몇 달 뒤여도 같은 날들(캐시 · 같은 입력이면 같은 답)."""
    p = tmp_path / "market.sqlite3"
    dates = _collector_db(p, days=700, end=date(2026, 6, 30))
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    a = mc.load_daily("005930", "2y", today=date(2026, 7, 1))
    b = mc.load_daily("005930", "2y", today=date(2026, 10, 15))       # 석 달 반 뒤 — 수집이 멈춘 채
    assert a["as_of"] == b["as_of"] == "2026-06-30"
    assert a["from"] == b["from"] >= "2024-06-30" and a["fingerprint"] == b["fingerprint"]
    assert a["from"] < "2024-10-15"                                     # 오늘에서 셌다면 창이 석 달 반 짧았다
    assert dates[0] < a["from"]


# ── TC-MV-20 라우트 — 관리자 여부 · 화면 머리글 · 오류를 상태 코드로 ─────

def test_mv20_routes_admin_flag_screen_header_and_errors(monkeypatch):
    from fastapi import HTTPException, Response
    from starlette.requests import Request

    from app.routes import model_compare as R

    got = {}

    async def fake_compute(symbol, period, n_splits, gap, admin=False):
        got.update(symbol=symbol, period=period, n_splits=n_splits, gap=gap, admin=admin)
        return {"contract": mc.CONTRACT}

    async def fake_start(symbol, period, n_splits, gap, admin=False):
        got.update(start=(symbol, period, n_splits, gap, admin))
        return {"status": "running" if symbol != "cached" else "done", "job_id": "j1"}

    monkeypatch.setattr(R.model_compare_jobs, "compute", fake_compute)
    monkeypatch.setattr(R.model_compare_jobs, "start", fake_start)
    assert asyncio.run(R.model_compare_route(symbol="000660", period="3y", n_splits=4, gap=6,
                                             user={"roles": ["admin"]})) == {"contract": mc.CONTRACT}
    assert got == {"symbol": "000660", "period": "3y", "n_splits": 4, "gap": 6, "admin": True}
    ch = asyncio.run(R.model_compare_choices(user={"roles": []}))
    assert ch["admin"] is False and ch["choices"] == mc.choices() and ch["model_count"] == 8

    def req(headers):
        return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})

    with pytest.raises(HTTPException) as e:                            # 화면 머리글 없음 → 403
        R._require_screen_action(req({}), None)
    assert e.value.status_code == 403 and e.value.detail["code"] == "screen_only"
    with pytest.raises(HTTPException) as e:                            # 다른 사이트 → 403
        R._require_screen_action(req({"Sec-Fetch-Site": "cross-site"}), R.ACTION_VALUE)
    assert e.value.detail["code"] == "cross_site"
    R._require_screen_action(req({"Sec-Fetch-Site": "same-origin"}), R.ACTION_VALUE)
    # 검사 함수가 있어도 라우트에 걸려 있지 않으면 소용없다(깨 보기 V22) — 계산을 띄우는 POST 에만 걸려 있다
    deps = {(next(iter(r.methods)), r.path): {d.call for d in r.dependant.dependencies} for r in R.router.routes}
    assert R._require_screen_action in deps[("POST", "/api/model-compare/jobs")]
    assert all(R._require_screen_action not in calls for (m, _), calls in deps.items() if m == "GET")
    body = R.ModelCompareJobBody(symbol="005930", period="2y")
    resp = Response()
    asyncio.run(R.model_compare_job_start(body, resp, user={"roles": []}, _screen=None))
    assert resp.status_code == 202 and got["start"] == ("005930", "2y", None, None, False)
    resp = Response()
    asyncio.run(R.model_compare_job_start(R.ModelCompareJobBody(symbol="cached"), resp, user={"roles": []}, _screen=None))
    assert resp.status_code == 200

    def boom(*a, **k):
        raise mc.ModelCompareError(404, "작업 없음", "hint", code="job_not_found")

    monkeypatch.setattr(R.model_compare_jobs, "status", boom)
    with pytest.raises(HTTPException) as e:
        asyncio.run(R.model_compare_job_status("x", user={"roles": []}))
    assert e.value.status_code == 404 and e.value.detail == {"code": "job_not_found", "message": "작업 없음"}
    with pytest.raises(HTTPException) as e:
        asyncio.run(R.model_compare_job_status("x", user={"roles": ["admin"]}))
    assert e.value.detail["admin_hint"] == "hint"


# ── TC-MV-21 자료 지문 · 설정 지문 ───────────────────────────────

def test_mv21_fingerprints_change_with_data_and_settings(monkeypatch):
    c = make_candles(300, seed=41)
    fp = mc.data_fingerprint(c)
    assert fp == mc.data_fingerprint([dict(x) for x in c])             # 같은 자료 → 같은 지문
    changed = [dict(x) for x in c]
    changed[10]["close"] = changed[10]["close"] * 0.5                   # 지난날 수정주가가 고쳐짐(분할 · 권리락)
    assert mc.data_fingerprint(changed) != fp
    for field in ("open", "high", "low", "volume"):                     # 칸마다 — 거래량만 고쳐져도(깨 보기 V17) 다른 지문
        one = [dict(x) for x in c]
        one[10][field] = one[10][field] + (1000 if field == "volume" else 1.0)
        assert mc.data_fingerprint(one) != fp, field
    shifted = [dict(x) for x in c]
    shifted[10]["time"] += 86400                                        # 날짜가 바뀌어도
    assert mc.data_fingerprint(shifted) != fp
    k = mc.cache_key("005930", "2y", 5, None)
    assert k.startswith("model_compare:v1:005930:2y:")
    assert k != mc.cache_key("005930", "2y", 4, None) != mc.cache_key("005930", "2y", 5, 8)
    assert k != mc.cache_key("005930", "3y", 5, None) != mc.cache_key("000660", "2y", 5, None)
    monkeypatch.setattr(mc, "MLP_MAX_ITER", mc.MLP_MAX_ITER + 1)       # 모델 설정이 바뀌면 옛 결과를 쓰지 않는다
    k2 = mc.cache_key("005930", "2y", 5, None)
    assert k2 != k
    monkeypatch.setattr(mc, "RESULT_VERSION", mc.RESULT_VERSION + 1)   # 응답 꼴이 바뀌면 옛 꼴 저장본을 쓰지 않는다(화면 확인에서 찾음)
    assert mc.cache_key("005930", "2y", 5, None) not in (k, k2)


# ── TC-MV-22 작업 · 진행 · 결과 캐시 · 같은 열쇠 한 번만 ─────────────

@pytest.fixture()
def jobs(monkeypatch):
    from app.services import model_compare_jobs as mj

    mj.reset_for_tests()
    store: dict = {}

    async def fake_get(key, max_age_hours=24):
        return store.get(key)

    async def fake_set(key, data):
        store[key] = data

    monkeypatch.setattr(mj, "cache_get", fake_get)
    monkeypatch.setattr(mj, "cache_set", fake_set)
    monkeypatch.setattr(mc, "default_models", small_models)
    monkeypatch.setattr(mc, "load_daily", lambda code, period: _fake_loaded(code, period, n=450, seed=22))
    yield mj, store
    mj.reset_for_tests()


def test_mv22_job_progress_then_result_then_cache(jobs):
    mj, store = jobs

    async def run():
        first = await mj.start("005930", "2y")
        assert first["status"] in ("queued", "running") and first["job_id"] and first["cached"] is False
        assert first["expected_basis"] == "typical" and first["expected_ms"] == mc.PERIOD_SPEC["2y"]["expected_ms"]
        again = await mj.start("005930", "2y")                          # 같은 열쇠 — 새로 띄우지 않고 붙는다
        assert again["job_id"] == first["job_id"]
        seen = []
        for _ in range(600):
            st = mj.status(first["job_id"])
            seen.append(st["progress"].get("stage"))
            if st["status"] == "done":
                break
            await asyncio.sleep(0.02)
        assert st["status"] == "done" and st["result"]["contract"] == mc.CONTRACT and st["result"]["cached"] is False
        assert st["result"]["computed_at"]
        key = mc.cache_key("005930", "2y", mc.N_SPLITS, None)
        assert store[key]["fingerprint"] == _fake_loaded(n=450, seed=22)["fingerprint"]
        hit = await mj.start("005930", "2y")                            # 저장본 — 계산 없이 곧바로
        assert hit["status"] == "done" and hit["cached"] is True and hit["result"]["cached"] is True
        assert mj.expected_ms("2y")["expected_basis"] == "last"         # 다음엔 지난 계산 시간이 「보통」 의 근거
        return seen

    seen = asyncio.run(run())
    assert "models" in seen or "judging" in seen


def test_mv22b_stale_cache_with_other_fingerprint_is_recomputed(jobs, monkeypatch):
    mj, store = jobs
    key = mc.cache_key("005930", "2y", mc.N_SPLITS, None)
    store[key] = {"fingerprint": "옛-지문", "result": {"contract": mc.CONTRACT, "old": True}}

    async def run():
        got = await mj.start("005930", "2y")
        assert got["status"] != "done"                                  # 지문이 다르면 저장본을 주지 않는다
        await asyncio.shield(mj._jobs[got["job_id"]].task)
        return mj.status(got["job_id"])

    st = asyncio.run(run())
    assert st["status"] == "done" and "old" not in st["result"]
    assert store[key]["fingerprint"] != "옛-지문"


def test_mv22c_errors_job_not_found_and_compute_failure(jobs, monkeypatch):
    mj, _ = jobs
    with pytest.raises(mc.ModelCompareError) as e:
        mj.status("없는-작업")
    assert e.value.status == 404 and e.value.code == "job_not_found"

    def broken(*a, **k):
        raise RuntimeError("엔진 고장")

    monkeypatch.setattr(mc, "compute_loaded", broken)

    async def run():
        got = await mj.start("005930", "2y")
        await asyncio.shield(mj._jobs[got["job_id"]].task)
        return got["job_id"]

    jid = asyncio.run(run())
    with pytest.raises(mc.ModelCompareError) as e:
        mj.status(jid)
    assert e.value.status == 500 and e.value.code == "compute_failed"
    assert "RuntimeError" in e.value.detail(True)["admin_hint"] and "admin_hint" not in e.value.detail(False)


def test_mv22d_sync_compute_uses_same_job_and_cache(jobs):
    mj, store = jobs
    out = asyncio.run(mj.compute("005930", "2y"))
    assert out["contract"] == mc.CONTRACT and out["cached"] is False
    out2 = asyncio.run(mj.compute("005930", "2y"))
    assert out2["cached"] is True and len(store) == 1


# ── TC-MV-23 진행은 실제로 센 값 ─────────────────────────────────

def test_mv23_progress_reports_real_counts():
    info = []
    mc.evaluate(synthetic_dataset(), models=small_models(), n_boot=100, progress=info.append)
    stages = [i["stage"] for i in info]
    assert stages[0] == "baselines" and stages[-1] == "judging"
    fits = [i for i in info if i["stage"] == "models"]
    assert len(fits) == 2 * mc.N_SPLITS                                 # 모델 2 × 겹 5 — 한 번씩
    assert [(i["model_index"], i["fold"]) for i in fits] == [(m, f) for m in (1, 2) for f in range(1, mc.N_SPLITS + 1)]
    assert all(i["model_count"] == 2 and i["folds"] == mc.N_SPLITS and i["test_from"] <= i["test_to"] for i in fits)


# ── TC-MV-24 「왜」 세 줄 · 짧은 이름표 · 종목 제안은 서버 한 곳 ─────────

def test_mv24_insights_labels_and_suggest_come_from_server(full_run):
    from app.services.stock import QUANT_STOCKS

    assert [i["key"] for i in full_run["insights"]] == ["accuracy_trap", "memorize", "chance_band"]
    base = {b["key"]: b for b in full_run["baselines"]}
    trap, mem, band = full_run["insights"]
    assert [b["value"] for b in trap["bars"]] == [base["majority"]["accuracy"], base["majority"]["balanced_accuracy"]]
    best = max((m for m in full_run["models"] if m["key"] != "Ensemble(Stacking)"),
               key=lambda r: r["train_fold_mean"] - r["balanced_accuracy"])
    assert mem["text"].startswith(best["name"]) and "Stacking" not in mem["text"]   # 학습 점수의 뜻이 다른 모델은 뺀다
    assert [b["value"] for b in band["bars"]] == [base["random"]["fold_min"], base["random"]["fold_max"]]
    assert full_run["verdict_labels"] == mc.VERDICT_LABEL and set(mc.VERDICT_LABEL) == set(mc.VERDICT_TEXT)
    ch = mc.choices()
    assert {"code": "005930", "name": "삼성전자"} in ch["suggest"] and len(ch["suggest"]) == len(QUANT_STOCKS)
