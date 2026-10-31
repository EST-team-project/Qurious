# app — 서버 (FastAPI)

앱 컨테이너가 돌리는 서버 코드입니다. 화면 파일은 `public/`, 수집기는 `collector/` 에 있습니다.

## 무엇이 들어 있나

| 위치 | 역할 |
|---|---|
| `main.py` · `config.py` · `celery_app.py` | 앱 진입 · 설정 · 비동기 작업 진입 |
| `routes/` | HTTP 라우트 — 요청을 받아 `services/` 를 부르고 응답을 돌려준다 |
| `services/` | 업무 규칙 · 계산 · 외부 호출 (파일이 가장 많은 곳) |
| `models/` | 데이터베이스 표 정의 (SQLAlchemy) |
| `lib/` | 여러 곳이 같이 쓰는 부품 — 인증(`jwt_auth`) · 세션 · 캐시 · LLM 클라이언트 · 벡터 DB 문지기(`vector_db`) 등 |
| `tasks/` | Celery 작업 (동기화 · 수집 요청 · 모의계좌 스냅샷 등) |
| `database/` | PostgreSQL · Neo4j 연결 |

라우트 수·메서드·인증 분포는 `python scripts/api_scan.py --check` 가 코드에서 센다(2026-10-31 기준 라우트 285개). 손으로 적은 숫자를 믿지 말고 다시 센다.

## 넣지 않는 것

- 수집기 코드 — `collector/` (앱 컨테이너에는 수집기가 없다. Dockerfile 이 담는 것은 `app/ public/ prompts/ alembic/`)
- 화면 파일 — `public/`
- 비밀값 · `.env` 값 — 읽지도 찍지도 않는다

## 지키는 약속 (어기면 시험이나 스캐너가 멈춘다)

- 라우트를 더하거나 바꾸면 API 명세서와 카탈로그를 같이 맞춘다: `api_scan.py --assign <세션>` → `--catalog` → `--check`
- 벡터 DB 는 `app/lib/vector_db.py` 로만 부른다 (`QdrantClient(...)` 직접 호출 금지)
- 「현재가」 는 `app/services/quote_now.py` 한 곳에서만 만든다 (출처와 시각을 함께 · 「실시간」 낱말 금지)
- 그림자 일지 판 지문에 드는 함수(`get_quant_indicators` · `_generate_signal` 등)를 고치면 새 판으로 기록된다 — 화면 개선 때 건드리지 않는다
- 새 표가 `users.id` 를 가리키면 같은 PR 에서 탈퇴 처리를 정하고 시험한다
- 코드 식별자 · 출처 이름에 공급자 상표(야후 등)를 쓰지 않는다 (봉인 시험이 글자를 센다)

## 관련 문서

[API 명세서](../docs/phase-3/02-design/api/API명세서.md) · [데이터 사전](../docs/phase-3/02-design/data/데이터사전.md) · [시험 계획서](../docs/phase-3/04-testing/테스트계획서.md) · [폴더 지도](../docs/README.md)
