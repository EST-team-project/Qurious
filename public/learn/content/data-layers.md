---
slug: data-layers
title: 원문 · 정제 · 파생 — 세 층(Bronze · Silver · Gold)
section: tech
part: 2부 데이터 파이프라인
order: 2.1
status: skeleton
summary: 받은 원문을 그대로 남기고(Bronze), 규격에 맞춰 정리하고(Silver), 계산한 결과를 따로 두는(Gold) 까닭과, 우리 수집기가 그 층을 어떻게 갖고 있는지 봅니다.
level: 입문
minutes: 25
owner: 이동원
feature: P01-①-2
work: W2
prereq: map
tags: Bronze, Silver, Gold, 데이터 레이크, 원문 보관
updated: 2026-10-01
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 세 층이 각각 무엇을 지키는지 설명할 수 있습니다.
- 원문을 해시(sha256)와 함께 남기는 까닭을 말할 수 있습니다.
- 우리 수집기의 표가 어느 층인지 짚을 수 있습니다.

## 다룰 질문

1. 정제한 표가 있는데 원문은 왜 남기나요?
2. 파생 값(수정주가)이 틀렸을 때 어느 층에서 다시 만드나요?
3. 객체 저장소(MinIO)와 분석 DB(DuckDB) 없이도 같은 층을 가질 수 있을까요?
4. 카탈로그(수집 이력)는 무엇을 적나요?

## 보여 줄 코드

- 원문 바이트와 sha256 을 함께 저장하는 함수
- Silver 규격 검사 → Gold 계산으로 이어지는 짧은 흐름

## 우리 프로젝트와 닿는 곳

- 「자료 안내」 화면의 원문 · 정제 · 파생 구분
- 수집 DB `raw_response` · `price_daily` · 수정주가 표

## 먼저 읽을 1차 자료

- Databricks, 「Medallion architecture」 <https://www.databricks.com/glossary/medallion-architecture>
- python-crawling-lab 실습 저장소의 Bronze · Silver · Gold 구성
