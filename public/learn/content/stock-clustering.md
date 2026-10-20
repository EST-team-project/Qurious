---
slug: stock-clustering
title: 종목 군집화 — 같이 움직인 묶음과 닮은 특성 묶음
section: tech
part: 12부 머신러닝 모델
order: 12.3
status: skeleton
summary: 수익률의 상관을 거리로 바꿔 같이 움직인 종목을 묶는 방법과, 변동성 · 수익 같은 특성으로 KMeans 묶음을 만드는 방법을 견주고, 묶음 수를 실루엣으로 고르는 법을 앱의 군집화 코드로 익힙니다.
level: 심화
minutes: 40
owner: 이동원
prereq: map
tags: 군집화, 상관 거리, KMeans, 실루엣, 계층 군집
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 상관계수 ρ 를 거리 d = √(2(1 − ρ)) 로 바꾸는 까닭과, 시장 몫을 뺀 수익률로 상관을 재는 까닭을 설명할 수 있습니다.
- KMeans 의 묶음 수 k 를 실루엣 점수로 고를 수 있습니다.
- 묶음에 「성장주 · 가치주」 같은 투자 스타일 이름을 붙이면 왜 틀릴 수 있는지 말할 수 있습니다.

## 다룰 질문

1. 시장 전체가 오른 날 거의 모든 종목이 함께 오릅니다. 그 몫을 빼지 않으면 상관이 어떻게 보이나요?
2. 실루엣 점수가 1 에 가깝다는 것은 무엇을 뜻하나요?
3. 같은 입력이면 같은 묶음이 나오게 하려면 KMeans 에 무엇을 정해야 하나요?
4. 거리 행렬을 두 축 지도로 펼치는 고전 MDS 와, 특성을 두 축으로 줄이는 PCA 는 무엇이 다른가요?
5. 묶음 결과를 업종 분류와 견주면 무엇을 알 수 있나요?

## 보여 줄 코드

- `app/services/stock_clusters.py` 의 `market_residuals`(시장 몫 빼기) · `movement_clusters`(상관 거리 묶음) · `_classical_mds`(지도)
- 종목 열 개로 상관 거리 묶음과 KMeans 묶음을 각각 만들어 견주기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 「ML·딥러닝 › 종목 군집화」 화면이 이 계산을 씁니다. 묶음 이름은 숫자로 만든 낱말(「변동성 높음」 등)입니다.

## 먼저 읽을 1차 자료

- Mantegna, R. N. (1999). 「Hierarchical Structure in Financial Markets」, *European Physical Journal B* 11(1).
- scikit-learn 문서 「Clustering」 · 「Silhouette Coefficient」 <https://scikit-learn.org/stable/modules/clustering.html>
