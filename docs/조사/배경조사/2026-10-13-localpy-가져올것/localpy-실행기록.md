<!-- 옮김 2026-10-16 — 원래 자리 docs/_git-drafts/2026-10-13-S110/배경-localpy-가져올것/localpy-실행기록.md · 작업 기록(그때 쓴 그대로 · 세션 번호 등 내부 표기 포함) · 정본 없음 · 관련 docs/github-archive/2026-09-28/이슈-강사님자료-변경추적/17-2026-10-13-th06-새10커밋.md -->
# local-py 실험 기동 기록 — 강사님 lumina-invest `8624e81` 판

| 문서 정보 | |
|---|---|
| **판 · 상태** | 초안 · S110 배경 ② 결과(메인 검토 전) |
| **기준** | 강사님 원본 사본 `learning/th06-lumina-invest/lecture` 의 `8624e81`(2026-10-12 12:40) `local-py/` 22파일 — `git archive` 로 저장소 밖 스크래치에 풀어 돌림 · 우리 판 Qurious `main` `8975696` |
| **실행** | 2026-10-13(화) 09:04 ~ 09:11 KST · 정규장 안 · Python 3.12.13(Windows) · 패키지 설치 없음 |
| **지킨 것** | `--mode live` · `--source kis` · `KIS_PAPER=false` · KIS 키를 쓰지 않음 · `.env` 를 만들지 않음 · loop 는 60초 × 2회를 한 번만 · nohup · cron · 작업 스케줄러 없음 · git 은 읽기만 · 강사님 커밋 작성자 · 이메일은 읽지 않음 |
| **관련 문서** | 같은 폴더 `결과.md` · `가져올것-점검.tsv` · 지시서 `../지시서-localpy-가져올것.md` · 조사서 `docs/조사/기초코드-최신판-융합-조사.md` <표 7> |

> **이 문서로 알 수 있는 것**
> 1. local-py 의 명령이 무엇까지 되나(시험 · mock · 야후 · paper · 백테스트)
> 2. 증권사 호출이 정말 0 이었나 — 무엇으로 쟀나
> 3. 우리 앱과 무엇이 다르고, 그 차이가 무엇을 뜻하나
> 4. 이 도구를 우리에게 어떻게 쓸 수 있나

## 0. 요약

1. 자가 시험 32/32 통과 · mock 다섯 명령 · 야후 두 명령 · paper 세 명령 + loop 2회 · 백테스트 셋(+ 종목 확인 하나)이 모두 돌았다. 감시기를 거친 18회 모두 **증권사(KIS) 주소 시도 0건**이고, 바깥 HTTP 39건은 전부 `query2.finance.yahoo.com` 이다. `data/kis_token.json` 도 생기지 않았다.
2. 눈에 띈 것 셋 — ① paper 체결가가 야후 캐시 일봉의 마지막 종가라 10-13 아침에 **10-08 종가**로 체결됐고, 현재가로 다시 재면 곧바로 −1.4% 였다. ② 백테스트 `--fee-bps` 가 매수 · 매도에 **각각** 붙어 기본 왕복 비용이 0.50% 다(문서는 「왕복 0.25%」). ③ 사이클이 3분이어도 일봉 캐시가 6시간이라, 그동안 판단 가격과 일손실 판정이 바뀌지 않는다.
3. 우리 앱과 가장 큰 차이는 실거래 관문(local-py 는 설정 두 줄로 실계좌 주문) · 체결 가격 · 비용 모델이다(3절).
4. 추천 — 앱에 합치지 않고 **저장소 밖 실험 도구로 따로 둔다**(4절 안 1). 앱에 들이는 판단은 강민석 · 오준영 님 몫이라 이슈 초안 한 줄씩만 남긴다(5절).

## 1. 준비 · 감시 방법

**<표 1> 돌리기 전 확인**

| 확인 | 결과 |
|---|---|
| Python | 3.12.13 (3.11 이상) |
| 환경 변수 `KIS_*` 개수 · `QUANT_MODE` · `MARKET_DATA_SOURCE` 있음 | 0 · False · False (이름 · 개수만 봄 · 값은 찍지 않음) |
| 프록시 환경 변수 이름 개수 | 0 |
| 지금 시각 | 2026-10-13(화) 09:03 KST — 정규장 안이라 loop 한 번을 돌림 |
| 사본 | `git -C <강사님 사본> archive 8624e81 local-py \| tar -x -C <스크래치>/localpy` — 22파일 · `.env` 없음 · `.env.example` 은 값을 가리고 변수 이름만 봄 |
| 코드 읽기 | KIS 클라이언트는 `--mode live`(`broker.py:231-240` build_broker) 또는 `--source kis` + 키(`broker.py:243-249` build_market_client)일 때만 만들어진다 → 허용 명령만 쓰면 KIS 를 부를 길이 없다 |

감시기 `<스크래치>/localpy/_guard/guard_run.py` — 저장소 밖 스크래치에 둔 작은 실행기다.

- `socket.getaddrinfo`(DNS) 와 `urllib.request.urlopen`(HTTP) 두 층에서 나가는 호스트를 모두 센다.
- `koreainvestment.com` 으로 끝나는 호스트는 **연결 전에 막고** 따로 센다(막았다면 아래 표의 마지막 칸이 1 이상).
- 돌리기 전에 `KIS_` 변수 · `QUANT_MODE` · `MARKET_DATA_SOURCE` · local-py 폴더의 `.env` 를 보고, 하나라도 있으면 멈춘다. `--mode live` · `--source kis` 인자도 멈춘다.
- 차단 판정은 네트워크 없이 먼저 확인했다 — `openapivts` · `openapi` · `apiportal`(`.koreainvestment.com`) → 막음 · `query2.finance.yahoo.com` → 통과.

**<표 2> 감시기를 거친 실행 18회 (감시 기록 `_runs/*.net.json` 에서 그대로 옮김)**

| # | 단계 | 명령 | 종료 코드 | 초 | 바깥 HTTP | 증권사(KIS) 시도 |
|---|---|---|---|---|---|---|
| 1 | 1단계 준비 | `python trade.py --help` | 0 | 0.3 | 0 | 0 |
| 2 | 1단계 준비 | `python trade.py config` | 0 | 0.08 | 0 | 0 |
| 3 | 자가 시험 | `python -m unittest discover -s tests -v` | 0 | 5.43 | 0 | 0 |
| 4 | 1단계 mock | `python trade.py signals --source mock` | 0 | 0.49 | 0 | 0 |
| 5 | 1단계 mock | `python trade.py cycle --source mock` | 0 | 0.62 | 0 | 0 |
| 6 | 1단계 mock | `python trade.py status --source mock` | 0 | 0.1 | 0 | 0 |
| 7 | 1단계 mock | `python trade.py orders` | 0 | 0.07 | 0 | 0 |
| 8 | 1단계 mock | `python trade.py reset --yes` | 0 | 0.07 | 0 | 0 |
| 9 | 2단계 야후 · 주문 없음 | `python trade.py signals` | 0 | 16.81 | query2.finance.yahoo.com 31 | 0 |
| 10 | 2단계 야후 · 주문 없음 | `python trade.py cycle --dry-run` | 0 | 0.93 | query2.finance.yahoo.com 1 | 0 |
| 11 | 3단계 paper | `python trade.py cycle` | 0 | 0.75 | query2.finance.yahoo.com 1 | 0 |
| 12 | 3단계 paper | `python trade.py status` | 0 | 1.39 | query2.finance.yahoo.com 3 | 0 |
| 13 | 3단계 paper | `python trade.py orders` | 0 | 0.08 | 0 | 0 |
| 14 | 3단계 paper · 정규장 안 | `python trade.py loop --interval 60 --max-cycles 2` | 0 | 61.25 | query2.finance.yahoo.com 2 | 0 |
| 15 | 4단계 백테스트 | `python trade.py backtest 005930.KS --period 2y` | 0 | 0.79 | 0 | 0 |
| 16 | 4단계 백테스트 | `python trade.py backtest 005930.KS --strategy ma-cross-basic` | 0 | 0.79 | 0 | 0 |
| 17 | 4단계 백테스트 · 수수료 바꿈 | `python trade.py backtest 005930.KS --period 2y --fee-bps 21.77` | 0 | 0.91 | 0 | 0 |
| 18 | 덧붙인 확인(허용 명령 backtest) | `python trade.py backtest 012510.KS --period 1y` | 1 | 0.49 | query2.finance.yahoo.com 1 | 0 |
| 합 | — | 18회 | — | — | 39건 | **0** |

