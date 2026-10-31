# prompts — AI 에이전트 지침 글 (마크다운 3개)

| 파일 | 내용 |
|---|---|
| `system.md` | 에이전트의 기본 역할 · 언어(한국어로만 답한다) |
| `refusal_policy.md` | 거절해야 하는 경우의 정책 |
| `answer_format.md` | 답변 형식 |

## 알아 둘 것

- Dockerfile 이 이 폴더를 앱 이미지에 담는다 (`COPY prompts/ ./prompts/`). 앱 컨테이너 안에서는 `app/ public/ prompts/ alembic/` 만 보인다
- **이 파일들을 이름으로 읽는 코드를 이 README 를 쓰면서 찾지 못했다** (`app/` · `scripts/` · `tests/` 에서 `system.md` · `refusal_policy` · `answer_format` 검색 결과 없음). 지금 쓰이는 지침인지, 옛 자료인지는 확인이 필요하다 — 고치기 전에 사용처부터 확인하고, 안 쓰이면 이 README 와 파일에 그렇다고 적는다
- 사용자 입력 · 비밀값을 이 글에 넣지 않는다

## 관련 문서

[폴더 지도](../docs/README.md)
