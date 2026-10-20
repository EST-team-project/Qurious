---
slug: langchain-basics
title: LangChain 기초 — 체인(LCEL) · 검색기 · 출력 파서
section: tech
part: 8부 AI 에이전트
order: 8.1
status: skeleton
summary: 언어 모델 앱의 부품(검색기 · 프롬프트 · 모델 · 출력 파서)을 | 연산자로 이어 붙이는 LangChain 표현 언어(LCEL)를, 앱의 수집 문서 검색 체인으로 익힙니다.
level: 기초
minutes: 30
owner: 이동원
prereq: rag-basics
tags: LangChain, LCEL, Runnable, 검색기, 프롬프트, 출력 파서
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- Runnable 이 무엇이고, `|` 로 이으면 무엇이 만들어지는지 말할 수 있습니다.
- 검색기 · 프롬프트 · 모델 · 출력 파서가 각각 무엇을 받고 무엇을 넘기는지 그릴 수 있습니다.
- 같은 RAG 를 체인으로 짤 때와 함수를 직접 이어 짤 때, 시험하기 · 고치기가 어떻게 다른지 비교할 수 있습니다.

## 다룰 질문

1. `retriever | format_docs | prompt | llm | StrOutputParser()` 에서 각 칸은 무엇을 받아 무엇을 넘기나요?
2. 체인 맨 앞의 `{"context": …, "question": RunnablePassthrough()}` 사전은 왜 필요한가요?
3. LangChain 의 `QdrantVectorStore` 로 찾을 때와 `qdrant-client` 를 직접 부를 때는 무엇이 다른가요?
4. 앱은 Qdrant 점의 글 칸 이름이 다른 문서도 읽으려고 `QdrantVectorStore` 를 이어받은 클래스를 둡니다. 이어받기로 고친 곳은 어디인가요?
5. 근거 답([3.1 RAG](#/p/rag-basics))처럼 단계 사이에 검사(출처 번호 · 숫자)를 끼워야 할 때 체인은 어떻게 나누나요?

## 보여 줄 코드

- 앱의 LCEL 체인 다섯 칸(`app/services/rag_pipeline.py` 의 `rag_search` 안)
- 임베딩(`OllamaEmbeddings`)과 벡터 저장소(`QdrantVectorStore`)를 만드는 곳
- 같은 질문을 체인 없이 함수 넷으로 이어 짠 판과 나란히 놓고 중간 값 찍어 보기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- AI 투자 상담과 수집 문서 검색이 LangChain 체인을 씁니다. 법령 근거 답(`app/services/kb_answer.py`)은 LangChain 을 쓰지 않습니다.
- 의존 묶음은 `requirements.txt` 의 `langchain` · `langchain-core` · `langchain-community` · `langchain-ollama` · `langchain-qdrant` 다섯입니다.
- 다음 장 [8.2 LangGraph 상담 에이전트](#/p/langgraph-agent) 가 이 부품들 위에 고리를 얹습니다.

## 먼저 읽을 1차 자료

- LangChain 문서 <https://docs.langchain.com/oss/python/langchain/overview>
- LangChain 문서 「Tools」 <https://docs.langchain.com/oss/python/langchain/tools>
- langchain-qdrant 안내(Qdrant 문서의 LangChain 연동 절) <https://qdrant.tech/documentation/frameworks/langchain/>
