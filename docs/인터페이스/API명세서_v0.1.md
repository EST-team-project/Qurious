# API 명세서 v0.1 — Qurious

| 항목 | 내용 |
|------|------|
| **문서 버전** | v0.1 (첫 판) |
| **작성일** | 2026-09-29 (KST) · S63 |
| **작성자** | 이동원 (P-A) |
| **기준 코드** | `main` = `5adfb81` (PR #48 머지 뒤) — `app/` 은 이 커밋과 같다 · **2026-09-29 DF-17 수정 뒤 2 · 4절 표를 다시 채웠다**(`stocks.py` 줄 번호 · STK-03 · 04 캐시 칸) |
| **추출기** | [`scripts/api_scan.py`](../../scripts/api_scan.py) — 앱을 import 하지 않는 정적 AST · 시험 [`tests/test_api_scan.py`](../../tests/test_api_scan.py) (TC-AP 13건) |
| **ID 대장** | [`API-ID대장.tsv`](API-ID대장.tsv) — ~~146줄~~ ~~181줄~~ **189줄**(2026-09-30 — 강사님 기초 코드 반영 181 · 계정 관리 +4 · 용어사전 +4 · 9절) · 한 번 붙인 ID 는 바뀌지 않는다 |
| **정답 대조** | 도커 안 `app.openapi()`(= `/openapi.json`) 와 **145/145 일치** — 메서드 · 경로 · 경로/질의 인자 · 요청 본문 모델 (1.2절) |
| **산출물 구분** | 강사님 표 **7 인터페이스 설계** — API 명세서 · 인터페이스 정의서(7절 · 시작) · 데이터 매퍼(8절 · 시작) |
| **목적** | ② 강사님 요구 29개 설계(S63)의 **입력** — 요구마다 「어느 API 가 받고 어디에 닿는가」를 이 문서의 API ID 로 가리킨다 |

> **읽는 사람이 둘이다.**
> 팀원은 **4절 라우터별 표**에서 「파트(제안)」 칸으로 자기 몫을 찾고, 3절 발견에서 자기 파트 줄을 읽으면 된다.
> 강사님 표 7구분(인터페이스 설계 — 요청·응답 · 인증 · 오류 코드 · 데이터 교환 규칙)으로 보는 분은
> 2절(한눈에) → 6절(오류 코드) → 7절(인터페이스 정의서) → 8절(데이터 매퍼) 순서가 빠르다.

---

## 0. 쉬운 요약 세 줄

1. 앱의 API 는 **146개**(라우터 파일 19개)다. 소스를 읽어 뽑은 표가 실제 앱이 내놓는 명세(`/openapi.json`)와 **145/145 같다** — 146번째는 명세에서 일부러 뺀 `docs-summary` 하나다.
2. **응답 모양을 선언한 API 가 0개**다(`response_model` 0/146). 그래서 이 문서의 「응답」 칸은 코드의 `return {...}` 글자 키를 적은 것이고, 응답이 **계약으로 보장되는 곳은 계약 시험이 붙은 2곳**(시세 등락률 TC-A1 · 일봉 다리 TC-CD)뿐이다.
3. 명세를 만들다 **새 결함 후보 하나**가 나왔다 — 일봉 · 지표 API 앞에 **6시간 캐시**가 있어, 12:30 일일 갱신 뒤에도 최대 6시간 동안 옛 기준일(`as_of`)을 돌려준다. S57 다리가 약속한 「캐시를 거치지 않는다」가 **라우트 층에서** 깨져 있었다(3절 F2 · DF-17 후보 · P-A 몫).
   → **고쳤다(DF-17 · 2026-09-29)** — 수집 DB 에서 읽는 요청(국내 주식 · 일봉)은 이제 라우트 캐시를 거치지 않아, 12:30 갱신이 바로 보인다.

---

## 1. 이 문서를 어떻게 만들었나

### 1.1 만드는 길 — 손으로 옮긴 숫자가 없다

```
   app/routes/*.py  ─┐
   app/services/**  ─┼─▶ scripts/api_scan.py ──▶ 라우트 146 ──┬─▶ --md       (4절 라우터별 표)
   app/lib/**       ─┤    (AST · import 안 함)                 ├─▶ --overview (2절 · 6절 요약 표)
   app/main.py      ─┘            │                            ├─▶ --models   (5절 요청 모델)
                                  │                            └─▶ --doc 이 문서 (표시 사이만 다시 채움)
   docs/인터페이스/API-ID대장.tsv ─┘ (ID 는 여기서 온다)
   public/app.html · js/*.js ──▶ scripts/view_scan.py ──▶ 「화면」 칸

   정답 대조:  도커 이미지(5adfb81) 안에서 app.openapi() ──▶ --openapi 대조 ──▶ 145/145
```

- 앱을 **import 하지 않는** 이유 — 앱 import 는 PostgreSQL · Redis · Neo4j · Qdrant · Ollama 5개가 떠 있어야 하고(collector README §2) 로컬 파이썬에는 앱 의존성도 없다(`neo4j` 없음 · 실측). 정적 추출은 **1초 남짓**(화면 잇기 포함 · 실측 1.1초)에 돌고 네트워크를 쓰지 않는다.
- 표 셋(2절 · 4절 · 5절)은 문서 안 표시(`<!-- api_scan:이름 -->`) 사이를 스캐너가 채운다. 코드가 바뀌면 `python scripts/api_scan.py --doc docs/인터페이스/API명세서_v0.1.md` 한 줄이면 되고, 표시 밖의 글(이 절 · 3절 · 7절 · 8절)은 사람이 고친다. **`--check` 를 붙이면 고치지 않고 「문서가 뒤처졌는가」만 본다**(종료코드 1). 시험 게이트로는 걸지 않았다 — 다른 파트가 라우트를 고칠 때 그 PR 을 막으면 안 되고, 팀 공용 장치는 논의 먼저다(ADR-0003).

### 1.2 정답과 한 번 맞춰 봤다 — 145/145 🟢

도커 이미지를 `5adfb81` 의 `app/`·`public/`·`alembic/` 만으로 빌드하고(`data/` 2.9GB 를 컨텍스트에 싣지 않으려고 따로 모음),
**네트워크를 끊은 컨테이너**(`--network none`)에서 `app.openapi()` 만 불렀다. 서버는 띄우지 않았다.

| 대조 | 결과 |
|------|------|
| OpenAPI 오퍼레이션 | 145 |
| 스캐너 라우트 | 146 = 145 + `include_in_schema=False` 1 (`GET /openapi/v1/docs-summary`) |
| OpenAPI 에만 있음 · 스캐너에만 있음 | **0 · 0** |
| 경로 · 질의 인자 이름이 다름 | **0** (처음 2건 → `AlpacaTestBody \| None` 선택형 본문을 못 알아본 것 · 고침 · 시험 TC-AP-08) |
| 요청 본문 모델이 다름 | **0** |

> **뒤집을 조건** — 라우터를 `include_router(prefix=...)` 로 다시 접두어를 붙이거나, 데코레이터를 문자열이 아닌 변수 경로로 쓰면
> 스캐너가 경로를 틀리게 적는다. 지금 코드에는 둘 다 없다(`main.py` 의 `include_router` 19줄 모두 인자 하나).
> 그런 코드가 들어오면 `--openapi` 대조가 「한쪽에만」 으로 드러낸다.

### 1.3 칸 읽는 법 · 용어

| 칸 | 뜻 | 이 문서에서 | 헷갈리는 점 |
|----|----|------------|-------------|
| **API ID** | `API-<라우터 머리글>-NN` | [ID 대장](API-ID대장.tsv)에서 온다. 라우트가 사라져도 번호를 다시 쓰지 않는다(「폐기」) | **순번이 아니다.** 순번이면 하나가 끼는 순간 뒤가 전부 밀린다(RTM v1.0 §2.2 의 교훈 · 시험 TC-AP-09) |
| **인증** | 인자 기본값 `Depends(...)` 를 풀어 붙인 이름표 | `세션` = 쿠키 `fin_session` · `세션·JWT` = 쿠키 또는 `Authorization: Bearer <JWT>` · `API 키` = Open API 키 · `+ 관리자` · `+ 역할(…)` · `없음` | 인증 **의존성 안**에서 도는 일(세션 조회 = Redis)은 「닿는 곳」 에 넣지 않았다 — 7절 IF-05 에 따로 셌다 |
| **요청** | 경로 `{x}` · 질의 `x`(\* = 필수) · 본문 `Model` · 파일 · 쿠키 | FastAPI 가 읽는 규칙 그대로 | 본문 모델의 칸은 5절 |
| **응답** | `response_model` → 없으면 응답 클래스 → 없으면 `return {...}` 글자 키 | 146개 모두 `response_model` 이 없어 **글자 키**다. 「외 N」 은 키가 더 있다는 뜻 | 키가 있다고 값이 채워진다는 보장은 없다 — 계약 시험이 있는 곳만 보장(F3) |
| **오류** | 라우트 **본문에 적힌** `HTTPException` 과 그 하위 클래스의 코드 | `401 UNAUTHORIZED` 처럼 뒤 글자는 Open API 의 오류 이름 | 인증 의존성의 401 · FastAPI 가 스스로 내는 422 · 서비스 안에서 던지는 것은 **이 칸에 없다**(6절) |
| **닿는 곳** | 라우트 본문에서 시작한 **정적 호출 그래프**가 닿는 시스템 | 수집DB · 야후 · 증권사(관문) · 주문 · PostgreSQL · Redis · Neo4j · Qdrant · LLM · Celery · LEAN · Docker · 알림 · 외부(호스트) · 라우트 캐시 N h | **가능한 길의 합집합**이다. `get_candles` 는 국내 주식 일봉이면 수집DB, 아니면 야후 — 둘 다 뜬다 |
| **다리** | DF-08 `app/services/collector_db.py` — 앱이 수집 DB 를 읽는 유일한 길 | 「다리 결과 그대로 (`source`·`as_of`)」 = 응답에 기준일이 실린다 | 다리에 **닿는** 것과 응답에 기준일이 **실리는** 것은 다르다(19 대 2 · F6) |
| **관문** | ADR-0001 실거래 차단 — `brokers/factory.get_broker_client` 한 곳 | 「증권사」 = 이 함수에 닿는다 · 「주문」 = `.place_order(` 를 부른다 | 관문을 지나도 `QURIOUS_ALLOW_LIVE_TRADING` 이 꺼져 있으면 모의로 강등된다 |
| **라우트 캐시** | 라우트 본문이 직접 `cache_get(…, max_age_hours=N)` 을 부름 | PostgreSQL `data_cache` 표. N 시간 안이면 서비스 함수를 안 부르고 저장본을 돌려준다 | 서비스 함수의 캐시와 다르다 — 다리는 서비스 층에서 캐시를 건너뛰는데 라우트 층이 다시 씌웠다(F2) |
| **화면** | 그 API 를 부르는 메뉴 화면(IA 의 view 키) | `view_scan.py` 가 `app.html`·`paper.js` 에서 화면별로 뽑은 경로를 맞춘 것. `(다른 곳)` = 메뉴 화면은 아니지만 `public/` 어디엔가 경로 글자가 있다(로그인 · 공통 JS) | JS 에는 메서드가 없어 같은 경로의 GET · POST 가 함께 잡힌다 |
| **파트(제안)** | 분배안 v1.0(옛 `#62`) §3 요구 → 파트 대응을 **경로에 옮긴 것** | P-A 데이터 · P-B 지표·신호 · P-C 자산배분·리밸런싱 · P-D 검증·성과 · P-E 안전·실행·운영 · 공통(인증·관리) | **합의된 소유가 아니다** — D0 ⑤ 역할이 3/4. 경계가 걸친 경로는 근거 칸에 「경계」 로 적었다(`--json` 의 `part_basis`) |
| **요구 ID** | RTM v1.0 의 계층 ID (`P01-③-2` · 사각지대 `RFP2-3.1.3-①`) | [기능 설계서 v0.1](../설계/기능설계_v0.1.md) **부록 A** 의 표를 스캐너가 뒤집어 채운다(S63 ②) — **146 중 105**. 비는 41개는 인증 10 · 관리 3 · 모의투자 코인 · 대체자산 · 알파카 19 · Open API 계좌 · 주문 6 · 그래프 문서 · 시드 2 · `API-QNT-01` 1 — 요구 밖(D1 ③ 동결 후보가 많다) | API 하나가 요구 여럿을 받을 수 있다. 정본은 설계서 쪽(요구 → API)이고 이 칸은 그 역방향이다 |

확실도 — 🟢 코드·실측으로 확인 · 🟡 코드로는 그렇게 보이나 실행으로 확인 안 함 · 🔴 틀렸거나 결함

### 1.4 한계 — 이 문서가 판정하지 않는 것

- **런타임에 그 길을 타는가.** 「닿는 곳」 은 정적 호출 그래프다. 인스턴스 메서드(`client.get_balance()`) · `getattr` · 문자열 태스크 이름은 이름으로 못 풀어 **빠질 수 있고**(과소), 지역 변수가 가져온 이름을 가리면 **없는 길이 생길 수 있다**(과대). 증권사를 「관문 함수에 닿는가」로 보는 이유가 이것이다.
- **응답 값이 맞는가.** 글자 키가 있다고 값이 옳다는 뜻이 아니다. 옛 `A1`(등락률이 늘 `None`)은 키는 있고 값이 비어 있던 사례다.
- **화면이 정말 부르는가.** 「화면」 칸은 view_scan 의 휴리스틱(진입 훅 + 버튼 리스너 1단계)을 따른다. IA v0.2 1.5절의 브라우저 확인은 주 경로 12개뿐이다.

---

## 2. 한눈에 — 숫자

```mermaid
flowchart LR
  B["브라우저<br/>메뉴 화면 49"] -->|"쿠키 fin_session<br/>74개 호출"| API["앱 API 146<br/>(라우터 19)"]
  C["외부 클라이언트"] -->|"Bearer API 키<br/>/openapi/v1 9"| API
  API -->|"107"| PG[("PostgreSQL")]
  API -->|"22 (+ 인증 105)"| RD[("Redis")]
  API -->|"19 · 응답에 as_of 2"| CDB[("수집 DB<br/>SQLite 읽기 전용")]
  API -->|"43"| YH["야후 🔴 약관"]
  API -->|"7 · 주문 3"| GATE{"실거래 관문<br/>ADR-0001"}
  GATE --> BRK["증권사<br/>KIS 실전·모의 · KB · eBest …"]
  API -->|"16"| QD[("Qdrant")]
  API -->|"15"| LLM["LLM<br/>Ollama · vLLM"]
  API -->|"6"| NEO[("Neo4j")]
  API -->|"7"| CEL["Celery 워커"]
  API -->|"2"| LEAN["LEAN<br/>Docker 소켓"]
  API -->|"6"| NOTI["알림<br/>텔레그램 · SMS"]
  API -->|"42"| EXT["그 밖의 외부<br/>KRX KIND · 업비트 · Alpaca …"]
```

| 묶음 | 수 (S63 · `5adfb81`) |
|------|------|
| 메서드 | GET 79 · POST 58 · DELETE 8 · PATCH 1 = **146** |
| 인증 | 세션 61 · 세션·JWT 40 · **없음 33** · API 키 8 · 세션 + 관리자 3 · 세션·JWT + 역할 1 |
| 파트(제안) | P-E 62 · P-A 43 · P-B 15 · 공통 13 · P-D 11 · **P-C 2** |
| 응답 | `response_model` **0/146** · 다리 결과 그대로 2 · 라우트 캐시 7 |
| 화면 | 메뉴 화면이 부름 74 · `public/` 어디에도 경로 글자가 없음 **56** |
| 요구 | 요구 ID 가 붙은 API **105** / 146 — [기능 설계서 v0.1](../설계/기능설계_v0.1.md) 부록 A |

라우터별 · 닿는 곳 × 라우터 · 인증 없는 API · 오류 코드 — 스캐너 출력(`--overview`):

<!-- api_scan:overview -->
| 라우터 | 파일 | API | 인증 없음 | 메뉴 화면이 부름 | public/ 에 없음 | 파트(제안) |
|---|---|---:|---:|---:|---:|---|
| `auth` | `app/routes/auth.py` | 14 | 5 | 0 | 4 | 공통 14 |
| `ingest` | `app/routes/ingest.py` | 12 | 0 | 5 | 7 | P-A 12 |
| `health` | `app/routes/health.py` | 1 | 1 | 0 | 1 | P-E 1 |
| `chat` | `app/routes/chat.py` | 2 | 0 | 1 | 1 | P-A 2 |
| `stocks` | `app/routes/stocks.py` | 37 | 9 | 33 | 4 | P-E 21 · P-A 8 · P-B 5 · 미배정 2 · P-D 1 |
| `library` | `app/routes/library.py` | 1 | 0 | 1 | 0 | P-A 1 |
| `admin` | `app/routes/admin.py` | 3 | 0 | 2 | 1 | 공통 3 |
| `system` | `app/routes/system.py` | 3 | 0 | 1 | 0 | P-E 3 |
| `quant` | `app/routes/quant.py` | 3 | 1 | 0 | 3 | P-D 3 |
| `ml` | `app/routes/ml.py` | 10 | 0 | 10 | 0 | P-D 8 · P-C 2 |
| `macro` | `app/routes/macro.py` | 4 | 0 | 4 | 0 | P-A 4 |
| `documents` | `app/routes/documents.py` | 4 | 0 | 0 | 4 | P-A 4 |
| `notification` | `app/routes/notification.py` | 4 | 0 | 4 | 0 | P-B 4 |
| `graph` | `app/routes/graph.py` | 6 | 6 | 0 | 6 | P-A 6 |
| `conversations` | `app/routes/conversations.py` | 8 | 0 | 0 | 8 | P-A 8 |
| `tasks` | `app/routes/tasks.py` | 2 | 2 | 0 | 2 | P-E 2 |
| `paper` | `app/routes/paper.py` | 32 | 8 | 18 | 5 | P-E 29 · P-B 3 |
| `openapi` | `app/routes/openapi.py` | 9 | 1 | 1 | 8 | P-E 6 · P-B 3 |
| `lean` | `app/routes/lean.py` | 3 | 1 | 2 | 0 | P-D 3 |
| `rebalance` | `app/routes/rebalance.py` | 9 | 0 | 3 | 0 | 미배정 9 |
| `tradingview` | `app/routes/tradingview.py` | 5 | 1 | 3 | 0 | 미배정 5 |
| `formula` | `app/routes/formula.py` | 13 | 0 | 4 | 0 | 미배정 13 |
| `glossary` | `app/routes/glossary.py` | 4 | 4 | 0 | 4 | P-A 4 |
| `learn` | `app/routes/learn.py` | 7 | 2 | 0 | 7 | P-A 7 |
| **합계** | 24개 | **196** | **41** | **92** | **65** | |

| 라우터 | 수집DB | 야후 | 증권사 | 주문 | PostgreSQL | Redis | Neo4j | Qdrant | LLM | Celery | LEAN | Docker | 알림 | 외부 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `auth` | · | · | · | · | 7 | 13 | · | · | · | · | · | · | · | · |
| `ingest` | · | · | · | · | 9 | 4 | · | 9 | 9 | 4 | · | · | · | 3 |
| `health` | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| `chat` | · | · | · | · | 2 | 2 | · | 2 | 2 | 1 | · | · | · | · |
| `stocks` | 8 | 13 | 7 | 3 | 34 | 3 | · | · | · | · | · | · | 6 | 11 |
| `library` | · | · | · | · | 1 | · | · | · | · | · | · | · | · | · |
| `admin` | · | · | · | · | 3 | · | · | · | · | · | · | · | · | · |
| `system` | 1 | 2 | · | · | 2 | 1 | · | 1 | 1 | · | · | · | · | · |
| `quant` | 2 | 2 | · | · | 2 | · | · | · | · | · | · | · | · | 2 |
| `ml` | 7 | 7 | · | · | 7 | · | · | · | · | · | · | · | · | · |
| `macro` | · | 4 | · | · | 3 | · | · | · | · | · | · | · | · | · |
| `documents` | · | · | · | · | 3 | · | · | 3 | 2 | · | · | · | · | · |
| `notification` | · | · | · | · | 4 | · | · | · | · | · | · | · | 1 | 1 |
| `graph` | · | · | · | · | · | · | 6 | 1 | 1 | · | · | · | · | · |
| `conversations` | · | · | · | · | 8 | 5 | · | · | · | · | · | · | · | · |
| `tasks` | · | · | · | · | · | · | · | · | · | 2 | · | · | · | · |
| `paper` | 2 | 13 | · | · | 23 | · | · | · | · | · | · | · | · | 20 |
| `openapi` | 2 | 5 | · | · | 8 | · | · | · | · | · | · | · | · | 6 |
| `lean` | · | 1 | · | · | 2 | · | · | · | · | · | 2 | 2 | · | · |
| `rebalance` | 5 | 6 | · | · | 9 | · | · | · | · | · | · | · | · | 6 |
| `tradingview` | · | 2 | · | · | 4 | 1 | · | · | · | · | 1 | 1 | 1 | 1 |
| `formula` | 3 | 3 | · | · | 12 | · | · | · | · | · | · | · | · | · |
| `glossary` | · | · | · | · | 4 | · | · | · | · | · | · | · | · | · |
| `learn` | · | · | · | · | · | · | · | · | · | · | · | · | · | 7 |
| **합계** | **30** | **58** | **7** | **3** | **147** | **29** | **6** | **16** | **15** | **7** | **3** | **3** | **8** | **57** |

| API ID | 메서드 | 경로 | 닿는 곳 | 화면 |
|---|---|---|---|---|
| API-AUTH-01 | POST | `/api/auth/register` | PostgreSQL · Redis | (다른 곳) |
| API-AUTH-02 | POST | `/api/auth/login` | PostgreSQL · Redis | (다른 곳) |
| API-AUTH-04 | POST | `/api/auth/token` | PostgreSQL · Redis | — |
| API-AUTH-05 | POST | `/api/auth/token/refresh` | Redis | — |
| API-AUTH-11 | GET | `/api/auth/password-policy` | — | (다른 곳) |
| API-HLTH-01 | GET | `/api/health` | — | — |
| API-STK-01 | GET | `/api/stocks/market` | 야후 · PostgreSQL · 라우트 캐시 2h | `quant-dashboard` |
| API-STK-02 | GET | `/api/stocks/quote` | 야후 | `robo-patterns`, `trading-chart`, `us-chart`, `us-dashboard`, `us-order`, `us-portfolio` |
| API-STK-03 | GET | `/api/stocks/candles` | 수집DB · 야후 · PostgreSQL · 라우트 캐시 6h (다리 요청 제외) | `robo-patterns`, `trading-chart`, `us-chart` |
| API-STK-04 | GET | `/api/stocks/quant/indicators` | 수집DB · 야후 · PostgreSQL · 라우트 캐시 6h (다리 요청 제외) | `indicator-strategy`, `quant-backtest`, `quant-dashboard` |
| API-STK-05 | GET | `/api/stocks/quant/list` | — | `quant-dashboard` |
| API-STK-06 | GET | `/api/stocks/search` | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | `company-dashboard`, `quant-dashboard`, `trading-chart` |
| API-STK-07 | GET | `/api/stocks/fundamentals` | 야후 · PostgreSQL | `company-dashboard` |
| API-STK-08 | GET | `/api/stocks/signals` | 수집DB · 야후 · PostgreSQL · 라우트 캐시 3h | `robo-patterns`, `robo-screening` |
| API-STK-14 | GET | `/api/broker/catalog` | — | — |
| API-QNT-01 | GET | `/api/quant/ml/stocks` | — | — |
| API-GRPH-01 | GET | `/api/graph/related/{symbol}` | Neo4j | — |
| API-GRPH-02 | GET | `/api/graph/sector` | Neo4j | — |
| API-GRPH-03 | GET | `/api/graph/path` | Neo4j | — |
| API-GRPH-04 | GET | `/api/graph/documents/{symbol}` | Neo4j | — |
| API-GRPH-05 | POST | `/api/graph/seed` | Neo4j | — |
| API-GRPH-06 | POST | `/api/graph/rag` | Neo4j · Qdrant · LLM | — |
| API-TASK-01 | GET | `/api/tasks/{task_id}` | Celery | — |
| API-TASK-02 | DELETE | `/api/tasks/{task_id}` | Celery | — |
| API-PAPR-03 | GET | `/api/paper/stocks/quote` | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | (다른 곳) |
| API-PAPR-11 | GET | `/api/paper/crypto/market-list` | 외부(api.upbit.com) | `paper-crypto` |
| API-PAPR-12 | GET | `/api/paper/crypto/rankings` | 외부(api.upbit.com) | `paper-crypto` |
| API-PAPR-13 | GET | `/api/paper/crypto/ticker` | 외부(api.upbit.com) | `paper-crypto` |
| API-PAPR-14 | GET | `/api/paper/crypto/{code}/candles` | 외부(api.upbit.com) | `paper-crypto` |
| API-PAPR-15 | GET | `/api/paper/crypto/{code}/domestic-prices` | 외부(api.bithumb.com, api.korbit.co.kr …) | `paper-crypto` |
| API-PAPR-22 | GET | `/api/paper/alternatives/markets` | 야후 | `paper-alternative` |
| API-PAPR-23 | GET | `/api/paper/alternatives/markets/{symbol}/chart` | 야후 | `paper-alternative` |
| API-OAPI-09 | GET | `/openapi/v1/docs-summary` | — | `paper-openapi` |
| API-LEAN-01 | GET | `/api/backtests/lean/status` | LEAN · Docker | `quant-lean` |
| API-TV-01 | POST | `/api/webhooks/tradingview` | 야후 · PostgreSQL · Redis · 알림 · 외부(api.coolsms.co.kr, api.telegram.org …) | (다른 곳) |
| API-GLOS-01 | GET | `/api/glossary` | PostgreSQL | — |
| API-GLOS-02 | GET | `/api/glossary/categories` | PostgreSQL | — |
| API-GLOS-03 | GET | `/api/glossary/meta` | PostgreSQL | — |
| API-GLOS-04 | GET | `/api/glossary/{name}` | PostgreSQL | — |
| API-LRN-01 | GET | `/api/learn/catalog` | 외부(huggingface.co) | — |
| API-LRN-02 | GET | `/api/learn/pages/{slug}` | 외부(huggingface.co) | — |

| 코드 | 뜻 | 본문에 적힌 API 수 | API ID |
|---|---|---:|---|
| `400` | 요청 값이 틀림 | 14 | API-AUTH-01, API-AUTH-13, API-AUTH-14, API-STK-12, API-DOC-01, API-DOC-03 외 8 |
| `400 INVALID_REQUEST` | 요청 값이 틀림 | 1 | API-OAPI-05 |
| `401` | 인증 실패 | 4 | API-AUTH-02, API-AUTH-04, API-AUTH-05, API-LRN-02 |
| `403` | 권한 없음 | 2 | API-AUTH-06, API-TV-01 |
| `404` | 대상 없음 | 21 | API-AUTH-09, API-STK-34, API-STK-30, API-STK-33, API-QNT-02, API-ML-01 외 15 |
| `404 NOT_FOUND` | 대상 없음 | 1 | API-OAPI-02 |
| `409` |  | 5 | API-STK-24, API-STK-27, API-FRML-05, API-FRML-07, API-LRN-03 |
| `413` | 너무 큼 | 1 | API-DOC-01 |
| `422` | 검증 실패 | 25 | API-AUTH-01, API-AUTH-12, API-AUTH-13, API-AUTH-14, API-STK-15, API-STK-18 외 19 |
| `429` | 호출 한도 초과 | 1 | API-TV-01 |
| `500` | 서버 내부 오류 | 1 | API-CHAT-01 |
| `502` | 바깥 서버 실패 | 10 | API-STK-06, API-STK-07, API-STK-19, API-STK-20, API-STK-21, API-STK-22 외 4 |
| `503` | 의존 서비스 없음 | 10 | API-AUTH-01, API-AUTH-02, API-AUTH-04, API-CHAT-01, API-GRPH-01, API-GRPH-02 외 4 |
| `503 MARKET_DATA_UNAVAILABLE` | 의존 서비스 없음 | 1 | API-OAPI-01 |
| `504` | 시간 초과 | 1 | API-CHAT-01 |
| `?` |  | 1 | API-TV-01 |
<!-- /api_scan:overview -->

---

## 3. 발견 — 명세를 만들며 드러난 것

| # | 발견 | 확실도 | 누구 몫 (분배안) | 다음 |
|:-:|------|:------:|------|------|
| F1 | 정적 추출 = 실제 앱 명세 **145/145**. 146 은 옛 A3(09-17)의 라우트 수와도 같다 | 🟢 실측 | P-A | 이 문서의 표를 믿어도 되는 근거. 대조는 코드가 크게 바뀔 때 다시 |
| F2 | **일봉 · 지표 API 앞에 라우트 캐시 6시간** — `API-STK-03` `/api/stocks/candles` · `API-STK-04` `/api/stocks/quant/indicators` 가 `data_cache`(PostgreSQL)를 먼저 본다(옛 `stocks.py:62-66` · `:78-82`). 12:30 갱신 뒤에도 **최대 6시간 옛 `as_of`** 를 돌려주고 응답에 `from_cache: true` 가 붙는다 | 🟢 코드 · ~~🟡 실행 재현 안 함~~ 🟢 시험으로 재현(옛 코드는 캐시의 옛 기준일을 돌려줬다) | **P-A** (DF-08 다리의 뒷일) | ~~**DF-17 후보** — 테스트계획서 v1.2 6.1절에 적음. S57 의 TC-CD 는 **서비스 함수**만 시험해서 라우트 층이 사각지대였다. 고치는 방향(제안): 다리가 받는 요청(국내 주식 · 일봉)은 라우트 캐시를 건너뛴다~~ ✅ **DF-17 고침(2026-09-29)** — 수집 DB 가 받는 요청(국내 주식 기호 · 일봉 · 아는 기간 · DB 파일 있음 = `collector_db.handles()`)은 라우트가 캐시를 **읽지도 쓰지도 않는다**. 매시간 캐시 데우기(`sync_scheduler`)도 그 종목은 건너뛴다(라우트가 더는 읽지 않는 키였다). 지수 · 해외 · 주봉 · 수집 DB 가 없는 환경은 예전과 같다. 시험 `tests/test_route_cache_df17.py` 17건 — 라우트 함수를 직접 부른다 |
| F3 | **응답 계약이 코드에 없다** — `response_model` 0/146. 응답이 보장되는 곳은 계약 시험이 붙은 2곳(TC-A1 시세 등락률 · TC-CD 일봉 `source`·`as_of`)뿐 | 🟢 코드 | 전 파트 | ② 설계에서 **요구가 걸린 API 부터** 응답 모델을 적는다(설계 초안의 「출력」 칸). 한꺼번에 146개가 아니다 |
| F4 | **인증 없는 API 33** (옛 A3 34 → `11d6562` 가 `/api/auth/token/revoke` 에 인증을 붙여 1 줄었다). 세 무리 — ① 공개가 맞음 10(로그인 전 · 상태 · 목록) ② 공개 시세 대리 호출 15(누구나 서버를 통해 야후 · 업비트를 부른다 — 호출 한도 · 약관) ③ 🔴 **쓰기 · 비용 · 남의 것 8** — `POST /api/graph/seed` · `POST /api/graph/rag`(LLM 비용) · 그래프 조회 4 · `GET`·`DELETE /api/tasks/{task_id}`(남의 태스크 조회 · 취소) | 🟢 코드 | 공통 · P-A(graph) · P-E(tasks) | ③ 은 결정 대장 D3 ③ 「권한 경계」(🟡 조건부 · `tasks 인증`)와 같은 안건이라 **여기서 새로 정하지 않는다** — D3 결론 뒤 설계에 반영 |
| F5 | **증권사 관문에 닿는 API 7 · 주문 3** — 전부 `세션` 인증 · 전부 `get_broker_client` 경유. 주문 3 = `API-STK-22` `/api/broker/order` · `API-STK-24` `/api/auto-trade/start` · `API-STK-27` `/api/quant/auto/start`. **API 키(Open API)로는 증권사에 닿는 길이 없다** | 🟢 코드 | P-E | ADR-0001 표와 일치. TC-LT 21건이 관문을 지킨다 |
| F6 | **야후 43 · 수집 DB 19** — 다리에 닿는 19개 중 응답에 기준일이 실리는 것은 **2개**. 나머지 17(ML 6 · 모의투자 계좌 · 자동매매 · 파이프라인 …)은 수집 DB 값을 쓰고도 **언제 값인지 응답에 없다** | 🟢 코드 | P-A · 각 소비 파트 | 분배안 §3.3 「모든 화면 상단에 출처 · 수집일 배너」의 크기가 곧 이 17이다. ② 에서 P01-①-4(갱신일)의 설계 입력 |
| F7 | **P-C 에 붙는 API 가 2개뿐이고 리밸런싱 API 는 0** — `API-ML-04` 자산배분 · `API-ML-03` 군집화. 요구 P01-③-1 · ③-2 · ③-3(리밸런싱 세 축)은 받을 API 가 없다 | 🟢 코드 | P-C | RTM §5 의 🔴 3줄과 같은 사실을 API 쪽에서 본 것 — ② 설계에서 새 API 초안 |
| F8 | **`public/` 어디에도 경로 글자가 없는 API 56** — 대화 8 · Open API 8 · 적재 비동기 등 7 · 그래프 6 · 토큰 · 세션 6 · 모의투자 5(`orders/buy`·`sell`·`pine` · Alpaca 2) · 문서 4 · 증권사 4(`catalog`·`balance`·`ohlcv`·`order`) … | 🟢 실측(글자 검색) | 전 파트 | 옛 S15 의 「화면이 안 부르는 API 31」 과 **기준이 다르다**(그때는 Open API · 토큰 API 를 뺐다). 죽은 API 인지, 외부 클라이언트 몫인지는 D3 ⑦ 「죽은 것 정리」 의 입력 |
| F9 | **오류 응답 형식이 둘** — FastAPI 기본 `{"detail": "문자열"}` 과 Open API 의 `{"detail": {"error": "코드", "message": "…"}}`. 본문에 코드가 적힌 오류는 13종 | 🟢 코드 | 공통 · P-B(Open API) | 6절. ② 설계에서 오류 규약 한 줄(새 API 는 어느 형식인가) |
| F10 | **라우트 캐시 7곳** — 위 2곳 + `/api/stocks/market` 2h · 거시 3곳 2h · `/api/ml/robo/allocation` 3h(다리에 닿음) | 🟢 코드 | P-A · P-C | F2 와 함께 「캐시 규칙」 한 장(누가 · 몇 시간 · 무엇을 기준으로 무효화)이 필요하다. DF-17 뒤 위 2곳은 **수집 DB 가 받지 않는 요청에만** 캐시를 쓴다(4절 「라우트 캐시 6h (다리 요청 제외)」). `/api/ml/robo/allocation` 의 3h 캐시는 종목별 학습 결과(`ai_predict:{기호}`)라 계산 비용 캐시이고 응답에 기준일을 싣지 않는다 — 이번에 바꾸지 않았다 |

> **F2 가 왜 사각지대였나.** S57 은 다리를 `stock.get_candles`(서비스 함수) 안에 놓고 「캐시를 거치지 않는다」를 시험으로 못 박았다(TC-CD).
> 그런데 화면이 부르는 것은 서비스 함수가 아니라 **라우트**이고, 라우트가 그 앞에서 자기 캐시를 먼저 본다.
> 층이 둘인데 한 층만 쟀다. 정적 추출이 「다리에 닿는 라우트」를 **라우트 단위로** 나열하자 곧바로 보였다.

---

## 4. 라우터별 명세

`main.py` 의 `include_router` 순서다. 칸 뜻은 1.3절.

<!-- api_scan:routes -->
#### `auth` — `app/routes/auth.py` · 14개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-AUTH-01 | POST | `/api/auth/register` | 없음 | 본문 `RegisterBody` | {ok, user} | 400 · 422 · 503 | PostgreSQL · Redis | (다른 곳) | 공통 | — | auth.py:149 |
| API-AUTH-02 | POST | `/api/auth/login` | 없음 | 본문 `LoginBody` | {ok, user} | 401 · 503 | PostgreSQL · Redis | (다른 곳) | 공통 | — | auth.py:194 |
| API-AUTH-03 | POST | `/api/auth/logout` | 세션 | 쿠키 `fin_session` | {ok} | — | Redis | (다른 곳) | 공통 | — | auth.py:219 |
| API-AUTH-04 | POST | `/api/auth/token` | 없음 | 본문 `LoginBody` | 모델 없음 | 401 · 503 | PostgreSQL · Redis | — | 공통 | — | auth.py:234 |
| API-AUTH-05 | POST | `/api/auth/token/refresh` | 없음 | 본문 `TokenRefreshBody` | {access_token, token_type, expires_in} | 401 | Redis | — | 공통 | — | auth.py:261 |
| API-AUTH-06 | POST | `/api/auth/token/revoke` | 세션·JWT | 본문 `TokenRevokeBody` | {ok, revoked} | 403 | Redis | — | 공통 | — | auth.py:284 |
| API-AUTH-07 | GET | `/api/me` | 세션·JWT | — | {user, state} | — | PostgreSQL · Redis | (다른 곳) | 공통 | — | auth.py:325 |
| API-AUTH-08 | GET | `/api/sessions` | 세션·JWT | — | {sessions, count} | — | Redis | (다른 곳) | 공통 | — | auth.py:352 |
| API-AUTH-09 | DELETE | `/api/sessions/{sid}` | 세션·JWT | `{sid}` | {ok} | 404 | Redis | — | 공통 | — | auth.py:359 |
| API-AUTH-10 | DELETE | `/api/sessions` | 세션·JWT + 역할(admin·user) | — | {ok, revoked} | — | Redis | (다른 곳) | 공통 | — | auth.py:372 |
| API-AUTH-11 | GET | `/api/auth/password-policy` | 없음 | — | 모델 없음 | — | — | (다른 곳) | 공통 | — | auth.py:385 |
| API-AUTH-12 | PATCH | `/api/me` | 세션·JWT | 본문 `ProfileUpdateBody` | {ok, user} | 422 | PostgreSQL · Redis | (다른 곳) | 공통 | — | auth.py:391 |
| API-AUTH-13 | PUT | `/api/me/password` | 세션·JWT | 본문 `PasswordChangeBody` · 쿠키 `fin_session` | {ok, other_sessions_revoked} | 400 · 422 | PostgreSQL · Redis | (다른 곳) | 공통 | — | auth.py:414 |
| API-AUTH-14 | DELETE | `/api/me` | 세션·JWT | 본문 `AccountDeleteBody` | {ok, deleted} | 400 · 422 | PostgreSQL · Redis | (다른 곳) | 공통 | — | auth.py:447 |

#### `ingest` — `app/routes/ingest.py` · 12개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-ING-01 | POST | `/api/ingest/financial` | 세션 | — | {ok, result, log} | — | PostgreSQL | `crawl-ingest` | P-A | P01-①-2 | ingest.py:22 |
| API-ING-02 | POST | `/api/ingest/crawl/auto` | 세션 | — | {ok, result, log} | — | PostgreSQL · Qdrant · LLM · 외부(api.github.com, github.com …) | `crawl-auto` | P-A | P01-①-2 | ingest.py:32 |
| API-ING-03 | POST | `/api/ingest/crawl/url` | 세션 | 본문 `CrawlUrlBody` | {ok, chunks, log} | — | PostgreSQL · Qdrant · LLM | `crawl-manual` | P-A | P01-①-2 | ingest.py:47 |
| API-ING-04 | POST | `/api/ingest/crawl/naver` | 세션 | 본문 `CrawlNaverBody` | {ok, chunks, message} | — | PostgreSQL · Qdrant · LLM · 외부(finance.naver.com) | `crawl-manual` | P-A | P01-①-2 | ingest.py:63 |
| API-ING-05 | POST | `/api/ingest/local-docs` | 세션 | — | {ok, total_chunks, log} | — | PostgreSQL · Qdrant · LLM | — | P-A | P01-①-3 | ingest.py:77 |
| API-ING-06 | POST | `/api/ingest/translation-data` | 세션 | 본문 `TranslationIngestBody` | {ok, result, log} | — | Qdrant · LLM | — | P-A | P01-①-3 | ingest.py:127 |
| API-ING-07 | POST | `/api/ingest/translation-search` | 세션 | 본문 `TranslationSearchBody` | {ok, hits, collection} | — | Qdrant · LLM | — | P-A | P01-①-3 | ingest.py:153 |
| API-ING-08 | POST | `/api/ingest/financial/async` | 세션 | — | {task_id, poll_url} | — | PostgreSQL · Redis · Celery | — | P-A | P01-①-4 | ingest.py:172 |
| API-ING-09 | POST | `/api/ingest/crawl/auto/async` | 세션 | — | {task_id, poll_url} | — | PostgreSQL · Redis · Qdrant · LLM · Celery · 외부(api.github.com, github.com …) | — | P-A | P01-①-4 | ingest.py:182 |
| API-ING-10 | POST | `/api/ingest/crawl/url/async` | 세션 | 본문 `CrawlUrlBody` | {task_id, poll_url} | — | PostgreSQL · Redis · Qdrant · LLM · Celery | — | P-A | P01-①-4 | ingest.py:190 |
| API-ING-11 | POST | `/api/ingest/translation-data/async` | 세션 | 본문 `TranslationIngestBody` | {task_id, poll_url} | — | Redis · Qdrant · LLM · Celery | — | P-A | P01-①-4 | ingest.py:198 |
| API-ING-12 | GET | `/api/ingest/crawl/list` | 세션 | — | {items} | — | PostgreSQL | `crawl-manual`, `robo-patterns` | P-A | P01-①-2 | ingest.py:214 |

#### `health` — `app/routes/health.py` · 1개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-HLTH-01 | GET | `/api/health` | 없음 | — | {status, service} | — | — | — | P-E | P02-⑤-3 | health.py:6 |

#### `chat` — `app/routes/chat.py` · 2개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-CHAT-01 | POST | `/api/chat` | 세션·JWT | 본문 `ChatBody` | {conversation_id} | 500 · 503 · 504 | PostgreSQL · Redis · Qdrant · LLM | `agent-cb`, `agent-chat`, `agent-products` | P-A | P01-①-3 | chat.py:95 |
| API-CHAT-02 | POST | `/api/chat/async` | 세션·JWT | 본문 `ChatBody` | {task_id, conversation_id, poll_url} | — | PostgreSQL · Redis · Qdrant · LLM · Celery | — | P-A | P01-①-3 | chat.py:177 |

#### `stocks` — `app/routes/stocks.py` · 37개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-STK-01 | GET | `/api/stocks/market` | 없음 | — | {indices, from_cache} | — | 야후 · PostgreSQL · 라우트 캐시 2h | `quant-dashboard` | P-A | P01-①-2 | stocks.py:42 |
| API-STK-02 | GET | `/api/stocks/quote` | 없음 | `symbol`* | 모델 없음 | — | 야후 | `robo-patterns`, `trading-chart`, `us-chart`, `us-dashboard`, `us-order`, `us-portfolio` | P-A | P01-①-2 | stocks.py:53 |
| API-STK-03 | GET | `/api/stocks/candles` | 없음 | `symbol`* · `period` · `interval` | 다리 결과 그대로 (`source`·`as_of`) | — | 수집DB · 야후 · PostgreSQL · 라우트 캐시 6h (다리 요청 제외) | `robo-patterns`, `trading-chart`, `us-chart` | P-A | P01-①-2 · P02-④-1 | stocks.py:58 |
| API-STK-04 | GET | `/api/stocks/quant/indicators` | 없음 | `symbol`* · `period` | 다리 결과 그대로 (`source`·`as_of`) | — | 수집DB · 야후 · PostgreSQL · 라우트 캐시 6h (다리 요청 제외) | `indicator-strategy`, `quant-backtest`, `quant-dashboard` | P-B | P01-②-1 · P01-②-3 · P02-①-1 · P02-②-2 | stocks.py:79 |
| API-STK-05 | GET | `/api/stocks/quant/list` | 없음 | — | {stocks} | — | — | `quant-dashboard` | P-A | P01-①-2 | stocks.py:98 |
| API-STK-06 | GET | `/api/stocks/search` | 없음 | `q`* | {results} | 502 | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | `company-dashboard`, `quant-dashboard`, `trading-chart` | P-A | P01-①-2 | stocks.py:103 |
| API-STK-07 | GET | `/api/stocks/fundamentals` | 없음 | `symbol`* | 모델 없음 | 502 | 야후 · PostgreSQL | `company-dashboard` | P-A | P01-①-2 · RFP2-3.1.4-② | stocks.py:147 |
| API-STK-08 | GET | `/api/stocks/signals` | 없음 | `signal` · `model` · `min_confidence` | {signals, count} | — | 수집DB · 야후 · PostgreSQL · 라우트 캐시 3h | `robo-patterns`, `robo-screening` | P-B | P01-②-2 · P01-②-3 · RFP2-3.1.4-① · RFP2-3.1.4-③ | stocks.py:156 |
| API-STK-09 | GET | `/api/portfolio` | 세션 | — | {holdings} | — | PostgreSQL | `robo-patterns`, `trading-portfolio`, `us-portfolio` | P-E | P01-③-1 · P01-③-2 | stocks.py:215 |
| API-STK-10 | POST | `/api/portfolio` | 세션 | 본문 `HoldingBody` | {ok} | — | PostgreSQL | `robo-patterns`, `trading-portfolio`, `us-portfolio` | P-E | P01-④-3 | stocks.py:227 |
| API-STK-11 | DELETE | `/api/portfolio/{symbol}` | 세션 | `{symbol}` | {ok} | — | PostgreSQL | `robo-patterns`, `trading-portfolio` | P-E | P01-④-3 | stocks.py:246 |
| API-STK-12 | POST | `/api/orders` | 세션 | 본문 `OrderBody` | {ok, status, cost} | 400 | PostgreSQL | `robo-patterns`, `trading-order`, `us-order` | P-E | P01-④-3 | stocks.py:296 |
| API-STK-13 | GET | `/api/orders` | 세션 | — | {orders} | — | PostgreSQL | `robo-patterns`, `trading-order`, `us-order` | P-E | P01-④-3 | stocks.py:350 |
| API-STK-14 | GET | `/api/broker/catalog` | 없음 | — | {brokers} | — | — | — | P-E | P02-⑤-1 | stocks.py:423 |
| API-STK-15 | POST | `/api/broker/settings` | 세션 | 본문 `BrokerSettingsBody` | {ok} | 422 | PostgreSQL | `indicator-api`, `robo-patterns`, `trading-order` | P-E | P02-⑤-1 | stocks.py:428 |
| API-STK-16 | GET | `/api/broker/settings` | 세션 | — | {broker, connected, app_key, account_no, paper} 외 1 | — | PostgreSQL | `indicator-api`, `robo-patterns`, `trading-order` | P-E | P02-⑤-1 | stocks.py:449 |
| API-STK-17 | GET | `/api/quant/settings` | 세션 | — | {mode, broker, connected, app_key, account_no} 외 11 | — | PostgreSQL | `robo-patterns`, `settings` | P-E | P02-⑤-2 | stocks.py:475 |
| API-STK-18 | POST | `/api/quant/settings` | 세션 | 본문 `QuantSettingsBody` | {ok} | 422 | PostgreSQL | `robo-patterns`, `settings` | P-E | P02-⑤-2 | stocks.py:516 |
| API-STK-19 | GET | `/api/broker/price` | 세션 | `symbol`* | {symbol, name, current, open, high} 외 4 | 502 | 증권사 · PostgreSQL · 외부(developer.kbsec.com, openapi.ebestsec.co.kr …) | `settings` | P-E | P02-⑤-1 | stocks.py:575 |
| API-STK-20 | GET | `/api/broker/balance` | 세션 | — | {total_eval, total_buy, total_gain, holdings} | 502 | 증권사 · PostgreSQL · 외부(developer.kbsec.com, openapi.ebestsec.co.kr …) | — | P-E | P02-⑤-1 | stocks.py:594 |
| API-STK-21 | GET | `/api/broker/ohlcv` | 세션 | `symbol`* · `start`* · `end`* | {candles} | 502 | 증권사 · PostgreSQL · 외부(developer.kbsec.com, openapi.ebestsec.co.kr …) | — | P-E | P02-⑤-1 | stocks.py:620 |
| API-STK-22 | POST | `/api/broker/order` | 세션 | 본문 `BrokerOrderBody` | {ok, result} | 422 · 502 | 증권사 · 주문 · PostgreSQL · 알림 · 외부(api.coolsms.co.kr, api.telegram.org …) | — | P-E | P02-⑤-1 | stocks.py:643 |
| API-STK-23 | GET | `/api/broker/test` | 세션 | — | {ok, broker_price} | 502 | 증권사 · PostgreSQL · 외부(developer.kbsec.com, openapi.ebestsec.co.kr …) | `indicator-api` | P-E | P02-⑤-1 | stocks.py:712 |
| API-STK-34 | GET | `/api/stocks/patterns` | 세션 | `symbol` · `period` | {symbol} | 404 · 422 | 수집DB · 야후 · PostgreSQL | `robo-patterns` | P-A | — | stocks.py:728 |
| API-STK-35 | GET | `/api/stocks/mtf-signal` | 세션 | `symbol` | 모델 없음 | — | 수집DB · 야후 · PostgreSQL | `robo-patterns` | P-A | — | stocks.py:741 |
| API-STK-24 | POST | `/api/auto-trade/start` | 세션 | — | {ok, started, scheduler} | 409 | 수집DB · 야후 · 증권사 · 주문 · PostgreSQL · Redis · 알림 · 외부(api.coolsms.co.kr, api.telegram.org …) | `quant-auto` | P-E | P01-④-3 · P02-⑤-1 · P02-⑤-2 | stocks.py:750 |
| API-STK-25 | POST | `/api/auto-trade/stop` | 세션 | — | {ok, stopped} | — | PostgreSQL · 알림 · 외부(api.coolsms.co.kr, api.telegram.org) | `quant-auto` | P-E | P02-⑤-2 | stocks.py:759 |
| API-STK-26 | GET | `/api/auto-trade/status` | 세션 | — | 모델 없음 | — | PostgreSQL | `quant-auto`, `robo-patterns` | P-E | P01-④-2 · P02-⑤-2 | stocks.py:765 |
| API-STK-36 | GET | `/api/quant/risk/status` | 세션 | — | 모델 없음 | — | 야후 · PostgreSQL · Redis | `quant-auto` | 미배정 | — | stocks.py:777 |
| API-STK-37 | POST | `/api/quant/risk/kill-switch` | 세션 | 본문 `KillSwitchBody` | {ok, kill_switch, auto_trade_stopped} | — | PostgreSQL · 알림 · 외부(api.coolsms.co.kr, api.telegram.org) | `quant-auto` | 미배정 | — | stocks.py:803 |
| API-STK-27 | POST | `/api/quant/auto/start` | 세션 | — | {ok, started} | 409 | 수집DB · 야후 · 증권사 · 주문 · PostgreSQL · Redis · 알림 · 외부(api.coolsms.co.kr, api.telegram.org …) | `robo-decision` | P-E | P01-④-3 · P02-⑤-1 · P02-⑤-2 | stocks.py:818 |
| API-STK-28 | POST | `/api/quant/auto/stop` | 세션 | — | {ok, stopped} | — | PostgreSQL · 알림 · 외부(api.coolsms.co.kr, api.telegram.org) | `robo-decision` | P-E | P02-⑤-2 | stocks.py:828 |
| API-STK-29 | GET | `/api/quant/auto/status` | 세션 | — | {running, logs, signals} | — | PostgreSQL | `robo-decision`, `robo-patterns` | P-E | P01-④-2 · P02-⑤-2 | stocks.py:835 |
| API-STK-30 | GET | `/api/quant/pipeline` | 세션 | `symbol` · `period` · `base` · `short` · `mid` · `rsi` · `buy_th` · `strategy` · `cost_bps` · `cost_model` · `slippage_bps` · `market` · `stop_loss_pct` · `take_profit_pct` | 모델 없음 | 404 · 422 | 수집DB · 야후 · PostgreSQL · 라우트 캐시 3h | `indicator-backtest`, `indicator-custom`, `robo-patterns` | P-D | P01-④-1 · P02-①-2 · P02-①-3 · P02-②-1 · P02-②-2 | stocks.py:862 |
| API-STK-31 | GET | `/api/custom-indicators` | 세션 | — | {items} | — | PostgreSQL | `indicator-custom`, `robo-patterns` | P-B | P02-②-1 · P02-②-3 | stocks.py:960 |
| API-STK-32 | POST | `/api/custom-indicators` | 세션 | 본문 `CustomIndicatorBody` | 모델 없음 | 422 | PostgreSQL | `indicator-custom`, `robo-patterns` | P-B | P02-①-2 · P02-②-1 · P02-②-3 | stocks.py:975 |
| API-STK-33 | DELETE | `/api/custom-indicators/{indicator_id}` | 세션 | `{indicator_id}` | {ok} | 404 | PostgreSQL | `indicator-custom`, `robo-patterns` | P-B | P02-②-1 · P02-②-3 | stocks.py:995 |

#### `library` — `app/routes/library.py` · 1개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-LIB-01 | GET | `/api/library/search` | 세션 | `q` · `category` | {items, query} | — | PostgreSQL | `agent-news` | P-A | P01-①-2 | library.py:12 |

#### `admin` — `app/routes/admin.py` · 3개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-ADM-01 | POST | `/api/admin/reset` | 세션 + 관리자 | — | {ok, message} | — | PostgreSQL | `crawl-ingest` | 공통 | — | admin.py:25 |
| API-ADM-02 | GET | `/api/admin/stats` | 세션 + 관리자 | — | {stats} | — | PostgreSQL | — | 공통 | — | admin.py:39 |
| API-ADM-03 | GET | `/api/admin/audit-log` | 세션 + 관리자 | `event_type` · `user_id` · `limit` | {events, count} | — | PostgreSQL | `robo-patterns`, `sysadmin-logs` | 공통 | — | admin.py:51 |

#### `system` — `app/routes/system.py` · 3개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-SYS-01 | GET | `/api/system/status` | 세션 | — | 모델 없음 | — | Redis · Qdrant · LLM | `robo-patterns`, `sysadmin-dashboard` | P-E | P02-⑤-3 | system.py:11 |
| API-SYS-02 | GET | `/api/system/sync-status` | 세션 | — | {online, scheduler, cache} | — | 야후 · PostgreSQL | (다른 곳) | P-E | P01-①-4 · P02-⑤-3 | system.py:16 |
| API-SYS-03 | POST | `/api/system/sync` | 세션 | — | 모델 없음 | — | 수집DB · 야후 · PostgreSQL | (다른 곳) | P-E | P01-①-4 · P02-⑤-3 | system.py:38 |

#### `quant` — `app/routes/quant.py` · 3개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-QNT-01 | GET | `/api/quant/ml/stocks` | 없음 | — | {stocks} | — | — | — | P-D | — | quant.py:11 |
| API-QNT-02 | GET | `/api/quant/ml/run` | 세션 | `symbol`* · `period` · `model` · `commission_bps` · `slippage_bps` · `stop_loss_pct` · `take_profit_pct` | 모델 없음 | 404 · 422 | 수집DB · 야후 · PostgreSQL · 외부(paper-api.alpaca.markets) | — | P-D | P01-④-1 · P02-④-2 | quant.py:17 |
| API-QNT-03 | POST | `/api/quant/ml/run/batch` | 세션 | 본문 `BatchRunBody` | {results} | — | 수집DB · 야후 · PostgreSQL · 외부(paper-api.alpaca.markets) | — | P-D | P01-④-1 | quant.py:53 |

#### `ml` — `app/routes/ml.py` · 10개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-ML-01 | GET | `/api/ml/compare` | 세션 | `symbol` · `period` | 모델 없음 | 404 · 422 | 수집DB · 야후 · PostgreSQL | `ml-compare` | P-D | P01-④-1 | ml.py:21 |
| API-ML-02 | GET | `/api/ml/tune` | 세션 | `symbol` · `period` · `model_name` | 모델 없음 | 404 · 422 | 수집DB · 야후 · PostgreSQL | `ml-tune` | P-D | P01-④-1 | ml.py:38 |
| API-ML-03 | POST | `/api/ml/cluster` | 세션 | 본문 `ClusterBody` | 모델 없음 | 422 | 수집DB · 야후 · PostgreSQL | `ml-cluster` | P-C | RFP2-3.1.4-① · RFP2-3.1.4-④ | ml.py:67 |
| API-ML-04 | POST | `/api/ml/robo/allocation` | 세션 | 본문 `RoboAllocationBody` | {risk_profile, horizon_years, amount_manwon, allocations, stock_picks} 외 10 | 422 | 수집DB · 야후 · PostgreSQL · 라우트 캐시 3h | `robo-portfolio` | P-C | RFP2-3.1.3-① · RFP2-3.1.3-② · RFP2-3.1.3-③ · RFP2-3.1.3-④ · RFP2-3.1.4-④ | ml.py:86 |
| API-ML-07 | GET | `/api/ml/robo/questions` | 세션 | — | {questions, levels} | — | — | `robo-portfolio` | P-D | — | ml.py:287 |
| API-ML-08 | POST | `/api/ml/robo/risk-profile` | 세션 | 본문 `RiskProfileBody` | 모델 없음 | 422 | — | `robo-portfolio` | P-D | — | ml.py:293 |
| API-ML-09 | POST | `/api/ml/robo/goal-simulation` | 세션 | 본문 `GoalSimBody` | 모델 없음 | — | — | `robo-portfolio` | P-D | — | ml.py:303 |
| API-ML-10 | GET | `/api/ml/explain` | 세션 | `symbol`* · `refresh` | {symbol, name, prediction, explanation} | 422 | 수집DB · 야후 · PostgreSQL · 라우트 캐시 3h | `robo-screening` | P-D | — | ml.py:311 |
| API-ML-05 | GET | `/api/ml/seasonality` | 세션 | `symbol` · `period` | 모델 없음 | 404 · 422 | 수집DB · 야후 · PostgreSQL | `quant-seasonal` | P-D | P01-④-1 | ml.py:334 |
| API-ML-06 | GET | `/api/ml/regression` | 세션 | `symbol` · `period` | 모델 없음 | 404 · 422 | 수집DB · 야후 · PostgreSQL | `ml-regression` | P-D | P01-④-1 | ml.py:351 |

#### `macro` — `app/routes/macro.py` · 4개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-MACR-01 | GET | `/api/macro/indicators` | 세션 | — | {indicators, from_cache} | — | 야후 · PostgreSQL · 라우트 캐시 2h | `macro-dashboard`, `robo-patterns` | P-A | P01-①-2 | macro.py:32 |
| API-MACR-02 | GET | `/api/macro/industry` | 세션 | — | {sectors, from_cache} | — | 야후 · PostgreSQL · 라우트 캐시 2h | `macro-industry`, `robo-patterns` | P-A | P01-①-2 | macro.py:47 |
| API-MACR-03 | GET | `/api/macro/us-stocks` | 세션 | — | {stocks, from_cache} | — | 야후 · PostgreSQL · 라우트 캐시 2h | `robo-patterns`, `us-dashboard` | P-A | P01-①-2 | macro.py:63 |
| API-MACR-04 | GET | `/api/macro/fundamental` | 세션 | `symbol` | {symbol, price, valuation, note, error} | — | 야후 | `invest-fundamental` | P-A | P01-①-2 | macro.py:78 |

#### `documents` — `app/routes/documents.py` · 4개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-DOC-01 | POST | `/api/documents/upload` | 세션 | 파일 `file`* | {ok, doc_id, filename, chunks, message} | 400 · 413 · 422 | PostgreSQL · Qdrant · LLM | — | P-A | P01-①-3 | documents.py:32 |
| API-DOC-02 | GET | `/api/documents/list` | 세션 | — | {items} | — | PostgreSQL | — | P-A | P01-①-3 | documents.py:105 |
| API-DOC-03 | DELETE | `/api/documents/{doc_id}` | 세션 | `{doc_id}` | {ok, message} | 400 · 404 | PostgreSQL · Qdrant | — | P-A | P01-①-3 | documents.py:127 |
| API-DOC-04 | POST | `/api/documents/search` | 세션 | 본문 `DocSearchBody` | {ok, hits} | — | Qdrant · LLM | — | P-A | P01-①-3 | documents.py:168 |

#### `notification` — `app/routes/notification.py` · 4개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-NOTI-01 | GET | `/api/notification/settings` | 세션 | — | {channels, telegram_token, telegram_chat_id, slack_webhook_url, email_to} 외 13 | — | PostgreSQL | `notification-settings`, `robo-patterns` | P-B | P02-③-3 | notification.py:62 |
| API-NOTI-02 | POST | `/api/notification/settings` | 세션 | 본문 `NotificationSettingsBody` | {ok} | — | PostgreSQL | `notification-settings`, `robo-patterns` | P-B | P02-③-3 | notification.py:105 |
| API-NOTI-03 | POST | `/api/notification/test` | 세션 | — | {ok, message} | — | PostgreSQL · 알림 · 외부(api.coolsms.co.kr, api.telegram.org) | `notification-settings` | P-B | P02-③-3 · P02-⑤-3 | notification.py:149 |
| API-NOTI-04 | GET | `/api/notification/history` | 세션 | `limit` | {events, count} | — | PostgreSQL | `notification-settings` | P-B | P02-③-3 | notification.py:172 |

#### `graph` — `app/routes/graph.py` · 6개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-GRPH-01 | GET | `/api/graph/related/{symbol}` | 없음 | `{symbol}` | 모델 없음 | 404 · 503 | Neo4j | — | P-A | P01-①-1 | graph.py:11 |
| API-GRPH-02 | GET | `/api/graph/sector` | 없음 | `name`* | {sector, stocks, count} | 503 | Neo4j | — | P-A | P01-①-1 | graph.py:23 |
| API-GRPH-03 | GET | `/api/graph/path` | 없음 | `from_symbol`* · `to_symbol`* | {found, from, to, chain} | 503 | Neo4j | — | P-A | P01-①-1 | graph.py:33 |
| API-GRPH-04 | GET | `/api/graph/documents/{symbol}` | 없음 | `{symbol}` | {symbol, documents, count} | 503 | Neo4j | — | P-A | — | graph.py:48 |
| API-GRPH-05 | POST | `/api/graph/seed` | 없음 | — | {ok, message} | 503 | Neo4j | — | P-A | — | graph.py:58 |
| API-GRPH-06 | POST | `/api/graph/rag` | 없음 | 본문 `GraphRagRequest` | {answer} | 503 | Neo4j · Qdrant · LLM | — | P-A | P01-①-3 | graph.py:74 |

#### `conversations` — `app/routes/conversations.py` · 8개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-CONV-01 | POST | `/api/conversations` | 세션·JWT | 본문 `ConversationCreate` | {id, title, active} | — | PostgreSQL · Redis | — | P-A | P01-①-3 | conversations.py:102 |
| API-CONV-02 | GET | `/api/conversations` | 세션·JWT | `limit` · `offset` | {items, total, offset, limit} | — | PostgreSQL · Redis | — | P-A | P01-①-3 | conversations.py:119 |
| API-CONV-03 | GET | `/api/conversations/active` | 세션·JWT | — | {active_conversation} | — | PostgreSQL · Redis | — | P-A | P01-①-3 | conversations.py:145 |
| API-CONV-04 | GET | `/api/conversations/{cid}` | 세션·JWT | `{cid}` · `msg_limit` · `msg_offset` | 모델 없음 | — | PostgreSQL | — | P-A | P01-①-3 | conversations.py:164 |
| API-CONV-05 | PATCH | `/api/conversations/{cid}` | 세션·JWT | `{cid}` · 본문 `ConversationPatch` | {ok, title} | — | PostgreSQL | — | P-A | P01-①-3 | conversations.py:194 |
| API-CONV-06 | DELETE | `/api/conversations/{cid}` | 세션·JWT | `{cid}` | 모델 없음 | — | PostgreSQL · Redis | — | P-A | P01-①-3 | conversations.py:208 |
| API-CONV-07 | POST | `/api/conversations/{cid}/activate` | 세션·JWT | `{cid}` | {ok, active_conversation_id} | — | PostgreSQL · Redis | — | P-A | P01-①-3 | conversations.py:225 |
| API-CONV-08 | GET | `/api/conversations/{cid}/messages` | 세션·JWT | `{cid}` · `limit` · `offset` | {items, total} | — | PostgreSQL | — | P-A | P01-①-3 | conversations.py:237 |

#### `tasks` — `app/routes/tasks.py` · 2개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-TASK-01 | GET | `/api/tasks/{task_id}` | 없음 | `{task_id}` | {result, error} | — | Celery | — | P-E | P02-⑤-3 | tasks.py:26 |
| API-TASK-02 | DELETE | `/api/tasks/{task_id}` | 없음 | `{task_id}` · `terminate` | {task_id, revoked, terminate} | — | Celery | — | P-E | P02-⑤-3 | tasks.py:50 |

#### `paper` — `app/routes/paper.py` · 32개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-PAPR-01 | GET | `/api/paper/account` | 세션·JWT | — | 모델 없음 | — | 수집DB · 야후 · PostgreSQL · 외부(api.upbit.com, kind.krx.co.kr) | `paper-dashboard`, `paper-stock` | P-E | P01-③-1 · P01-③-2 · P01-③-3 · P01-④-3 | paper.py:41 |
| API-PAPR-02 | POST | `/api/paper/account/reset` | 세션·JWT | — | {status, cash} | — | PostgreSQL | (다른 곳) | P-E | P01-④-3 | paper.py:49 |
| API-PAPR-03 | GET | `/api/paper/stocks/quote` | 없음 | `symbol`* | 모델 없음 | 404 | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | (다른 곳) | P-E | P01-④-3 | paper.py:65 |
| API-PAPR-04 | GET | `/api/paper/stocks/positions` | 세션·JWT | `volatility` | {positions} | — | 수집DB · 야후 · PostgreSQL · 외부(kind.krx.co.kr) | `paper-stock` | P-E | P01-④-3 | paper.py:73 |
| API-PAPR-05 | POST | `/api/paper/stocks/orders/preview` | 세션·JWT | 본문 `StockOrderBody` | 모델 없음 | — | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | (다른 곳) | P-E | P01-④-1 · P01-④-3 | paper.py:79 |
| API-PAPR-06 | POST | `/api/paper/stocks/orders` | 세션·JWT | 본문 `StockOrderBody` | 모델 없음 | — | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | (다른 곳) | P-E | P01-④-3 | paper.py:100 |
| API-PAPR-07 | POST | `/api/paper/stocks/orders/buy` | 세션·JWT | 본문 `StockOrderBody` | 모델 없음 | — | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | — | P-E | P01-④-3 | paper.py:105 |
| API-PAPR-08 | POST | `/api/paper/stocks/orders/sell` | 세션·JWT | 본문 `StockOrderBody` | 모델 없음 | — | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | — | P-E | P01-④-3 | paper.py:110 |
| API-PAPR-09 | POST | `/api/paper/stocks/orders/pine` | 세션·JWT | 본문 `StockOrderBody` | 모델 없음 | — | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | — | P-E | P02-③-1 | paper.py:115 |
| API-PAPR-10 | GET | `/api/paper/stocks/orders/history` | 세션·JWT | `limit` | {history} | — | PostgreSQL | `paper-dashboard`, `paper-stock` | P-E | P01-④-3 | paper.py:121 |
| API-PAPR-11 | GET | `/api/paper/crypto/market-list` | 없음 | — | {markets, marketCodes} | — | 외부(api.upbit.com) | `paper-crypto` | P-E | — | paper.py:146 |
| API-PAPR-12 | GET | `/api/paper/crypto/rankings` | 없음 | `limit` | {rankings} | — | 외부(api.upbit.com) | `paper-crypto` | P-E | — | paper.py:152 |
| API-PAPR-13 | GET | `/api/paper/crypto/ticker` | 없음 | `markets`* | {tickers} | — | 외부(api.upbit.com) | `paper-crypto` | P-E | — | paper.py:157 |
| API-PAPR-14 | GET | `/api/paper/crypto/{code}/candles` | 없음 | `{code}` · `unit` · `count` | {market, candles} | 400 · 502 | 외부(api.upbit.com) | `paper-crypto` | P-E | — | paper.py:162 |
| API-PAPR-15 | GET | `/api/paper/crypto/{code}/domestic-prices` | 없음 | `{code}` | 모델 없음 | — | 외부(api.bithumb.com, api.korbit.co.kr …) | `paper-crypto` | P-E | — | paper.py:172 |
| API-PAPR-16 | GET | `/api/paper/crypto/{code}` | 세션·JWT | `{code}` | {marketCode, koreanName, englishName, buyCryptoCount, ticker} | 404 | PostgreSQL · 외부(api.upbit.com) | `paper-crypto` | P-E | — | paper.py:177 |
| API-PAPR-17 | GET | `/api/paper/trade/hold` | 세션·JWT | — | 모델 없음 | — | PostgreSQL · 외부(api.upbit.com) | `paper-crypto` | P-E | — | paper.py:188 |
| API-PAPR-18 | POST | `/api/paper/trade/order/preview` | 세션·JWT | 본문 `CryptoPreviewBody` | 모델 없음 | — | PostgreSQL · 외부(api.upbit.com) | (다른 곳) | P-E | — | paper.py:195 |
| API-PAPR-19 | POST | `/api/paper/trade/order/buy` | 세션·JWT | 본문 `CryptoBuyBody` | 모델 없음 | — | PostgreSQL · 외부(api.upbit.com) | (다른 곳) | P-E | — | paper.py:203 |
| API-PAPR-20 | POST | `/api/paper/trade/order/sell` | 세션·JWT | 본문 `CryptoSellBody` | 모델 없음 | — | PostgreSQL · 외부(api.upbit.com) | (다른 곳) | P-E | — | paper.py:215 |
| API-PAPR-21 | GET | `/api/paper/trade/order/history` | 세션·JWT | `limit` | {history} | — | PostgreSQL | `paper-crypto`, `paper-dashboard` | P-E | — | paper.py:227 |
| API-PAPR-22 | GET | `/api/paper/alternatives/markets` | 없음 | — | {markets, notice} | — | 야후 | `paper-alternative` | P-E | — | paper.py:241 |
| API-PAPR-23 | GET | `/api/paper/alternatives/markets/{symbol}/chart` | 없음 | `{symbol}` · `days` | {symbol, data} | 404 | 야후 | `paper-alternative` | P-E | — | paper.py:247 |
| API-PAPR-24 | GET | `/api/paper/alternatives/positions` | 세션·JWT | `volatility` | {positions, totalEvalAmount} | — | 야후 · PostgreSQL | `paper-alternative` | P-E | — | paper.py:255 |
| API-PAPR-25 | GET | `/api/paper/alternatives/orders/history` | 세션·JWT | `limit` | {history} | — | PostgreSQL | `paper-alternative`, `paper-dashboard` | P-E | — | paper.py:261 |
| API-PAPR-26 | POST | `/api/paper/alternatives/orders/preview` | 세션·JWT | 본문 `AltOrderBody` | 모델 없음 | — | 야후 · PostgreSQL | (다른 곳) | P-E | — | paper.py:266 |
| API-PAPR-27 | POST | `/api/paper/alternatives/orders` | 세션·JWT | 본문 `AltOrderBody` | 모델 없음 | — | 야후 · PostgreSQL | (다른 곳) | P-E | — | paper.py:274 |
| API-PAPR-28 | GET | `/api/paper/api-keys` | 세션·JWT | — | {keys} | — | PostgreSQL | `paper-openapi` | P-B | P02-②-3 | paper.py:302 |
| API-PAPR-29 | POST | `/api/paper/api-keys` | 세션·JWT | 본문 `ApiKeyBody` | {apiKey} | — | PostgreSQL | `paper-openapi` | P-B | P02-②-3 | paper.py:308 |
| API-PAPR-30 | DELETE | `/api/paper/api-keys/{key_id}` | 세션·JWT | `{key_id}` | {status} | 404 | PostgreSQL | `paper-openapi` | P-B | P02-②-3 | paper.py:321 |
| API-PAPR-31 | POST | `/api/paper/alpaca/account` | 세션·JWT | 본문 `AlpacaTestBody` | {ok, environment, connection, accountStatus, tradingBlocked} 외 4 | — | 외부(paper-api.alpaca.markets) | — | P-E | — | paper.py:367 |
| API-PAPR-32 | POST | `/api/paper/alpaca/positions` | 세션·JWT | 본문 `AlpacaTestBody` | {ok, count, positions} | — | 외부(paper-api.alpaca.markets) | — | P-E | — | paper.py:377 |

#### `openapi` — `app/routes/openapi.py` · 9개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-OAPI-01 | GET | `/openapi/v1/stocks` | API 키 | `limit` · `market` | {stocks} | 503 MARKET_DATA_UNAVAILABLE | PostgreSQL · 외부(kind.krx.co.kr) | — | P-B | P02-②-3 | openapi.py:83 |
| API-OAPI-02 | GET | `/openapi/v1/quote/{symbol}` | API 키 | `{symbol}` | {symbol, code, name, market, price} 외 4 | 404 NOT_FOUND | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | — | P-B | P02-②-3 | openapi.py:98 |
| API-OAPI-03 | GET | `/openapi/v1/account` | API 키 | — | 모델 없음 | — | 수집DB · 야후 · PostgreSQL · 외부(api.upbit.com, kind.krx.co.kr) | — | P-E | — | openapi.py:111 |
| API-OAPI-04 | GET | `/openapi/v1/positions` | API 키 | — | {positions} | — | 수집DB · 야후 · PostgreSQL · 외부(kind.krx.co.kr) | — | P-E | — | openapi.py:118 |
| API-OAPI-05 | POST | `/openapi/v1/orders` | API 키 | 본문 `OpenApiOrderBody` | 모델 없음 | 400 INVALID_REQUEST | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | — | P-E | — | openapi.py:129 |
| API-OAPI-06 | GET | `/openapi/v1/orders` | API 키 | `limit` | {orders} | — | PostgreSQL | — | P-E | — | openapi.py:142 |
| API-OAPI-07 | GET | `/openapi/v1/crypto/hold` | API 키 | — | 모델 없음 | — | PostgreSQL · 외부(api.upbit.com) | — | P-E | — | openapi.py:147 |
| API-OAPI-08 | GET | `/openapi/v1/alternatives/positions` | API 키 | — | {positions, totalEvalAmount} | — | 야후 · PostgreSQL | — | P-E | — | openapi.py:154 |
| API-OAPI-09 | GET | `/openapi/v1/docs-summary` | 없음 | — | {baseUrl, auth, rateLimit, endpoints} | — | — | `paper-openapi` | P-B | P02-②-3 | openapi.py:160 |

#### `lean` — `app/routes/lean.py` · 3개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-LEAN-01 | GET | `/api/backtests/lean/status` | 없음 | — | 모델 없음 | — | LEAN · Docker | `quant-lean` | P-D | P02-③-2 | lean.py:63 |
| API-LEAN-02 | POST | `/api/backtests/lean/run` | 세션·JWT | 본문 `BacktestRequest` | 모델 없음 | 422 · 502 | 야후 · PostgreSQL · LEAN · Docker | (다른 곳) | P-D | P02-①-1 · P02-①-3 · P02-③-2 · P02-④-1 · P02-④-2 | lean.py:68 |
| API-LEAN-03 | GET | `/api/backtests/lean/history` | 세션·JWT | `limit` | {runs} | — | PostgreSQL | `quant-lean` | P-D | P02-①-3 · P02-③-2 · P02-④-2 | lean.py:94 |

#### `rebalance` — `app/routes/rebalance.py` · 9개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-RBAL-01 | GET | `/api/rebalance/plan` | 세션·JWT | — | 모델 없음 | — | PostgreSQL | (다른 곳) | 미배정 | — | rebalance.py:59 |
| API-RBAL-02 | PUT | `/api/rebalance/plan` | 세션·JWT | 본문 `PlanBody` | 모델 없음 | 400 | 야후 · PostgreSQL · 외부(kind.krx.co.kr) | (다른 곳) | 미배정 | — | rebalance.py:66 |
| API-RBAL-03 | GET | `/api/rebalance/status` | 세션·JWT | — | {plan, snapshot, triggers} | — | 수집DB · 야후 · PostgreSQL · 외부(kind.krx.co.kr) | `robo-rebalance` | 미배정 | — | rebalance.py:83 |
| API-RBAL-04 | POST | `/api/rebalance/preview` | 세션·JWT | — | 모델 없음 | 400 | 수집DB · 야후 · PostgreSQL · 외부(kind.krx.co.kr) | (다른 곳) | 미배정 | — | rebalance.py:96 |
| API-RBAL-05 | POST | `/api/rebalance/execute` | 세션·JWT | 본문 `ExecuteBody` | 모델 없음 | 400 | 수집DB · 야후 · PostgreSQL · 외부(kind.krx.co.kr) | (다른 곳) | 미배정 | — | rebalance.py:109 |
| API-RBAL-06 | POST | `/api/rebalance/check` | 세션·JWT | — | 모델 없음 | — | 수집DB · 야후 · PostgreSQL · 외부(kind.krx.co.kr) | (다른 곳) | 미배정 | — | rebalance.py:129 |
| API-RBAL-07 | POST | `/api/rebalance/cashflow` | 세션·JWT | 본문 `CashflowBody` | 모델 없음 | 400 | 수집DB · 야후 · PostgreSQL · 외부(kind.krx.co.kr) | (다른 곳) | 미배정 | — | rebalance.py:139 |
| API-RBAL-08 | GET | `/api/rebalance/cashflows` | 세션·JWT | `limit` | {events} | — | PostgreSQL | `robo-rebalance` | 미배정 | — | rebalance.py:154 |
| API-RBAL-09 | GET | `/api/rebalance/runs` | 세션·JWT | `limit` | {runs} | — | PostgreSQL | `robo-rebalance` | 미배정 | — | rebalance.py:160 |

#### `tradingview` — `app/routes/tradingview.py` · 5개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-TV-01 | POST | `/api/webhooks/tradingview` | 없음 | — | {ok, status, message, symbol, side} 외 2 | 400 · 403 · 429 · ? | 야후 · PostgreSQL · Redis · 알림 · 외부(api.coolsms.co.kr, api.telegram.org …) | (다른 곳) | 미배정 | — | tradingview.py:36 |
| API-TV-02 | GET | `/api/tradingview/webhook-info` | 세션·JWT | — | {webhook_url, alert_template, alert_template_text, notes} | — | — | `indicator-tradingview` | 미배정 | — | tradingview.py:85 |
| API-TV-03 | GET | `/api/tradingview/signals` | 세션·JWT | `limit` | {signals} | — | PostgreSQL | `indicator-tradingview` | 미배정 | — | tradingview.py:103 |
| API-TV-04 | POST | `/api/tradingview/compare` | 세션·JWT | 본문 `CompareBody` | 모델 없음 | 422 · 502 | 야후 · PostgreSQL · LEAN · Docker | (다른 곳) | 미배정 | — | tradingview.py:131 |
| API-TV-05 | GET | `/api/tradingview/comparisons` | 세션·JWT | `limit` | {comparisons} | — | PostgreSQL | `indicator-tradingview` | 미배정 | — | tradingview.py:188 |

#### `formula` — `app/routes/formula.py` · 13개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-FRML-01 | GET | `/api/formula-indicators/reference` | 세션·JWT | — | {functions, templates, rules} | — | — | `indicator-formula` | 미배정 | — | formula.py:116 |
| API-FRML-02 | POST | `/api/formula-indicators/validate` | 세션·JWT | 본문 `ValidateBody` | 모델 없음 | 422 | 수집DB · 야후 · PostgreSQL | (다른 곳) | 미배정 | — | formula.py:125 |
| API-FRML-03 | POST | `/api/formula-indicators/compute` | 세션·JWT | 본문 `AdhocComputeBody` | 모델 없음 | — | 수집DB · 야후 · PostgreSQL | (다른 곳) | 미배정 | — | formula.py:140 |
| API-FRML-04 | GET | `/api/formula-indicators` | 세션·JWT | — | {indicators} | — | PostgreSQL | (다른 곳) | 미배정 | — | formula.py:145 |
| API-FRML-05 | POST | `/api/formula-indicators` | 세션·JWT | 본문 `SaveBody` | 모델 없음 | 409 · 422 | PostgreSQL | (다른 곳) | 미배정 | — | formula.py:151 |
| API-FRML-06 | GET | `/api/formula-indicators/{ind_id}` | 세션·JWT | `{ind_id}` | 모델 없음 | — | PostgreSQL | `indicator-formula` | 미배정 | — | formula.py:170 |
| API-FRML-07 | PUT | `/api/formula-indicators/{ind_id}` | 세션·JWT | `{ind_id}` · 본문 `SaveBody` | {version_bumped} | 409 · 422 | PostgreSQL | `indicator-formula` | 미배정 | — | formula.py:175 |
| API-FRML-08 | DELETE | `/api/formula-indicators/{ind_id}` | 세션·JWT | `{ind_id}` | {ok} | — | PostgreSQL | `indicator-formula` | 미배정 | — | formula.py:199 |
| API-FRML-09 | GET | `/api/formula-indicators/{ind_id}/versions` | 세션·JWT | `{ind_id}` | {current_version, versions} | — | PostgreSQL | (다른 곳) | 미배정 | — | formula.py:208 |
| API-FRML-10 | POST | `/api/formula-indicators/{ind_id}/versions/{version}/restore` | 세션·JWT | `{ind_id}` · `{version}` | {restored, message} | 404 | PostgreSQL | (다른 곳) | 미배정 | — | formula.py:215 |
| API-FRML-11 | POST | `/api/formula-indicators/{ind_id}/compute` | 세션·JWT | `{ind_id}` · 본문 `ComputeBody` | {from_cache} | — | 수집DB · 야후 · PostgreSQL | (다른 곳) | 미배정 | — | formula.py:231 |
| API-FRML-12 | GET | `/api/formula-indicators/{ind_id}/results` | 세션·JWT | `{ind_id}` · `limit` | {results} | — | PostgreSQL | (다른 곳) | 미배정 | — | formula.py:257 |
| API-FRML-13 | GET | `/api/formula-indicators/{ind_id}/export` | 세션·JWT | `{ind_id}` · `format` | 모델 없음 | — | PostgreSQL | (다른 곳) | 미배정 | — | formula.py:265 |

#### `glossary` — `app/routes/glossary.py` · 4개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-GLOS-01 | GET | `/api/glossary` | 없음 | `q` · `category` · `limit` · `offset` | 모델 없음 | — | PostgreSQL | — | P-A | P01-①-1 | glossary.py:27 |
| API-GLOS-02 | GET | `/api/glossary/categories` | 없음 | — | 모델 없음 | — | PostgreSQL | — | P-A | P01-①-1 | glossary.py:39 |
| API-GLOS-03 | GET | `/api/glossary/meta` | 없음 | — | 모델 없음 | — | PostgreSQL | — | P-A | P01-①-1 | glossary.py:45 |
| API-GLOS-04 | GET | `/api/glossary/{name}` | 없음 | `{name}` | 모델 없음 | 404 | PostgreSQL | — | P-A | P01-①-1 | glossary.py:51 |

#### `learn` — `app/routes/learn.py` · 7개

| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-LRN-01 | GET | `/api/learn/catalog` | 없음 | `section` · `q` | {contract, pages, builtin_errors, team} | — | 외부(huggingface.co) | — | P-A | — | learn.py:69 |
| API-LRN-02 | GET | `/api/learn/pages/{slug}` | 없음 | `{slug}` | {history_url} | 401 · 404 | 외부(huggingface.co) | — | P-A | — | learn.py:91 |
| API-LRN-03 | POST | `/api/learn/pages` | 세션 | 본문 `PageIn` | {slug, version, commit} | 409 | 외부(huggingface.co) | — | P-A | — | learn.py:109 |
| API-LRN-04 | PUT | `/api/learn/pages/{slug}` | 세션 | `{slug}` · 본문 `PageUpdate` | {slug, version, commit, changed} | 400 · 404 | 외부(huggingface.co) | — | P-A | — | learn.py:124 |
| API-LRN-05 | DELETE | `/api/learn/pages/{slug}` | 세션 | `{slug}` · `base_version`* | Response | 400 · 404 | 외부(huggingface.co) | — | P-A | — | learn.py:143 |
| API-LRN-06 | GET | `/api/learn/pages/{slug}/history` | 세션 | `{slug}` | {slug, commits, url} | 404 | 외부(huggingface.co) | — | P-A | — | learn.py:160 |
| API-LRN-07 | POST | `/api/learn/sync` | 세션 | — | {team} | — | 외부(huggingface.co) | — | P-A | — | learn.py:172 |

<!-- /api_scan:routes -->

---

## 5. 요청 본문 모델

본문(`Body`)으로 받는 Pydantic 모델의 칸이다. 응답 모델은 없다(F3).

<!-- api_scan:models -->
| 모델 | 칸 (타입 = 기본값) | 쓰는 API |
|---|---|---|
| `AccountDeleteBody` | `password: str` · `confirm: str` = `''` | API-AUTH-14 |
| `AdhocComputeBody` | — | API-FRML-03 |
| `AlpacaTestBody` | `api_key: str` = `''` · `secret_key: str` = `''` | API-PAPR-31, API-PAPR-32 |
| `AltOrderBody` | `symbol: str` · `side: str` · `quantity: int` = `Field(..., ge=1)` | API-PAPR-26, API-PAPR-27 |
| `ApiKeyBody` | `label: str` = `'My API Key'` | API-PAPR-29 |
| `BacktestRequest` | `ticker: str` = `Field(min_length=1, max_length=12, examples=['005930.KS'])` · `start_date: date` · `end_date: date` · `compare_start_date: date` · `compare_end_date: date` · `initial_cash: float` = `Field(default=10000, ge=1000, le=1000000000)` · `strategy: str` = `Field(default='buy_hold', description='buy_hold \| ma_cross \| dca \| momentum')` · `short_window: int` = `Field(default=20, ge=2, le=120)` · `long_window: int` = `Field(default=60, ge=5, le=300)` · `dca_interval_days: int` = `Field(default=21, ge=1, le=120)` · `breakout_window: int` = `Field(default=20, ge=5, le=120)` | API-LEAN-02 |
| `BatchRunBody` | `symbols: list[str]` = `[]` · `period: str` = `'2y'` · `model: str` = `'lgb'` | API-QNT-03 |
| `BrokerOrderBody` | `symbol: str` · `side: str` · `quantity: int` · `price: float` | API-STK-22 |
| `BrokerSettingsBody` | `broker: str` = `Field(default=DEFAULT_BROKER, alias='broker_type')` · `app_key: str` = `''` · `app_secret: str` = `''` · `account_no: str` = `''` · `paper: bool` = `Field(default=True, alias='paper_trading')` | API-STK-15 |
| `CashflowBody` | `kind: str` = `Field(..., description='DEPOSIT \| WITHDRAW \| DIVIDEND')` · `amount: float` = `Field(..., gt=0)` · `symbol: str` = `''` · `memo: str` = `''` | API-RBAL-07 |
| `ChatBody` | `question: str` · `history: list[dict]` = `[]` · `use_rag: bool` = `True` · `conversation_id: Optional[str]` = `None` | API-CHAT-01, API-CHAT-02 |
| `ClusterBody` | `symbols: list[str]` = `[]` · `period: str` = `'2y'` | API-ML-03 |
| `CompareBody` | `ticker: str` = `Field(..., min_length=1, max_length=12)` · `strategy: str` = `Field('ma_cross', description='buy_hold \| ma_cross \| dca \| momentum')` · `start_date: date` · `end_date: date` · `initial_cash: float` = `Field(10000, ge=1000)` · `short_window: int` = `Field(20, ge=2, le=120)` · `long_window: int` = `Field(60, ge=5, le=300)` · `dca_interval_days: int` = `Field(21, ge=1, le=120)` · `breakout_window: int` = `Field(20, ge=5, le=120)` · `tv_metrics: TvMetricsBody \| None` = `None` · `tv_trades_csv: str \| None` = `Field(None, description='Strategy Tester 거래 목록 CSV 원문')` | API-TV-04 |
| `ComputeBody` | `symbol: str` = `'005930.KS'` · `period: str` = `Field('2y', description='1y \| 2y \| 5y \| 10y')` · `commission_bps: float` = `Field(0.0, ge=0, le=500)` · `slippage_bps: float` = `Field(0.0, ge=0, le=500)` · `stop_loss_pct: float \| None` = `Field(None, ge=0.1, le=90)` · `take_profit_pct: float \| None` = `Field(None, ge=0.1, le=500)` · `use_cache: bool` = `True` | API-FRML-11 |
| `ConversationCreate` | `title: Optional[str]` = `None` | API-CONV-01 |
| `ConversationPatch` | `title: str` | API-CONV-05 |
| `CrawlNaverBody` | `code: str` | API-ING-04 |
| `CrawlUrlBody` | `url: str` | API-ING-03, API-ING-10 |
| `CryptoBuyBody` | `marketCode: str` · `buyKrw: float` = `Field(..., gt=0)` | API-PAPR-19 |
| `CryptoPreviewBody` | `marketCode: str` · `side: str` · `buyKrw: float \| None` = `None` · `sellCount: float \| None` = `None` | API-PAPR-18 |
| `CryptoSellBody` | `marketCode: str` · `sellCount: float` = `Field(..., gt=0)` | API-PAPR-20 |
| `CustomIndicatorBody` | `name: str` = `Field(..., min_length=1, max_length=60)` · `base: str` = `Field('rsi_ma', description='rsi_ma \| macd_bb \| volume_rsi \| triple_ma')` · `short_window: int` = `Field(5, ge=2, le=30)` · `mid_window: int` = `Field(20, ge=3, le=120)` · `rsi_period: int` = `Field(14, ge=5, le=40)` · `buy_threshold: float` = `Field(35.0, ge=5.0, le=50.0)` | API-STK-32 |
| `DocSearchBody` | `query: str` · `top_k: int` = `5` · `source: str \| None` = `None` | API-DOC-04 |
| `ExecuteBody` | `run_id: str \| None` = `Field(None, description='제안(proposed) 이력을 승인해 실행할 때')` · `note: str` = `''` | API-RBAL-05 |
| `GoalSimBody` | `amount_manwon: float` = `5000` · `monthly_contribution_manwon: float` = `0` · `horizon_years: int` = `3` · `target_return_pct: float` = `8.0` · `expected_return_pct: float` = `7.0` · `expected_volatility_pct: float` = `12.0` · `n_paths: int` = `3000` | API-ML-09 |
| `GraphRagRequest` | `query: str` · `top_k: int` = `5` · `answer: bool` = `False` | API-GRPH-06 |
| `HoldingBody` | `symbol: str` · `name: str` · `quantity: int` · `avg_price: float` | API-STK-10 |
| `KillSwitchBody` | `enabled: bool` · `reason: str` = `''` | API-STK-37 |
| `LoginBody` | `email: str` · `password: str` | API-AUTH-02, API-AUTH-04 |
| `NotificationSettingsBody` | `channels: list[str]` = `Field(default_factory=list, description='활성화할 채널 목록')` · `telegram_token: str` = `''` · `telegram_chat_id: str` = `''` · `slack_webhook_url: str` = `''` · `email_to: str` = `''` · `email_host: str` = `''` · `email_port: int` = `Field(default=587, ge=1, le=65535)` · `email_user: str` = `''` · `email_password: str` = `''` · `email_from: str` = `''` · `kakao_api_key: str` = `''` · `kakao_api_secret: str` = `''` · `kakao_sender_key: str` = `''` · `kakao_phone: str` = `''` · `sms_api_key: str` = `''` · `sms_api_secret: str` = `''` · `sms_from: str` = `''` · `sms_to: str` = `''` | API-NOTI-02 |
| `OpenApiOrderBody` | `symbol: str` · `side: str` = `Field(..., description='BUY \| SELL')` · `quantity: int` = `Field(..., ge=1)` | API-OAPI-05 |
| `OrderBody` | `symbol: str` · `name: str` · `order_type: str` · `quantity: int` · `price: float` · `broker: str` = `'virtual'` | API-STK-12 |
| `PageIn` | `meta: dict[str, MetaValue]` = `Field(..., description='머리말 칸(규격 learn-v1 · 설계서 6절 표 6)')` · `body: str` = `Field('', max_length=lp.MAX_BODY, description='본문 마크다운')` | API-LRN-03 |
| `PageUpdate` | `base_version: str` = `Field(..., pattern=VERSION_PATTERN, description='편집을 시작할 때 받은 판(git 블롭 해시)')` | API-LRN-04 |
| `PasswordChangeBody` | `current_password: str` · `new_password: str` | API-AUTH-13 |
| `PlanBody` | `name: str \| None` = `None` · `is_active: bool \| None` = `None` · `targets: list[TargetBody] \| None` = `None` · `time_period: str \| None` = `Field(None, description='none \| monthly \| quarterly \| yearly')` · `drift_enabled: bool \| None` = `None` · `drift_threshold_pct: float \| None` = `None` · `cashflow_enabled: bool \| None` = `None` · `cashflow_min_amount: float \| None` = `None` · `auto_execute: bool \| None` = `None` · `min_order_amount: float \| None` = `None` | API-RBAL-02 |
| `ProfileUpdateBody` | `name: str` | API-AUTH-12 |
| `QuantSettingsBody` | `mode: str` = `Field(default='paper', description='paper \| live')` · `broker: str` = `DEFAULT_BROKER` · `app_key: str` = `''` · `app_secret: str` = `''` · `account_no: str` = `''` · `symbol_source: str` = `Field(default='ai', description='ai \| manual')` · `selected_symbols: list[str]` = `Field(default_factory=list)` · `ai_top_n: int` = `Field(default=3, ge=1, le=5)` · `per_trade_budget: float` = `Field(default=1000000, ge=10000, le=10000000)` · `buy_ratio: float` = `Field(default=1.0, ge=0.1, le=1.0)` · `sell_ratio: float` = `Field(default=0.5, ge=0.1, le=1.0)` · `risk_daily_loss_limit_pct: float` = `Field(default=3.0, ge=0, le=50, description='0이면 비활성')` · `risk_max_position_pct: float` = `Field(default=30.0, ge=0, le=100, description='0이면 비활성')` · `risk_max_orders_per_day: int` = `Field(default=20, ge=0, le=500, description='0이면 비활성')` · `risk_cooldown_min: int` = `Field(default=30, ge=0, le=1440, description='0이면 비활성')` | API-STK-18 |
| `RegisterBody` | `name: str` · `email: str` · `password: str` | API-AUTH-01 |
| `RiskProfileBody` | `answers: dict[str, int]` | API-ML-08 |
| `RoboAllocationBody` | `risk_profile: str` = `'moderate'` · `horizon_years: int` = `3` · `amount_manwon: int` = `5000` | API-ML-04 |
| `SaveBody` | `name: str` = `Field(..., min_length=1, max_length=60)` · `description: str` = `Field('', max_length=300)` · `note: str` = `Field('', max_length=200, description='버전 메모')` | API-FRML-05, API-FRML-07 |
| `StockOrderBody` | `symbol: str` = `Field(..., description='005930 또는 005930.KS (해외 티커도 가능)')` · `side: str` = `Field(..., description='BUY \| SELL')` · `quantity: int` = `Field(..., ge=1)` | API-PAPR-05, API-PAPR-06, API-PAPR-07, API-PAPR-08, API-PAPR-09 |
| `TokenRefreshBody` | `refresh_token: str` | API-AUTH-05 |
| `TokenRevokeBody` | `access_token: str` · `refresh_token: str \| None` = `None` | API-AUTH-06 |
| `TranslationIngestBody` | `data_type: str` = `'labeled'` · `categories: list[str]` = `[]` · `languages: list[str]` = `[]` · `max_docs: int` = `0` | API-ING-06, API-ING-11 |
| `TranslationSearchBody` | `query: str` · `top_k: int` = `5` · `category: str \| None` = `None` · `target_language: str \| None` = `None` | API-ING-07 |
| `ValidateBody` | `symbol: str \| None` = `None` | API-FRML-02 |
<!-- /api_scan:models -->

---

## 6. 오류 코드와 오류 응답 형식

2절의 오류 코드 표는 **라우트 본문에 적힌 것만** 센다. 실제로 나가는 오류는 그보다 많다.

| 어디서 | 코드 | 몸통 모양 | 몇 곳 |
|--------|------|-----------|------|
| 라우트 본문 `HTTPException(code, "…")` | 표의 코드 | `{"detail": "문자열"}` | 표 참고 |
| Open API `OpenApiError(code, "이름", "…")` | `401 UNAUTHORIZED` · `404 NOT_FOUND` · `400 INVALID_REQUEST` · `429 RATE_LIMITED` · `503 MARKET_DATA_UNAVAILABLE` | `{"detail": {"error": "이름", "message": "…"}}` | 라우트 9 + 인증 의존성 |
| 인증 의존성 (`session.get_current_user` 등) | `401` 「로그인이 필요합니다」 · 「세션이 만료되었습니다」 · `403`(역할 · 관리자) | `{"detail": "문자열"}` | 인증 이름표가 붙은 113곳 |
| Open API 인증 (`require_api_key`) | `401 UNAUTHORIZED` · `429 RATE_LIMITED`(키당 분당 60회) | Open API 모양 | 8곳 |
| FastAPI 스스로 | `422` 요청 검증 실패 | `{"detail": [{"loc", "msg", "type"}, …]}` | 인자가 있는 전부 |

> 🟡 **규약 제안(② 에서 정함)** — 새로 만드는 API 는 한 형식만 쓴다. 후보는 Open API 모양(`error` 이름 + `message`)이다.
> 이유: 화면이 문자열을 비교하지 않고 이름으로 가를 수 있다. 옛 API 를 바꾸는 것은 화면 코드가 함께 바뀌어야 해서 이 판에서 제안하지 않는다.

---

## 7. 인터페이스 정의서 (시작)

**인터페이스** — 두 시스템이 주고받는 경계 하나. API 명세서가 「앱이 받는 요청」 이라면, 이 절은 「앱이 **바깥에** 닿는 길」 과 「바깥이 앱에 닿는 길」 을 한 줄씩 적는다.
수는 4절 「닿는 곳」 칸을 센 것이다(가능한 길의 합집합 · 1.4절).

| IF ID | 양쪽 | 방식 | 인증 · 설정 키 (기본값) | 닿는 API | 코드 | 파트 | 확실도 · 비고 |
|-------|------|------|------|:--:|------|:----:|------|
| IF-01 | 브라우저 → 앱 | HTTP JSON · 쿠키 세션 | 쿠키 `fin_session` · `SESSION_TTL` 604800(7일 · 슬라이딩) | 146 (메뉴 화면 74) | `app/lib/session.py:108` | 공통 | 🟢 |
| IF-02 | 외부 클라이언트 → 앱 Open API | HTTP JSON `/openapi/v1` | `Authorization: Bearer <API 키>` → SHA-256 대조 · `OPENAPI_RATE_LIMIT_MAX` 60/`WINDOW` 60초 | 9 | `app/routes/openapi.py:58` | P-B · P-E | 🟢 증권사에 닿는 길 없음(F5) |
| IF-03 | 앱 → 수집 DB | SQLite 파일 **읽기 전용**(`mode=ro`) | `COLLECTOR_DB_PATH` → `data/collector/market.sqlite3` → 도커 `/app/data/csv/collector/market.sqlite3` | 19 (기준일 실림 2) | `app/services/collector_db.py` | **P-A** | 🟢 · 매퍼 8절 DM-01 |
| IF-04 | 앱 → 야후(비공식 차트 · 검색 · 펀더멘털) | HTTPS · `query1`·`query2`·`fc` 호스트 | 없음 | 43 | `app/services/stock.py` 외 | **P-A** | 🔴 팀이 약관 근거로 배제(옛 `#23` · `#31`) · 봉인 시험 TC-YH |
| IF-05 | 앱 ↔ Redis | Redis 프로토콜 | `REDIS_URL`(`redis://localhost:6379`) · 세션 `fin_session:{sid}` · JWT 폐기 목록 · Open API 한도 `openapi_rl` · Celery 브로커 · 결과 | 본문 22 + **인증 105** | `app/lib/redis_cache.py` · `session.py` | 공통 | 🟢 · 세션 인증 105곳(세션 64 · 세션·JWT 41)이 Redis 를 읽는다 |
| IF-06 | 앱 ↔ PostgreSQL | asyncpg · 시작 때 alembic `upgrade head` | `DATABASE_URL` | 107 | `app/database/postgres.py` · `main.py:20-25` | 전 파트 | 🟢 · 라우트 캐시 표 `data_cache`(F2 · F10) |
| IF-07 | 앱 ↔ Neo4j | bolt | `NEO4J_URI`(`bolt://localhost:7687`) | 6 (전부 인증 없음) | `app/database/neo4j.py` · `graph_service.py` | P-A | 🟢 · F4 ③ |
| IF-08 | 앱 ↔ Qdrant | HTTP | `QDRANT_URL`(`:6333`) · `QDRANT_COLLECTION` = `DOCUMENT_COLLECTION` = `fin_chunks`(기본값이 같다) · `translation_docs` | 16 | `rag_pipeline.py` · `crawl.py` · `translation_ingest.py` | P-A | 🟡 업로드 문서와 크롤 청크가 기본값으로 한 컬렉션(옛 A2 · A10) |
| IF-09 | 앱 → LLM | HTTP (Ollama · vLLM OpenAI 호환) | `LLM_PROVIDER` `ollama` · `OLLAMA_BASE_URL`(`127.0.0.1:11434`) · `LLM_MODEL` `llama3.1` · `EMBED_MODEL` `nomic-embed-text` · `VLLM_BASE_URL` | 15 | `app/lib/ollama.py` · `llm_client.py` | P-A | 🟡 스위치가 세 갈래에 안 듣는다(옛 A10) |
| IF-10 | 앱 → Celery 워커 | Redis 브로커 · `.delay()` | `REDIS_URL` | 7 (+ 조회 · 취소 2 · 인증 없음) | `app/celery_app.py:32-33` · `app/tasks/` | P-E | 🟡 태스크 등록 문제(옛 A4 — 실행 불가 6개)는 이 판에서 다시 재지 않음 |
| IF-11 | 앱 → LEAN | Docker 소켓 위 HTTP(`http://docker`) 또는 SSH | `LEAN_MODE` `auto` · `DOCKER_SOCK` `/var/run/docker.sock` · `LEAN_SSH_*` | 2 | `app/services/lean_backtest.py:276` | P-D | 🟢 · 도커 소켓은 옛 A3 의 보안 안건 |
| IF-12 | 앱 → 증권사 | HTTPS REST | 사용자별 `broker_settings`(app key · secret) · **관문 `QURIOUS_ALLOW_LIVE_TRADING`** · 호스트 KIS 실전 `openapi.koreainvestment.com` / 모의 `openapivts.koreainvestment.com` · KB `developer.kbsec.com` · eBest `openapi.ebestsec.co.kr` | 7 (주문 3) | `app/services/brokers/` | **P-E** | 🟢 ADR-0001 · TC-LT 21 |
| IF-13 | 앱 → 알림 채널 | HTTPS · SMTP | `TELEGRAM_*` · `SLACK_WEBHOOK_URL` · `SMTP_*` · `KAKAO_*` · `COOLSMS_*` · `SMS_*` · 호스트 `api.telegram.org` · `api.coolsms.co.kr` | 6 | `app/services/notification.py` | P-B (보조 P-E) | 🟡 옛 A12(전역 폴백 · 이스케이프 · 한도) |
| IF-14 | 앱 → 그 밖의 외부 | HTTPS | KRX KIND 상장법인 목록(`kind.krx.co.kr` 14) · 업비트(13) · Alpaca paper(4) · GitHub(2) · 빗썸 · 코빗 · 네이버 금융(각 1) | 42 | `krx_companies.py` · `paper_trading.py` · `crawl.py` | P-A · P-E | 🟡 네이버는 `robots.txt` 전면 금지(옛 A11) — 학습용 허용은 팀 판단이라 이 판에서 다시 재지 않는다 |
| IF-15 | 수집기 → 공공데이터포털 · KRX · DART | HTTPS · 일 1회(12:30 작업 스케줄러) | 각자 발급 키(`.env` · 양도 금지) | — (앱 밖) | `collector/` · [README](../../collector/README.md) | P-A | 이 판 범위 밖 → v0.2 「수집기 인터페이스」 |
| IF-16 | 수집기 → HF private 데이터셋 | HTTPS · `huggingface_hub` | HF 토큰 · 조직 `qurious-quant` | — (앱 밖) | `scripts/hf_dataset.py` | P-A | 이 판 범위 밖 |

> **뒤집을 조건** — IF-05 의 「인증 105」 는 세션 인증이 Redis 를 읽는다는 코드(`session.py:117` `get_session`)에 기댄다.
> 세션 저장소를 PostgreSQL 로 옮기면(D3 ⑥ 인증 구조) 이 칸이 PostgreSQL 로 간다.

---

## 8. 데이터 매퍼 (시작)

**데이터 매퍼** — 원천의 칸이 응답의 어느 칸으로, 어떤 변환을 거쳐 가는지 한 줄씩 잇는 표. 첫 판은 **P-A 가 책임지는 다리 두 개**만 적는다.

### DM-01 수집 DB → `API-STK-03` `GET /api/stocks/candles` (국내 주식 일봉)

원천 쿼리 — `price_adjusted AS a JOIN price_daily AS d ON (bas_dt, srtn_cd)` · `WHERE a.srtn_cd = 단축코드 AND a.bas_dt BETWEEN 시작 AND 오늘` (`collector_db.py:77-84`)

| 응답 칸 | 원천 | 변환 | 조건 · 비고 |
|---------|------|------|-------------|
| `symbol` | 요청 `symbol` | 그대로 | `NNNNNN.KS` · `NNNNNN.KQ` 만 다리로 — 아니면 None → 옛 경로(야후) |
| `interval` · `period` | 요청 | 그대로 | `1d` 만 · 기간 `1mo`~`10y` · `max` 9개 → 개월 수 |
| `candles[].time` | `a.bas_dt` (YYYYMMDD) | 그날 00:00 UTC 유닉스 초 | = 09:00 KST 장 시작 |
| `candles[].open` | `a.adj_mkp` | 소수 2자리 | `d.mkp` 가 0 · 없음(거래 없던 날)이면 **= 종가** (평평한 봉) |
| `candles[].high` · `low` | `a.adj_hipr` · `a.adj_lopr` | 소수 2자리 | 위와 같은 날 = 종가 |
| `candles[].close` | `a.adj_clpr` | 소수 2자리 | 없거나 0 이하면 **그 봉을 버린다** |
| `candles[].volume` | `d.trqu ÷ a.cum_factor` | 반올림 정수 | 분할 전 거래량을 분할 뒤 주식 수로 · 둘 중 하나 없으면 0 |
| `source` | 상수 | `"collector"` | 옛 경로(야후)면 **이 칸이 없다** |
| `as_of` | 남은 마지막 봉의 `bas_dt` | `YYYY-MM-DD` | **오늘이 아니다** — 공공데이터포털이 다음 날 낮에 준다(collector README §7) |
| `from_cache` | 라우트 캐시 | `true` | ~~🔴 붙어 있으면 최대 6시간 전 응답이다(F2 · DF-17 후보)~~ 수집 DB 가 받은 요청에는 **붙지 않는다**(DF-17 고침). 옛 경로(지수 · 해외 · 주봉 · 수집 DB 없음)에서만 붙고, 그때는 최대 6시간 전 응답이다 |

### DM-02 DM-01 → `API-STK-04` `GET /api/stocks/quant/indicators`

| 응답 칸 | 원천 | 변환 | 비고 |
|---------|------|------|------|
| `times` · `closes` | DM-01 `candles[].time` · `close` | 종가가 있는 봉만 · **뒤 100개** | |
| `rsi` · `ma5` · `ma20` · `ma60` · `bb_*` | DM-01 전체 종가 | 계산 뒤 뒤 100개 | 계산식은 옛 A5(RSI 세 벌 · 볼린저 ddof) — P-B |
| `current_price` | DM-01 마지막 `close` | 그대로 | ⚠️ **오늘 값이 아니라 `as_of` 의 값** — 자동매매가 체결가로 쓴다(`auto_trade.py:270`·`308` · 이슈 #35 E-1 · P-E) |
| `as_of` · `source` | DM-01 | 그대로 (`stock.py:387-388`) | 옛 경로면 둘 다 `null` |
| `error` | — | `"데이터 부족"` | 봉이 20개 미만이면 **이 칸만** 온다 |

> 다음 판(v0.2)에 넣을 매퍼 — 증권사 응답 → `API-STK-19` 시세 칸(P-E) · 모의투자 체결 → `paper_orders` 칸(P-E) · 벤치마크 12계열 → 성과 비교(P-D). 각 파트 몫이라 설계(②) 뒤 담당과 함께 쓴다.

---

## 9. 다음 판에 넣을 것 (변경 노트)

판을 올리지 않고 여기에 모은다(산출물목록 0.1절 규칙).

| 무엇 | 언제 | 왜 |
|------|------|----|
| ~~「요구 ID」 칸 채우기~~ | ~~S63 ② 설계 뒤~~ ✅ **S63** | 기능 설계서 v0.1 부록 A → 105/146 (스캐너 `load_requirement_map` · 시험 TC-AP-13) |
| ~~F2 고친 뒤 DM-01 `from_cache` 줄~~ | ~~DF-17 코드 PR 뒤~~ ✅ **2026-09-29** | ~~라우트 캐시를 건너뛰면 이 줄이 사라진다~~ 줄은 남았다 — 옛 경로(야후)에서는 여전히 붙는다. 뜻만 고쳤다 |
| 응답 모델(`response_model`) 칸 | ② 설계에서 적는 출력 모양을 코드에 옮긴 뒤 | F3 |
| IF-15 · IF-16 수집기 인터페이스 절 | v0.2 | 앱 밖이라 첫 판에서 뺐다 |
| 오류 규약 결정 | ② 설계 | 6절 제안 |
| 파트(제안) → 확정 | 결정 대장 v1.0 (D0 ⑤ 역할) 뒤 | 지금은 분배안 해석 |
| **강사님 기초 코드 반영 — API 146 → 181** (2026-09-30 · 2 · 4절 표는 이미 다시 채움) | v0.2 — 본문 숫자(머리표 146 · 0 · 2절 요약 · 인증 없음 33 → 34)와 새 라우터 셋 설명 | 강사님 lumina-invest `b055ab0` 을 받으며 라우터 셋(`rebalance` 9 · `tradingview` 5 · `formula` 13)과 `stocks` 4 · `ml` 4 가 늘었다. 새 ID 35개는 ID 대장에 날짜(2026-09-30)로 붙였다. `POST /api/webhooks/tradingview`(API-TV-01)는 세션 대신 본문의 API 키로 사용자를 찾는 구조라 「인증 없음」 으로 센다 — 받는 쪽 확인(비밀 토큰 · 중복 신호)은 요구 `P02-③-3` 설계에서 본다. 정답 대조(`app.openapi()`)는 이 판에서 다시 하지 않았다 |
| **용어사전 API 넷 — API 185 → 189 · 라우터 22 → 23** (2026-09-30 · 2 · 4절 표는 이미 다시 채움) | v0.2 — 본문 숫자(머리표 · 0 · 2절 요약 · 인증 없음 +4)와 새 라우터 `glossary` 설명 | `GET /api/glossary`(목록 · 검색) · `/categories` · `/meta` · `/{name}`(한 건) — `API-GLOS-01~04` · 요구 `P01-①-1` · 파트 P-A. **로그인 없이 읽는다** — 용어 풀이는 누구에게나 같은 참조 자료이고 사용자 데이터가 없다(바꾸는 주소는 없다 · 용어는 파일에서 고친다). 요청 · 응답 예 · 상태 코드(200 · 404 · 422) · 검색 순위는 [용어사전 설계서 v0.1](../설계/용어사전-설계_v0.1.md) 6절. 「화면」 칸이 「—」 인 것은 화면이 아직 이 API 를 부르지 않아서다(다음 작업). 같은 날 계정 관리 넷(`API-AUTH-11~14` · 181 → 185)도 이 표에 빠져 있었다 — 함께 옮긴다 |
| **개념 학습 API 일곱 — API 189 → 196 · 라우터 23 → 24** (2026-10-01 · 2 · 4절 표는 스캐너로 다시 채움) | v0.2 — 본문 숫자와 새 라우터 `learn` 설명 | `GET /api/learn/catalog`(목록 · 팀 저장소 상태) · `GET/POST/PUT/DELETE /api/learn/pages…` · `GET …/{slug}/history` · `POST /api/learn/sync` — `API-LRN-01~07` · 요구 `P01-①-1` 확장(제안) · 파트 P-A. **기본 교재는 로그인 없이, 팀 자료는 로그인 뒤.** 고치기 · 지우기는 `base_version`(git 블롭 해시)이 필수이고, 낡으면 **409 `LEARN_CONFLICT` + 지금 글**을 돌려준다(말없이 덮어쓰지 않음). 팀 자료 저장처는 HF 비공개 데이터셋 `qurious-quant/learn-pages` — HF 가 안 되면 503 `LEARN_TEAM_UNAVAILABLE`, 권한이 없으면 403. 오류 응답은 `detail: {code · message · field · current}` 모양(6절 오류 규약 결정 전이라 이 라우터만의 모양). 설계 · 상태 코드 · 충돌 차례는 [개념 학습 설계서 v0.1](../설계/개념학습-설계_v0.1.md) 5 · 7절 |

---

## 10. 다시 만드는 법

```bash
python scripts/api_scan.py                               # 요약 + 검사(미등록 ID · 중복 · 붙지 않은 라우터)
python scripts/api_scan.py --doc docs/인터페이스/API명세서_v0.1.md          # 표 셋을 다시 채운다
python scripts/api_scan.py --doc docs/인터페이스/API명세서_v0.1.md --check  # 뒤처졌는가만 (종료코드 1)
python scripts/api_scan.py --assign S64                  # 새 라우트에 ID (대장 파일을 고친다)
python -m pytest tests/test_api_scan.py                  # TC-AP 13건
```

정답 대조(선택 · 앱 코드가 크게 바뀔 때) — 도커 이미지 안에서 `python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" > openapi.json` 뒤
`python scripts/api_scan.py --openapi openapi.json`. 컨테이너는 `--network none` 으로 띄우고 서버는 띄우지 않는다.

---

## 11. 참조

- [RTM v1.0](../요구사항/RTM_v1.0.md) — 요구 ID 체계 · §5 B계열 29
- [분배안 v1.0 (옛 `#62`)](../github-archive/2026-09-21/이슈-062/00-기록.md) — 파트(제안) 칸의 근거 §3 · §4
- [ERD v1.1](../데이터/ERD_v1.1.md) · [데이터 사전 v1.1](../데이터/데이터사전_v1.1.md) — 수집 DB 표 · `data_cache`
- [IA v0.2](../화면/IA_v0.2.md) — 「화면」 칸의 view 키
- [테스트계획서 v1.2](../시험/테스트계획서_v1.2.md) — TC-A1 · TC-CD · TC-LT · TC-YH · 6.1절 DF-17(고침) · TC-AP · TC-DF17
- [ADR-0001](../ADR/ADR-0001-실거래-주문-경로-차단.md) — 실거래 차단 관문
- [결정 대장 v0.9](../계획서/논의결정대장_v0.9.md) — D3 ③ 권한 경계 · ⑥ 인증 구조 · ⑦ 죽은 것 정리
