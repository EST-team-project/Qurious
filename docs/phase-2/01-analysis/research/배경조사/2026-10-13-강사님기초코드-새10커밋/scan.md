<!-- 옮김 2026-10-16 — 원래 자리 docs/_git-drafts/2026-10-13-S110/배경-th06-새10커밋/scan.md · 작업 기록(그때 쓴 그대로 · 세션 번호 등 내부 표기 포함) · 정본 없음 · 관련 docs/github-archive/2026-09-28/이슈-강사님자료-변경추적/17-2026-10-13-th06-새10커밋.md -->
# 스캐너 결과 — th06 줄 (2026-10-13 10:20 KST)

- 명령: 저장소 뿌리에서 `PYTHONIOENCODING=utf-8 python scripts/lecture_scan.py --md` (읽기 모드 · 종료 코드 0)
- 스캐너는 로컬 `origin/main` 만 읽는다(네트워크 0 · 파일 쓰기는 `--update` 갈래뿐). `--update` 는 쓰지 않았고, 실행 뒤 `git status` 로 `기준점.tsv` 가 바뀌지 않은 것을 봤다.
- 아래 「원문」 은 스캐너 출력에서 th06 두 줄과 th06 두 절만 그대로 옮긴 것이다. 「비교:」 줄은 커밋 해시 고정 링크라 댓글 초안에는 넣지 않았다.

## 원문 — 상태 표의 th06 줄

| 폴더 | 원본 | 지금 끝 | 상태 |
|---|---|---|---|
| th06-lumina-invest · 서버 | `edumgt/lumina-invest` | `ebf4668` 2026-10-12 17:12 | **20커밋** (`e815be3` 부터) |
| th06-lumina-invest · 화면 | `edumgt/lumina-invest` | `ebf4668` 2026-10-12 17:12 | **31커밋** (`9478811` 부터) |

## 원문 — th06 절

### th06-lumina-invest · 서버 — 20커밋 (`e815be3` → `ebf4668` · 58 files changed, 7350 insertions(+), 164 deletions(-))

비교: https://github.com/edumgt/lumina-invest/compare/e815be3...ebf4668

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
| `9675dcc` | 10-12 14:44 | feat: 섹터별 투자 인디케이터 모달 설명 추가 및 기존 기능 개선 |
| `c66fa00` | 10-12 15:03 | feat: 통화 단위 처리 개선 및 재무 데이터 표시 방식 수정 |
| `91e482d` | 10-12 15:13 | feat: DART 모듈 추가 및 영업이익·재무상태표 데이터 처리 개선 |
| `033f777` | 10-12 15:25 | feat: DART API 키 추가 및 재무 데이터 처리 개선 |
| `46da4cc` | 10-12 16:14 | feat: 패턴 분석에 일목균형표·매물대·갭·거래량 급증 탐지 추가, 분봉 지원 |
| `2852210` | 10-12 16:44 | feat: 일봉 데이터 시스템 OHLCV 저장소 우선 → 없는 구간 적재 → Yahoo, #quant-backtest 실제 백테스트 화면으로 |
| `4e64241` | 10-12 16:47 | fix: #quant-backtest 백테스트 API 경로 /api/quant/pipeline 로 수정 |
| `03eed2b` | 10-12 17:02 | feat: 비교 트레이에 분석 자료 추가 — 순위표·읽는 법·주의·Markdown 복사, 항목별 구조화 지표 저장 |
| `3a135b1` | 10-12 17:09 | fix: #quant-backtest 비교에 추가 버튼 onclick 속성이 ')' 앞에서 닫히던 오류 |
| `ebf4668` | 10-12 17:12 | fix: 공통 CSS Pretendard 가변 폰트 woff2 를 npm CDN 경로로 교체 (gh 경로 404) |

### th06-lumina-invest · 화면 — 31커밋 (`9478811` → `ebf4668` · 28 files changed, 17784 insertions(+), 340 deletions(-))

비교: https://github.com/edumgt/lumina-invest/compare/9478811...ebf4668

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
| … | | 외 11커밋 — 비교 링크에서 |

## 읽는 법 — 이번 점검과 맞춰 보기

| 줄 | 지난 확인(댓글 16 · 10-12) | 이번 | 새것 | 메모 |
|---|---|---|---|---|
| th06 · 서버 | `8624e81` 까지 10커밋 | `ebf4668` 까지 **20커밋** | 10 — 새 10커밋이 모두 `public/` 밖을 건드림(적어도 `todo.md`) | 9675dcc · 4e64241 · 03eed2b · 3a135b1 은 서버 쪽 변경이 `todo.md` 뿐 |
| th06 · 화면 | `8624e81` 까지 22커밋 | `ebf4668` 까지 **31커밋** | 9 — `ebf4668` 만 `public/` 을 안 건드림(바깥 공통 CSS · `todo.md`) | 화면 표는 앞 20줄만 보이고 새 9커밋은 「외 11커밋」 안에 들어 있다 → `결과.md` 1절 표에 모두 적음 |

- 기준점 TSV 의 th06 두 줄(서버 `e815be3` · 화면 `9478811`)은 그대로다. 받은 뒤 그 줄만 옮긴다(스캐너 머리말 · 기억 「기준점은 그 줄만 옮김」).

## 같은 실행에서 보인 다른 줄 — 이번 점검 범위 밖(내용은 보지 않음)

| 폴더 | 상태 | 메모 |
|---|---|---|
| th03-stock-coin-trade | `9d5fa01` 2026-10-12 16:52 · **13커밋**(`9242a3d` 부터) | 댓글 16(10-12)은 `138cf28` 까지 10커밋을 봤다 → 새 3커밋 `ca84180`(ag-Grid 포트폴리오 표) · `a3227c4`(ag-Grid 보유 그리드 · 종목 코드 조회 내장 폴백) · `9d5fa01`(OHLCV 수집 주기 · 시간대) — 다음 점검 몫 |
| th07-domain-rag-lab | `fbdf17b` · 1커밋 | 댓글 16 에서 봄(공통 CSS 판 번호) |
| th19-multi-db-lab | `29a9a92` 2026-10-12 15:53 · 「이력 바뀜」 | 댓글 16 때 끝은 `42b07bd` 였다 — 얕은 사본이라 커밋 수를 못 셈 |
| th24-stock-kms-portal | `76a6045` · 「이력 바뀜」 | 댓글 16 과 같은 끝 |
| 나머지 | 변화 없음 · th04 lecture 없음 | — |
