- **한계**: ① 매수후보유가 flat/real 호출에서 다름(94.71 vs 94.25) — 각 호출의 최신 데이터 날짜가 달라서. 재현 시 반드시 데이터 기준일 병기 ② 단일 종목 · 단일 기간

---

### E3 상세 — 모의계좌 성과

- **질문**: 「모의계좌의 기간 성과(수익률 · MDD · 회전율)와 벤치마크는」
- **전략**: 모의계좌 실제 운영 (장부 체결 · 실제 비용)
- **데이터**: 모의계좌 스냅샷 6일 (2026-09-28 ~ 2026-10-07) · 스냅샷 6개
- **비용**: 장부의 실제 체결 비용
- **결과**

| 항목 | 값 |
|---|---|
| 총수익률 | **-0.44%** |
| MDD | -1.44% |
| Sharpe | -1.20 |
| Sortino | -1.73 |
| Sterling / Calmar | -15.37 |
| 회전율 | **4.914x (연환산 206.4%)** |
| 총 매수 | 9,851,250 |
| 총 매도 | 0 |
| 평균 자기자본 | 100,236,924 |
| Beta (1m) | 0.61 |
| 표준편차 (1m) | 0.191 |
| 추적오차 | 0.163 |
| 정보비율 | -0.177 |
| Jensen α | -0.107 |
| 벤치마크(KOSPI) 최종 | 우리 99.56 vs 벤치 99.61 |
| 배분 | cash 35% · stock 50% · crypto 10% · alt 5% (6일간 불변) |

- **결과**: 표본 6일 · 매도 0건 · 배분 불변. 총수익 -0.44% 로 벤치마크와 사실상 동일.
- **해석(두 독자)**:  
· 쉬운 말 — 「아직 6일치라 판단하기 이르다. 벤치마크와 거의 같은 움직임.」  
· 지표 — 「회전율 연환산 206% 는 매수만 있고 매도가 없어서. 10-16 「모의투자 검증」 전까지 매도 발생 후 재측정 필요.」
- **재현 명령**:
```
GET /api/paper/performance/metrics
GET /api/paper/performance/returns-table
GET /api/paper/performance/risk-metrics
GET /api/paper/performance/turnover
GET /api/paper/performance/allocation-history
GET /api/paper/performance/benchmark
```
- **한계**: ① 표본 6일 — 통계적 유의성 없음 ② 매도 0건이라 회전율·실현손익 판단 불가 ③ 배분 6일간 불변 — 리밸런싱 미발생 ④ 1m/3m/6m/1y 수익률은 null (스냅샷 부족)

---

## 5. 재현 — 엔진마다 다시 돌리는 법

로컬 앱(`pwsh -File scripts/personal/start.ps1 -Dev`) 켜고 로그인 후:

```text
# ① 지표 백테스트 — 대시보드 기본 호출(비용 flat)
GET /api/quant/pipeline?symbol=005930.KS&period=1y&strategy=rsi&cost_bps=10&slippage_bps=0

# ① 같은 전략을 실제 비용으로
GET /api/quant/pipeline?symbol=005930.KS&period=1y&strategy=rsi&cost_model=real

# ④ 모의계좌 성과 (E3)
GET /api/paper/performance/metrics
GET /api/paper/performance/returns-table
GET /api/paper/performance/risk-metrics
GET /api/paper/performance/turnover
GET /api/paper/performance/allocation-history
GET /api/paper/performance/benchmark