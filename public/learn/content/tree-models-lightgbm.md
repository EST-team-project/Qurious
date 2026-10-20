---
slug: tree-models-lightgbm
title: 트리 모델과 그래디언트 부스팅 — 결정 나무에서 LightGBM 까지
section: tech
part: 12부 머신러닝 모델
order: 12.1
status: skeleton
summary: 질문을 이어 붙여 답을 고르는 결정 나무, 나무 여러 그루의 오차를 차례로 메우는 그래디언트 부스팅, 빠른 구현인 LightGBM 을 앱의 방향 예측 코드(조기 종료 · 다중 분류)로 익힙니다.
level: 기초
minutes: 40
owner: 이동원
prereq: map
tags: 결정 나무, 그래디언트 부스팅, LightGBM, 분류, 조기 종료
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 결정 나무가 특성 값의 문턱으로 자료를 나누는 방법을 그림으로 그릴 수 있습니다.
- 그래디언트 부스팅이 앞 나무의 오차를 다음 나무가 메우는 방식이라는 것을 설명할 수 있습니다.
- 학습 · 검증을 시간 순서로 나누고 조기 종료(early stopping)로 나무 수를 정하는 까닭을 말할 수 있습니다.

## 다룰 질문

1. 나무 하나가 깊어질수록 학습 자료에는 잘 맞고 새 자료에는 못 맞는 까닭은?
2. 학습률(learning rate)을 낮추면 나무가 더 필요해지는 까닭은?
3. 매도 · 관망 · 매수 세 클래스를 가르면 나무는 클래스마다 따로 자라나요?
4. 검증 구간을 뒤쪽(최근)으로 두고 조기 종료를 거는 것과, 무작위로 섞어 두는 것은 무엇이 다른가요?
5. 같은 자료에 선형 모델(Ridge)과 트리 모델을 함께 두는 까닭은?

## 보여 줄 코드

- `app/services/investment_research.py` 의 `ai_predict_return` — 시계열 교차 검증으로 회귀(Ridge · 그래디언트 부스팅)와 방향 분류(LightGBM)를 함께 학습
- `lgb.train(…, callbacks=[lgb.early_stopping(10)])` 로 멈춘 나무 수 찍어 보기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 투자분석 화면의 AI 예측과, 그 예측의 이유를 보여 주는 설명([9.5 추천 이유 설명](#/p/xai-shap))이 이 모델을 씁니다.
- 모델끼리 견주는 법은 다음 장 [12.2 시간 순서를 지킨 모델 평가](#/p/time-ordered-model-evaluation) 가 다룹니다.

## 먼저 읽을 1차 자료

- LightGBM 문서 「Features」 · 「Parameters」 <https://lightgbm.readthedocs.io/>
- Ke, G. 등 (2017). 「LightGBM: A Highly Efficient Gradient Boosting Decision Tree」, NeurIPS 2017.
- Friedman, J. H. (2001). 「Greedy Function Approximation: A Gradient Boosting Machine」, *Annals of Statistics* 29(5).
