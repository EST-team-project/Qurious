"""모델 비교 — 시간 순서를 지킨 정직한 평가 (화면 키 `ml-compare` · ML·딥러닝 › 모델 비교 · 2026-10-15)

왜 새로 쓰나 — 강사님 `app/services/ml_models.py` 의 `compare_models` 를 코드 줄로 읽어 찾은 문제
---------------------------------------------------------------------------------------------
① `cross_val_score(cv=5)` — 분류기라 `StratifiedKFold`(섞지 않음)가 되어 **시험 겹보다 뒤(미래) 자료로 학습**한다.
② 스케일러를 앞 80% 에 맞춘 뒤 전체에 적용해 교차검증에 넘긴다 — 앞 80% 안의 시험 겹이 스케일러에 들어간다.
③ LightGBM 만 뒤 20% 로 조기 종료와 평가를 함께 하고 표준편차를 0 으로 둔다 — 다른 잣대로 같은 순위표에 선다.
④ 라벨(5거래일 뒤 수익률)이 이웃 행끼리 4일씩 겹치는데 학습 · 시험 사이 간격이 없고, 앞날이 없는 마지막 5행이
   「관망」 라벨로 남는다(`quant_pipeline.feature_engineer` 가 `target` 을 0 으로 먼저 채워 `dropna()` 에 안 걸림).
⑤ 기준선이 없고 정확도 하나로 1등을 고른다 — 모델 8개를 한꺼번에 견주는 다중 비교를 거르지 않는다.
⑥ 메뉴 이름표는 「7종」 인데 모델은 8개다(Stacking 이 부제에서 빠짐).
강사님 길(`GET /api/ml/compare`)은 강사님 코드라 그대로 두고, 화면만 이 서비스의 새 길(`GET /api/model-compare`)로 옮긴다
(계절성 · 종목 군집화와 같은 꼴 — 다음 기초 코드 반영 때 충돌이 없다).

여기서는 (2026-10-15 사용자 결정 — 결정 대장 부록 C)
--------------------------------------------------
- 특징 12개 · 모델 8개는 강사님 것. 라벨은 앞날 `horizon` 거래일이 다 있는 행만 만든다 — 마지막 `horizon` 행은 뺀다(`dropped_tail`).
  강사님 `feature_engineer` 의 `target` 칸은 쓰지 않는다(④ — 같은 함수를 쓰는 다른 화면은 결함대장 · 주담당 이슈로).
- 겹은 `TimeSeriesSplit(n_splits, gap)` — 학습은 늘 시험 앞 · 간격 기본 = 라벨 기간. 간격이 라벨 기간 − 1 보다 작으면
  거절한다(말없이 고치지 않는다). 겹 수 · 간격은 **관리자만** 바꾼다(일반 사용자는 종목 · 기간만 — 고르는 손잡이가 많으면
  같은 자료로 좋아 보이는 것만 고르는 데이터 스누핑).
- 겹마다 `Pipeline(StandardScaler, 모델)` 을 **학습 겹에서만** 맞춘다.
- **계층 균형 가중** — 학습 겹마다 계층(오름 · 관망 · 내림) 수에 반비례하는 표본 가중을 **받을 수 있는 모델 모두**에 같은 방식으로
  준다(한 모델에만 주면 그 모델만 균형 정확도에서 유리해져 비교가 기울어진다). 못 받는 모델은 응답 경고 칸에 「가중 없음」.
- **반복 한도를 늘린다** — 강사님 값(SVM 500 · 양상블 안 MLP 200)에서는 다 배우기 전에 멈춰 덜 학습된 채 순위에 섰다.
- LightGBM 은 **고정 100회**(평가 구간으로 멈출 때를 고르지 않는다) · 같은 겹 · 같은 파이프라인을 탄다.
- 기준선 넷을 같은 겹 · 같은 행에서 함께 계산한다 — 늘 같은 답 · 지난 흐름 그대로 · 이동 평균 위아래 · 무작위.
- 대표 지표 = **균형 정확도**(계층마다 맞힌 비율의 평균 · 3계층이면 「늘 같은 답」 이 1/3).
- 「낫다 · 못하다」 = 모든 시험 행을 합쳐 **기준선 셋(무작위 제외)과 각각 같은 행으로 짝지어** 균형 정확도 차이를 보고,
  이웃 행이 겹치는 만큼 **20거래일 블록으로 다시 뽑아(블록 부트스트랩)** 95% 구간과 p 값을 낸 뒤 기준선마다 모델 수만큼
  **홀름 보정**하고, **셋 모두** 같은 쪽으로 뚜렷할 때만 판정한다. 일부 기준선과만 다르면 「차이 없음」 + 기준선별 차이는 응답에.
- 시험 행이 `MIN_JUDGE_ROWS` 보다 적으면(1년 자료) 계산은 하되 판정하지 않는다(「판정 안 함」 · 까닭 문장).
- 판정 글 · 한계 문장 · 정의 글은 이 파일 한 곳에서 만든다 — 화면은 다시 계산하지 않고 응답 글을 그대로 보인다.
- 자료는 **수집 DB 일봉(수정주가)만** 읽는다(`read_model_compare`) — 없으면 다른 출처로 말없이 넘어가지 않고 503 · 404 로 까닭을 알린다.

근거(원문 · 조회일 · 확실도)와 모의실험(무작위 걸음 60종 거짓 판정률 · 검정력)은 조사서 `docs/phase-2/01-analysis/research/모델비교-시간순서평가-조사.md`.
평가 엔진(`compare_models_v2` · `evaluate`)은 DB · 네트워크를 쓰지 않는 순수 계산이다 — 읽기는 `read_model_compare` 한 곳.
"""
from __future__ import annotations

import math
import time
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from app.services.quant_pipeline import FEATURE_COLS, feature_engineer, preprocess
from app.services.seasonality import holm

CONTRACT = "ml-compare-v2"
HORIZON = 5            # 라벨 기간(거래일) — 강사님 `feature_engineer` 와 같다
THRESHOLD = 0.02       # 라벨 문턱(±2%) — 강사님과 같다
N_SPLITS = 5
MAX_HORIZON = 20       # 지속 기준선이 특징 창(20일) 안에서 계산되도록
MIN_ROWS = 120         # 라벨까지 만든 행이 이보다 적으면 계산하지 않는다(422)
#: 첫 학습 겹이 이보다 짧으면 계산하지 않는다(422). 5겹이면 첫 학습 ≈ 행 ÷ 6 − 간격이라 60 으로 두면 1년 자료가
#: 「판정 안 함」 에 닿기 전에 거절된다 — 1년 자료도 겹별 점수는 보여 주고 판정만 미루려고 30.
MIN_TRAIN_ROWS = 30
MIN_FOLD_TEST = 20     # 시험 겹 하나가 이보다 짧으면 계산하지 않는다(422)
#: 시험 행을 모두 합쳐 이보다 적으면 판정하지 않는다. 5일 라벨이 겹쳐 서로 겹치지 않는 창은 대략 행 ÷ 5 개 —
#: 200행이면 약 40개. 2년 자료(약 465행 → 시험 약 385행)는 판정하고, 1년 자료(시험 약 190행)는 판정하지 않는다.
MIN_JUDGE_ROWS = 200
ALPHA = 0.05
N_BOOT = 1000
SEED = 42
CLASSES = (-1, 0, 1)
#: 화면이 고르는 기간 — 수집 시작이 2020-01-02 라 5년까지 꽉 찬다. 1년은 계산만 하고 판정하지 않는다.
PERIODS = ("1y", "2y", "3y", "5y")
#: 겹 수 · 간격을 바꿀 수 있는 범위(관리자만) — 간격 위 끝은 한 달 남짓(라벨 기간의 네 배를 넉넉히 넘김)
N_SPLITS_RANGE = (2, 10)
GAP_MAX = 30
#: 반복 한도 — 강사님 값(SVM 500 · MLP 300 · 양상블 안 MLP 200)에서는 수렴 전에 멈춘다는 경고가 겹마다 났다
#: (합성 2년 실측: LinearSVM 1겹 · Voting 5겹 모두 — Voting 의 경고는 안쪽 MLP(조기 종료 없음)에서 난다).
#: 안쪽 MLP 는 1,000 에서 5겹 · 3,000 에서 1겹 · 6,000 에서 0 이고 3,000 과 6,000 의 시간 차는 0.1초였다 —
#: 조기 종료가 있는 단독 MLP 는 한도에 닿기 전에 멈추므로 같은 값을 써도 시간이 늘지 않는다.
SVM_MAX_ITER = 20_000
MLP_MAX_ITER = 6_000

