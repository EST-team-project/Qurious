# alembic — 앱 DB(PostgreSQL) 마이그레이션

앱 데이터베이스의 표 구조 변경 기록입니다. 수집 DB(SQLite)는 여기가 아니라 `collector/db.py` 의 `SCHEMA` 가 맡습니다.

## 무엇이 들어 있나

| 위치 | 역할 |
|---|---|
| `versions/` | 마이그레이션 파일 (차례대로 쌓인다 — 지우거나 고쳐 쓰지 않는다) |
| `env.py` · `script.py.mako` | 실행 환경 · 새 파일 틀 |
| `README` | alembic 기본 안내 한 줄 (확장자 없는 원래 파일) |

## 새 마이그레이션을 만들 때

1. 모델(`app/models/`)을 고친 뒤 일회용 DB 에서 `upgrade` → `alembic check`(차이 없음) → `downgrade` → `upgrade` 를 거치고 나서 `versions/` 에 둔다
2. 부분 고유 색인은 모델과 이전의 조건이 같아야 `ON CONFLICT` 가 맞는다
3. 새 표가 `users.id` 를 가리키면 같은 PR 에서 탈퇴 처리를 정하고 시험한다
4. 같은 시기에 다른 사람이 만든 마이그레이션과 `heads` 가 갈라지지 않는지 본다

## 알아 둘 것

- 개발 앱은 시작할 때 `upgrade head` 를 돌려 바로 적용한다. 마이그레이션이 든 PR 은 머지 전 브랜치에서 앱을 켜면 다른 갈래의 revision 을 못 찾는다는 경고가 남을 수 있다
- Dockerfile 이 앱 이미지에 이 폴더를 담는다(`COPY alembic/`)

## 관련 문서

[데이터 사전](../docs/phase-3/02-design/data/데이터사전.md) · [폴더 지도](../docs/README.md)
