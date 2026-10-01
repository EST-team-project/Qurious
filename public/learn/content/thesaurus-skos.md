---
slug: thesaurus-skos
title: 용어 사전과 시소러스 — 연관 · 상위 · 하위 · 혼동
section: tech
part: 4부 지식 구조
order: 4.1
status: skeleton
summary: 용어 사이의 관계를 국제 표준 SKOS 의 방식(연관 · 상위 · 하위)으로 적고, 우리가 더한 「혼동」 관계와 빌드 검사로 관계를 지키는 법을 익힙니다.
level: 기초
minutes: 30
owner: 이동원
feature: P01-①-1
work: W5
prereq: map
tags: 용어사전, 시소러스, SKOS, 연관 개념
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 W5 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- SKOS 의 broader · narrower · related 를 구분할 수 있습니다.
- 관계 규칙(양방향 · 짝 · 자기 참조 금지)을 검사 코드로 쓸 수 있습니다.
- 용어 사전으로 검색어를 넓히는 법(3.1 장 셋째 실행)을 설명할 수 있습니다.

## 다룰 질문

1. 「자산배분 → 리밸런싱」 은 상위 · 하위일까요, 연관일까요?
2. 「배당기준일 ↔ 배당락일」 같은 혼동 쌍은 왜 따로 두나요?
3. 용어 755개의 관계를 사람이 다 적을 수 있나요(후보 자동 · 사람 확정)?
4. 관계를 앱 DB 에 넣을 때 판을 어떻게 맞추나요?

## 보여 줄 코드

- 관계 대칭 · 짝 검사 함수
- 용어 사전으로 검색어 넓히기

## 우리 프로젝트와 닿는 곳

- 용어사전 설계서 v0.1 · `scripts/glossary_build.py` · `app/services/glossary_data/terms.json`
- 목표 기능 ① 상세 설계서 5.4(관계 모델 · API `/api/glossary/{id}/graph`)

## 먼저 읽을 1차 자료

- W3C, SKOS Reference <https://www.w3.org/TR/skos-reference/>