#: 판정 네 갈래의 화면 글 — 판정 글은 이 사전 한 곳에서만 나온다(TC-MV-08)
VERDICT_TEXT = {
    "better": "기준선 셋 모두보다 뚜렷이 나았습니다",
    "worse": "기준선 셋 모두보다 뚜렷이 못했습니다",
    "no_difference": "기준선과 뚜렷한 차이가 없습니다",
    "insufficient": "시험 자료가 적어 판정하지 않습니다",
}
#: 화면 배지에 쓰는 짧은 이름표 — 판정 글(`VERDICT_TEXT`)과 같은 갈래 · 이 사전 한 곳에서만
VERDICT_LABEL = {"better": "뚜렷이 나음", "worse": "뚜렷이 못함", "no_difference": "차이 없음", "insufficient": "판정 안 함"}
BASELINE_NAMES = {
    "majority": "늘 같은 답",
    "persistence": "지난 흐름 그대로",
    "ma_trend": "이동 평균 위아래",
    "random": "무작위",
}
#: 판정의 잣대가 되는 기준선 셋 — 무작위는 뺀다(기대값이 늘 1/3 이라 「우연 띠」 로만 보인다).
#: 판정은 「셋 **모두**보다 뚜렷이 나아야 낫다」(교집합-합집합 검정)로 한다. 시험 자료로 셋 중 「가장 강한 것」 을 골라
#: 견주면 그 최댓값이 위로 치우쳐 정보 없는 자료에서도 모델이 「뚜렷이 못함」 으로 나온다 — 무작위 걸음 60종 모의실험에서
#: 가족 단위 거짓 판정 8 ~ 15%(목표 5%) · 셋 모두 규칙은 블록 20 에서 0%(조사서 <표 7>).
#: 「가장 강한 기준선」(`strongest_baseline`)은 화면 설명용으로만 남긴다.
JUDGE_BASELINES = ("majority", "persistence", "ma_trend")
#: 블록 부트스트랩의 블록 길이 하한(거래일). 라벨 겹침(5일)만이 아니라 예측도 이동 평균 · RSI 같은 느린 특징을 따라
#: 몇 주씩 같은 답을 내므로 짧은 블록은 분산을 낮게 잡는다. 무작위 걸음 60종 · 기준선 하나와 비교(홀름 뒤) 실측 —
#: 블록 10 → 거짓 판정 11.7% · 20 → 6.7% · 40 → 20% · 60 → 21.7%(블록이 길면 시험 400행에 덩어리가 너무 적다).
#: 목표 5% 에 가장 가까운 20(씨앗 60개라 ±3%p 쯤 흔들린다).
BLOCK_MIN = 20
#: 강사님 화면이 견주던 모델 8개 — 응답 `model_count` 가 화면 이름표 대신 이 수를 알린다(이름표에 숫자를 적지 않는다).
MODEL_NAMES = ("LinearSVM", "RBF SVM", "RandomForest", "GradientBoosting", "MLP",
               "Ensemble(Voting)", "Ensemble(Stacking)", "LightGBM")
NOTICE = "과거 성과는 앞으로의 수익을 보장하지 않습니다. 투자 권유가 아닙니다."
DATA_SOURCE = "collector"
#: 출처 표시 — 계절성 · 군집화(`ATTRIBUTION`)와 같은 꼴. 화면은 이 글을 그대로 쓴다(화면 코드에 출처 글을 적지 않는다 · TC-MVS-02).
SOURCE_LABEL = "우리 수집 일봉(수정주가)"
#: 수정 방식은 collector/preprocess.py — 분할 · 병합 · 권리락 날의 기준가(종가 − 전일대비)로 조정계수를 구해 이어 붙인 가격 계열(배당 제외 · db.py:23).
ATTRIBUTION = "공공데이터포털 주식시세정보(금융위원회) · 수정주가는 분할 · 병합 · 권리락 날의 기준가로 우리 수집기가 이어 붙임(배당 제외)"


