---
slug: rag-evaluation
title: RAG 평가 — Recall@k · MRR · 충실도
section: tech
part: 3부 근거 RAG
order: 3.6
status: skeleton
summary: 검색과 생성을 따로 재는 지표(Recall@k · MRR · 출처 일치율 · 근거 밖 문장 비율)와, 질문 50개 평가셋을 만드는 법을 익힙니다.
level: 심화
minutes: 40
owner: 이동원
feature: P01-①-3
work: W8
prereq: hybrid-search-rrf
tags: 평가, Recall@k, MRR, 충실도, 평가셋
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 W8 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- 검색 지표와 생성 지표를 구분할 수 있습니다.
- 질문마다 정답 조각을 적은 평가셋을 만들 수 있습니다.
- 모델 · 임베딩 후보를 같은 평가셋으로 비교할 수 있습니다.

## 다룰 질문

1. Recall@5 0.8 은 무엇을 뜻하나요?
2. MRR 은 Recall 이 못 보는 무엇을 보나요?
3. 충실도(faithfulness)는 사람이 재야 하나요, 모델이 재도 되나요?
4. 평가셋에 반드시 넣을 함정 질문은 무엇인가요?

## 보여 줄 코드

- Recall@k · MRR 계산 함수와 작은 평가셋
- 임베딩 두 개를 같은 평가셋으로 비교하는 표

## 우리 프로젝트와 닿는 곳

- 목표 기능 ① 상세 설계서 5.3.5(평가) · 인수 기준 9
- 💬 ④ 답 만드는 LLM 고르기

## 먼저 읽을 1차 자료

- Es 등, RAGAS <https://arxiv.org/abs/2309.15217>
- Anthropic, Contextual Retrieval(1 − Recall@20) <https://www.anthropic.com/news/contextual-retrieval>
