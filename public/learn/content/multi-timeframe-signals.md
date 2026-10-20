---
slug: multi-timeframe-signals
title: 여러 주기 신호 합치기 — 60분 · 일 · 주봉과 신뢰도
section: tech
part: 9부 신호와 설명
order: 9.3
status: skeleton
summary: 60분봉 · 일봉 · 주봉마다 지표 규칙으로 매긴 점수를 가중 평균해 매수 · 매도 · 관망을 정하고, 주기들이 같은 방향을 가리키는 정도로 신뢰도(0 ~ 1)를 매기는 방법과 그날 종가까지의 봉만 쓰는 규칙을 익힙니다.
level: 기초
minutes: 35
owner: 이동원
prereq: indicator-definitions
tags: 다중 주기, 멀티 타임프레임, 신호, 신뢰도, 주봉
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 주기마다 −6 ~ +6 점수를 매기는 규칙과, 가중치(0.2 · 0.5 · 0.3)로 합친 종합 점수를 계산할 수 있습니다.
- 종합 점수의 경계(±1 · ±2.5)로 신호와 강도를 정하는 표를 읽을 수 있습니다.
- 신뢰도가 확률이 아니라 「방향 일치도와 점수 크기의 평균」 이라는 것을 설명할 수 있습니다.

## 다룰 질문

1. 한 주기의 점수는 어떤 규칙들(RSI · 이동평균 배열 · MACD · 볼린저)의 합인가요?
2. 일봉에 가장 큰 가중치(0.5)를 둔 까닭은?
3. 주기 셋 중 둘이 매수 쪽인데 종합 점수가 관망일 수 있나요?
4. 날 D 의 주봉은 그 주가 끝나지 않았으면 어떻게 만드나요?
5. 신호를 매 거래일 한 번 기록해 두면 무엇을 할 수 있나요(지난 날의 설명 · 통계)?

## 보여 줄 코드

- `app/services/patterns.py` 의 `timeframe_score`(주기 점수와 근거 문장)
- `app/services/mtf_signals.py` 의 `combine`(종합 점수 · 신뢰도) · `classify`(신호 · 강도) · `signal_at`(날 D 까지의 봉만 읽기)
- 같은 종목의 세 주기 점수를 손으로 합쳐 함수 결과와 맞대기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 매일 수집 러너가 분봉 대상 401종목의 신호를 계산해 기록합니다. 신호 설명 카드([9.5 추천 이유 설명](#/p/xai-shap))는 이 기록을 읽습니다.
- 60분봉이 없는 종목은 남은 주기로만 셈하고, 설명에 그 사실을 적습니다.

## 먼저 읽을 1차 자료

- Elder, A. (2014). *The New Trading for a Living*. Wiley. (세 화면 매매 · Triple Screen)
- TradingView Pine Script 문서 「Other timeframes and data」(`request.security`) <https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/>