class ModelCompareError(Exception):
    """상태 코드 + 갈래 이름(`code` — 화면이 다음 행동 단추를 고른다) + 사람에게 보일 글 + 관리자에게만 줄 할 일."""

    def __init__(self, status: int, message: str, hint: str = "", code: str = "invalid"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.hint = hint
        self.code = code

    def detail(self, admin: bool) -> Dict:
        out: Dict = {"code": self.code, "message": self.message}
        if admin and self.hint:
            out["admin_hint"] = self.hint
        return out


# ══════════════════════════════════════════════════════════════════
# 1. 자료 — 강사님 특징 12개 + 앞날이 다 있는 행만 라벨
# ══════════════════════════════════════════════════════════════════

@dataclass
class Dataset:
    X: np.ndarray            # (n, 12) 특징 — 그날까지의 값만 본다
    y: np.ndarray            # (n,) 라벨 −1 · 0 · 1
    dates: List[str]         # 'YYYY-MM-DD' (KST)
    fwd_ret: np.ndarray      # (n,) 앞날 horizon 거래일 수익률 — 라벨의 원천(방향 적중에만 씀)
    persist: np.ndarray      # (n,) 지속 기준선 예측 = 직전 horizon 거래일 수익률의 라벨
    ma_trend: np.ndarray     # (n,) 이동 평균 기준선 예측 = 종가가 20일 평균 위면 1 · 아니면 −1
    horizon: int
    threshold: float
    dropped_tail: int        # 앞날이 없어 라벨을 만들지 않은 마지막 행 수
    feature_names: Tuple[str, ...] = tuple(FEATURE_COLS)


def label(r: np.ndarray, threshold: float) -> np.ndarray:
    """수익률 → 3계층(1 = 문턱 초과 · −1 = −문턱 미만 · 0 = 그 사이). 강사님 규칙과 같다."""
    r = np.asarray(r, dtype=float)
    out = np.zeros(len(r), dtype=int)
    out[r > threshold] = 1
    out[r < -threshold] = -1
    return out


def build_dataset(candles: List[Dict], horizon: int = HORIZON, threshold: float = THRESHOLD) -> Dataset:
    if not 1 <= horizon <= MAX_HORIZON:
        raise ModelCompareError(422, f"라벨 기간은 1 ~ {MAX_HORIZON} 거래일입니다", code="bad_target")
    if not 0 < threshold < 0.5:
        raise ModelCompareError(422, "라벨 문턱은 0 보다 크고 50% 보다 작아야 합니다", code="bad_target")
    if not candles:
        raise ModelCompareError(404, "시세 자료가 없습니다", code="no_data")
    df = preprocess(candles)
    feat = feature_engineer(df)          # 강사님 특징 — `target` 칸은 쓰지 않는다(마지막 행 오류 · 머리말 ④)
    close = df["close"].astype(float)
    fwd = (close.shift(-horizon) / close - 1).reindex(feat.index)
    past = (close / close.shift(horizon) - 1).reindex(feat.index)
    known = fwd.notna() & past.notna()
    dropped_tail = int(fwd.isna().sum())
    feat, fwd, past = feat[known], fwd[known], past[known]
    if len(feat) < MIN_ROWS:
        raise ModelCompareError(422, f"자료가 짧습니다 — 라벨까지 만든 행 {len(feat)}개(최소 {MIN_ROWS}개)",
                                hint="기간을 늘린다(2y 이상)", code="too_short")
    dates = [d.strftime("%Y-%m-%d") for d in feat.index.tz_convert("Asia/Seoul")]
    return Dataset(
        X=feat[list(FEATURE_COLS)].to_numpy(dtype=float),
        y=label(fwd.to_numpy(), threshold),
        dates=dates,
        fwd_ret=fwd.to_numpy(dtype=float),
        persist=label(past.to_numpy(), threshold),
        ma_trend=np.where(feat["ma20_ratio"].to_numpy(dtype=float) > 1.0, 1, -1),
        horizon=horizon, threshold=threshold, dropped_tail=dropped_tail,
    )


# ══════════════════════════════════════════════════════════════════
# 2. 겹 나누기 · 모델 · 학습(학습 겹에서만 · 계층 균형 가중)
# ══════════════════════════════════════════════════════════════════

def make_splits(n: int, n_splits: int, gap: int, horizon: int) -> List[Tuple[np.ndarray, np.ndarray]]:
    from sklearn.model_selection import TimeSeriesSplit

    lo, hi = N_SPLITS_RANGE
    if not lo <= n_splits <= hi:
        raise ModelCompareError(422, f"겹 수는 {lo} ~ {hi} 입니다", code="bad_splits")
    if gap < horizon - 1:
        # 학습 끝 행의 라벨 창(앞날 horizon 일)이 시험 첫 행의 라벨 창과 겹친다 — 정답이 샌다
        raise ModelCompareError(422, f"간격(gap)은 라벨 기간 − 1({horizon - 1}) 이상이어야 합니다 — "
                                     f"작으면 학습 끝 라벨이 시험 구간 가격을 봅니다", code="bad_gap")
    if gap > GAP_MAX:
        raise ModelCompareError(422, f"간격(gap)은 {GAP_MAX} 거래일 이하입니다", code="bad_gap")
    test_size = n // (n_splits + 1)
    first_train = n - gap - test_size * n_splits
    if test_size < MIN_FOLD_TEST or first_train < MIN_TRAIN_ROWS:
        raise ModelCompareError(422, f"자료가 짧아 {n_splits}겹으로 나눌 수 없습니다 — 시험 겹 {test_size}행 · "
                                     f"첫 학습 {first_train}행(최소 {MIN_FOLD_TEST} · {MIN_TRAIN_ROWS})",
                                hint="기간을 늘리거나 겹 수를 줄인다", code="too_short")
    return list(TimeSeriesSplit(n_splits=n_splits, gap=gap, test_size=test_size).split(np.arange(n)))


ModelFactory = Callable[[], object]


def default_models() -> Dict[str, ModelFactory]:
    """강사님 `compare_models` 의 8개 — 이름 · 구조 그대로. 바뀐 곳만 적는다.

    - SVM 둘 `max_iter` 500 → `SVM_MAX_ITER` · MLP 300 · 양상블 안 MLP 200 → `MLP_MAX_ITER` — 다 배우기 전에 멈추지 않게.
    - RandomForest `n_jobs=-1 → 1`: 겹 안에서 프로세스를 띄우지 않는다(결과 같음).
    - LightGBM: `lgb.train` + 뒤 20% 조기 종료 → `LGBMClassifier(n_estimators=100)` 고정 — 평가 구간으로 멈출 때를
      고르지 않으려고. 같은 겹 · 같은 파이프라인을 탄다.
    - 계층 균형 가중은 모델 설정이 아니라 `fit_fold` 가 표본 가중으로 준다(모든 모델에 같은 방식).
    """
    from sklearn.ensemble import (GradientBoostingClassifier, RandomForestClassifier, StackingClassifier,
                                  VotingClassifier)
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier
    from sklearn.svm import SVC

    models: Dict[str, ModelFactory] = {
        "LinearSVM": lambda: SVC(kernel="linear", C=0.1, random_state=42, max_iter=SVM_MAX_ITER),
        "RBF SVM": lambda: SVC(kernel="rbf", C=1.0, random_state=42, max_iter=SVM_MAX_ITER),
        "RandomForest": lambda: RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=1),
        "GradientBoosting": lambda: GradientBoostingClassifier(n_estimators=100, random_state=42),
        "MLP": lambda: MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=MLP_MAX_ITER, early_stopping=True,
                                     random_state=42, verbose=False),
        "Ensemble(Voting)": lambda: VotingClassifier(estimators=[
            ("rf", RandomForestClassifier(n_estimators=50, random_state=42)),
            ("gb", GradientBoostingClassifier(n_estimators=50, random_state=42)),
            ("mlp", MLPClassifier(hidden_layer_sizes=(32,), max_iter=MLP_MAX_ITER, random_state=42, verbose=False)),
        ], voting="hard"),
        # 안쪽 cv=3 은 학습 겹 안에서만 나눈다 — 시험 겹은 보지 않으므로 바깥 평가는 정직하다
        # (TimeSeriesSplit 은 cross_val_predict 가 모든 행을 예측하지 못해 Stacking 안쪽에 쓸 수 없다)
        "Ensemble(Stacking)": lambda: StackingClassifier(estimators=[
            ("rf", RandomForestClassifier(n_estimators=50, random_state=42)),
            ("gb", GradientBoostingClassifier(n_estimators=50, random_state=42)),
        ], final_estimator=LogisticRegression(max_iter=1000), cv=3),
    }
    try:
        from lightgbm import LGBMClassifier
        models["LightGBM"] = lambda: LGBMClassifier(n_estimators=100, learning_rate=0.05, num_leaves=31,
                                                    colsample_bytree=0.8, random_state=42, verbose=-1, n_jobs=1)
    except ImportError:  # 설치가 안 된 곳 — 응답 `skipped` 에 까닭을 싣는다
        pass
    return models


def balanced_weights(y: np.ndarray) -> np.ndarray:
    """계층 수에 반비례하는 표본 가중(sklearn `class_weight="balanced"` 와 같은 값) — 합은 표본 수."""
    from sklearn.utils.class_weight import compute_sample_weight

    return compute_sample_weight("balanced", y)


