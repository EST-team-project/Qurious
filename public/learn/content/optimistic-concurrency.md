---
slug: optimistic-concurrency
title: 같은 글을 둘이 고치면? — 낙관적 동시성
section: tech
part: 6부 서버 · 운영
order: 6.4
status: skeleton
summary: 잠그지 않고 저장할 때 바뀐 것을 알아채는 낙관적 동시성을, 이 교재의 팀 자료 저장(HF parent_commit · 412 · 409)을 예로 익힙니다.
level: 기초
minutes: 25
owner: 이동원
feature: 공통
work: 이 교재
prereq: map
tags: 낙관적 동시성, 충돌, 버전, HF
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 필요해질 때 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- 낙관적 · 비관적 동시성의 차이를 설명할 수 있습니다.
- 판(버전)을 비교해 충돌을 알리는 흐름을 그릴 수 있습니다.
- 충돌을 사람에게 보이는 화면을 설계할 수 있습니다.

## 다룰 질문

1. 잠금 대신 판 비교를 고른 까닭은(서버 없음 · 잠금을 풀 사람 없음)?
2. HTTP 412 와 409 는 무엇이 다른가요?
3. 다른 글이 바뀌어서 난 412 는 왜 사람에게 묻지 않고 다시 시도하나요?

## 보여 줄 코드

- `app/services/learn_team.py` 의 `_commit` — parent_commit 과 한 번 재시도
- git 블롭 해시로 판 만들기

## 우리 프로젝트와 닿는 곳

- 개념 학습 설계서 5.6절 · 그림 3

## 먼저 읽을 1차 자료

- Martin Fowler, Optimistic Offline Lock <https://martinfowler.com/eaaCatalog/optimisticOfflineLock.html>
- huggingface_hub `create_commit` 의 `parent_commit` <https://huggingface.co/docs/huggingface_hub/guides/upload>
