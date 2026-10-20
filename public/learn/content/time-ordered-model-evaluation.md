---
slug: time-ordered-model-evaluation
title: 시간 순서를 지킨 모델 평가 — 시계열 분할 · 간격 · 기준선 · 블록 부트스트랩
section: tech
part: 12부 머신러닝 모델
order: 12.2
status: skeleton
summary: 주가 예측 모델을 평가할 때 미래 자료로 학습하는 실수를 막는 시계열 분할과 간격(gap), 「늘 같은 답」 같은 기준선과의 비교, 블록 부트스트랩으로 「뚜렷이 나은가」 를 판정하는 방법을 앱의 모델 비교 코드로 익힙니다.
level: 심화
minutes: 45
owner: 이동원
prereq: tree-models-lightgbm
tags: 교차 검증, TimeSeriesSplit, 정보 누수, 기준선, 부트스트랩
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 섞어서 나누는 교차 검증이 시계열에서 왜 미래로 과거를 맞히는 셈이 되는지 설명할 수 있습니다.
- 라벨이 앞날 5거래일 수익률일 때 학습 끝과 시험 시작 사이에 간격을 몇 행 둬야 하는지 계산할 수 있습니다.
- 모델 점수를 기준선과 견주고, 「차이 없음」 이라는 판정을 받아들이는 까닭을 말할 수 있습니다.

## 다룰 질문

1. 분류 모델에 `cross_val_score(cv=5)` 를 쓰면 어떤 분할이 되고, 무엇이 새나요?
2. 스케일러를 전체 자료에 맞춘 뒤 나누면 왜 시험 자료가 학습에 끼어드나요?
3. 간격(gap)이 「라벨 기간 − 1」 보다 작으면 어떤 행의 라벨이 시험 구간 가격을 보나요?
4. 기준선(늘 같은 답 · 지난 흐름 그대로 · 이동 평균 위아래)을 셋 모두 이겨야 「낫다」 고 판정하는 까닭은?
5. 이웃한 날끼리 결과가 닮은 자료에서 부트스트랩을 블록으로 뽑는 까닭은?

## 보여 줄 코드

- `app/services/model_compare.py` 의 `make_splits`(시계열 분할 · 간격 검사) · `block_indices`(블록 부트스트랩) · `verdict`(판정 네 갈래)
- 같은 모델을 섞은 교차 검증과 시계열 분할로 각각 평가해 점수 차이 보기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 「ML·딥러닝 › 모델 비교」 화면이 이 평가를 씁니다. 1년 자료는 점수만 보여 주고 판정은 하지 않습니다(시험 자료가 적어서).
- 전략의 강건성(워크포워드 · 민감도)을 보는 일과 같은 원리이고, 금융 필수 지식의 「백테스트 결과를 믿어도 될까」 와 짝입니다.

## 먼저 읽을 1차 자료

- scikit-learn 문서 「TimeSeriesSplit」 <https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html>
- López de Prado, M. (2018). *Advances in Financial Machine Learning*, 7장(교차 검증 · purging · embargo). Wiley.
- Politis, D. N. · Romano, J. P. (1994). 「The Stationary Bootstrap」, *Journal of the American Statistical Association* 89(428).