def fit_fold(factory: ModelFactory, X: np.ndarray, y: np.ndarray, train_idx: np.ndarray, weighted: bool = True):
    """학습 겹 행만으로 스케일러 + 모델을 맞춘다(누수 시험 TC-MV-04 가 직접 부른다).

    `weighted` 면 학습 겹 라벨로 만든 계층 균형 가중을 마지막 단계(모델)에 `단계이름__sample_weight` 로 넘긴다 —
    양상블(Voting · Stacking)은 받은 가중을 안쪽 모델에 그대로 넘긴다. 가중을 받지 않는 모델이면 가중 없이 맞추고
    돌려준 파이프라인의 `weighted_` 를 False 로 둔다(응답 경고 칸 「가중 없음」 — 말없이 넘기지 않는다).
    """
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    Xt, yt = X[train_idx], y[train_idx]
    if weighted:
        pipe = make_pipeline(StandardScaler(), factory())
        try:
            pipe.fit(Xt, yt, **{f"{pipe.steps[-1][0]}__sample_weight": balanced_weights(yt)})
            pipe.weighted_ = True
            return pipe
        except TypeError:   # fit 이 sample_weight 를 받지 않는다(옛 판 등) — 아래에서 가중 없이 다시
            pass
    pipe = make_pipeline(StandardScaler(), factory())
    pipe.fit(Xt, yt)
    pipe.weighted_ = False
    return pipe


# ══════════════════════════════════════════════════════════════════
# 3. 지표 · 블록 부트스트랩 · 판정 — 지표 정의는 이 한 곳 · 홀름은 계절성 서비스와 같은 함수 하나
# ══════════════════════════════════════════════════════════════════

def balanced_accuracy(y: np.ndarray, p: np.ndarray) -> float:
    """계층마다 맞힌 비율(재현율)의 평균 — 시험 구간에 나온 계층만 센다."""
    rec = [float(np.mean(p[y == c] == c)) for c in CLASSES if np.any(y == c)]
    return float(np.mean(rec)) if rec else float("nan")


def accuracy(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(y == p))


def direction(y_fwd: np.ndarray, p: np.ndarray) -> Tuple[Optional[float], float]:
    """(방향 적중률, 신호 비율) — 오름 · 내림이라 말한 날만 앞날 수익률 부호와 견준다. 「관망」 은 세지 않는다."""
    m = p != 0
    cover = float(np.mean(m))
    if not m.any():
        return None, cover
    return float(np.mean(np.sign(y_fwd[m]) == p[m])), cover


