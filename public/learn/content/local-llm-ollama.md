---
slug: local-llm-ollama
title: 로컬 LLM — Ollama · 양자화 · CPU 추론
section: tech
part: 3부 근거 RAG
order: 3.7
status: skeleton
summary: GPU 없이 이 PC 에서 언어 모델을 돌리는 Ollama 의 구조(모델 받기 · API · 유지 시간)와 양자화, CPU 추론 속도를 다루는 법을 익힙니다.
level: 기초
minutes: 30
owner: 이동원
feature: P01-①-3
work: W6
prereq: rag-basics
tags: Ollama, LLM, 양자화, CPU 추론
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 W6 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- Ollama 의 `/api/generate` · `/api/chat` · `/api/embed` 를 구분해 쓸 수 있습니다.
- 양자화가 크기 · 속도 · 품질에 주는 영향을 설명할 수 있습니다.
- 답이 느릴 때 쓸 수 있는 방법(짧은 답 · 스트리밍 · 작은 모델)을 고를 수 있습니다.

## 다룰 질문

1. 80억 매개변수 모델이 4.9GB 인 까닭은(양자화)?
2. `temperature 0` · `seed` 를 주면 늘 같은 답이 나오나요?
3. 컨테이너 안의 앱이 PC 의 Ollama 에 닿으려면 주소를 어떻게 쓰나요?
4. 한국어 답 품질은 어떻게 비교하나요?

## 보여 줄 코드

- `/api/generate` 를 스트리밍으로 받기
- 모델 유지 시간(`keep_alive`)과 첫 답 지연 재기

## 우리 프로젝트와 닿는 곳

- 이 PC 의 Ollama — `llama3.1` 8B · `bge-m3`
- 목표 기능 ① 상세 설계서 3.2(계산 자원) · 13절(CPU LLM 위험)

## 먼저 읽을 1차 자료

- Ollama API 문서 <https://github.com/ollama/ollama/blob/main/docs/api.md>