- 실행 밖 오프라인 점검 둘(2.19 · 2.20)은 네트워크를 쓰지 않는 계산 · 파일 읽기다.
- 18번의 「종료 코드 1」 은 local-py `backtest` 가 야후 404 를 잡지 않은 것이다(2.18).

## 2. 명령별 출력 원문

- 모든 명령은 감시기(`_guard/guard_run.py`)를 거쳐 `<스크래치>/localpy/local-py` 에서 돌렸다. 출력 맨 앞 · 맨 끝의 「[감시]」 두 줄은 감시기가 찍은 것이다.
- 경로의 스크래치 앞부분만 `<스크래치>` 로 줄였다 — 그 밖은 원문 그대로. 40줄이 넘는 출력은 앞 40줄과 전체 줄 수만 싣는다.

### 2.1 1단계 준비 — `python trade.py --help`

- 시각 2026-10-13 09:04:59 ~ 09:05:00 (KST) · 종료 코드 0 · 걸린 시간 0.3초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
usage: trade.py [-h] [-v]
                {signals,cycle,loop,status,orders,backtest,kill,resume,reset,config}
                ...

lumina 로컬 자동매매

positional arguments:
  {signals,cycle,loop,status,orders,backtest,kill,resume,reset,config}
    signals             지표·시그널만 출력(주문 없음)
    cycle               한 사이클 실행
    loop                주기 루프 실행
    status              계좌·보유·위험관리 상태
    orders              주문 기록
    backtest            단일 종목 백테스트
    kill                비상 정지
    resume              비상 정지 해제
    reset               장부 초기화
    config              현재 설정 확인

options:
  -h, --help            show this help message and exit
  -v, --verbose         디버그 로그
[감시] 끝 — 0.3초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.2 1단계 준비 — `python trade.py config`

- 시각 2026-10-13 09:05:01 ~ 09:05:02 (KST) · 종료 코드 0 · 걸린 시간 0.08초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**
- 읽은 것: 키 칸(`kis_app_key` · `kis_app_secret` · `kis_account_no`)은 값이 없으면 빈 칸으로 나온다 — 값이 있을 때만 `***` 로 가린다(`config.py:171-176`). 모드 paper · 시세 yahoo 확인.

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
{
  "data_dir": "<스크래치>\\localpy\\local-py\\data",
  "cycle_sec": 180,
  "mode": "paper",
  "market_data_source": "yahoo",
  "user_id": "local",
  "symbol_source": "ai",
  "selected_symbols": [],
  "ai_top_n": 3,
  "strategy_id": "",
  "candle_period": "2y",
  "candle_cache_hours": 6.0,
  "initial_capital": 10000000.0,
  "per_trade_budget": 1000000.0,
  "buy_ratio": 1.0,
  "sell_ratio": 0.5,
  "risk_daily_loss_limit_pct": 3.0,
  "risk_max_position_pct": 30.0,
  "risk_max_orders_per_day": 20,
  "risk_cooldown_min": 30,
  "aggressive": false,
  "aggressive_candle_interval": "5m",
  "aggressive_candle_range": "5d",
  "aggressive_cache_min": 2,
  "aggressive_cooldown_min": 3,
  "aggressive_max_orders_per_day": 300,
  "aggressive_max_buys_per_cycle": 2,
  "aggressive_max_sells_per_cycle": 3,
  "aggressive_force_buy": true,
  "aggressive_take_profit_pct": 1.5,
  "aggressive_stop_loss_pct": 1.0,
  "kis_app_key": "",
  "kis_app_secret": "",
  "kis_account_no": "",
  "kis_paper": true,
  "kis_enforce_market_hours": true,
  "http_timeout": 15.0
}

… (앞 40줄만 · 전체 42줄)
```

### 2.3 자가 시험 — `python -m unittest discover -s tests -v`

- 시각 2026-10-13 09:05:09 ~ 09:05:15 (KST) · 종료 코드 0 · 걸린 시간 5.43초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**
- 읽은 것: README 는 「32개 · 1초대」 — 이 PC 에서 32개 모두 통과 · 5.3초. 「[감시] 시작」 줄이 뒤에 찍힌 것은 unittest 가 stderr 로 쓰고 감시기 줄은 stdout 이라 버퍼 순서가 바뀐 것이다.

```text
test_force_buy_rotation (test_local.AggressiveTests.test_force_buy_rotation) ... ok
test_score_intraday_trend (test_local.AggressiveTests.test_score_intraday_trend) ... ok
test_stop_loss_sells_everything (test_local.AggressiveTests.test_stop_loss_sells_everything) ... ok
test_take_profit_sells_everything (test_local.AggressiveTests.test_take_profit_sells_everything) ... ok
test_backtest_needs_enough_bars (test_local.BacktestTests.test_backtest_needs_enough_bars) ... ok
test_backtest_returns_metrics (test_local.BacktestTests.test_backtest_returns_metrics) ... ok
test_cycle_fills_and_persists (test_local.CycleTests.test_cycle_fills_and_persists) ... ok
test_daily_loss_triggers_halt (test_local.CycleTests.test_daily_loss_triggers_halt) ... 자동매매 비상 정지: 일손실 한도 초과: 당일 -50.00% ≤ -3.0% (당일 -50.00%)
ok
test_dry_run_changes_nothing (test_local.CycleTests.test_dry_run_changes_nothing) ... ok
test_kill_switch_blocks_cycle (test_local.CycleTests.test_kill_switch_blocks_cycle) ... ok
test_live_mode_sends_order_to_broker (test_local.CycleTests.test_live_mode_sends_order_to_broker) ... ok
test_live_order_skipped_outside_market_hours (test_local.CycleTests.test_live_order_skipped_outside_market_hours) ... ok
test_manual_symbols (test_local.CycleTests.test_manual_symbols) ... ok
test_max_orders_per_day_limit (test_local.CycleTests.test_max_orders_per_day_limit) ... ok
test_signal_needs_20_bars (test_local.IndicatorTests.test_signal_needs_20_bars) ... ok
test_signal_shape (test_local.IndicatorTests.test_signal_shape) ... ok
test_sma_and_rsi_windows (test_local.IndicatorTests.test_sma_and_rsi_windows) ... ok
test_cooldown_blocks_second_order (test_local.RiskGuardTests.test_cooldown_blocks_second_order) ... ok
test_cooldown_zero_always_allows (test_local.RiskGuardTests.test_cooldown_zero_always_allows) ... ok
test_daily_loss (test_local.RiskGuardTests.test_daily_loss) ... ok
test_orders_today_counter (test_local.RiskGuardTests.test_orders_today_counter) ... ok
test_position_cap (test_local.RiskGuardTests.test_position_cap) ... ok
test_buy_shrinks_to_affordable_quantity (test_local.StoreTests.test_buy_shrinks_to_affordable_quantity) ... ok
test_buy_skipped_when_cash_too_small (test_local.StoreTests.test_buy_skipped_when_cash_too_small) ... ok
test_buy_then_sell_updates_cash_and_avg (test_local.StoreTests.test_buy_then_sell_updates_cash_and_avg) ... ok
test_sell_without_position_is_skipped (test_local.StoreTests.test_sell_without_position_is_skipped) ... ok
test_state_survives_reload (test_local.StoreTests.test_state_survives_reload) ... ok
test_empty_intersection_keeps_original (test_local.StrategyTests.test_empty_intersection_keeps_original) ... ok
test_rules_override_threshold (test_local.StrategyTests.test_rules_override_threshold) ... ok
test_shipped_specs_load (test_local.StrategyTests.test_shipped_specs_load) ... ok
test_threshold_judgement (test_local.StrategyTests.test_threshold_judgement) ... ok
test_universe_and_max_symbols (test_local.StrategyTests.test_universe_and_max_symbols) ... ok

