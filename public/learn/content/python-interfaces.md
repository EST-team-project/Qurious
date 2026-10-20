---
slug: python-interfaces
title: 약속으로 갈아 끼우기 — ABC · Protocol · 인자 설계
section: tech
part: 6부 파이썬 중급
order: 6.3
status: skeleton
summary: 「무엇을 할 수 있어야 하는가」 를 먼저 약속하고 구현을 갈아 끼우는 방법(추상 클래스 ABC · 구조로 맞추는 Protocol)과, 부르는 쪽이 틀리기 어렵게 인자를 설계하는 법(키워드 전용 * · 언패킹)을 익힙니다.
level: 심화
minutes: 40
owner: 이동원
feature: 공통
work: 3차 (사)
prereq: python-data-containers
tags: 파이썬, ABC, Protocol, 인터페이스, 인자
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 「약속(인터페이스)과 구현을 나눈다」 를 우리 코드의 예로 설명할 수 있습니다.
- ABC(상속으로 약속을 지키게 함)와 Protocol(모양이 맞으면 통과)의 차이를 말하고 고를 수 있습니다.
- 키워드 전용 인자(`*`)로 부르는 쪽의 실수(자리 바뀜)를 막을 수 있습니다.

## 다룰 질문

1. 증권사가 바뀌어도(모의 · 한국투자 · Alpaca) 주문 코드를 고치지 않으려면 무엇을 먼저 정해야 하나요?
2. ABC 의 `@abstractmethod` 를 빠뜨린 하위 클래스는 언제 오류가 나나요? Protocol 은 언제 잡히나요?
3. 시험이 진짜 구현 대신 가짜를 끼울 때, 약속이 있으면 무엇이 쉬워지나요?
4. `def order(symbol, qty, price, side)` 와 `def order(symbol, *, qty, price, side)` 는 부르는 쪽에서 무엇이 다른가요?

## 보여 줄 코드

- 같은 약속을 ABC 와 Protocol 로 각각 적고, 메서드 하나를 빠뜨린 구현을 넣어 보는 예(직접 돌린 출력)
- 키워드 전용 인자로 바꾸기 전과 뒤에 인자 자리를 바꿔 불러 보기
- `zip` · `*args` · `**kwargs` 언패킹으로 표의 줄을 함수 인자로 넘기기

## 우리 프로젝트와 닿는 곳

- `app/services/brokers/base.py` — 증권사 연결의 약속(ABC)
- `app/lib/llm_client.py` · `app/services/trading_cost.py` — Protocol 로 모양을 약속한 곳
- 저장소 다섯을 같은 약속 뒤에 두는 이야기는 7부 「저장소 다섯과 포트 · 어댑터」 와 짝이다.

## 먼저 읽을 1차 자료

- multi-db-lab 실습 저장소(2026-10-12 판)의 기술 노트 tech004(ABC 와 Protocol) · tech013(인자 전달 — 키워드 전용 `*` · 언패킹 · `zip`)
- 파이썬 문서 `abc` · `typing.Protocol` · PEP 544
