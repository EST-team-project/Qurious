---
slug: order-safety
title: 주문 안전 — 중복 주문 · 주문 수 한도 · 비중 한도 · 일손실 한도 · 비상 정지
section: tech
part: 11부 자산배분과 주문
order: 11.4
status: skeleton
summary: 자동매매가 같은 주문을 두 번 내거나 손실이 커져도 멈추지 않는 일을 막는 장치 다섯(중복 방지 · 하루 주문 수 · 종목 비중 · 일손실 한도 · 비상 정지)을, Redis 의 원자적 명령과 앱의 위험관리 코드로 익힙니다.
level: 심화
minutes: 40
owner: 이동원
prereq: broker-api-basics, celery-task-queue
tags: 주문 안전, 위험 관리, 멱등성, 비상 정지, Redis
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 같은 종목 · 같은 방향 주문을 일정 시간 안에 다시 내지 않게 하는 「자리 잡기」 를 Redis `SET … NX EX` 로 설명할 수 있습니다.
- 하루 주문 수 · 종목 비중 · 일손실 한도가 각각 무엇을 막는지 말할 수 있습니다.
- 위험 관리 저장소(Redis)가 꺼졌을 때 주문을 막을지 계속할지, 그 선택의 득실을 설명할 수 있습니다.

## 다룰 질문

1. 「값이 없을 때만 넣고, 정한 시간이 지나면 지운다」(`SET … NX EX`)가 왜 중복 주문을 막는 데 맞나요? 두 워커가 같은 순간에 시도하면?
2. 매수 뒤 종목 평가액이 총자산의 N% 를 넘으면 수량을 줄입니다. 줄인 수량이 0 이면 어떻게 되나요?
3. 일손실은 무엇과 견주나요(그날 시작 자산)? 한도에 닿으면 무엇이 멈추고 누구에게 알리나요?
4. 비상 정지(kill switch)는 수동과 자동 둘 다 켤 수 있습니다. 다시 켜는 것은 누가 하나요?
5. 실거래 주문을 막아 두는 장치는 이 다섯과 어떻게 다른 층에 있나요?

## 보여 줄 코드

- `app/services/risk_guard.py` 의 `acquire_order_slot`(중복 방지) · `increment_orders_today`(하루 주문 수) · `cap_buy_quantity`(종목 비중) · `daily_loss_breached`(일손실) · `RiskLimits`
- 같은 주문을 두 번 연달아 시도해 둘째가 막히는지 확인하기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 자동매매 주기([7.6 Celery 와 Redis](#/p/celery-task-queue))가 주문을 내기 전에 이 검사를 지납니다.
- Redis 가 꺼져도 자동매매를 막지 않도록 메모리 상태로 넘어가는 설계입니다. 그 대신 여러 워커 사이의 중복 방지는 약해집니다.
- 같은 글을 둘이 고칠 때의 충돌 막기([7.4 낙관적 동시성](#/p/optimistic-concurrency))와 같은 계열의 문제입니다.

## 먼저 읽을 1차 자료

- Redis 문서 「SET」(NX · EX 선택지) <https://redis.io/docs/latest/commands/set/>
- Redis 문서 「INCR」 <https://redis.io/docs/latest/commands/incr/>
- 한국투자증권 KIS Developers 포털(주문 · 정정 · 취소 API) <https://apiportal.koreainvestment.com>
