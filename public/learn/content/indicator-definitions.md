---
slug: indicator-definitions
title: 지표 계산 정의 — RMA · RSI · 볼린저 · ATR · MACD
section: tech
part: 9부 신호와 설명
order: 9.1
status: skeleton
summary: 같은 이름의 지표가 라이브러리마다 다른 값을 내는 까닭(평활 방식 · 시작값 · 표준편차의 나눗수)을 짚고, 앱이 지표를 한 모듈 · 한 정의로 모은 방식을 TradingView Pine 의 식과 견주며 익힙니다.
level: 기초
minutes: 35
owner: 이동원
prereq: ohlcv-bars
tags: 기술 지표, RSI, RMA, 볼린저 밴드, ATR, MACD, Pine
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- RSI 의 평활 방식(단순평균 · 지수평균 · Wilder 의 RMA)에 따라 값이 어떻게 갈리는지 보여 줄 수 있습니다.
- 볼린저 밴드의 표준편차를 n 으로 나눌 때와 n − 1 로 나눌 때의 차이를 설명할 수 있습니다.
- 지표 정의를 한 곳에 모으면 무엇이 지켜지는지(화면 · 신호 · 백테스트가 같은 값을 씀) 말할 수 있습니다.

## 다룰 질문

1. RMA 는 왜 첫 n 개의 단순평균으로 시작하고, 그 뒤 α = 1/n 로 평활하나요?
2. 하락폭이 0 이면 RSI 는 얼마가 되어야 하나요? 상승폭이 0 이면?
3. 같은 종목인데 RSI 30 아래인 날 수가 계산 방식에 따라 크게 달라진 까닭은?
4. ATR 의 첫 봉 TR 은 왜 「고가 − 저가」 인가요?
5. MACD(12 · 26 · 9)의 신호선과 히스토그램은 각각 무엇인가요?

## 보여 줄 코드

- `app/services/ta_utils.py` 의 `rma` · `rsi` · `bollinger` · `atr` · `macd`
- 같은 종가 열에 단순평균 RSI · 첫 값 시작 Wilder RSI · RMA RSI 를 나란히 계산해 차이 보기(직접 돌린 출력)
- TradingView Pine 의 `ta.rsi` · `ta.stdev` · `ta.atr` 정의와 한 줄씩 맞대기

## 우리 프로젝트와 닿는 곳

- 화면의 RSI · 볼린저 · ATR 과 다중 주기 신호([9.3](#/p/multi-timeframe-signals)), 패턴 통계([9.4](#/p/pattern-event-study))가 모두 이 모듈 하나로 계산합니다.
- 지표를 「읽는 법」 은 금융 필수 지식 강의(기술적 분석 기초)가 다루고, 이 장은 「계산 정의」 를 다룹니다.
- 3차의 Pine 지표([5.2 Pine Script 기초](#/p/pine-script-basics))와 값이 같아야 성과를 견줄 수 있습니다.

## 먼저 읽을 1차 자료

- TradingView Pine Script 레퍼런스(`ta.rsi` · `ta.rma` · `ta.stdev` · `ta.atr`) <https://www.tradingview.com/pine-script-reference/v6/>
- TA-Lib 함수 목록 <https://ta-lib.org/functions/>
- Wilder, J. W. (1978). *New Concepts in Technical Trading Systems*. Trend Research.
