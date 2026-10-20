---
slug: lightweight-charts
title: Lightweight Charts 로 가격 차트 그리기
section: tech
part: 5부 차트 · Pine
order: 5.1
status: skeleton
summary: TradingView 가 공개한 차트 라이브러리로 캔들 · 거래량 · 지표 선을 그리고, 우리 OHLCV API 와 잇는 법을 익힙니다.
level: 입문
minutes: 30
owner: 이동원
feature: 3차 ③
work: 3차
prereq: ohlcv-bars
tags: TradingView, Lightweight Charts, 캔들 차트
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 캔들 · 히스토그램 · 선 시리즈를 그릴 수 있습니다.
- 시간 축에 거래일만 이어 보이게 할 수 있습니다.
- 라이선스가 요구하는 표시(제작자 표기)를 지킬 수 있습니다.

## 다룰 질문

1. 라이브러리 판(v5)에서 시리즈를 더하는 방법은?
2. UTC 타임스탬프와 KST 표시는 어떻게 맞추나요?
3. 손절 · 익절 선을 차트에 그리려면?

## 보여 줄 코드

- 캔들 + 거래량 + 이동평균 선 예제
- `/api/data/ohlcv` 응답을 시리즈 데이터로 바꾸기

## 우리 프로젝트와 닿는 곳

- 「투자 인디케이터」 메뉴의 지표 차트 · 손절 · 익절 선 표시

## 먼저 읽을 1차 자료

- Lightweight Charts 문서 <https://tradingview.github.io/lightweight-charts/>