def block_indices(n: int, block: int, n_boot: int, seed: int) -> np.ndarray:
    """이동 블록 부트스트랩 행 번호 (n_boot, n) — 이웃 행이 겹치는 라벨이라 행을 하나씩 뽑지 않고 덩어리로 뽑는다."""
    rng = np.random.default_rng(seed)
    block = max(1, min(block, n))
    n_blocks = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(n_boot, n_blocks))
    return (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[:, :n]


def _boot_ba(y: np.ndarray, correct: np.ndarray, idx: np.ndarray) -> np.ndarray:
    yb, cb = y[idx], correct[idx]
    rec = []
    for c in CLASSES:
        m = yb == c
        cnt = m.sum(axis=1)
        hit = (cb & m).sum(axis=1)
        rec.append(np.where(cnt > 0, hit / np.maximum(cnt, 1), np.nan))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(np.vstack(rec), axis=0)


def paired(y: np.ndarray, pa: np.ndarray, pb: np.ndarray, idx: np.ndarray) -> Dict:
    """a − b 균형 정확도 차이 · 95% 구간 · 양쪽 p(부트스트랩 근사) — 같은 행 번호로 짝지어 다시 뽑는다."""
    diff = balanced_accuracy(y, pa) - balanced_accuracy(y, pb)
    boots = _boot_ba(y, pa == y, idx) - _boot_ba(y, pb == y, idx)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    b = len(boots)
    p_better = (1 + int(np.sum(boots <= 0))) / (b + 1)
    p_worse = (1 + int(np.sum(boots >= 0))) / (b + 1)
    return {"diff": diff, "ci95": [float(lo), float(hi)], "p_two": min(1.0, 2 * min(p_better, p_worse))}


def verdict(n_test: int, comps: List[Dict]) -> str:
    """판정 갈래 — 기준선 셋과의 비교(`diff` · `p_holm`) **모두**가 같은 쪽으로 뚜렷할 때만. 글은 `VERDICT_TEXT` 에서만."""
    if n_test < MIN_JUDGE_ROWS or any(c["p_holm"] is None for c in comps):
        return "insufficient"
    if all(c["p_holm"] < ALPHA and c["diff"] > 0 for c in comps):
        return "better"
    if all(c["p_holm"] < ALPHA and c["diff"] < 0 for c in comps):
        return "worse"
    return "no_difference"


def headline(verdicts: List[str], strongest: str, n_test: int) -> str:
    """응답 맨 위 한 문장 — 판정 글(`VERDICT_TEXT`)을 그대로 끼워 만든다."""
    if n_test < MIN_JUDGE_ROWS:
        return (f"시험 자료가 {n_test}행이라(최소 {MIN_JUDGE_ROWS}행) 모델이 기준선보다 나은지 판정하지 않습니다 — "
                f"기간을 늘려 다시 보세요.")
    better = sum(v == "better" for v in verdicts)
    name = BASELINE_NAMES[strongest]
    if better == 0:
        return (f"모델 {len(verdicts)}개 모두 기준선 셋(이번 시험에서 가장 높았던 것은 「{name}」)을 뚜렷이 넘지 "
                f"못했습니다 — 이 종목 · 기간에서는 모델이 기준선 이상으로 배운 것이 보이지 않습니다.")
    return (f"모델 {len(verdicts)}개 중 {better}개: {VERDICT_TEXT['better']} — "
            f"과거 한 구간의 결과이고 거래 비용은 넣지 않았습니다.")


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def insights(baselines: List[Dict], models: List[Dict]) -> List[Dict]:
    """「왜 이런 결과인가」 세 줄 — 문장과 막대 값을 서버가 짓는다(화면은 다시 짓지 않는다).

    ① 정확도의 함정(늘 같은 답의 정확도 vs 균형 정확도) ② 외움(학습 점수 − 시험 점수가 가장 큰 모델 — Stacking 은 학습 점수의
    뜻이 달라 뺀다) ③ 우연 띠(무작위 기준선의 겹별 범위).
    """
    base = {b["key"]: b for b in baselines}
    out: List[Dict] = []
    maj = base.get("majority")
    if maj:
        out.append({"key": "accuracy_trap", "title": "정확도의 함정",
                    "text": f"「{maj['name']}」(학습 구간에서 가장 많던 답만 말하기)도 정확도는 {_pct(maj['accuracy'])} 입니다. "
                            f"오름 · 관망 · 내림을 각각 얼마나 맞혔는지 평균한 균형 정확도로 보면 "
                            f"{_pct(maj['balanced_accuracy'])} — 찍기(약 33%)와 같은 자리입니다.",
                    "bars": [{"label": "정확도", "value": maj["accuracy"]},
                             {"label": "균형 정확도", "value": maj["balanced_accuracy"]}]})
    cand = [m for m in models if m["key"] != "Ensemble(Stacking)"]
    if cand:
        m = max(cand, key=lambda r: r["train_fold_mean"] - r["balanced_accuracy"])
        out.append({"key": "memorize", "title": "외움과 배움",
                    "text": f"{m['name']} 은 학습한 날에는 {_pct(m['train_fold_mean'])} 를 맞혔지만 처음 보는 날에는 "
                            f"{_pct(m['balanced_accuracy'])} 였습니다 — 학습 점수가 높다고 앞날을 맞히는 것은 아닙니다.",
                    "bars": [{"label": "학습한 날", "value": m["train_fold_mean"]},
                             {"label": "처음 보는 날", "value": m["balanced_accuracy"]}]})
    rnd = base.get("random")
    if rnd:
        out.append({"key": "chance_band", "title": "우연 띠",
                    "text": f"아무 정보 없이 찍는 「{rnd['name']}」 도 겹에 따라 {_pct(rnd['fold_min'])} ~ "
                            f"{_pct(rnd['fold_max'])} 가 나왔습니다 — 겹 하나에서 이만큼의 차이는 우연으로도 납니다.",
                    "bars": [{"label": "가장 낮은 겹", "value": rnd["fold_min"]},
                             {"label": "가장 높은 겹", "value": rnd["fold_max"]}]})
    return out


def limits(ds: Dataset) -> List[str]:
    return [
        f"라벨은 {ds.horizon}거래일 뒤 수익률을 ±{ds.threshold * 100:g}% 로 나눈 것입니다 — 기준을 바꾸면 결과가 달라집니다.",
        "점수는 맞힌 비율이지 수익률이 아닙니다 — 거래 비용 · 세금 · 체결 지연을 넣지 않았습니다.",
        "모델 설정(하이퍼파라미터)은 고정값입니다 — 같은 자료로 설정을 골랐다면 점수가 부풀어 보입니다.",
        f"이웃한 날의 라벨이 {ds.horizon - 1}일씩 겹쳐 시험 행 수만큼 독립된 증거가 있는 것은 아닙니다 — "
        "그래서 덩어리(블록)로 다시 뽑아 판정합니다.",
        "한 종목 · 한 기간의 결과입니다 — 다른 기간 · 종목에서는 순위가 바뀔 수 있습니다.",
    ]


DEFINITIONS = {
    "balanced_accuracy": "계층(오름 · 관망 · 내림)마다 맞힌 비율을 평균한 값 — 무작위 · 늘 같은 답은 약 33%",
    "accuracy": "전체에서 맞힌 비율 — 한 계층이 많으면 「늘 그 답」 만으로도 높게 나옵니다",
    "direction_hit": "오름 · 내림이라고 말한 날만 세어 실제 방향과 맞은 비율(관망은 세지 않음)",
    "coverage": "오름 · 내림이라고 말한 날의 비율",
    "train_score": "학습한 날로 다시 잰 균형 정확도 — 시험 점수보다 훨씬 높으면 외운 것입니다. Stacking 은 예외로, 안쪽 "
                   "나눔(시간 덩어리 셋)에서 바탕 모델이 처음 보는 구간을 맞힌 결과로 답을 합치는 가중을 배웁니다. 정보가 적은 "
                   "자료에서는 그 결과가 실제와 거꾸로 움직여 가중이 음수가 되기도 해서, 바탕 모델이 정답을 외운 학습한 날에는 "
                   "답을 뒤집어 학습 점수가 찍기보다 낮게 나옵니다 — 이 모델은 시험 점수로 보세요",
    "fold": "과거로 학습하고 바로 뒤 구간으로 시험한 한 번 — 다음 겹은 시험 구간까지 학습에 더해 한 칸 나아갑니다",
    "gap": "학습 끝과 시험 시작 사이에 비우는 거래일 — 라벨이 앞날을 보기 때문에 정답이 새지 않게 합니다",
    "weighting": "학습할 때 적게 나온 계층(대개 오름 · 내림)의 날에 더 큰 무게를 줍니다 — 「늘 관망」 으로 쏠리지 않게, "
                 "모든 모델에 같은 방식으로",
    "verdict": f"모든 시험 날을 합쳐 기준선 셋(늘 같은 답 · 지난 흐름 그대로 · 이동 평균 위아래)과 각각 같은 날끼리 "
               f"견주고, 덩어리로 {N_BOOT}번 다시 뽑아 차이가 우연인지 보고, 모델 수만큼 엄격하게(홀름) 한 값이 "
               f"{ALPHA * 100:.0f}% 보다 작은 비교가 셋 모두 같은 쪽일 때만 「뚜렷」",
    "top_group": "1등 모델과 같은 방식으로 견줘 차이가 우연 범위 안이면 같은 묶음 — 순위 하나로 단정하지 않습니다",
}


# ══════════════════════════════════════════════════════════════════
# 4. 평가 엔진 — 겹마다 학습 · 예측 → 겹별 점수 · 합친 판정
# ══════════════════════════════════════════════════════════════════

def _baseline_preds(key: str, ds: Dataset, tr: np.ndarray, te: np.ndarray, k: int, seed: int) -> np.ndarray:
    if key == "majority":   # 학습 겹에서 가장 많던 계층(동점이면 작은 값)
        counts = [int(np.sum(ds.y[tr] == c)) for c in CLASSES]
        return np.full(len(te), CLASSES[int(np.argmax(counts))])
    if key == "persistence":
        return ds.persist[te]
    if key == "ma_trend":
        return ds.ma_trend[te]
    if key == "random":     # 학습 겹 비율대로 무작위(겹마다 씨앗 고정)
        rng = np.random.default_rng(seed + k)
        prior = np.array([np.mean(ds.y[tr] == c) for c in CLASSES])
        return rng.choice(np.array(CLASSES), size=len(te), p=prior / prior.sum())
    raise KeyError(key)


def _summary(scores: List[float]) -> Dict:
    a = np.asarray(scores, dtype=float)
    return {"fold_scores": [round(float(s), 4) for s in a], "fold_mean": round(float(a.mean()), 4),
            "fold_std": round(float(a.std(ddof=1)) if len(a) > 1 else 0.0, 4),
            "fold_min": round(float(a.min()), 4), "fold_max": round(float(a.max()), 4)}


def block_length(horizon: int) -> int:
    return max(2 * horizon, BLOCK_MIN)


ProgressFn = Callable[[Dict], None]


def evaluate(ds: Dataset, models: Optional[Dict[str, ModelFactory]] = None, n_splits: int = N_SPLITS,
             gap: Optional[int] = None, n_boot: int = N_BOOT, seed: int = SEED, weighted: bool = True,
             progress: Optional[ProgressFn] = None) -> Dict:
    """`progress` 가 있으면 단계마다 실제로 센 값을 알린다 — 모델 k / 전체 · 겹 f / 전체(지어낸 백분율이 아니다)."""
    models = default_models() if models is None else models
    tell = progress or (lambda _info: None)
    gap = ds.horizon if gap is None else gap
    block = block_length(ds.horizon)
    n = len(ds.y)
    splits = make_splits(n, n_splits, gap, ds.horizon)
    for k, (tr, _) in enumerate(splits):
        if len(np.unique(ds.y[tr])) < 2:   # 분류 모델은 라벨이 두 가지 이상 있어야 배운다 — 말없이 건너뛰지 않는다
            raise ModelCompareError(422, f"{k + 1}겹 학습 구간에 라벨이 한 가지뿐이라 비교할 수 없습니다",
                                    hint="기간을 늘리거나 라벨 문턱(threshold)을 낮춘다", code="one_label")
    tell({"stage": "baselines", "model_index": 0, "model_count": len(models), "fold": 0, "folds": len(splits)})
    te_all = np.concatenate([te for _, te in splits])          # 시험 행(시간 순서 · 겹치지 않음)
    y_te = ds.y[te_all]

    folds = [{"k": k + 1, "train_from": ds.dates[tr[0]], "train_to": ds.dates[tr[-1]],
              "test_from": ds.dates[te[0]], "test_to": ds.dates[te[-1]],
              "train_rows": int(len(tr)), "test_rows": int(len(te)),
              "train_end_idx": int(tr[-1]), "test_start_idx": int(te[0])} for k, (tr, te) in enumerate(splits)]

    # 기준선 — 같은 겹 · 같은 행
    base_pred: Dict[str, np.ndarray] = {}
    base_rows = []
    for key in BASELINE_NAMES:
        preds, scores = [], []
        for k, (tr, te) in enumerate(splits):
            p = _baseline_preds(key, ds, tr, te, k, seed)
            preds.append(p)
            scores.append(balanced_accuracy(ds.y[te], p))
        pp = np.concatenate(preds)
        base_pred[key] = pp
        hit, cover = direction(ds.fwd_ret[te_all], pp)
        base_rows.append({"key": key, "name": BASELINE_NAMES[key],
                          "balanced_accuracy": round(balanced_accuracy(y_te, pp), 4),
                          "accuracy": round(accuracy(y_te, pp), 4),
                          "direction_hit": None if hit is None else round(hit, 4), "coverage": round(cover, 4),
                          **_summary(scores)})
    strongest = max((r for r in base_rows if r["key"] in JUDGE_BASELINES), key=lambda r: r["balanced_accuracy"])["key"]
    for r in base_rows:
        r["strongest"] = r["key"] == strongest
        r["role"] = "judge" if r["key"] in JUDGE_BASELINES else "chance_band"

    # 모델 — 겹마다 학습 겹에서만 맞춤 · 계층 균형 가중
    from sklearn.exceptions import ConvergenceWarning

    model_pred: Dict[str, np.ndarray] = {}
    rows = []
    unweighted: List[str] = []
    for mi, (name, factory) in enumerate(models.items(), 1):
        preds, scores, train_scores, notes = [], [], [], []
        weighted_all = True
        for k, (tr, te) in enumerate(splits):
            tell({"stage": "models", "model_index": mi, "model_count": len(models), "model": name,
                  "fold": k + 1, "folds": len(splits), "test_from": ds.dates[te[0]], "test_to": ds.dates[te[-1]]})
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ConvergenceWarning)
                pipe = fit_fold(factory, ds.X, ds.y, tr, weighted=weighted)
            if any(issubclass(w.category, ConvergenceWarning) for w in caught):
                notes.append(f"{k + 1}겹: 반복 한도에서 멈춤(덜 학습)")
            weighted_all = weighted_all and bool(getattr(pipe, "weighted_", False))
            p = np.asarray(pipe.predict(ds.X[te]), dtype=int)
            preds.append(p)
            scores.append(balanced_accuracy(ds.y[te], p))
            train_scores.append(balanced_accuracy(ds.y[tr], np.asarray(pipe.predict(ds.X[tr]), dtype=int)))
        if weighted and not weighted_all:
            notes.append("가중 없음 — 이 모델은 표본 가중을 받지 않아 계층 균형 가중 없이 맞췄습니다")
            unweighted.append(name)
        if type(pipe[-1]).__name__ == "StackingClassifier" and np.mean(train_scores) < 1 / len(CLASSES):
            # 실측(합성 2년 · 마지막 겹): 메타 로지스틱이 RF 확률의 정답 칸에 음수 가중(−0.52 · −0.71 · −0.28)을 배웠고
            # 바탕 RF 의 학습 점수는 1.0 · Stacking 은 0.12 — 외운 답을 뒤집는다. 값은 그대로 보이고 까닭만 붙인다.
            notes.append("학습 점수가 찍기(약 33%)보다 낮습니다 — 합치는 가중이 안쪽 나눔에서 거꾸로 배워져, 바탕 모델이 "
                         "외운 학습한 날에는 답을 뒤집습니다(정의 「학습 점수」) · 시험 점수로 보세요")
        pp = np.concatenate(preds)
        model_pred[name] = pp
        hit, cover = direction(ds.fwd_ret[te_all], pp)
        rows.append({"key": name, "name": name,
                     "balanced_accuracy": round(balanced_accuracy(y_te, pp), 4),
                     "accuracy": round(accuracy(y_te, pp), 4),
                     "direction_hit": None if hit is None else round(hit, 4), "coverage": round(cover, 4),
                     "train_fold_mean": round(float(np.mean(train_scores)), 4),
                     "warnings": notes, **_summary(scores)})

    # 판정 — 기준선 셋과 각각 짝지어 · 블록 부트스트랩 · 기준선마다 모델 수만큼 홀름 → 셋 모두 같은 쪽이어야 「뚜렷」
    tell({"stage": "judging", "model_index": len(models), "model_count": len(models), "fold": len(splits),
          "folds": len(splits)})
    idx = block_indices(len(te_all), block, n_boot, seed)
    per_base = {}
    for b in JUDGE_BASELINES:
        comps = [paired(y_te, model_pred[r["key"]], base_pred[b], idx) for r in rows]
        for c, pa in zip(comps, holm([c["p_two"] for c in comps])):
            c["p_holm"] = pa
        per_base[b] = comps
    for i, r in enumerate(rows):
        cs = [dict(per_base[b][i], baseline=b) for b in JUDGE_BASELINES]
        v = verdict(len(te_all), cs)
        r["vs_baselines"] = [{"baseline": c["baseline"], "diff": round(c["diff"], 4),
                              "ci95": [round(x, 4) for x in c["ci95"]], "p_two": round(c["p_two"], 4),
                              "p_holm": None if c["p_holm"] is None else round(c["p_holm"], 4)} for c in cs]
        r["vs_strongest"] = next(c for c in r["vs_baselines"] if c["baseline"] == strongest)
        r["verdict"] = v
        r["verdict_text"] = VERDICT_TEXT[v]

    # 순위 대신 묶음 — 1등과 견줘 95% 구간이 0 을 품으면 같은 묶음
    rows.sort(key=lambda r: r["balanced_accuracy"], reverse=True)
    top = rows[0]["key"]
    for r in rows:
        if r["key"] == top:
            r["top_group"] = True
            continue
        lo, hi = paired(y_te, model_pred[top], model_pred[r["key"]], idx)["ci95"]
        r["top_group"] = bool(lo <= 0 <= hi)
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    counts = {str(c): int(np.sum(y_te == c)) for c in CLASSES}
    return {
        "cv": {"method": "walk_forward_expanding", "n_splits": n_splits, "gap": gap, "folds": folds,
               "block": block, "n_boot": n_boot, "seed": seed},
        "samples": {"rows": n, "test_rows": int(len(te_all)), "test_class_counts": counts,
                    "dropped_tail": ds.dropped_tail, "min_judge_rows": MIN_JUDGE_ROWS,
                    "judged": len(te_all) >= MIN_JUDGE_ROWS},
        "weighting": {"method": "balanced" if weighted else "none", "unweighted": unweighted},
        "baselines": base_rows,
        "strongest_baseline": strongest,
        "models": rows,
        "headline": headline([r["verdict"] for r in rows], strongest, len(te_all)),
    }


