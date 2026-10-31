# tools — 영상 · 발표 자료 만들기 도구

서비스 코드가 아니라 발표 · 시연 자료를 만드는 도구입니다.

## 무엇이 들어 있나

| 위치 | 역할 |
|---|---|
| `demo/record_demo.py` | 장면 파일(YAML)을 읽어 앱 화면을 녹화한다 |
| `demo/export_mp4.py` | 녹화본을 mp4 로 내보낸다 |
| `demo/upload_hf.py` | 녹화 원본을 HF 비공개 저장소에 올린다 (비공개 확인 뒤) |
| `demo/help_videos.py` | 녹화 결과를 앱이 내보내는 로컬 폴더(`data/help/`)로 옮기고 영상 표(`videos.json`)를 만든다 (`build` · `pull` · `status`) |
| `deck/bundle_deck.py` | 발표 자료 HTML 을 그림 · 영상 · 글꼴까지 담은 한 파일로 묶는다 |
| `deck/render_mermaid.py` | 발표 그림 초안(Mermaid `.mmd`)을 SVG 로 굳힌다 |
| `deck/svg_check.py` | 손으로 쓴 완성 그림(SVG)의 글자 넘침을 재고 PNG 로 굽는다 |

## 약속

- 장면 파일이 정본이다. 화면이 바뀌면 그 장면만 다시 찍는다
- 녹화 중에는 `app/` · `public/` 을 고치지 않고 `git pull` 도 하지 않는다 (개발 앱이 다시 떠서 장면이 끊긴다). 12:30 갱신이 끝난 뒤에 찍는다
- 관리자 화면 장면은 계정을 환경 변수 `DEMO_EMAIL` · `DEMO_PASSWORD` 로만 받는다 (파일에 쓰지 않는다)
- 녹화 「성공 · 콘솔 오류 0」 은 자막이 맞다는 뜻이 아니다 — 장면 사진을 눈으로 본다
- 메뉴 같은 공용 화면을 바꾸면 그 화면이 나오는 영상을 모두 다시 찍는다

## 관련 문서

[폴더 지도](../docs/README.md) (영상 · 발표 자료 위치) · [UI 명세서](../docs/phase-3/02-design/ui/UI명세서.md)
