---
slug: hybrid-search-rrf
title: 낱말 검색과 섞어 찾기 — BM25 · FTS5 · RRF
section: tech
part: 3부 근거 RAG
order: 3.3
status: skeleton
summary: 낱말 검색의 점수 BM25 가 무엇을 세는지, SQLite FTS5 로 한국어를 찾는 요령, 두 검색을 순위로 합치는 RRF 를 깊게 다룹니다.
level: 기초
minutes: 35
owner: 이동원
feature: P01-①-3
work: W5
prereq: rag-basics
tags: BM25, FTS5, trigram, RRF, 하이브리드
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 W5 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- BM25 의 세 요소(낱말 빈도 · 드문 정도 · 문서 길이)를 설명할 수 있습니다.
- 한국어에 trigram 을 쓸 때의 장단점을 말할 수 있습니다.
- RRF 의 k 가 결과를 어떻게 바꾸는지 계산할 수 있습니다.

## 다룰 질문

1. 「제17조」 처럼 정확한 낱말은 왜 뜻 검색에서 놓치나요?
2. 두 글자 검색어(세금 · 배당)는 trigram 에서 어떻게 찾나요?
3. BM25 점수와 코사인 점수를 그냥 더하면 안 되는 까닭은?
4. RRF 대신 점수 정규화로 합치는 방법은 무엇이 다른가요?

## 보여 줄 코드

- FTS5 `bm25()` 와 `highlight()` · `snippet()`
- k 를 바꿔 가며 RRF 순위가 바뀌는 표 만들기

## 우리 프로젝트와 닿는 곳

- 목표 기능 ① 상세 설계서 5.3.3(섞어 찾기) · 5.1.7(FTS5 검색)
- 3.1 RAG 장 「직접 해 보기」 의 낱말 검색 결과

## 먼저 읽을 1차 자료

- SQLite FTS5 <https://www.sqlite.org/fts5.html>
- Elastic, Reciprocal rank fusion <https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion>
