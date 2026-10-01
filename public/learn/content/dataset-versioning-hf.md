---
slug: dataset-versioning-hf
title: 데이터셋 판과 공유 — HF Hub · 매니페스트 · 태그
section: tech
part: 2부 데이터 파이프라인
order: 2.3
status: skeleton
summary: 팀이 같은 데이터를 쓰게 하는 Hugging Face 비공개 데이터셋의 구조(파일 · 커밋 · 태그)와, 매니페스트로 「같은 판인가」 를 확인하는 법을 익힙니다.
level: 기초
minutes: 30
owner: 이동원
feature: P01-①-2
work: W2
prereq: data-layers
tags: Hugging Face, 데이터셋, 매니페스트, 태그, 비공개
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 **뼈대**입니다 — 목표 · 다룰 질문 · 보여 줄 코드 · 1차 자료만 있고, 본문은 W2 구현 직전에 채웁니다.
> 읽다가 더 알고 싶은 개념이 생기면 알려 주세요. 목차에 더합니다.

## 이 장에서 할 수 있게 되는 것

- 데이터셋 저장소가 git 처럼 커밋 · 태그를 갖는다는 것을 설명할 수 있습니다.
- 매니페스트(파일별 행 수 · 해시)로 원격과 로컬이 같은지 확인할 수 있습니다.
- 올리기 전에 비공개 여부를 확인하는 까닭을 말할 수 있습니다.

## 다룰 질문

1. HF 의 저장소 만들기 기본값은 공개일까요, 비공개일까요?
2. 파케이 한 줄이 바뀌면 전체를 다시 올려야 하나요(Xet 증분)?
3. 날짜 태그는 무엇을 보장하나요?
4. 팀원 자료는 왜 `contrib/<아이디>/` 에 따로 두나요?

## 보여 줄 코드

- `HfApi.create_repo(private=True)` 와 `repo_info().private` 확인
- 매니페스트 대조 — 행 수 · sha256

## 우리 프로젝트와 닿는 곳

- `scripts/hf_dataset.py`(Xet 증분 · 날짜 태그 · 비공개 검사)
- 새 데이터셋 `qurious-quant/krx-ohlcv`(설계서 5.1.2)

## 먼저 읽을 1차 자료

- Hugging Face Hub — Datasets <https://huggingface.co/docs/hub/datasets>
- huggingface_hub — 올리기 안내 <https://huggingface.co/docs/huggingface_hub/guides/upload>
