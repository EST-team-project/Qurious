---
slug: docker-compose-dev
title: Docker Compose 와 개발 모드
section: tech
part: 6부 서버 · 운영
order: 6.2
status: skeleton
summary: 앱 · DB · Redis · Celery 를 Compose 로 함께 띄우는 법과, 코드를 고치면 바로 반영되는 개발 모드(연결 · 자동 재시작)의 원리를 익힙니다.
level: 입문
minutes: 25
owner: 이동원
feature: 공통
work: 언제든
prereq: fastapi-basics
tags: Docker, Compose, 볼륨, 개발 모드
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 필요해질 때 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- 서비스 · 볼륨 · 환경 변수 파일의 역할을 설명할 수 있습니다.
- 덧씌우기 파일(compose.dev.yml)로 개발 모드를 만들 수 있습니다.
- 읽기 전용 연결과 쓰기 가능한 볼륨을 구분해 쓸 수 있습니다.

## 다룰 질문

1. Windows 폴더를 연결하면 파일 변경 알림이 왜 안 오나요(폴링)?
2. 컨테이너가 쓸 수 있는 곳은 어디로 정하나요?
3. requirements 를 바꾸면 왜 이미지를 다시 만들어야 하나요?

## 보여 줄 코드

- `scripts/personal/compose.dev.yml` 읽기
- `start.ps1 -Dev` 가 하는 일

## 우리 프로젝트와 닿는 곳

- 로컬 실행 안내서 · `scripts/personal/`

## 먼저 읽을 1차 자료

- Docker Compose 문서 <https://docs.docker.com/compose/>
