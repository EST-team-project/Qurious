---
slug: testing-pytest
title: 시험 코드 — pytest · 가짜 객체 · 계약 시험
section: tech
part: 6부 서버 · 운영
order: 6.3
status: skeleton
summary: 네트워크 · DB 없이 도는 시험을 만드는 법(가짜 객체 · 저장해 둔 응답)과, API 의 약속(상태 코드 · 응답 모양)을 지키는 계약 시험을 우리 시험으로 익힙니다.
level: 기초
minutes: 30
owner: 이동원
feature: 공통
work: 언제든
prereq: fastapi-basics
tags: pytest, 가짜 객체, 계약 시험
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 필요해질 때 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- 외부 호출을 가짜 객체로 바꿔 시험할 수 있습니다.
- 의존성 덮어쓰기로 로그인이 필요한 API 를 시험할 수 있습니다.
- 시험이 통과한 뒤에도 결과를 눈으로 훑는 까닭을 말할 수 있습니다.

## 다룰 질문

1. 가짜 HF 저장소로 412 충돌을 어떻게 재현하나요?
2. DB 가 필요한 시험은 어떻게 따로 돌리나요?
3. 「시험은 통과했는데 자료가 틀렸다」 는 어떻게 생기나요?

## 보여 줄 코드

- `tests/test_learn.py` 의 가짜 HfApi
- `app.dependency_overrides` 로 로그인 바꾸기

## 우리 프로젝트와 닿는 곳

- `scripts/personal/test.ps1` · 테스트 계획서

## 먼저 읽을 1차 자료

- pytest 문서 <https://docs.pytest.org/>
