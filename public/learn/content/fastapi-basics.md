---
slug: fastapi-basics
title: FastAPI 로 API 만들기 — 라우터 · 의존성 · 스키마
section: tech
part: 6부 서버 · 운영
order: 6.1
status: skeleton
summary: Qurious 서버의 뼈대인 FastAPI 의 라우터 · 의존성 주입(로그인 확인) · Pydantic 스키마 · 동기와 비동기 함수의 차이를 우리 코드로 익힙니다.
level: 입문
minutes: 30
owner: 이동원
feature: 공통
work: 언제든
prereq: map
tags: FastAPI, 라우터, 의존성, 스키마
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 필요해질 때 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- 라우터를 나누고 앱에 붙일 수 있습니다.
- 의존성으로 로그인 사용자를 받을 수 있습니다.
- 블로킹 호출이 있을 때 `def` 와 `async def` 를 고를 수 있습니다.

## 다룰 질문

1. `async def` 안에서 블로킹 호출을 하면 무슨 일이 생기나요?
2. 같은 경로 모양(`/categories` · `/{name}`)은 왜 등록 차례가 중요한가요?
3. 오류 응답 모양을 하나로 모으려면?

## 보여 줄 코드

- `app/routes/learn.py` — 동기 함수와 로그인 의존성
- Pydantic 으로 요청 본문 검사

## 우리 프로젝트와 닿는 곳

- `app/main.py` 라우터 등록 · `app/lib/session.py` 의 `get_current_user`

## 먼저 읽을 1차 자료

- FastAPI 문서 <https://fastapi.tiangolo.com/>
