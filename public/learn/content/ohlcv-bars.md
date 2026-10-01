---
slug: ohlcv-bars
title: 봉과 OHLCV — 일봉 · 주봉 · 분봉은 어떻게 만들어지나
section: tech
part: 1부 시세 데이터
order: 1.1
status: skeleton
summary: 시가 · 고가 · 저가 · 종가 · 거래량 다섯 숫자가 봉 하나가 되는 과정과, 일봉에서 주봉을 만드는 규칙을 익힙니다.
level: 입문
minutes: 30
owner: 이동원
feature: P01-①-2
work: W2
prereq: map
tags: OHLCV, 캔들, 일봉, 주봉, 분봉
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 W2 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- 봉 하나에 담긴 다섯 숫자(OHLCV)와 거래대금의 뜻을 설명할 수 있습니다.
- 일봉을 묶어 주봉을 만드는 규칙(첫 시가 · 최고 · 최저 · 마지막 종가 · 거래량 합)을 코드로 쓸 수 있습니다.
- 봉이 지켜야 할 값 규칙(저가 ≤ 시가 · 종가 ≤ 고가 등)을 검사할 수 있습니다.

## 다룰 질문

1. 봉 하나는 어떤 시간 동안의 무엇을 담나요?
2. 일봉 다섯 개로 주봉을 만들 때 시가 · 종가는 어느 날 값을 쓰나요?
3. 주의 중간에 휴장일이 있으면 주봉은 어떻게 되나요?
4. 거래정지일의 봉(거래량 0 · 네 가격이 같음)은 지워야 할까요?
5. 진행 중인 주의 주봉은 어떻게 표시하나요?

## 보여 줄 코드

- pandas `resample('W-FRI')` 로 일봉 → 주봉 만들기와 직접 묶기의 차이
- 값 규칙 검사 함수 — `low <= min(open, close) <= max(open, close) <= high`

## 우리 프로젝트와 닿는 곳

- 목표 기능 ① 상세 설계서 5.1.1 — 규격 `ohlcv-v1` 의 칸 · 기본 키 · 값 규칙 · 주봉 규칙
- 수집 DB `price_daily` (일봉 4,477,927행 · 2020-01-02~)

## 먼저 읽을 1차 자료

- pandas — `DataFrame.resample` 문서 <https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.resample.html>
- 목표 기능 ① 상세 설계서 5.1절(저장소 `docs/설계/`)