----------------------------------------------------------------------
Ran 32 tests in 5.323s

OK
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
[감시] 끝 — 5.4초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.4 1단계 mock — `python trade.py signals --source mock`

- 시각 2026-10-13 09:05:23 ~ 09:05:25 (KST) · 종료 코드 0 · 걸린 시간 0.49초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
시세=mock 전략=기본 지표 공격모드=False / 대상종목=3개
대상     점수 종목                             현재가 판단       근거
 *      2 161890.KS 한국콜마           170,871 매수       RSI 과매도 (매수 신호), 단기 이평 < 중기 이평 (매도 우위), 볼린저 하단 이탈 (반등 가능)
 *      1 000660.KS SK하이닉스         116,107 매수       RSI 중립 (53.0), 단기 이평 > 중기 이평 (매수 우위)
 *      1 042700.KS 한미반도체          153,109 매수       RSI 중립 (54.2), 단기 이평 > 중기 이평 (매수 우위)
        1 000990.KS DB하이텍          167,281 매수       RSI 중립 (61.4), 단기 이평 > 중기 이평 (매수 우위)
        1 014680.KS 한솔케미칼          128,709 매수       RSI 중립 (42.5), 단기 이평 > 중기 이평 (매수 우위)
        1 403870.KQ HPSP            67,253 매수       RSI 중립 (53.2), 단기 이평 > 중기 이평 (매수 우위)
        1 012510.KQ 더존비즈온          212,588 매수       RSI 중립 (66.8), 단기 이평 > 중기 이평 (매수 우위)
        1 263750.KQ 펄어비스            71,437 매수       RSI 중립 (60.0), 단기 이평 > 중기 이평 (매수 우위)
        1 051900.KS LG생활건강         146,734 매수       RSI 중립 (61.0), 단기 이평 > 중기 이평 (매수 우위)
        0 058470.KQ 리노공업           272,561 관망       RSI 중립 (36.5), 단기 이평 < 중기 이평 (매도 우위), 볼린저 하단 이탈 (반등 가능)
        0 257720.KQ 실리콘투            92,895 관망       RSI 중립 (37.6), 단기 이평 < 중기 이평 (매도 우위), 볼린저 하단 이탈 (반등 가능)
       -1 005930.KS 삼성전자            66,060 매도       RSI 중립 (51.2), 단기 이평 < 중기 이평 (매도 우위)
       -1 039030.KQ 이오테크닉스          75,443 매도       RSI 중립 (35.8), 단기 이평 < 중기 이평 (매도 우위)
       -1 240810.KQ 원익IPS          191,901 매도       RSI 중립 (36.8), 단기 이평 < 중기 이평 (매도 우위)
       -1 036930.KQ 주성엔지니어링         71,275 매도       RSI 중립 (50.0), 단기 이평 < 중기 이평 (매도 우위)
       -1 035420.KS NAVER           74,911 매도       RSI 중립 (59.4), 단기 이평 < 중기 이평 (매도 우위)
       -1 035720.KS 카카오             73,569 매도       RSI 중립 (30.9), 단기 이평 < 중기 이평 (매도 우위)
       -1 018260.KS 삼성에스디에스        102,314 매도       RSI 중립 (41.0), 단기 이평 < 중기 이평 (매도 우위)
       -1 064400.KS LG CNS         176,889 매도       RSI 과매수 (매도 신호), 단기 이평 > 중기 이평 (매수 우위)
       -1 259960.KS 크래프톤           210,761 매도       RSI 중립 (39.7), 단기 이평 < 중기 이평 (매도 우위)
       -1 036570.KS 엔씨소프트          189,235 매도       RSI 중립 (32.8), 단기 이평 < 중기 이평 (매도 우위)
       -1 307950.KS 현대오토에버          76,613 매도       RSI 중립 (42.5), 단기 이평 < 중기 이평 (매도 우위)
       -1 293490.KQ 카카오게임즈          31,145 매도       RSI 중립 (44.3), 단기 이평 < 중기 이평 (매도 우위)
       -1 090430.KS 아모레퍼시픽         175,752 매도       RSI 중립 (47.7), 단기 이평 < 중기 이평 (매도 우위)
       -1 278470.KS 에이피알            90,284 매도       RSI 중립 (47.9), 단기 이평 < 중기 이평 (매도 우위)
       -1 237880.KQ 클리오             47,749 매도       RSI 중립 (37.9), 단기 이평 < 중기 이평 (매도 우위)
       -1 018290.KQ 브이티            111,573 매도       RSI 중립 (48.6), 단기 이평 < 중기 이평 (매도 우위)
       -1 241710.KQ 코스메카코리아        165,752 매도       RSI 중립 (52.9), 단기 이평 < 중기 이평 (매도 우위)
       -2 357780.KQ 솔브레인           130,117 매도       RSI 과매수 (매도 신호), 단기 이평 > 중기 이평 (매수 우위), 볼린저 상단 돌파 (조정 가능)
       -2 192820.KS 코스맥스            92,597 매도       RSI 과매수 (매도 신호), 단기 이평 > 중기 이평 (매수 우위), 볼린저 상단 돌파 (조정 가능)
       -3 108320.KS LX세미콘          248,409 강력 매도    RSI 중립 (54.4), 데드크로스 (강력 매도)
[감시] 끝 — 0.5초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.5 1단계 mock — `python trade.py cycle --source mock`

- 시각 2026-10-13 09:05:25 ~ 09:05:26 (KST) · 종료 코드 0 · 걸린 시간 0.62초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**
- 읽은 것: 사이클 줄의 시각 `00:05:26` 은 UTC 다(`auto_trade.py:108`) — 실행은 09:05 KST.

