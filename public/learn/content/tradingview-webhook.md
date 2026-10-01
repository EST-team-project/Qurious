---
slug: tradingview-webhook
title: TradingView 경보를 서버로 받기 — 웹훅
section: tech
part: 5부 차트 · Pine
order: 5.3
status: skeleton
summary: TradingView 경보가 우리 서버로 HTTP 요청을 보내는 웹훅의 구조와, 받는 쪽에서 지킬 것(비밀 값 · 중복 · 순서 · 기록)을 익힙니다.
level: 기초
minutes: 25
owner: 이동원
feature: 3차 ③
work: 3차
prereq: pine-script-basics
tags: 웹훅, 경보, 보안, 멱등성
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 3차 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- 웹훅 요청의 모양과 응답 규칙을 설명할 수 있습니다.
- 비밀 값으로 위조 요청을 거를 수 있습니다.
- 같은 경보가 두 번 와도 한 번만 처리할 수 있습니다.

## 다룰 질문

1. 경보 메시지에 무엇을 담아 보내나요?
2. 로컬 PC 의 서버는 인터넷에서 어떻게 받나요(공개 주소 · 터널)?
3. 경보를 받아 곧바로 주문하면 무엇이 위험한가요?

## 보여 줄 코드

- FastAPI 웹훅 엔드포인트 · 비밀 값 비교 · 중복 키

## 우리 프로젝트와 닿는 곳

- 앱의 `indicator-tradingview` 화면 · `app/routes/tradingview.py`

## 먼저 읽을 1차 자료

- TradingView 도움말 「About webhooks」(TradingView 지원 페이지)
