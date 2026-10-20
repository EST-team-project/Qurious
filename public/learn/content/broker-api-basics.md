---
slug: broker-api-basics
title: 증권사 Open API 기초 — 토큰 · 모의와 실전 주소 · 호출 제한
section: tech
part: 11부 자산배분과 주문
order: 11.3
status: skeleton
summary: 증권사 Open API 로 시세를 받고 주문을 내려면 무엇이 필요한지(앱 키 · 접근 토큰 · 모의와 실전 주소 · 호출 제한)를, 여러 증권사를 한 약속 뒤에 두는 앱의 어댑터 구조와 토큰 공유 방식으로 익힙니다.
level: 기초
minutes: 40
owner: 이동원
prereq: public-api-basics, python-interfaces
tags: 증권사 API, 한국투자증권, KIS, 토큰, 모의투자, 어댑터
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 앱 키 · 앱 시크릿으로 접근 토큰을 받고, 그 토큰으로 시세 · 잔고 · 주문을 부르는 차례를 그릴 수 있습니다.
- 모의투자 주소와 실전 주소를 나누는 까닭과, 실전 주문을 막아 두는 방법을 설명할 수 있습니다.
- 토큰 발급과 호출에 한도가 있을 때 여러 요청이 토큰 하나를 나눠 쓰게 하는 방법을 말할 수 있습니다.

## 다룰 질문

1. 접근 토큰은 얼마나 오래 쓰고, 만료 전에 다시 받으면 어떤 일이 생기나요?
2. 한국투자증권 Open API 의 모의투자 주소와 실전 주소는 어떻게 다르고, 앱은 어디서 그것을 고르나요?
3. 토큰 발급을 짧은 시간에 여러 번 요청하면 왜 실패하나요? 앱은 발급 자리를 1분 동안 잡아 두는 방식으로 어떻게 막나요?
4. 여러 증권사(한국투자 · 키움 · KB 등)를 같은 함수 이름(`get_token` · `get_price` · `get_balance` · `place_order`)으로 부르면 무엇이 쉬워지나요?
5. 미국 주식 모의 계좌(Alpaca Paper)는 연결 시험만 하고 주문은 내지 않는 까닭은?

## 보여 줄 코드

- `app/services/brokers/base.py` 의 `BrokerClient`(추상 클래스 · 증권사마다 같은 약속)
- `app/services/brokers/kis.py` 의 모의 · 실전 주소와 `app/services/brokers/kis_token.py` 의 토큰 공유
- 시험용 가짜 증권사(`brokers/mock.py`)로 같은 약속을 돌려 보기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 「현재가」 는 사용자 자기 증권사 키가 있으면 그 시세를 먼저 씁니다. 3차에는 증권사 API 로 모의 자동매매를 엽니다.
- 증권사 키는 서버 설정이나 사용자 저장소에만 두고, 화면 · 로그 · 저장소에는 남기지 않습니다.
- 같은 약속 뒤에 구현을 바꿔 끼우는 원리는 [6.3 약속으로 갈아 끼우기](#/p/python-interfaces) 와 이어집니다.

## 먼저 읽을 1차 자료

- 한국투자증권 KIS Developers 포털 <https://apiportal.koreainvestment.com>
- Alpaca 문서 「Paper Trading」 <https://docs.alpaca.markets/docs/paper-trading>
