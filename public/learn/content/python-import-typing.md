---
slug: python-import-typing
title: import 와 타입 힌트 — 패키지 · from __future__ · mypy
section: tech
part: 6부 파이썬 중급
order: 6.1
status: skeleton
summary: 파이썬 파일이 서로를 불러오는 규칙(패키지 · __init__.py · 순환 import)과, 실행에는 영향이 없는데도 우리 코드 대부분이 쓰는 타입 힌트 · from __future__ import annotations · mypy 를 익힙니다.
level: 기초
minutes: 35
owner: 이동원
feature: 공통
work: 3차 (사)
prereq: map
tags: 파이썬, import, 패키지, 타입 힌트, mypy
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 모듈 · 패키지 · `__init__.py` 의 차이를 말하고, 절대 import 와 상대 import 를 고를 수 있습니다.
- 순환 import 가 왜 생기고 어떻게 끊는지 설명할 수 있습니다.
- 타입 힌트가 실행 중에는 검사되지 않는다는 것과, 그런데도 쓰는 까닭(읽기 · 도구 · 문서)을 말할 수 있습니다.
- `from __future__ import annotations` 가 무엇을 미루는지, 그것 때문에 생기는 함정을 알 수 있습니다.

## 다룰 질문

1. `import app.services.stock` 과 `from app.services import stock` 은 무엇이 같고 무엇이 다른가요?
2. 두 모듈이 서로를 import 하면 언제 오류가 나고, 함수 안으로 import 를 옮기면 왜 풀리나요?
3. `from __future__ import annotations` 를 쓰면 힌트가 언제 평가되나요? 실행 중에 힌트를 읽는 라이브러리(pydantic · FastAPI)와는 어떻게 맞물리나요?
4. `Optional[X]` · `X | None` · `Literal` · `TypedDict` 는 각각 언제 쓰나요?
5. mypy 를 처음 붙일 때 저장소 전체가 아니라 한 층부터 엄격하게 시작하는 까닭은?

## 보여 줄 코드

- 패키지 하나(`__init__.py` · 하위 모듈 둘)와 순환 import 를 일부러 만든 뒤 끊는 예
- 힌트를 틀리게 적어도 실행은 되고 mypy 만 잡는 예(직접 돌린 출력)
- `from __future__ import annotations` 가 있을 때와 없을 때 `__annotations__` 를 찍어 견주기

## 우리 프로젝트와 닿는 곳

- `app/` 의 파이썬 파일 206개 중 130개가 `from __future__ import annotations` 를 쓴다(2026-10-20 셈).
- FastAPI 라우터와 Pydantic 스키마는 실행 중에 힌트를 읽는다. 그래서 미룬 힌트를 다시 푸는 지점이 있다.
- mypy 설정은 아직 없다. 수집 · 데이터 코드부터 엄격하게 시작하는 안을 검토하고 있다.

## 먼저 읽을 1차 자료

- multi-db-lab 실습 저장소(2026-10-12 판)의 기술 노트 tech001(`__init__.py` 와 패키지) · tech002(`from __future__ import annotations` 와 전방 참조) · tech005(타입 힌트 심화)
- PEP 563 · PEP 649 · PEP 749(힌트 평가를 미루는 방식의 변천)
- mypy 공식 문서 「Getting started」 · 「Using mypy with an existing codebase」
