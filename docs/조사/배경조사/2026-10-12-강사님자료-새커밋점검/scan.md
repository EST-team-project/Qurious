<!-- 옮김 2026-10-16 — 원래 자리 docs/_git-drafts/2026-10-12-S109/배경-강사님자료/scan.md · 작업 기록(그때 쓴 그대로 · 세션 번호 등 내부 표기 포함) · 정본 없음 · 관련 docs/github-archive/2026-09-28/이슈-강사님자료-변경추적/16-2026-10-12-th06-새2커밋-th03-10커밋.md -->
<!-- 원문 · `PYTHONIOENCODING=utf-8 python scripts/lecture_scan.py --md` (저장소 뿌리 · 읽기 모드 · --update 쓰지 않음) · 2026-10-12 15:18 KST 실행 · 손대지 않은 출력 -->

## 강사님 자료 변경 — 2026-10-12 15:18 확인

| 폴더 | 원본 | 지금 끝 | 상태 |
|---|---|---|---|
| th01-investment-analysis | `edumgt/investment-analysis` | `12f423d` 2026-10-02 17:37 | 변화 없음 |
| th02-docker | `edumgt/docker-class` | `50547fd` 2026-09-11 15:23 | 변화 없음 |
| th03-stock-coin-trade | `edumgt/stock-coin-trade` | `138cf28` 2026-10-12 14:21 | **10커밋** (`9242a3d` 부터) |
| th04-in2 | — | — | lecture 없음 |
| th05-quant-krx | `edumgt/krx-aggrid` | `8684a2b` 2026-08-28 17:46 | 변화 없음 |
| th06-lumina-invest · 서버 | `edumgt/lumina-invest` | `8624e81` 2026-10-12 12:40 | **10커밋** (`e815be3` 부터) |
| th06-lumina-invest · 화면 | `edumgt/lumina-invest` | `8624e81` 2026-10-12 12:40 | **22커밋** (`9478811` 부터) |
| th07-domain-rag-lab | `edumgt/domain-rag-lab` | `fbdf17b` 2026-10-12 11:57 | **1커밋** (`35f9027` 부터) |
| th08-aws-ec2-alb-lab | `edumgt/aws-ec2-alb-lab` | `d47c244` 2026-09-21 14:54 | 변화 없음 |
| th09-python-ai-basic-lab | `edumgt/python-ai-basic-lab` | `b723826` 2026-07-30 04:23 | 변화 없음 |
| th10-stock-ml-dl-project | `edumgt/stock-ml-dl-project` | `ef0240e` 2026-10-02 17:46 | 변화 없음 |
| th11-python-ml-class | `edumgt/python-ml-class` | `e84cf65` 2026-07-30 04:06 | 변화 없음 |
| th12-python-crawling-lab | `edumgt/python-crawling-lab` | `1572282` 2026-07-02 10:45 | 변화 없음 |
| th13-py-util | `edumgt/py-util` | `e8554b9` 2026-06-11 21:41 | 변화 없음 |
| th14-edumgt-lab-init | `edumgt/edumgt-lab-init` | `3783d98` 2026-09-14 21:13 | 변화 없음 |
| th15-aihub-rag | `edumgt/aihub-rag` | `a1fbe8d` 2026-07-02 14:42 | 변화 없음 |
| th16-ai-agent-lab | `edumgt/ai-agent-lab` | `7151a88` 2026-06-29 12:49 | 변화 없음 |
| th17-invest-flow | `edumgt/invest-flow` | `81165da` 2026-07-02 14:06 | 변화 없음 |
| th18-langchain-lab | `edumgt/langchain-lab` | `87bc4d5` 2026-06-29 11:58 | 변화 없음 |
| th19-multi-db-lab | `edumgt/multi-db-lab` | `42b07bd` 2026-10-12 12:10 | 이력 바뀜 — 기준 커밋이 원격 이력에 없다 |
| th20-aws-serverless | `edumgt/aws-serverless` | `206b70c` 2026-10-01 11:49 | 변화 없음 |
| th21-ollama-llava-canvas | `edumgt/ollama-llava-canvas` | `fb4ea94` 2026-07-30 04:11 | 변화 없음 |
| th22-vdp-agent | `edumgt/vdp-agent` | `8745eb9` 2026-07-07 11:18 | 변화 없음 |
| th23-meeting-agent | `edumgt/meeting-agent` | `0b56382` 2026-07-06 15:03 | 변화 없음 |
| th24-stock-kms-portal | `edumgt/stock-kms-portal` | `76a6045` 2026-10-12 11:57 | 이력 바뀜 — 기준 커밋이 원격 이력에 없다 |
| th25-fe-vanilla | `edumgt/fe-vanilla` | `f76c882` 2026-10-02 17:34 | 변화 없음 |

