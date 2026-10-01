---
slug: knowledge-graph-basics
title: 지식 그래프 맛보기 — 노드 · 간선 · 탐색 깊이
section: tech
part: 4부 지식 구조
order: 4.2
status: skeleton
summary: 용어를 노드로, 관계를 간선으로 보면 「연관 개념 탐색」 이 그래프 탐색이 됩니다. 깊이 1 · 2 탐색과 화면에 그리는 데이터 모양을 익힙니다.
level: 입문
minutes: 25
owner: 이동원
feature: P01-①-1
work: W5
prereq: thesaurus-skos
tags: 지식 그래프, 노드, 간선, 탐색
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 W5 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- 노드 · 간선 목록으로 그래프를 표현할 수 있습니다.
- 깊이 제한 탐색(BFS)으로 이웃을 모을 수 있습니다.
- 그래프 DB 가 필요한 때와 아닌 때를 구분할 수 있습니다.

## 다룰 질문

1. 용어 755개 규모에 그래프 DB(Neo4j)가 필요할까요?
2. 깊이 2 탐색 결과가 너무 커지면 어떻게 줄이나요?
3. 화면 그래프 라이브러리는 어떤 JSON 을 기대하나요?

## 보여 줄 코드

- 노드 · 간선 JSON 과 BFS 깊이 제한
- SQL 재귀 질의(WITH RECURSIVE)로 이웃 찾기

## 우리 프로젝트와 닿는 곳

- API `GET /api/glossary/{id}/graph?depth=1|2`(설계서 7절)
- 강사님 기초 코드의 Neo4j 그래프 기능(분석 A2 · A10 기록)

## 먼저 읽을 1차 자료

- PostgreSQL WITH 질의 <https://www.postgresql.org/docs/current/queries-with.html>
