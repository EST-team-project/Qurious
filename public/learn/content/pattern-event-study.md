---
slug: pattern-event-study
title: 사건 연구 — 패턴이 나온 뒤 5거래일 동안 무슨 일이 있었나
section: tech
part: 9부 신호와 설명
order: 9.4
status: skeleton
summary: 패턴이 나온 날을 사건으로 보고 그 뒤 5거래일 수익률과 시장 대비 초과수익을 모아, 패턴에 정말 앞날을 가르는 힘이 있는지 확인하는 사건 연구(event study)의 규칙(겹침 빼기 · 기준선 · 봉인 구간)을 익힙니다.
level: 심화
minutes: 40
owner: 이동원
prereq: candlestick-patterns-sr
tags: 사건 연구, 이벤트 스터디, 초과수익, 패턴 통계, 기준선
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 사건 · 결과 기간 · 기준선 세 가지로 사건 연구를 설계할 수 있습니다.
- 같은 종목에서 사건이 잇달아 나올 때 결과 구간이 겹치지 않게 빼는 까닭을 설명할 수 있습니다.
- 「패턴 뒤 5거래일 평균 수익률」 같은 숫자를 기준선 · 표본 수와 함께 읽을 수 있습니다.

## 다룰 질문

1. 날 t 의 패턴이 날 t 까지의 봉만으로 탐지되었는지는 어떻게 확인하나요?
2. 5거래일 뒤 수익률에서 같은 기간 코스피 수익률을 빼면 무엇이 보이나요?
3. 같은 패턴이 이틀 뒤 또 나오면 왜 두 번째 사건을 빼나요?
4. 기준선을 「그 종목의 모든 날 5일 수익률 평균」 으로 잡은 까닭은?
5. 최근 구간을 봉인해 두고 통계에서 빼면 무엇을 지킬 수 있나요?

## 보여 줄 코드

- `app/services/pattern_stats.py` 의 `detect_events` · `thin`(겹침 빼기) · `event_study` · `summarize`
- 한 종목 1년 자료로 사건 표를 만들어 평균 · 표본 수 · 기준선을 함께 찍기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 패턴 통계 화면이 이 계산 결과를 보여 줍니다. 탐지 정의는 화면 탐지기([9.2](#/p/candlestick-patterns-sr))와 같고, 두 쪽이 날마다 같은 결과를 내는지 시험으로 맞대 봅니다.
- 전 종목 통계에서 패턴 이름만으로 5거래일 뒤 방향이 갈린다는 근거는 보이지 않았습니다. 신호 설명([9.5](#/p/xai-shap))이 이 점을 함께 적는 까닭입니다.

## 먼저 읽을 1차 자료

- MacKinlay, A. C. (1997). 「Event Studies in Economics and Finance」, *Journal of Economic Literature* 35(1).
- Lo, A. W. · Mamaysky, H. · Wang, J. (2000). 「Foundations of Technical Analysis」, *Journal of Finance* 55(4).
