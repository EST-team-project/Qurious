---
slug: embedding-vector-search
title: 임베딩과 벡터 검색 — 코사인 · HNSW · Qdrant
section: tech
part: 3부 근거 RAG
order: 3.2
status: skeleton
summary: 임베딩 모델이 글을 벡터로 바꾸는 원리, 수만 개 벡터에서 가까운 것을 빨리 찾는 근사 검색(HNSW), Qdrant 의 컬렉션 · 점 · 거르기를 익힙니다.
level: 기초
minutes: 40
owner: 이동원
feature: P01-①-3
work: W5
prereq: rag-basics
tags: 임베딩, 코사인, HNSW, Qdrant, 벡터 DB
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 W5 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- 코사인 · 내적 · 유클리드 거리의 관계를 설명할 수 있습니다.
- 정확 검색과 근사 검색(HNSW)의 차이를 말할 수 있습니다.
- Qdrant 에 점을 넣고 payload 로 걸러 찾을 수 있습니다.

## 다룰 질문

1. 벡터 길이를 1로 맞추면 무엇이 쉬워지나요?
2. HNSW 는 왜 빠르고, 무엇을 조금 잃나요?
3. Qdrant 점 ID 로 sha256 문자열을 바로 쓸 수 없는 까닭은?
4. 「기준일에 시행 중인 판만」 은 어떻게 거르나요?
5. bge-m3 와 nomic-embed-text 는 무엇으로 비교하나요?

## 보여 줄 코드

- `qdrant-client` 로 컬렉션 만들기 · upsert · `query_points` + Filter
- sha256 → UUID 로 점 ID 만들기

## 우리 프로젝트와 닿는 곳

- 목표 기능 ① 상세 설계서 5.3.3(컬렉션 `kb_v1` · payload)
- Qurious compose 에 Qdrant 서비스 더하기(통합본 `vector` 프로필)

## 먼저 읽을 1차 자료

- Malkov · Yashunin, HNSW <https://arxiv.org/abs/1603.09320>
- Qdrant 문서 <https://qdrant.tech/documentation/>
- Chen 등, BGE M3 <https://arxiv.org/abs/2402.03216>