```text
09:05:26 INFO    lumina_local.auto_trade — 체결 buy 161890.KS 5주 @170,871 (현금 9,145,645원)
09:05:26 INFO    lumina_local.auto_trade — 체결 buy 000660.KS 8주 @116,107 (현금 8,216,789원)
09:05:26 INFO    lumina_local.auto_trade — 체결 buy 042700.KS 6주 @153,109 (현금 7,298,135원)
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
2026-10-13 00:05:26 | 판단 3종목 | 체결 3건 / 생략 0건 | 총자산 10,000,000원 (0.0%)
    buy   161890.KS 한국콜마           5주 @   170,871  [paper] RSI 과매도 (매수 신호) | 단기 이평 < 중기 이평 (매도 우위) | 볼린저 하단 이탈 (반등 가능)
    buy   000660.KS SK하이닉스         8주 @   116,107  [paper] RSI 중립 (53.0) | 단기 이평 > 중기 이평 (매수 우위)
    buy   042700.KS 한미반도체          6주 @   153,109  [paper] RSI 중립 (54.2) | 단기 이평 > 중기 이평 (매수 우위)
[감시] 끝 — 0.6초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.6 1단계 mock — `python trade.py status --source mock`

- 시각 2026-10-13 09:05:36 ~ 09:05:37 (KST) · 종료 코드 0 · 걸린 시간 0.1초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
계정 local / mode=paper / 시세=mock / 장운영=열림
상태파일 <스크래치>\localpy\local-py\data\state.json

[계좌] 원금 10,000,000 → 총자산 10,000,000원 (0.0%)  현금 7,298,135 / 평가 2,701,865

[보유 3종목]
  161890.KS 한국콜마           5주  평단    170,871  현재    170,871  +0.00%
  000660.KS SK하이닉스         8주  평단    116,107  현재    116,107  +0.00%
  042700.KS 한미반도체          6주  평단    153,109  현재    153,109  +0.00%

[위험관리] 비상정지=OFF
  당일손익 0.0% (한도 -3.0%) / 주문 3건 (잔여 17)
  종목비중 한도 30.0% / 쿨다운 30분

[마지막 사이클] 2026-10-13 00:05:26 — 체결 3건
[감시] 끝 — 0.1초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.7 1단계 mock — `python trade.py orders`

- 시각 2026-10-13 09:05:37 ~ 09:05:38 (KST) · 종료 코드 0 · 걸린 시간 0.07초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
2026-10-13T00:05:26 filled   buy   161890.KS 한국콜마           5주 @   170,871  [paper] RSI 과매도 (매수 신호) | 단기 이평 < 중기 이평 (매도 우위) | 볼린저 하단 이탈 (반등 가능)
2026-10-13T00:05:26 filled   buy   000660.KS SK하이닉스         8주 @   116,107  [paper] RSI 중립 (53.0) | 단기 이평 > 중기 이평 (매수 우위)
2026-10-13T00:05:26 filled   buy   042700.KS 한미반도체          6주 @   153,109  [paper] RSI 중립 (54.2) | 단기 이평 > 중기 이평 (매수 우위)
[감시] 끝 — 0.1초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.8 1단계 mock — `python trade.py reset --yes`

- 시각 2026-10-13 09:05:39 ~ 09:05:39 (KST) · 종료 코드 0 · 걸린 시간 0.07초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
초기화 완료 — 현금 10,000,000원
[감시] 끝 — 0.1초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.9 2단계 야후 · 주문 없음 — `python trade.py signals`

- 시각 2026-10-13 09:05:48 ~ 09:06:05 (KST) · 종료 코드 0 · 걸린 시간 16.81초 · 바깥 HTTP 31건(query2.finance.yahoo.com 31건) · DNS 31건 · **증권사(KIS) 주소 시도 0건**
- 읽은 것: 야후 31건 호출 · 더존비즈온 `012510.KQ` 는 일봉 0개라 「판단 불가」(가격 칸 `-`).

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
시세=yahoo 전략=기본 지표 공격모드=False / 대상종목=3개
대상     점수 종목                             현재가 판단       근거
 *      1 005930.KS 삼성전자           262,000 매수       RSI 중립 (47.5), 단기 이평 > 중기 이평 (매수 우위)
 *      1 042700.KS 한미반도체          267,000 매수       RSI 중립 (62.2), 단기 이평 > 중기 이평 (매수 우위)
 *      1 000990.KS DB하이텍          138,800 매수       RSI 중립 (63.8), 단기 이평 > 중기 이평 (매수 우위)
        1 108320.KS LX세미콘           37,400 매수       RSI 중립 (52.7), 단기 이평 > 중기 이평 (매수 우위)
        1 039030.KQ 이오테크닉스         524,000 매수       RSI 중립 (60.8), 단기 이평 > 중기 이평 (매수 우위)
        1 403870.KQ HPSP            64,600 매수       RSI 중립 (64.4), 단기 이평 > 중기 이평 (매수 우위)
        1 240810.KQ 원익IPS          133,700 매수       RSI 중립 (56.6), 단기 이평 > 중기 이평 (매수 우위)
        1 357780.KQ 솔브레인           411,500 매수       RSI 중립 (67.2), 단기 이평 > 중기 이평 (매수 우위)
        1 036570.KS 엔씨소프트          222,000 매수       RSI 중립 (50.7), 단기 이평 > 중기 이평 (매수 우위)
        1 307950.KS 현대오토에버         360,500 매수       RSI 중립 (39.7), 단기 이평 > 중기 이평 (매수 우위)
        1 293490.KQ 카카오게임즈           9,350 매수       RSI 중립 (50.2), 단기 이평 > 중기 이평 (매수 우위)
        1 278470.KS 에이피알           371,500 매수       RSI 중립 (48.4), 단기 이평 > 중기 이평 (매수 우위)
        1 257720.KQ 실리콘투            35,450 매수       RSI 과매도 (매수 신호), 단기 이평 < 중기 이평 (매도 우위)
        1 018290.KQ 브이티             12,940 매수       RSI 중립 (57.1), 단기 이평 > 중기 이평 (매수 우위)
        0 036930.KQ 주성엔지니어링        267,500 관망       RSI 중립 (67.5), 단기 이평 > 중기 이평 (매수 우위), 볼린저 상단 돌파 (조정 가능)
        0 035720.KS 카카오             32,300 관망       RSI 중립 (32.8), 단기 이평 < 중기 이평 (매도 우위), 볼린저 하단 이탈 (반등 가능)
        0 018260.KS 삼성에스디에스        195,300 관망       RSI 중립 (31.8), 단기 이평 < 중기 이평 (매도 우위), 볼린저 하단 이탈 (반등 가능)
        0 259960.KS 크래프톤           186,900 관망       RSI 중립 (30.2), 단기 이평 < 중기 이평 (매도 우위), 볼린저 하단 이탈 (반등 가능)
        0 012510.KQ 더존비즈온                - 판단 불가    
        0 192820.KS 코스맥스           306,500 관망       RSI 중립 (66.5), 단기 이평 > 중기 이평 (매수 우위), 볼린저 상단 돌파 (조정 가능)
       -1 000660.KS SK하이닉스       1,681,000 매도       RSI 중립 (43.7), 단기 이평 < 중기 이평 (매도 우위)
       -1 014680.KS 한솔케미칼          271,000 매도       RSI 과매수 (매도 신호), 단기 이평 > 중기 이평 (매수 우위)
       -1 058470.KQ 리노공업            87,900 매도       RSI 과매수 (매도 신호), 단기 이평 > 중기 이평 (매수 우위)
       -1 035420.KS NAVER          183,800 매도       RSI 중립 (30.5), 단기 이평 < 중기 이평 (매도 우위)
       -1 064400.KS LG CNS          67,500 매도       RSI 중립 (41.7), 단기 이평 < 중기 이평 (매도 우위)
       -1 263750.KQ 펄어비스            32,600 매도       RSI 중립 (44.0), 단기 이평 < 중기 이평 (매도 우위)
       -1 090430.KS 아모레퍼시픽         135,900 매도       RSI 중립 (44.6), 단기 이평 < 중기 이평 (매도 우위)
       -1 051900.KS LG생활건강         269,500 매도       RSI 중립 (36.5), 단기 이평 < 중기 이평 (매도 우위)
       -1 161890.KS 한국콜마           137,100 매도       RSI 중립 (45.1), 단기 이평 < 중기 이평 (매도 우위)
       -1 237880.KQ 클리오             12,180 매도       RSI 중립 (50.4), 단기 이평 < 중기 이평 (매도 우위)
       -1 241710.KQ 코스메카코리아        111,400 매도       RSI 중립 (40.9), 단기 이평 < 중기 이평 (매도 우위)
[감시] 끝 — 16.8초 · 종료 코드 0 · 바깥 HTTP 31건(query2.finance.yahoo.com 31건) · DNS 31건 · 증권사(KIS) 주소 시도 0건
```

### 2.10 2단계 야후 · 주문 없음 — `python trade.py cycle --dry-run`

- 시각 2026-10-13 09:06:24 ~ 09:06:26 (KST) · 종료 코드 0 · 걸린 시간 0.93초 · 바깥 HTTP 1건(query2.finance.yahoo.com 1건) · DNS 1건 · **증권사(KIS) 주소 시도 0건**
- 읽은 것: 장부는 그대로(현금 10,000,000 · 보유 0 · 주문 0) — 사이클 기록 한 줄(`dry_run: true`)만 남는다. HTTP 1건은 빈 응답이라 캐시하지 않는 `012510.KQ` 를 다시 부른 것.