def compare_models_v2(candles: List[Dict], *, symbol: str = "", data_source: Optional[str] = None,
                      data_as_of: Optional[str] = None, horizon: int = HORIZON, threshold: float = THRESHOLD,
                      n_splits: int = N_SPLITS, gap: Optional[int] = None,
                      models: Optional[Dict[str, ModelFactory]] = None, n_boot: int = N_BOOT,
                      seed: int = SEED, weighted: bool = True, progress: Optional[ProgressFn] = None) -> Dict:
    """캔들 → 자료 → 평가 → 응답(`ml-compare-v2`). DB · 네트워크를 쓰지 않는다(읽기는 `load_daily`)."""
    t0 = time.perf_counter()
    ds = build_dataset(candles, horizon, threshold)
    factories = default_models() if models is None else models
    skipped = [m for m in MODEL_NAMES if models is None and m not in factories]
    out = evaluate(ds, factories, n_splits, gap, n_boot, seed, weighted, progress)
    return {
        "contract": CONTRACT,
        "symbol": symbol,
        "data_source": data_source,
        "data_as_of": data_as_of,
        "period": {"from": ds.dates[0], "to": ds.dates[-1]},
        "target": {"horizon_days": ds.horizon, "threshold_pct": ds.threshold * 100,
                   "classes": {"1": f"오름(+{ds.threshold * 100:g}% 초과)", "0": f"관망(±{ds.threshold * 100:g}% 안)",
                               "-1": f"내림(−{ds.threshold * 100:g}% 미만)"}},
        "features": list(ds.feature_names),
        "primary_metric": "balanced_accuracy",
        **out,
        "model_count": len(out["models"]),
        "baseline_count": len(out["baselines"]),
        "skipped": [{"name": m, "reason": "lightgbm 이 설치되지 않음"} for m in skipped],
        "definitions": DEFINITIONS,
        "verdict_texts": VERDICT_TEXT,
        "verdict_labels": VERDICT_LABEL,
        "insights": insights(out["baselines"], out["models"]),
        "limits": limits(ds),
        "notice": NOTICE,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


# ══════════════════════════════════════════════════════════════════
# 5. 읽기 — 데이터 관문(수집 DB 일봉 수정주가) 한 길 · 기간 창은 자료 기준일에서 거꾸로 · 자료 지문 · 인자 검사
# ══════════════════════════════════════════════════════════════════
#: 기간 → 달 수 · 화면 이름표 · 보통 걸리는 시간(앱 안 실측 2026-10-15: 2년 11.8초 · 5년 30.3초 — 지난 계산이 있으면 그 값을 쓴다)
PERIOD_SPEC = {
    "1y": {"months": 12, "label": "1년", "expected_ms": 10_000},
    "2y": {"months": 24, "label": "2년", "expected_ms": 15_000},
    "3y": {"months": 36, "label": "3년", "expected_ms": 20_000},
    "5y": {"months": 60, "label": "5년", "expected_ms": 30_000},
}
assert tuple(PERIOD_SPEC) == PERIODS
DATA_BASIS = "adj_base"      # 데이터 관문의 주식 일봉 수정 방식 — 수정주가(가장 최근 날 = 원래 값)
#: 응답 꼴 판 — 응답 칸을 더하거나 바꾸면 올린다(캐시 열쇠에 든다). 2026-10-15 화면 확인에서 「왜」 세 줄 · 짧은 이름표를
#: 더하기 전 저장본이 자료 지문이 같다는 까닭으로 새 화면에 나가 그림이 멈췄다 — 옛 꼴 저장본을 새 화면에 주지 않게.
RESULT_VERSION = 4          # 3 — 창 설명 글을 실제 날짜로(머리 줄에 「자료 기준일」 이 두 번 나와서) · 4 — 출처 글 `data.label` · `data.attribution`
#: 사람에게 보일 글 — 계절성 · 군집화와 같은 말투(503) · 없는 까닭은 사람 글에(관리자 할 일은 따로)
TEXT_UNAVAILABLE = "시세 자료를 지금 읽을 수 없습니다. 잠시 뒤 다시 시도해 주세요."
TEXT_NOT_FOUND = ("수집 자료에 {code} 종목의 일봉이 없습니다 — 국내 상장 주식만 계산합니다"
                  "(ETF · 지수 · 해외 종목 · 막 상장한 종목은 없을 수 있습니다). 다른 종목을 골라 보세요.")
TEXT_ETF = "{code} 는 ETF 입니다 — 모델 비교는 아직 국내 상장 주식만 계산합니다. 주식 종목을 골라 보세요."


def normalize_symbol(symbol: str) -> str:
    """국내 주식 6자리 단축코드만(`.KS` · `.KQ` 를 붙여 와도 된다) — 그 밖은 422."""
    s = (symbol or "").strip().upper()
    if len(s) == 9 and s[6:] in (".KS", ".KQ"):
        s = s[:6]
    if len(s) == 6 and s.isdigit():
        return s
    raise ModelCompareError(422, "국내 주식 6자리 종목 코드를 넣어 주세요(예: 005930)", code="bad_symbol")


def check_request(symbol: str, period: str, n_splits: Optional[int], gap: Optional[int], admin: bool) -> str:
    """DB 를 열기 전에 거르는 것 — 기간 · 관리자 손잡이 · 종목 꼴. 돌려주는 값은 단축코드 6자리."""
    if period not in PERIOD_SPEC:
        raise ModelCompareError(422, f"기간은 {' · '.join(PERIODS)} 가운데 하나입니다", code="bad_period")
    if (n_splits is not None or gap is not None) and not admin:
        # 받아 놓고 말없이 무시하지 않는다 — 일반 사용자는 종목 · 기간만(고르는 손잡이가 많으면 데이터 스누핑)
        raise ModelCompareError(403, "겹 수 · 간격은 관리자만 바꿀 수 있습니다", code="admin_only")
    return normalize_symbol(symbol)


def _months_back(d: date, months: int) -> date:
    import pandas as pd

    return (pd.Timestamp(d) - pd.DateOffset(months=months)).date()


def data_fingerprint(candles: List[Dict]) -> str:
    """자료 지문 — 날짜 · 시고저종(소수 넷째 자리) · 거래량을 정해진 차례로 SHA-256. 수정주가가 고쳐지면 바뀐다."""
    import hashlib
    import json

    rows = [[c["time"], round(float(c["open"]), 4), round(float(c["high"]), 4), round(float(c["low"]), 4),
             round(float(c["close"]), 4), int(c["volume"])] for c in candles]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def settings_fingerprint(n_splits: int, gap: Optional[int]) -> str:
    """결과에 닿는 설정 · 라이브러리 판의 지문 — 하나라도 바뀌면 캐시 열쇠가 바뀐다(옛 결과를 새 설정의 답으로 보이지 않게)."""
    import hashlib

    import sklearn

    try:
        import lightgbm
        lgb_ver = lightgbm.__version__
    except ImportError:
        lgb_ver = "none"
    parts = [CONTRACT, RESULT_VERSION, n_splits, HORIZON if gap is None else gap, HORIZON, THRESHOLD, N_BOOT, SEED,
             BLOCK_MIN, SVM_MAX_ITER, MLP_MAX_ITER, MIN_JUDGE_ROWS, DATA_BASIS, sklearn.__version__, lgb_ver]
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]


