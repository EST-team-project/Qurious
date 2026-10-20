---
slug: backtest-basics
title: 백테스트의 뼈대 — 체결 시점 · 비용 · 매수 후 보유 기준선
section: tech
part: 10부 백테스트와 성과
order: 10.1
status: skeleton
summary: 신호를 과거 자료에 적용해 성과를 재는 백테스트가 결과를 부풀리지 않으려면 무엇을 정해야 하는지(신호를 언제 체결로 보나 · 수수료 · 세금 · 슬리피지 · 매수 후 보유와의 비교)를 앱의 백테스트 함수로 익힙니다.
level: 기초
minutes: 40
owner: 이동원
prereq: ohlcv-bars, trading-costs-tax
tags: 백테스트, 체결 가정, 슬리피지, 거래 비용, 매수 후 보유
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 신호를 「그날 종가」 에 체결할 때와 「다음 봉 시가」 에 체결할 때의 차이를 설명할 수 있습니다.
- 신호를 한 칸 미루는(`shift(1)`) 까닭, 곧 그날 종가로 낸 신호는 다음 날 수익에만 쓸 수 있다는 규칙을 말할 수 있습니다.
- 수수료 · 증권거래세 · 슬리피지를 넣기 전과 뒤의 성과를 견주고, 매수 후 보유를 기준선으로 읽을 수 있습니다.

## 다룰 질문

1. 오늘 종가로 계산한 신호로 오늘 종가에 샀다고 치면 무엇이 문제인가요?
2. TradingView 의 기본 체결(다음 봉 시가)과 앱의 기본(그날 종가)은 왜 다르고, 앱은 어떻게 둘 다 고를 수 있게 했나요?
3. 슬리피지 10bp 는 얼마이고, 거래가 잦은 전략에서 왜 크게 쌓이나요?
4. 비용을 넣은 전략과 비교할 매수 후 보유에도 비용을 넣어야 하나요?
5. 거래가 한 번도 없었던 백테스트는 화면에 어떻게 보여야 하나요?

## 보여 줄 코드

- `app/services/quant_pipeline.py` 의 `backtest` — 체결 시점 선택(`entry_mode` · `exit_mode`)과 신호 한 칸 미루기
- `app/services/trading_cost.py` 의 `order_costs` — 매수 · 매도 비용의 세목
- 같은 신호를 비용 없음 · 실제 비용 · 실제 비용 + 슬리피지로 세 번 돌려 견주기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 성과 검증 화면과 모의 주문 미리보기가 같은 비용 모델을 씁니다. 세율은 시행일 판을 따릅니다([F.3 매매 비용과 증권거래세](#/p/trading-costs-tax)).
- 삼성전자 1년 백테스트에서 실제 비용과 슬리피지 10bp 를 넣자 기준 전략 넷 모두 매수 후 보유를 넘지 못했습니다. 비용을 넣는 순간 결론이 바뀔 수 있다는 예입니다.
- 계산한 성과를 읽는 법은 [10.2 성과 지표 계산](#/p/performance-metrics-calc) 에서 이어집니다.

## 먼저 읽을 1차 자료

- QuantConnect 문서 「Reality Modeling」 <https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts>
- TradingView Pine Script 문서 「Strategies」(체결 시점 · 수수료 · 슬리피지 설정) <https://www.tradingview.com/pine-script-docs/concepts/strategies/>
- Bailey, D. H. 등 (2014). 「Pseudo-Mathematics and Financial Charlatanism」, *Notices of the AMS* 61(5).