```text
09:06:26 INFO    lumina_local.auto_trade — [DRY-RUN] buy 005930.KS 3주 @262,000
09:06:26 INFO    lumina_local.auto_trade — [DRY-RUN] buy 042700.KS 3주 @267,000
09:06:26 INFO    lumina_local.auto_trade — [DRY-RUN] buy 000990.KS 7주 @138,800
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
2026-10-13 00:06:25 | 판단 3종목 | 체결 3건 / 생략 0건 | 총자산 10,000,000원 (0.0%)
    buy   005930.KS 삼성전자           3주 @   262,000  [paper] RSI 중립 (47.5) | 단기 이평 > 중기 이평 (매수 우위)
    buy   042700.KS 한미반도체          3주 @   267,000  [paper] RSI 중립 (62.2) | 단기 이평 > 중기 이평 (매수 우위)
    buy   000990.KS DB하이텍          7주 @   138,800  [paper] RSI 중립 (63.8) | 단기 이평 > 중기 이평 (매수 우위)
[감시] 끝 — 0.9초 · 종료 코드 0 · 바깥 HTTP 1건(query2.finance.yahoo.com 1건) · DNS 1건 · 증권사(KIS) 주소 시도 0건
```

### 2.11 3단계 paper — `python trade.py cycle`

- 시각 2026-10-13 09:06:35 ~ 09:06:36 (KST) · 종료 코드 0 · 걸린 시간 0.75초 · 바깥 HTTP 1건(query2.finance.yahoo.com 1건) · DNS 1건 · **증권사(KIS) 주소 시도 0건**

```text
09:06:36 INFO    lumina_local.auto_trade — 체결 buy 005930.KS 3주 @262,000 (현금 9,214,000원)
09:06:36 INFO    lumina_local.auto_trade — 체결 buy 042700.KS 3주 @267,000 (현금 8,413,000원)
09:06:36 INFO    lumina_local.auto_trade — 체결 buy 000990.KS 7주 @138,800 (현금 7,441,400원)
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
2026-10-13 00:06:35 | 판단 3종목 | 체결 3건 / 생략 0건 | 총자산 10,000,000원 (0.0%)
    buy   005930.KS 삼성전자           3주 @   262,000  [paper] RSI 중립 (47.5) | 단기 이평 > 중기 이평 (매수 우위)
    buy   042700.KS 한미반도체          3주 @   267,000  [paper] RSI 중립 (62.2) | 단기 이평 > 중기 이평 (매수 우위)
    buy   000990.KS DB하이텍          7주 @   138,800  [paper] RSI 중립 (63.8) | 단기 이평 > 중기 이평 (매수 우위)
[감시] 끝 — 0.7초 · 종료 코드 0 · 바깥 HTTP 1건(query2.finance.yahoo.com 1건) · DNS 1건 · 증권사(KIS) 주소 시도 0건
```

### 2.12 3단계 paper — `python trade.py status`

- 시각 2026-10-13 09:06:37 ~ 09:06:39 (KST) · 종료 코드 0 · 걸린 시간 1.39초 · 바깥 HTTP 3건(query2.finance.yahoo.com 3건) · DNS 3건 · **증권사(KIS) 주소 시도 0건**
- 읽은 것: 체결가(삼성전자 262,000)는 캐시된 일봉의 마지막 종가 = **10-08 종가**다(2.20 점검). `status` 는 야후 `regularMarketPrice`(250,500)로 다시 매겨 곧바로 −1.4%. 10-12(월)는 우리 휴장일 목록(`stock_coin_trade_gateway.py:88-103`)에 없는 거래일인데 야후 일봉에 그 봉이 없었다.

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
계정 local / mode=paper / 시세=yahoo / 장운영=열림
상태파일 <스크래치>\localpy\local-py\data\state.json

[계좌] 원금 10,000,000 → 총자산 9,860,300원 (-1.4%)  현금 7,441,400 / 평가 2,418,900

[보유 3종목]
  005930.KS 삼성전자           3주  평단    262,000  현재    250,500  -4.39%
  042700.KS 한미반도체          3주  평단    267,000  현재    248,500  -6.93%
  000990.KS DB하이텍          7주  평단    138,800  현재    131,700  -5.12%

[위험관리] 비상정지=OFF
  당일손익 -1.397% (한도 -3.0%) / 주문 3건 (잔여 17)
  종목비중 한도 30.0% / 쿨다운 30분

[마지막 사이클] 2026-10-13 00:06:35 — 체결 3건
[감시] 끝 — 1.4초 · 종료 코드 0 · 바깥 HTTP 3건(query2.finance.yahoo.com 3건) · DNS 3건 · 증권사(KIS) 주소 시도 0건
```

### 2.13 3단계 paper — `python trade.py orders`

- 시각 2026-10-13 09:06:40 ~ 09:06:41 (KST) · 종료 코드 0 · 걸린 시간 0.08초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
2026-10-13T00:06:36 filled   buy   005930.KS 삼성전자           3주 @   262,000  [paper] RSI 중립 (47.5) | 단기 이평 > 중기 이평 (매수 우위)
2026-10-13T00:06:36 filled   buy   042700.KS 한미반도체          3주 @   267,000  [paper] RSI 중립 (62.2) | 단기 이평 > 중기 이평 (매수 우위)
2026-10-13T00:06:36 filled   buy   000990.KS DB하이텍          7주 @   138,800  [paper] RSI 중립 (63.8) | 단기 이평 > 중기 이평 (매수 우위)
[감시] 끝 — 0.1초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.14 3단계 paper · 정규장 안 — `python trade.py loop --interval 60 --max-cycles 2`

- 시각 2026-10-13 09:07:39 ~ 09:08:41 (KST) · 종료 코드 0 · 걸린 시간 61.25초 · 바깥 HTTP 2건(query2.finance.yahoo.com 2건) · DNS 2건 · **증권사(KIS) 주소 시도 0건**
- 읽은 것: 09:07 · 09:08 두 회차 모두 쿨다운(30분)이 같은 종목 매수 3건을 막음. 사이클 안의 총자산은 캐시 종가로 매겨 0.0% — 12번 `status` 의 −1.4% 와 다르다(일손실 판정도 캐시 종가 기준).

```text
09:07:40 INFO    lumina_local.auto_trade — 자동매매 루프 시작 — 60초 주기 / mode=paper / 시세=yahoo / 공격모드=False
09:07:40 INFO    lumina_local.auto_trade — [위험관리] buy 005930.KS 생략 — 중복 주문 방지: 30분 내 동일 종목·방향 주문 존재
09:07:40 INFO    lumina_local.auto_trade — [위험관리] buy 042700.KS 생략 — 중복 주문 방지: 30분 내 동일 종목·방향 주문 존재
09:07:40 INFO    lumina_local.auto_trade — [위험관리] buy 000990.KS 생략 — 중복 주문 방지: 30분 내 동일 종목·방향 주문 존재
09:08:41 INFO    lumina_local.auto_trade — [위험관리] buy 005930.KS 생략 — 중복 주문 방지: 30분 내 동일 종목·방향 주문 존재
09:08:41 INFO    lumina_local.auto_trade — [위험관리] buy 042700.KS 생략 — 중복 주문 방지: 30분 내 동일 종목·방향 주문 존재
09:08:41 INFO    lumina_local.auto_trade — [위험관리] buy 000990.KS 생략 — 중복 주문 방지: 30분 내 동일 종목·방향 주문 존재
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
[1] 2026-10-13 00:07:40 | 판단 3종목 | 체결 0건 / 생략 3건 | 총자산 10,000,000원 (0.0%)
[2] 2026-10-13 00:08:40 | 판단 3종목 | 체결 0건 / 생략 3건 | 총자산 10,000,000원 (0.0%)
[감시] 끝 — 61.2초 · 종료 코드 0 · 바깥 HTTP 2건(query2.finance.yahoo.com 2건) · DNS 2건 · 증권사(KIS) 주소 시도 0건
```

### 2.15 4단계 백테스트 — `python trade.py backtest 005930.KS --period 2y`

- 시각 2026-10-13 09:10:05 ~ 09:10:06 (KST) · 종료 코드 0 · 걸린 시간 0.79초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**
- 읽은 것: 캐시에서 읽어 바깥 연결 0. 423봉 = 일봉 483 − 워밍업 60.

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
005930.KS 삼성전자 [indicator-default] 423봉 · 거래 195건 · 승률 52.0% · 수익 +53.61% (매수후보유 +367.02%) · MDD -14.53%
[감시] 끝 — 0.8초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.16 4단계 백테스트 — `python trade.py backtest 005930.KS --strategy ma-cross-basic`

- 시각 2026-10-13 09:10:07 ~ 09:10:08 (KST) · 종료 코드 0 · 걸린 시간 0.79초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
005930.KS 삼성전자 [ma-cross-basic] 423봉 · 거래 148건 · 승률 28.6% · 수익 +204.72% (매수후보유 +367.02%) · MDD -20.94%
[감시] 끝 — 0.8초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.17 4단계 백테스트 · 수수료 바꿈 — `python trade.py backtest 005930.KS --period 2y --fee-bps 21.77`

- 시각 2026-10-13 09:10:08 ~ 09:10:10 (KST) · 종료 코드 0 · 걸린 시간 0.91초 · 바깥 HTTP 0건(없음) · DNS 0건 · **증권사(KIS) 주소 시도 0건**
- 읽은 것: 21.77bp(편도) = 우리 `real` 기본(2026 코스피 · 슬리피지 10bp)의 왕복 43.5bp 를 둘로 나눈 값. local-py 는 fee_bps 를 매수 · 매도에 각각 떼므로(2.19) 왕복이 우리와 같아진다. 25bp 보다 수익 +1.17%p.

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
005930.KS 삼성전자 [indicator-default] 423봉 · 거래 195건 · 승률 52.0% · 수익 +54.78% (매수후보유 +367.02%) · MDD -14.35%
[감시] 끝 — 0.9초 · 종료 코드 0 · 바깥 HTTP 0건(없음) · DNS 0건 · 증권사(KIS) 주소 시도 0건
```