def cache_key(code: str, period: str, n_splits: int, gap: Optional[int]) -> str:
    """앱 결과 캐시(`data_cache`) 열쇠 — 이름:판:대상 꼴."""
    return f"model_compare:v1:{code}:{period}:{settings_fingerprint(n_splits, gap)}"


def load_daily(code: str, period: str, *, today: Optional[date] = None, path=None) -> Dict:
    """수집 DB 일봉(수정주가)만 — 데이터 관문(`data_ohlcv.read_ohlcv`, API-DATA-02 와 같은 함수) 한 길.

    - 못 읽음 503 · 종목 없음 404 · ETF 는 422 로 가른다(수집 DB 다리 `read_daily_candles` 는 읽기 오류를 삼켜 「없음」 과
      구별되지 않는다). 다른 출처(KIS · 야후)로 말없이 넘어가지 않는다.
    - 기간 창은 **자료 기준일**(그 종목의 마지막 봉)에서 거꾸로 센다 — 같은 기준일이면 언제 불러도 같은 날들이라
      결과 캐시와 「같은 입력이면 같은 답」 이 지켜진다. 넉넉히 읽은 뒤 자른다.
    """
    from app.services import data_ohlcv

    spec = PERIOD_SPEC[period]
    today = today or datetime.now(timezone(timedelta(hours=9))).date()
    try:
        # 그 종목 일봉을 처음부터 읽는다(수집 시작 2020-01-02 · 한 종목 1,450줄 안팎) — 기준일을 알아야 창을 셀 수 있고,
        # 「오늘 − 기간」 으로 읽으면 수집이 멈춘 종목의 창 앞이 잘린다(시험 TC-MV-19b 가 찾음)
        got = data_ohlcv.read_ohlcv(code, "1d", start=(today - timedelta(days=366 * 30)).isoformat(),
                                    basis=DATA_BASIS, today=today, path=path)
    except data_ohlcv.OhlcvError as e:
        if e.status == 404:
            raise ModelCompareError(404, TEXT_NOT_FOUND.format(code=code), code="symbol_not_found",
                                    hint="수집 대상(상장 주식 · 2020-01-02 부터)인지 · 데이터 관문 답: " + e.message) from None
        if e.status == 503:
            raise ModelCompareError(503, TEXT_UNAVAILABLE, code="db_unavailable", hint=e.message) from None
        if DATA_BASIS not in (e.extra.get("allowed") or [DATA_BASIS]):
            # 6자리 숫자로 이미 걸렀으니 수정주가가 없는 종류는 ETF 다(관문 BASES — ETF 는 원 가격만)
            raise ModelCompareError(422, TEXT_ETF.format(code=code), code="etf_not_supported",
                                    hint="ETF 는 수정 방식이 달라(분배금 · 원 가격만) 이번 판에서 받지 않음") from None
        raise ModelCompareError(422, "국내 주식 6자리 종목 코드를 넣어 주세요(예: 005930)", code="bad_symbol",
                                hint=e.message) from None
    if got.get("market") == "ETF":
        raise ModelCompareError(422, TEXT_ETF.format(code=code), code="etf_not_supported",
                                hint="ETF 는 수정 방식이 달라(분배금) 이번 판에서 받지 않음")
    rows = got.get("rows") or []
    if not rows or not got.get("as_of"):
        raise ModelCompareError(404, TEXT_NOT_FOUND.format(code=code), code="symbol_not_found",
                                hint=f"기간 안에 봉이 없음(from {got.get('from')})")
    as_of = date.fromisoformat(got["as_of"])
    start = _months_back(as_of, spec["months"]).isoformat()
    rows = [r for r in rows if r["trade_date"] >= start]
    candles = [{"time": int(datetime.fromisoformat(r["trade_date"]).replace(tzinfo=timezone.utc).timestamp()),
                "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]}
               for r in rows]
    return {"code": code, "period": period, "candles": candles, "as_of": got["as_of"], "from": rows[0]["trade_date"],
            "market": got.get("market"), "basis": DATA_BASIS, "fingerprint": data_fingerprint(candles)}


def compute_loaded(loaded: Dict, n_splits: Optional[int] = None, gap: Optional[int] = None,
                   progress: Optional[ProgressFn] = None) -> Dict:
    """읽은 자료 → 응답 — 출처 · 수정 방식 · 기준일 · 자료 지문 · 창 첫날을 응답에 싣는다(재현성)."""
    out = compare_models_v2(loaded["candles"], symbol=loaded["code"], data_source=DATA_SOURCE,
                            data_as_of=loaded["as_of"], n_splits=N_SPLITS if n_splits is None else n_splits, gap=gap,
                            progress=progress)
    out["data"] = {"source": DATA_SOURCE, "label": SOURCE_LABEL, "attribution": ATTRIBUTION,
                   "basis": loaded["basis"], "as_of": loaded["as_of"], "from": loaded["from"],
                   "market": loaded.get("market"), "fingerprint": loaded["fingerprint"],
                   "window": f"{loaded['from']} ~ {loaded['as_of']}(기준일에서 {PERIOD_SPEC[loaded['period']]['label']})"}
    out["request"] = {"symbol": loaded["code"], "period": loaded["period"],
                      "period_label": PERIOD_SPEC[loaded["period"]]["label"]}
    return out


def choices() -> Dict:
    """화면이 고르는 값 — 기간 이름표 · 판정 여부 · 관리자 손잡이 범위(화면 코드에 따로 적지 않게)."""
    from app.services.stock import QUANT_STOCKS   # 종목 제안 — 자동매매 31종목(이름은 서버 한 곳 · 다른 6자리도 넣을 수 있다)

    return {"periods": [{"key": k, "label": v["label"], "judged": v["months"] >= 24, "expected_ms": v["expected_ms"]}
                        for k, v in PERIOD_SPEC.items()],
            "default": {"symbol": "005930", "period": "2y"},
            "suggest": [{"code": s["symbol"][:6], "name": s["name"]} for s in QUANT_STOCKS],
            "n_splits": {"min": N_SPLITS_RANGE[0], "max": N_SPLITS_RANGE[1], "default": N_SPLITS},
            "gap": {"min": HORIZON - 1, "max": GAP_MAX, "default": HORIZON}}


def read_model_compare(symbol: str = "005930", period: str = "2y", n_splits: Optional[int] = None,
                       gap: Optional[int] = None, admin: bool = False, progress: Optional[ProgressFn] = None) -> Dict:
    """캐시 없이 한 번에 — 인자 검사 → 데이터 관문 → 평가(시험 · 작업 모듈이 쓰는 한 길)."""
    code = check_request(symbol, period, n_splits, gap, admin)
    return compute_loaded(load_daily(code, period), n_splits, gap, progress)
