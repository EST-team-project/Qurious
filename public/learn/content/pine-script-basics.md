---
slug: pine-script-basics
title: Pine Script 기초 — 지표와 전략
section: tech
part: 5부 차트 · Pine
order: 5.2
status: skeleton
summary: TradingView 의 Pine Script 로 지표(`indicator`)와 전략(`strategy`)을 쓰는 법, 기본값(수수료 · 슬리피지 · 체결 시점)이 결과를 어떻게 바꾸는지 익힙니다.
level: 기초
minutes: 40
owner: 이동원
feature: 3차 ③
work: 3차
prereq: lightweight-charts
tags: Pine Script, 지표, 전략, 백테스트
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 3차 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- `indicator()` 와 `strategy()` 의 차이를 설명할 수 있습니다.
- `ta.rsi` · `ta.bb` 같은 내장 함수의 정의를 우리 계산과 대조할 수 있습니다.
- 전략 기본값을 명시해 결과를 재현 가능하게 만들 수 있습니다.

## 다룰 질문

1. `strategy()` 의 수수료 · 슬리피지 기본값은 얼마인가요?
2. `process_orders_on_close` 는 체결 시점을 어떻게 바꾸나요?
3. Pine 의 RSI(Wilder)와 단순 이동평균 RSI 는 얼마나 다른가요?
4. 앱이 Pine 코드를 만들 때 흔한 실수는(문자열 템플릿 누락)?

## 보여 줄 코드

- RSI 지표 · 손절 익절 전략 예제
- 같은 전략을 Python 과 Pine 으로 돌려 비교

## 우리 프로젝트와 닿는 곳

- 옛 분석 A5 · D6 기록(RSI 세 벌 · Pine 생성기 결함)
- 3차 ①② 인디케이터(신장환)와의 접점

## 먼저 읽을 1차 자료

- Pine Script 문서 <https://www.tradingview.com/pine-script-docs/>
