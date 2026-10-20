---
slug: storage-ports-adapters
title: 저장소 다섯과 포트 · 어댑터 — PostgreSQL · SQLite · Redis · Qdrant · Neo4j
section: tech
part: 7부 서버 · 운영
order: 7.5
status: skeleton
summary: Qurious 가 쓰는 저장소 다섯이 각각 무엇을 맡는지와, 저장소를 바꿔도 기능 코드를 덜 고치게 하는 포트(약속) · 어댑터(구현) 구조를, 읽기 전용으로 붙인 SQLite 의 장애 사례로 익힙니다.
level: 심화
minutes: 45
owner: 이동원
feature: 공통
work: 3차 (사)
prereq: python-interfaces, docker-compose-dev
tags: 저장소, PostgreSQL, SQLite, Redis, Qdrant, Neo4j, 포트, 어댑터
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 저장소 다섯(PostgreSQL · SQLite · Redis · Qdrant · Neo4j)이 각각 무엇을 담는지, 왜 하나로 몰지 않았는지 말할 수 있습니다.
- 포트(약속)와 어댑터(구현)를 나누면 무엇을 갈아 끼우기 쉬워지는지 설명할 수 있습니다.
- 다른 프로세스가 쓰는 SQLite 를 읽기 전용으로 붙일 때의 함정(저널 방식 · 보조 파일)을 알 수 있습니다.

## 다룰 질문

1. 사용자 · 주문 · 모의 장부는 PostgreSQL 에, 수집 자료는 SQLite 파일에 둡니다. 왜 나눴나요?
2. Redis 는 세션 · 캐시 · 작업 대기열을 맡습니다. 꺼지면 무엇이 멈추고 무엇은 그대로인가요?
3. 문서 근거 검색(Qdrant)과 종목 관계(Neo4j)는 왜 관계형 DB 가 아니라 전용 저장소인가요?
4. 앱이 읽기 전용으로 붙인 WAL 모드 SQLite 가 「unable to open database file」 로 멈춘 까닭은?
5. 기능 코드가 저장소를 직접 부르지 않고 약속을 거치게 하려면 어디부터 바꾸나요?

## 보여 줄 코드

- 저장소마다 연결을 만드는 곳을 한 곳(팩토리)에 모은 꼴
- 같은 약속(포트) 뒤에 실제 저장소 어댑터와 시험용 메모리 어댑터를 두는 예
- SQLite 를 `mode=ro` 로 열 때 롤백 저널과 WAL 의 차이를 보여 주는 재현(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 도커 컴포즈의 PostgreSQL · Redis · Qdrant · Neo4j 와 도커 밖 수집 러너의 SQLite(수집 DB · 근거 DB · 검색 색인) — README 구조 그림
- 수집 DB · 근거 DB · 검색 색인을 앱이 읽기 전용으로 붙인 일과, 그 때문에 생긴 장애 세 번
- 증권사 연결의 약속(`app/services/brokers/base.py`)은 6부 「약속으로 갈아 끼우기」 와 짝이다.

## 먼저 읽을 1차 자료

- multi-db-lab 실습 저장소(2026-10-12 판)의 `Readme.md` 의 아키텍처 · DB 절
- SQLite 문서 「Write-Ahead Logging」 · 「URI filenames」(mode=ro · immutable)
- Alistair Cockburn, 「Hexagonal Architecture」(포트 · 어댑터)