### 2.18 덧붙인 확인(허용 명령 backtest) — `python trade.py backtest 012510.KS --period 1y`

- 시각 2026-10-13 09:10:38 ~ 09:10:39 (KST) · 종료 코드 1 · 걸린 시간 0.49초 · 바깥 HTTP 1건(query2.finance.yahoo.com 1건) · DNS 1건 · **증권사(KIS) 주소 시도 0건**
- 읽은 것: 야후 404(「No data found, symbol may be delisted」) — `cmd_backtest` 가 오류를 잡지 않아 traceback 으로 끝났다(실제 종료 코드 1). 감시기 요약 줄의 「종료 코드 0」 은 감시기 한계다(예외가 감시기의 finally 뒤로 올라감). 바깥 연결은 야후 1건 · 증권사 0건.

```text
[감시] 시작 — KIS_ 변수 0개 · QUANT_MODE False · MARKET_DATA_SOURCE False · .env 파일 False
[감시] 끝 — 0.5초 · 종료 코드 0 · 바깥 HTTP 1건(query2.finance.yahoo.com 1건) · DNS 1건 · 증권사(KIS) 주소 시도 0건
Traceback (most recent call last):
  File "<스크래치>\localpy\local-py\lumina_local\market_data.py", line 48, in http_json
    with urllib.request.urlopen(req, timeout=timeout) as resp:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<스크래치>\localpy\_guard\guard_run.py", line 93, in guarded_urlopen
    return orig_urlopen(req, *a, **k)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\<사용자>\anaconda3\Lib\urllib\request.py", line 215, in urlopen
    return opener.open(url, data, timeout)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\<사용자>\anaconda3\Lib\urllib\request.py", line 521, in open
    response = meth(req, response)
               ^^^^^^^^^^^^^^^^^^^
  File "C:\Users\<사용자>\anaconda3\Lib\urllib\request.py", line 630, in http_response
    response = self.parent.error(
               ^^^^^^^^^^^^^^^^^^
  File "C:\Users\<사용자>\anaconda3\Lib\urllib\request.py", line 559, in error
    return self._call_chain(*args)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\<사용자>\anaconda3\Lib\urllib\request.py", line 492, in _call_chain
    result = func(*args)
             ^^^^^^^^^^^
  File "C:\Users\<사용자>\anaconda3\Lib\urllib\request.py", line 639, in http_error_default
    raise HTTPError(req.full_url, code, msg, hdrs, fp)
urllib.error.HTTPError: HTTP Error 404: Not Found

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "<스크래치>\localpy\_guard\guard_run.py", line 137, in <module>
    sys.exit(main())
             ^^^^^^
  File "<스크래치>\localpy\_guard\guard_run.py", line 104, in main
    runpy.run_path(str(root / "trade.py"), run_name="__main__")
  File "<frozen runpy>", line 287, in run_path
  File "<frozen runpy>", line 98, in _run_module_code
  File "<frozen runpy>", line 88, in _run_code
  File "<스크래치>\localpy\local-py\trade.py", line 15, in <module>
… (앞 40줄 · 가운데 줄임 · 끝 2줄 · 전체 57줄)
    raise MarketDataError(f"HTTP {exc.code} {url} — {detail}") from exc
lumina_local.market_data.MarketDataError: HTTP 404 https://query2.finance.yahoo.com/v8/finance/chart/012510.KS?interval=1d&range=1y — {"chart":{"result":null,"error":{"code":"Not Found","description":"No data found, symbol may be delisted"}}}
```

### 2.19 오프라인 점검 — fee_bps 가 왕복인가 편도인가(네트워크 없음 · 감시기 밖)

- 명령: `python _guard/fee_check.py <스크래치>/localpy/local-py`

```text
fee_bps=25 → 거래 2건 · 최종 9,950,150원 · 수익 -0.50% (왕복 해석이면 약 -0.25% · 편도 해석이면 약 -0.50%)
fee_bps=10 → 거래 2건 · 최종 9,980,020원 · 수익 -0.20% (왕복 해석이면 약 -0.10% · 편도 해석이면 약 -0.20%)
```

### 2.20 오프라인 점검 — 캐시 일봉의 마지막 봉 · 최종 장부(네트워크 없음)

- 명령: `python -I -c "...(캐시 JSON · state.json 읽기)"`

```text
005930.KS 일봉 483 개 · 캐시 파일 시각 10-13 09:05:49
    2026-10-06 시가 278500 종가 272000
    2026-10-07 시가 269500 종가 268500
    2026-10-08 시가 269500 종가 262000
042700.KS 일봉 483 개 · 캐시 파일 시각 10-13 09:05:50
    2026-10-06 시가 280000 종가 278000
    2026-10-07 시가 273500 종가 264500
    2026-10-08 시가 267500 종가 267000
000990.KS 일봉 483 개 · 캐시 파일 시각 10-13 09:05:51
    2026-10-06 시가 143000 종가 139700
    2026-10-07 시가 138500 종가 134400
    2026-10-08 시가 135000 종가 138800
012510.KQ 캐시 없음(빈 응답은 캐시하지 않음)
최종 장부: 현금 7441400 · 보유 {'005930.KS': 3, '042700.KS': 3, '000990.KS': 7} · 주문 3 · 사이클 기록 4 · 오늘 주문 수 {'20261013': 3} · 쿨다운 칸 3
data/ 안: ['cache', 'state.json'] · kis_token.json 있음: False
```

