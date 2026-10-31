# public — 화면 파일 (프런트)

브라우저가 받는 파일입니다. 번들러 없이 HTML · CSS · JavaScript(ES 모듈)를 그대로 내려줍니다.

## 무엇이 들어 있나

| 위치 | 역할 |
|---|---|
| `app.html` | 로그인 뒤 앱 본체 (모든 화면이 이 한 쪽 안에서 바뀐다) |
| `index.html` · `login.html` · `register.html` · `terms.html` · `privacy.html` | 첫 화면 · 로그인 · 가입 · 약관 · 개인정보 처리방침 |
| `js/` | 화면별 스크립트 |
| `css/` | 스타일 (색 · 간격은 앱 CSS 변수) |
| `learn/` | 개념 학습 콘텐츠 |
| `lectures/` | 강의 자료 화면 (`catalog.json` · `curriculum` · `days`) |
| `api-docs/` | API 문서 화면 (우리 목록 + 고른 API 하나만 Swagger UI) |

## 넣지 않는 것

- 서버가 계산하는 숫자의 복사본 — 경계 · 기간 숫자는 응답에서 읽고 화면 코드에 다시 적지 않는다
- 비밀값 · 계정 · 저장소 경로 · DB 이름 같은 개발 티 나는 글 (공개 저장소이고 사용자 화면이다)

## 지키는 약속

- `app.html` 에는 자동 서식을 돌리지 않는다
- `js/` 맨 위 함수 이름은 파일마다 다르게 짓는다 — 화면 구조 스캐너(`scripts/view_scan.py`)가 함수를 이름으로 잇는다. 새 CSS 클래스 · 함수 이름은 넣기 전에 `public/css` · `public/js` 에서 먼저 찾는다
- 화면 진입 훅은 화면 키를 글자 그대로 쓴다 (`if (view === "키")`)
- 화면은 Figma 에서 먼저 설계하고 만든다. 만든 뒤에는 모든 버튼 · 카드를 한 번씩 누르고 1280 · 1024 · 900 · 390 폭을 본다
- 화면 글은 자르지 않는다 (메뉴 · 단추 글이 폭마다 잘리는지 `tests/e2e/gnb_widths.py` 가 잰다)
- 같은 주소를 다시 열 때 브라우저 캐시를 의심한다

## 관련 문서

[UI 명세서](../docs/phase-3/02-design/ui/UI명세서.md) · [화면 설계 절차](../docs/phase-3/02-design/ui/화면설계절차.md) · [폴더 지도](../docs/README.md)