### th03-stock-coin-trade — 10커밋 (`9242a3d` → `138cf28` · 113 files changed, 1707 insertions(+), 278 deletions(-))

비교: https://github.com/edumgt/stock-coin-trade/compare/9242a3d...138cf28

| 커밋 | 시각 (KST) | 제목 |
|---|---|---|
| `50d91bc` | 10-08 11:27 | Add unit tests for crypto exchange candle retrieval |
| `6c7ab53` | 10-08 14:33 | feat: game.edumgt.co.kr에 대한 nginx 역프록시 설정 추가 |
| `b98409e` | 10-08 14:58 | feat: unify footer styles across multiple frontend pages for stock investment repositories |
| `696407a` | 10-08 14:59 | feat: 사용자 인증 상태에 따른 UI 업데이트 및 외부 API 요청 제한 미들웨어 추가 |
| `a227dd6` | 10-08 15:00 | feat: ExternalReadLimitMiddleware에 대한 단위 테스트 추가 |
| `363e934` | 10-08 17:18 | feat: unify common CSS across multiple repositories and update HTML files |
| `ab4e493` | 10-08 17:46 | fix: update common CSS version across multiple frontend files to resolve styling issues |
| `18a13c2` | 10-12 11:57 | 1 |
| `3e03fa2` | 10-12 14:14 | fix: restore broken CSS across multiple sites and unify styles (common cascade layers and standard tokens) - v20261012-common-3 |
| `138cf28` | 10-12 14:21 | feat: KIS 모의투자 탭 추가 및 포트폴리오 시각화 구현 |

### th06-lumina-invest · 서버 — 10커밋 (`e815be3` → `8624e81` · 50 files changed, 5628 insertions(+), 121 deletions(-))

비교: https://github.com/edumgt/lumina-invest/compare/e815be3...8624e81

| 커밋 | 시각 (KST) | 제목 |
|---|---|---|
| `995b9c7` | 10-08 10:23 | Refactor code structure for improved readability and maintainability |
| `c6e9c2f` | 10-08 11:27 | feat: Add company indicator help functionality and related tests |
| `6e26041` | 10-08 11:40 | feat: 화면 하단에 실행 로그 카드 추가 및 제어 카드에서 로그 새로고침 버튼 이동 |
| `0ca06dc` | 10-08 14:33 | feat: Update indicator backtest functionality and UI for multi-strategy comparison |
| `85c3444` | 10-08 14:58 | feat: KIS 연계 시세 및 패턴 분석 기능 개선, 공통 푸터 스타일 통일 |
| `5b40fbe` | 10-08 16:40 | feat: Implement local automated trading system with state management and strategy evaluation |
| `c63cc1a` | 10-08 17:18 | feat: 4개 사이트 공통 스타일 CSS 단일화 및 배포 스크립트 추가 |
| `5b0a768` | 10-08 17:46 | feat: OHLCV 저장소 클라이언트 추가 및 종목 검색 로직 개선 |
| `476d538` | 10-12 11:57 | feat: 공통 CSS 버전 업데이트 및 감사 스크립트 추가 |
| `8624e81` | 10-12 12:40 | feat: KIS 호출 최적화 및 confirm_fills 예산 초과 처리 개선 |

