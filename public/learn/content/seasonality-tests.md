---
slug: seasonality-tests
title: 계절성 검정 — 달 · 요일 효과와 여러 번 견줄 때의 보정
section: tech
part: 12부 머신러닝 모델
order: 12.4
status: skeleton
summary: 「1월에는 오른다」 같은 달 · 요일 효과를 달 수익률로 바르게 세고, 웰치 t 검정과 홀름 보정으로 「여럿을 한꺼번에 견주면 우연히 하나쯤은 두드러진다」 는 함정을 거르는 방법을 앱의 계절성 분석 코드로 익힙니다.
level: 기초
minutes: 35
owner: 이동원
prereq: ohlcv-bars
tags: 계절성, 달 효과, 요일 효과, t 검정, 다중 비교, 홀름 보정
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 일간 수익률의 달별 평균과 달 수익률(달 끝 → 달 끝)의 차이를 설명할 수 있습니다.
- 한 달과 나머지 달의 평균 차이를 웰치 t 검정으로 볼 수 있습니다.
- 열두 달을 한꺼번에 견줄 때 p 값을 홀름 방식으로 보정하는 까닭과 계산 차례를 말할 수 있습니다.

## 다룰 질문

1. 「1월 +0.08%」 는 하루 평균인가요, 한 달 수익률인가요? 둘은 왜 다르게 읽히나요?
2. 아직 끝나지 않은 달이나 앞달이 비어 있는 달을 세지 않는 까닭은?
3. 열두 달을 각각 유의수준 5% 로 검정하면, 효과가 전혀 없어도 하나쯤 「유의」 가 나올 확률은 얼마쯤인가요?
4. 홀름 보정은 가장 작은 p 값부터 무엇을 곱하나요? 앞 값보다 작아지지 않게 하는 까닭은?
5. 관측이 6 ~ 7년뿐인 종목 지수에서 「뚜렷한 달」 을 말해도 되나요?

## 보여 줄 코드

- `app/services/seasonality.py` 의 `monthly_matrix`(해마다 달 수익률 표) · `_welch_p` · `holm` · `weekday_stats`
- 코스피 지수 달 수익률로 보정 전 · 뒤 p 값을 나란히 찍기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 「금융 필수 지식 › 계절성 분석」 화면이 이 계산 결과와 문장을 씁니다. 과거 패턴은 예측이 아니라는 문장이 함께 나옵니다.
- 시장 지수는 매일 수집하는 한국은행 ECOS 주가지수를 씁니다.

## 먼저 읽을 1차 자료

- Holm, S. (1979). 「A Simple Sequentially Rejective Multiple Test Procedure」, *Scandinavian Journal of Statistics* 6(2).
- Sullivan, R. · Timmermann, A. · White, H. (2001). 「Dangers of Data Mining: The Case of Calendar Effects in Stock Returns」, *Journal of Econometrics* 105(1).
- SciPy 문서 `scipy.stats.ttest_ind`(`equal_var=False` 가 웰치 검정) <https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html>
