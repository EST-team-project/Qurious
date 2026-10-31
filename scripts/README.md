# scripts — 도구 · 스캐너 · 일일 갱신

사람이나 예약 작업이 터미널에서 돌리는 파이썬 · 셸 도구입니다. 서버 코드(`app/`)나 수집기(`collector/`)가 아닙니다.

## 무엇이 들어 있나

| 종류 | 예 |
|---|---|
| 일일 갱신 · 여러 PC | `daily_update.py`(12:30 러너) · `run_lease.py`(어느 PC 가 돌리나) · `collect_worker.py` · `runner_bg.py` |
| 문서 · 코드 점검(스캐너) | `docs_scan.py` · `api_scan.py` · `rtm_scan.py` · `view_scan.py` · `schema_scan.py` · `post_check.py` |
| 수집 자료 올리기 · 맞추기 | `hf_sync.py` · `hf_dataset.py` · `hf_*.py` |
| 강사님 자료 · 학습 콘텐츠 | `lecture_scan.py` · `lectures_build.py` · `glossary_build.py` |
| 신호 · 일지 · 대사 | `signals_daily.py` · `paper_journal.py` · `daily_lean_reconcile.py` · `strategy_v2_*.py` |
| 증권사 연결 점검 | `kis_*_probe.py` · `verify_*.py` |
| `personal/` | **사람이 손으로 돌리는 PowerShell** — `start.ps1` · `stop.ps1` · `test.ps1` · `check.ps1` 등. 설명은 [personal/README.md](personal/README.md) |

도구마다 맨 위 설명과 `--help` 가 사용법입니다. 이 표는 대표 예일 뿐 전부가 아닙니다 (파일 목록: `git ls-files scripts`).

## 넣지 않는 것

- 앱이 import 하는 코드 — 앱 컨테이너에는 `scripts/` 가 없다 (판정 규칙은 도구 한 곳에 두고 앱은 도구가 쓴 기록을 읽기만 한다)
- 비밀값 · 키 — 환경 변수로만 받는다

## 지키는 약속

- **12:30 일일 갱신이 도는 동안(잠금 · `daily_update.py status` 로 확인) `scripts/` · `collector/` 를 고치지 않는다.** 러너 파일을 바꾸면 예약 작업이 쓰는 인터프리터로 진입점 스모크를 돌린다
- 수집 DB(`market.sqlite3`)를 이 PC 에서 열지 않는다 (`schema_scan --doc` 은 판을 올릴 때만, 읽기 전용으로)
- 스캐너 `--check` 는 줄 끝(CRLF · LF)을 접어서 비교한다
- Git Bash 에서 돌릴 파이썬 도구는 출력을 UTF-8 로 맞추고, 쓰는 도구는 `write_bytes` 로 줄 끝을 지킨다

## 관련 문서

[로컬 실행 안내서](../docs/phase-3/05-deployment/로컬실행안내서.md) · [폴더 지도](../docs/README.md) · [수집기](../collector/README.md)