### th06-lumina-invest · 화면 — 22커밋 (`9478811` → `8624e81` · 25 files changed, 17336 insertions(+), 289 deletions(-))

비교: https://github.com/edumgt/lumina-invest/compare/9478811...8624e81

| 커밋 | 시각 (KST) | 제목 |
|---|---|---|
| `a4225b9` | 10-06 10:25 | feat(kis): 계정 무관 KIS 모의투자 백그라운드 배치 + todo 갱신 |
| `f250bda` | 10-06 10:37 | feat(quant): 유니버스 반도체·IT·K뷰티 31종목으로 조정, 자동매매 5분 주기 |
| `2970633` | 10-06 12:29 | feat(ui): 로보 어드바이저 > KIS 모의투자결과 전용 모니터링 화면 + /api/quant/kis/monitor |
| `e54b0d0` | 10-06 12:43 | feat(rebalance): KIS 모의투자 계좌 소스 + 섹터(반도체·IT·K뷰티)·종목 2단 목표 리밸런싱 |
| `d3206b8` | 10-06 16:39 | feat: Enhance stock screening functionality with progress indicators and modal explanations |
| `0c55dbc` | 10-06 17:16 | feat(pattern-analysis): 캔들 패턴 분석 기능 추가 및 UI 개선 |
| `a4be79a` | 10-07 11:38 | feat: update auto trading cycle to 3 minutes and adjust related configurations |
| `26658e2` | 10-07 12:36 | feat(orders): 봇 실주문 검색 기능 추가 및 UI 개선 |
| `a55488d` | 10-07 14:12 | feat: KIS 계좌 보유 및 정합성 정보 UI 개선 |
| `c0473f7` | 10-07 15:16 | feat: KIS 모의투자 단독 실행 모드 및 관련 기능 추가 |
| `9600595` | 10-07 15:47 | feat: LLM 모델 업데이트 및 공통 타이포그래피 가이드 추가 |
| `2fcdb83` | 10-07 15:52 | feat: LLM 모드 개선 및 RAG 모드에서 LLM 요약 사용 시 예외 처리 추가 |
| `5638a67` | 10-07 16:43 | feat: LLM 모드 레이블 수정 및 QdrantVectorStore 호환성 추가 |
| `e815be3` | 10-07 17:36 | feat: LLM 모델을 qwen2.5:3b로 변경 및 관련 UI 수정 |
| `995b9c7` | 10-08 10:23 | Refactor code structure for improved readability and maintainability |
| `c6e9c2f` | 10-08 11:27 | feat: Add company indicator help functionality and related tests |
| `6e26041` | 10-08 11:40 | feat: 화면 하단에 실행 로그 카드 추가 및 제어 카드에서 로그 새로고침 버튼 이동 |
| `0ca06dc` | 10-08 14:33 | feat: Update indicator backtest functionality and UI for multi-strategy comparison |
| `85c3444` | 10-08 14:58 | feat: KIS 연계 시세 및 패턴 분석 기능 개선, 공통 푸터 스타일 통일 |
| `c63cc1a` | 10-08 17:18 | feat: 4개 사이트 공통 스타일 CSS 단일화 및 배포 스크립트 추가 |
| … | | 외 2커밋 — 비교 링크에서 |

### th07-domain-rag-lab — 1커밋 (`35f9027` → `fbdf17b` · 9 files changed, 107 insertions(+), 13 deletions(-))

비교: https://github.com/edumgt/domain-rag-lab/compare/35f9027...fbdf17b

| 커밋 | 시각 (KST) | 제목 |
|---|---|---|
| `fbdf17b` | 10-12 11:57 | feat: 공통 CSS 버전 업데이트 및 스타일 통일화 작업 |
