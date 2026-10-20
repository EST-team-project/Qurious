---
slug: graph-rag-neo4j
title: GraphRAG — 벡터 검색에 종목 관계 그래프를 더하기
section: tech
part: 8부 AI 에이전트
order: 8.4
status: skeleton
summary: 비슷한 글을 찾는 벡터 검색에, 같은 업종 · 경쟁사 · 공급망 같은 종목 관계를 그래프 DB(Neo4j)에서 꺼내 더하는 GraphRAG 의 구조와 Cypher 질의를 앱의 그래프 검색 코드로 익힙니다.
level: 심화
minutes: 40
owner: 이동원
prereq: knowledge-graph-basics, langchain-basics
tags: GraphRAG, Neo4j, Cypher, 지식 그래프, 벡터 검색
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 노드 · 관계 · 속성으로 「회사가 업종에 속한다 · 다른 회사와 경쟁한다 · 부품을 공급한다」 를 나타낼 수 있습니다.
- Cypher 의 `MATCH (a)-[:관계]->(b)` 꼴로 이웃 노드를 찾을 수 있습니다.
- 벡터 검색만 쓸 때와 그래프 문맥을 더할 때, 답의 근거가 어떻게 달라지는지 비교할 수 있습니다.

## 다룰 질문

1. 질문에서 종목을 어떻게 알아보고(종목 이름 · 코드 찾기), 그 종목의 이웃을 어디까지 꺼내나요?
2. `BELONGS_TO` · `COMPETES_WITH` · `SUPPLIES_TO` 세 관계는 방향이 있나요? 경쟁 관계는 왜 방향 없이 찾나요?
3. 벡터 검색 결과와 그래프 결과를 한 프롬프트에 넣을 때 무엇을 먼저 두나요?
4. 그래프의 관계는 누가 언제 넣나요(처음 채우기 · 갱신)? 틀린 관계가 들어가면 답에 어떻게 드러나나요?
5. 관계형 DB 의 재귀 질의(`WITH RECURSIVE`)로도 같은 일을 할 수 있나요?

## 보여 줄 코드

- `app/services/graph_service.py` 의 `get_related_stocks` — 같은 업종 · 경쟁사 · 공급사 · 고객사를 찾는 Cypher 질의들
- `app/services/graph_rag.py` 의 `graph_rag_search` — 벡터 검색(`rag_search`)과 그래프 문맥을 함께 모으는 차례
- 같은 질문을 벡터 검색만 · 그래프 문맥까지로 두 번 물어 넘기는 근거를 견주기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 도커 컴포즈의 `neo4j` 서비스와 `app/database/neo4j.py` 연결
- 용어 관계 그래프([4.2 지식 그래프 맛보기](#/p/knowledge-graph-basics))는 같은 생각을 금융 용어에 쓴 것입니다.
- 앞 장의 LangChain 검색기([8.1](#/p/langchain-basics))가 벡터 쪽을 맡습니다.

## 먼저 읽을 1차 자료

- Neo4j 문서 「Cypher Manual」 <https://neo4j.com/docs/cypher-manual/current/>
- Edge, D. 등 (2024). 「From Local to Global: A Graph RAG Approach to Query-Focused Summarization」 <https://arxiv.org/abs/2404.16130>
