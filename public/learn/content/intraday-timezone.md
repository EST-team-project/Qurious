---
slug: intraday-timezone
title: 분봉과 시간대 — UTC 로 온 봉을 KST 장 시간에 맞추기
section: tech
part: 1부 시세 데이터
order: 1.3
status: skeleton
summary: 야후가 주는 한국 종목 분봉의 시각을 KST 로 바꾸고, 정규장 밖 봉 · 받을 수 있는 기간의 한계를 다루는 법을 익힙니다.
level: 기초
minutes: 30
owner: 이동원
feature: P01-①-2
work: W2
prereq: ohlcv-bars
tags: 분봉, 시간대, UTC, KST, 정규장
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 W2 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- UTC 시각을 KST 로 바꾸고 봉이 속한 거래일을 정할 수 있습니다.
- 주기별로 과거를 얼마나 받을 수 있는지(1분 7일 · 5분 60일 · 60분 730일) 알고 쌓아 가는 계획을 세울 수 있습니다.
- 정규장(09:00~15:30) 밖의 봉을 가려낼 수 있습니다.

## 다룰 질문

1. 09:00 KST 봉이 00:00 UTC 로 오는 까닭은 무엇인가요?
2. 봉의 「시작 시각」 과 「끝 시각」 중 무엇을 키로 쓸까요?
3. 과거로 받을 수 없는 창 밖의 분봉은 어떻게 모으나요?
4. 날짜 경계(자정)에 걸친 봉은 어느 거래일에 넣나요?

## 보여 줄 코드

- `zoneinfo` 로 UTC → Asia/Seoul 바꾸기와 흔한 실수(naive datetime)
- yfinance 로 `005930.KS` 분봉 받아 정규장 밖 봉 세기

## 우리 프로젝트와 닿는 곳

- 목표 기능 ① 상세 설계서 5.1.3 — 분봉 양 추정 · 유니버스(💬 ①)
- 규격 `ohlcv-v1` 의 `bar_start` 칸(+09:00)

## 먼저 읽을 1차 자료

- Python `zoneinfo` 문서 <https://docs.python.org/3/library/zoneinfo.html>
- yfinance 저장소 <https://github.com/ranaroussi/yfinance>
