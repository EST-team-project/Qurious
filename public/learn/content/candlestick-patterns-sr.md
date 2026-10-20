---
slug: candlestick-patterns-sr
title: 캔들 패턴 · 지지 · 저항 · 돌파를 코드로 찾기
section: tech
part: 9부 신호와 설명
order: 9.2
status: skeleton
summary: 도지 · 해머 · 장악형 같은 캔들 패턴, 피벗 고점 · 저점을 묶어 만든 지지 · 저항선, 거래량을 함께 보는 돌파 신호를 봉 자료에서 코드로 찾는 규칙과, 그 규칙이 그날까지의 봉만 쓰게 하는 법을 익힙니다.
level: 기초
minutes: 40
owner: 이동원
prereq: indicator-definitions
tags: 캔들 패턴, 지지선, 저항선, 돌파, 피벗
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 캔들 패턴 하나를 「몸통 · 꼬리 · 앞 봉과의 관계」 조건으로 바꿔 적을 수 있습니다.
- 피벗 고점 · 저점을 가격대로 묶어 지지 · 저항의 세기(닿은 횟수)를 매기는 방법을 설명할 수 있습니다.
- 돌파 신호에 거래량 조건을 붙이는 까닭과, 패턴 탐지가 미래 봉을 보지 않게 하는 법을 말할 수 있습니다.

## 다룰 질문

1. 「해머」 를 코드로 적으면 몸통 · 아래꼬리 · 위꼬리의 비율 조건은 어떻게 되나요?
2. 피벗 고점은 양옆 몇 봉보다 높아야 하나요? 그 「양옆」 의 오른쪽은 언제 확정되나요?
3. 가까운 가격대의 피벗을 하나로 묶는 허용 폭(%)은 어떻게 정하나요?
4. 저항 돌파에 거래량 확인을 붙이면 무엇이 줄어드나요?
5. 52주 신고가 · 골든크로스 · 볼린저 밴드 돌파는 패턴과 무엇이 다른가요?

## 보여 줄 코드

- `app/services/patterns.py` 의 `detect_candle_patterns` · `support_resistance` · `detect_breakouts`
- 패턴 하나를 손으로 그린 봉 다섯 개에 돌려 보기(직접 돌린 출력)
- 피벗 확정에 필요한 오른쪽 봉 때문에 신호가 늦게 나오는 예

## 우리 프로젝트와 닿는 곳

- 「차트 패턴·지지/저항·멀티타임프레임」 화면이 이 함수들로 패턴 · 지지 · 저항을 표시합니다.
- 같은 탐지 정의를 과거 모든 날에 돌려 「패턴 뒤 5거래일」 을 센 것이 [9.4 사건 연구](#/p/pattern-event-study) 입니다.
- 패턴 이름만으로 앞날의 방향이 갈린다는 근거는 전 종목 통계에서 보이지 않았습니다. 화면 설명도 그 점을 함께 적습니다.

## 먼저 읽을 1차 자료

- TA-Lib 패턴 인식 함수(CDL*) 목록 <https://ta-lib.org/functions/>
- Nison, S. (2001). *Japanese Candlestick Charting Techniques* (2nd ed.). Prentice Hall Press.
- Lo, A. W. · Mamaysky, H. · Wang, J. (2000). 「Foundations of Technical Analysis」, *Journal of Finance* 55(4).
