---
slug: python-functions-as-values
title: 함수를 값으로 — 고차 함수 · 클로저 · 데코레이터 · functools
section: tech
part: 6부 파이썬 중급
order: 6.4
status: skeleton
summary: 함수를 변수에 담고 넘기고 돌려주는 방법(고차 함수 · 클로저 · 전략 표)과, 그 위에 선 데코레이터 · functools(lru_cache · cached_property)를 우리 지표 · 저장본 코드로 익힙니다.
level: 심화
minutes: 40
owner: 이동원
feature: 공통
work: 3차 (사)
prereq: python-interfaces
tags: 파이썬, 고차 함수, 클로저, 데코레이터, functools
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 함수를 값처럼 다루는 세 가지(넘기기 · 돌려주기 · 표에 담기)를 예로 들 수 있습니다.
- 클로저가 바깥 변수를 「값」 이 아니라 「이름」 으로 잡는다는 것과 그 함정(반복문 안 람다)을 설명할 수 있습니다.
- 데코레이터가 「함수를 받아 함수를 돌려주는 함수」 라는 것과 `functools.wraps` 를 쓰는 까닭을 말할 수 있습니다.
- `lru_cache` 가 무엇을 저장하고, 언제 쓰면 안 되는지(바뀌는 자료 · 동시 첫 호출) 말할 수 있습니다.

## 다룰 질문

1. 지표 이름 → 계산 함수의 표(전략 표)는 `if … elif …` 사슬보다 무엇이 나은가요?
2. `[lambda: i for i in range(3)]` 의 함수를 부르면 왜 모두 2 가 나오나요?
3. 데코레이터를 씌운 함수의 이름 · 설명이 사라지는 까닭과 막는 법은?
4. `@lru_cache(maxsize=1)` 함수를 두 스레드가 동시에 처음 부르면 계산이 몇 번 도나요?

## 보여 줄 코드

- 전략 표(dict 에 함수를 담기)로 지표를 고르는 예
- 실행 시간을 재는 데코레이터를 만들고 `wraps` 가 있을 때와 없을 때 `__name__` 견주기
- `lru_cache` 동시 첫 호출을 스레드 둘로 재현한 출력(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- `app/services/pattern_view.py` 의 `@lru_cache(maxsize=1)` 두 곳 — 한 번 읽은 표를 프로세스 안에 둔다.
- FastAPI 의 `@router.get(…)` · `Depends(…)` 도 데코레이터 · 함수 넘기기다(7부 「FastAPI 로 API 만들기」 에서 다시 만난다).

## 먼저 읽을 1차 자료

- multi-db-lab 실습 저장소(2026-10-12 판)의 기술 노트 tech010(클로저 · 고차 함수 · 전략 테이블) · tech008(`functools` — `lru_cache` · `cached_property`)
- 파이썬 문서 `functools`