## 3. 우리 앱과 다른 점

- local-py 쪽 줄 번호는 강사님 `8624e81` 판 `local-py/` 기준, Qurious 쪽은 `main` `8975696` 을 `git show` · `grep` 으로 찾은 줄이다(짐작한 줄 없음).
- 「누구 몫」 은 앱에 들일지 정할 주담당이다. 이 문서는 관찰 · 비교까지만 한다.

**<표 3> local-py 와 Qurious 비교**

| 항목 | local-py (강사님) | Qurious 지금 (파일:줄) | 차이가 뜻하는 것 | 누구 몫 |
|---|---|---|---|---|
| 실거래 관문 | `--mode live`(또는 `QUANT_MODE=live`)면 가상 장부 체결과 함께 KIS 로 실주문. 모의 · 실전은 `KIS_PAPER` 한 칸이 정함 — true 면 `openapivts :29443`, false 면 `openapi :9443`(`broker.py:25-26 · 231-240` · `config.py:59 · 100`). 키가 없으면 MockBroker 가 로그만. 승인 관문은 없고, 정규장 밖 실주문만 막음(`auto_trade.py:91`) | 실거래는 `QURIOUS_ALLOW_LIVE_TRADING` 이 켜져야만 — 기본 거짓(`app/services/brokers/factory.py:41 · 51-57`). 꺼져 있으면 `paper=False` 요청을 모의로 강등하고, 모의 서버가 없는 증권사는 Mock(`factory.py:78-92`). 자동매매도 같은 관문을 두 겹으로(`app/services/auto_trade.py:266 · 283-285`) · 게이트웨이도 실전을 모의로 내림(`stock_coin_trade_gateway.py:57`) · `docs/ADR/ADR-0001-실거래-주문-경로-차단.md` | local-py 는 설정 두 줄(`QUANT_MODE=live` + `KIS_PAPER=false`)이면 실계좌 주문이 나간다. 앱에 그대로 들이면 rfp-2 §4.2 제외 범위를 깬다. 실험 도구로 쓸 때도 `.env` 를 만들지 않고 `--mode live` · `--source kis` 를 쓰지 않는 것이 안전선 | 오준영(3차 증권사) · 강민석(모의 주문) — 앱에는 들이지 않음(조사서 <표 7>) |
| 사이클 주기 | 180초(3분) — `config.py:58` · `loop --interval`(`cli.py:251`) · 하한 10초(`config.py:168`) | **600초(10분)** — `app/config.py:141-144`(10-08 사용자 결정 · 강민석 답 10-12 「600초 유지」) · 지킴이 `tests/test_base_code_merge_guard.py:98`. 다만 코드 주석 여섯 곳은 아직 「기본 3분」 — `app/services/auto_trade.py:1 · 5 · 52` · `app/celery_app.py:114` · `app/services/kis_batch.py:3` · `app/tasks/sync_tasks.py:117` | 값은 의도대로 600. 주석이 3분이라 읽는 사람이 헷갈린다(작은 정리 거리). local-py 는 3분이어도 일봉 캐시 6시간 때문에 가격이 그동안 그대로다(아래 「시세 · 체결 가격」) | 강민석(주기 값) · 주석은 다음 반영 때 함께(작음) |
| 비용 모델 | 백테스트 `--fee-bps` 기본 25 를 **매수 · 매도에 각각** 뗀다(`backtest.py:23 · 38-41 · 49`) → 실제 왕복 0.50%. 문서는 「왕복 0.25%」(`README.md:65` · `cli.py:267` · `backtest.py:5`) — 오프라인 점검(2.19)으로 확인: 가격 그대로 1회 왕복이면 −0.50%. paper 장부 체결은 비용 0(`store.py:131-169`) | 백테스트 기본 `real` — 위탁 0.0140527% · 유관기관 0.0036396% · 매도세 2026 코스피 0.05% + 농특세 0.15% · 슬리피지 10bp(`app/services/trading_cost.py:42 · 53 · 59 · 78-86 · 94 · 214-240` · 라우트 기본 `app/routes/stocks.py:1064`). 2026 코스피 왕복 ≈ 43.5bp(슬리피지 빼면 23.5bp). 자동매매 가상 체결도 같은 요율로 정산(`app/services/auto_trade.py:149-207`) | 같은 「25」 가 local-py 에선 왕복 50bp — 우리 real(43.5bp)보다 조금 비싸다. S110 삼성전자 2년: 편도 25bp +53.61% · 편도 21.77bp(우리 real 왕복과 같게) +54.78%. paper 비용이 0 이라 local-py 장부 수익은 우리 자동매매보다 조금 좋게 나온다 | 강민석(성과지표 · 비용 #134) — 참고만 |
| 접근 토큰 재사용 | `data/kis_token.json` 에 토큰 · 만료 시각 · 서버 주소를 두고 만료 5분 전까지 다시 씀(`broker.py:9-10 · 52-94`) — 이번에는 KIS 를 부르지 않아 파일이 생기지 않음(2.20) | 토큰을 클라이언트 객체 안에만 두고(`app/services/brokers/kis.py:24-25 · 74-91`) 요청마다 클라이언트를 새로 만든다 → 요청마다 새 토큰(**DF-84** 열림 · `docs/시험/테스트계획서.md:1266`) | 증권사는 토큰 발급을 1분 1회로 묶어 우리 앱은 잔고 · 시세 · 주문을 이어 부르면 막힐 수 있다. 우리 고치는 안(앱 키별 Redis + 만료 시각 · 값은 기록 안 함)이 파일보다 맞다. 다만 「서버 주소까지 함께 적어 모의 · 실전 토큰을 섞지 않는」 점은 그대로 참고할 만하다 | 오준영(3차 증권사) — #153 4절 DF-84 |
| 위험관리 다섯 | 규칙 · 기본값이 같다 — 쿨다운 30분 · 일 20건 · 종목 비중 30% · 일손실 −3% · 비상 정지(`risk_guard.py:60-74 · 84-95 · 99-120 · 124-141 · 145-156` · `config.py:78-81`). 상태는 `data/state.json` 의 `risk`. 공격 모드는 쿨다운 3분 · 일 300건으로 덮음 | 같은 규칙 — `app/services/risk_guard.py:42-62`(한도 = BrokerSettings 칸) · `68`(쿨다운 · Redis SET NX EX) · `105-117`(일 주문 수) · `134 · 156`(일손실) · `165`(비중) · `187`(상태). 비상 정지는 DB 칸(`app/models/trading.py:129` · `auto_trade.py:661 · 718`) · Redis 가 없으면 메모리 | 규칙이 같아 local-py 를 우리 위험관리의 「기대값 계산기」 로 쓸 수 있다. 실측: loop 2회에서 쿨다운이 매수 3건씩을 막음(2.14). 다만 local-py 는 일손실을 캐시된 일봉 종가로 재서 장중 하락을 최대 6시간 못 본다 | 강민석 — 참고 |
| 장부 | JSON 파일 하나(`data/state.json` · 임시 파일 → `os.replace` · 잠금 없음 — `store.py:44-68`). `reset` 은 계정을 통째로 새로 만들어 주문 · 사이클 · 위험 상태까지 지움(`store.py:66-68`) | PostgreSQL — 자동매매는 `QuantVirtualAccount` + `Portfolio(book=QUANT)`, 모의투자는 `PaperAccount` + `book=PAPER`(`app/services/auto_trade.py:9-16` 머리말). 모의 계좌 리셋은 오늘 머지된 #172 로 회차(epoch)를 +1 하고 QUANT · KIS 주문을 보존(`app/services/paper_trading.py:69-109` · `alembic/versions/0020_paper_epoch.py:18-26`) | local-py 리셋에는 회차 경계가 없는 대신 기록이 모두 사라진다 — 실험용으로는 충분하고, #172 가 고친 A1 · A2 를 설명할 때 비교 사례로 쓸 수 있다 | 강민석 — 참고 |
| 휴장일 판정 | 평일 · 09:00 ~ 15:30 만 본다(15:30 포함 · 휴장일은 모름 — `market_data.py:214-219`). 실주문만 이 판정을 쓰고(`auto_trade.py:91`) paper 사이클은 시각을 보지 않는다 — `loop --market-hours` 를 줘야 장 밖에 쉰다(`auto_trade.py:315`) | 게이트웨이의 2026 휴장일 17일 목록 + `KRX_EXTRA_HOLIDAYS`(15:30 미포함 · `app/services/brokers/stock_coin_trade_gateway.py:88-117`) · 수집 DB 달력(`app/services/market_calendar.py:101`) — 2027 판정을 달력에 묻게 하는 일은 남음(변경 추적 댓글 08) | local-py 를 휴장일에 paper 로 돌리면 전날 종가로 「체결」 된다. 실험 기록은 날짜와 함께 읽어야 한다 | 오준영(실행 일정) · 이동원(달력 데이터) — 참고 |
| 시세 · 체결 가격 | 기본 야후 — 일봉 2년 + 6시간 파일 캐시(`market_data.py:155-178` · `config.py:68-69`) · 공격 모드 분봉은 야후 약 20분 지연(`README.md:217` · `market_data.py:181-196`) · 현재가는 `regularMarketPrice`(`market_data.py:199-210`). **사이클 체결가 = 캐시된 일봉의 마지막 종가**(`auto_trade.py:212-215`) | 기본 `MARKET_DATA_SOURCE=kis`(`app/config.py:106`) · 국내 일봉은 수집 DB → KIS → 야후(`app/services/stock.py:269-300`) · 체결가 `current_price` = 마지막 봉 종가(`stock.py:406-409` — **DF-15** 열림 · `docs/시험/테스트계획서.md:1203`) · 공격 모드 분봉은 KIS 먼저 · 야후 폴백(`app/services/aggressive_mode.py:106-123`) | S110 실측 — 10-13 09:05 에 받은 야후 일봉의 마지막 봉이 10-08 이었다(10-12 거래일 봉 없음 · 우리 휴장일 목록 기준). 그래서 paper 체결가는 10-08 종가(삼성전자 262,000)였고 바로 뒤 `status` 현재가(250,500)로 재면 −1.4%. 두 앱 모두 「현재가 = 마지막 일봉 종가」 꼴(DF-15)인데, local-py 는 야후 지연 · 6시간 캐시가 더해져 더 묵는다 | 강민석(자동매매 체결가 · DF-15) · 이동원(시세 경로) — 참고 |
| 유니버스 · 종목 기호 | 반도체 · IT · K뷰티 31종목(`universe.py:8-44`). `012510.KQ`(더존비즈온)는 야후가 빈 값 · `012510.KS` 는 404(「symbol may be delisted」)라 「판단 불가」 · `backtest` 는 이 404 를 잡지 않아 traceback(`cli.py:172`) | 우리 31종목 · 18섹터(`app/services/stock.py:28` · 지킴이 `tests/test_base_code_merge_guard.py:108`) — 강사님 유니버스를 받을지는 오준영 님 판단 대기(#153 1절) | 강사님 유니버스를 받게 되면 012510 같은 종목 기호를 수집 DB 시장 칸과 먼저 대조해야 한다(#153 1절에 적힌 위험이 실제로 보임) | 오준영 — 참고 |

## 4. 이 도구를 우리에게 어떻게 쓸 수 있나

**<표 4> 쓰는 안 (추천은 첫 칸)**

| 안 | 무엇 | 까닭 | 조건 · 한계 |
|---|---|---|---|
| **1 (추천) 저장소 밖 실험 도구로 따로 둔다** | 강사님 사본(`learning/th06` · pull 전용)을 필요할 때 스크래치로 풀어 mock · paper · 야후로만 돌린다 | 표준 라이브러리만이라 설치가 없고, 시험이 몇 초 · 증권사 호출 0 · 우리 앱 코드에 영향이 없다. 같은 규칙(지표 점수 · 위험관리 다섯)의 동작을 빠르게 눈으로 볼 수 있다 | `.env` 를 만들지 않는다 · `--mode live` · `--source kis` 금지 · 감시기(바깥 연결 기록 · 증권사 주소 차단)로 돌린다 · 휴장일 · 야후 일봉 지연을 기록과 함께 읽는다 · 체결가 · 비용이 실제와 다르니 숫자는 실험용 |
| 2 시험 데이터 · 기대값 계산기 | mock 시세(종목코드로 시드를 고정한 랜덤워크)와 위험관리 순수 함수로 「같은 입력 → 같은 판정」 표를 만들어 우리 자동매매 시험의 기대값 대조에 쓴다 | 규칙 · 기본값이 우리 `risk_guard` 와 같아 회귀 확인에 좋다 | 코드를 옮기지 않고 입력 · 기대값 표만 · 강민석 님이 원할 때(5절 초안) |
| 3 본보기 코드로만 | 토큰 파일 재사용(서버 주소까지 함께 저장) · 「매수후보유와 나란히」 백테스트 출력 꼴 | DF-84 고치는 안 · 성과 화면 문구를 정할 때 참고 | 오준영 · 강민석 님 판단 · fee 문서 불일치는 반면교사(편도 · 왕복을 이름에 적기) |
| 4 앱에 합치기 | — | 하지 않는다 — 실거래 관문 없음 · 별도 스택 · 3분 · 비용 가정이 다름(조사서 <표 7> 그대로) | — |

## 5. 이슈 초안 한 줄 (앱에 들이는 판단은 주담당 몫)

- **강민석 님(@rkdalstjr)** — 「강사님 `local-py`(표준 라이브러리 자동매매)를 저장소 밖에서 mock · paper 로만 돌려 봤습니다. 위험관리 다섯의 규칙 · 기본값이 우리와 같아 자동매매 시험의 기대값 대조에 쓸 수 있고, 백테스트 `--fee-bps` 는 매수 · 매도에 각각 붙어 기본 왕복 0.50%(문서는 0.25%)입니다. paper 체결가는 야후 캐시 일봉의 마지막 종가라 우리 DF-15 와 같은 꼴입니다 — 시험에 쓸지 의견 주세요.」
- **오준영 님(@GoonGuMa)** — 「`local-py` 는 KIS 접근 토큰을 `data/kis_token.json` 에 서버 주소 · 만료 시각과 함께 두고 만료 5분 전까지 다시 씁니다. DF-84(우리는 요청마다 새 토큰 · 1분 1회 제한) 고치는 안을 정할 때 참고로 드립니다 — 우리 안은 앱 키별 Redis 입니다.」

## 6. 한계 · 남은 것

- KIS 경로(`--source kis` · `--mode live`)는 지시대로 돌리지 않았다 — 토큰 파일 재사용 · 실주문 경로는 코드 읽기로만 확인했다.
- 공격 모드(`--aggressive`)는 지시 범위 밖이라 돌리지 않았다 — 야후 분봉 20분 지연은 문서 · 코드 기준이다.
- 감시기는 표준 라이브러리 통신 경로(socket · urllib)를 본다. local-py 는 표준 라이브러리만 쓴다(`requirements.txt` — 설치할 것 없음).
- 백테스트는 야후 종가(수정 종가 `adjclose` 미사용 · `market_data.py:92-107`) 2년 · 종가 체결 가정이라 수익률 숫자는 실험용이다.
- 야후 일봉에 10-12 봉이 없던 것은 09:05 한 번의 관찰이다 — 다른 출처(수집 DB)와 대조하지 않았다(수집 DB 는 열지 않음).
