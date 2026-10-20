---
slug: python-data-containers
title: 데이터를 담는 그릇 — dataclass · pydantic v2 · 메서드 종류
section: tech
part: 6부 파이썬 중급
order: 6.2
status: skeleton
summary: 값을 묶어 다니는 그릇(dict · dataclass · pydantic 모델)을 고르는 기준과, 클래스 안 메서드 셋(@classmethod · @staticmethod · @property)을 우리 설정 파일 · 응답 스키마로 익힙니다.
level: 기초
minutes: 35
owner: 이동원
feature: 공통
work: 3차 (사)
prereq: python-import-typing
tags: 파이썬, dataclass, pydantic, 설정, property
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- dict · `dataclass` · pydantic 모델 가운데 무엇을 고를지 「바깥에서 들어오는 값인가」 로 가를 수 있습니다.
- `frozen=True` · 기본값에 `field(default_factory=…)` 를 쓰는 까닭을 말할 수 있습니다.
- pydantic v2 의 검사 · 변환(문자열 "3" → 3)과 설정 읽기(pydantic-settings)를 설명할 수 있습니다.
- `@classmethod` · `@staticmethod` · `@property` 를 각각 언제 쓰는지 예로 들 수 있습니다.

## 다룰 질문

1. 서버 안에서만 도는 값과 요청 본문 · `.env` 처럼 바깥에서 오는 값은 왜 그릇을 달리하나요?
2. `dataclass` 의 기본값으로 빈 목록을 바로 쓰면 무엇이 잘못되나요?
3. pydantic v1 꼴(`class Config:`)과 v2 꼴(`model_config = SettingsConfigDict(…)`)은 무엇이 다르고, 옛 꼴의 경고는 왜 시험에서 안 보이나요?
4. 계산해서 돌려주는 값은 메서드로 둘까요, `@property` 로 둘까요?

## 보여 줄 코드

- 같은 주문 한 건을 dict · `dataclass` · pydantic 모델로 담아 잘못된 값을 넣어 보는 예(직접 돌린 출력)
- 설정 클래스 하나를 v1 꼴에서 v2 꼴로 옮기기
- `@classmethod` 로 다른 꼴의 입력에서 객체를 만드는 예

## 우리 프로젝트와 닿는 곳

- `app/config.py` 의 `Settings(BaseSettings)` — 231행의 `class Config:` 가 v1 꼴이라 pydantic v2 가 경고를 내지만, `pytest.ini` 가 DeprecationWarning 을 걸러 시험에서는 보이지 않는다.
- `app/` 의 `@dataclass` 를 쓰는 파일 16개 · 라우터의 요청 · 응답 스키마(Pydantic)

## 먼저 읽을 1차 자료

- multi-db-lab 실습 저장소(2026-10-12 판)의 기술 노트 tech003(dataclass) · tech016(pydantic · pydantic-settings) · tech012(`@classmethod` · `@staticmethod` · `@property`)
- pydantic 공식 문서 「Migration Guide」(v1 → v2) · 파이썬 문서 `dataclasses`
