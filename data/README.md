# data — 커밋되는 자료와 로컬 자료

이 저장소는 **공개**입니다. 이 폴더에서 git 에 올라가는 것은 아래 둘뿐이고, 나머지는 각 PC 의 로컬 자료입니다.

## git 에 올라가는 것

| 위치 | 무엇 |
|---|---|
| `lean-workflows/` | LEAN 백테스트 대사 결과 — `workflow-*` 폴더(실행 한 번당 한 폴더) · `daily_replay_<날짜>.json` · 검증 보고서. `scripts/daily_lean_reconcile.py` 가 쓰고 `app/config.py` 가 위치를 안다 |
| `manifest.json` | 문서 목록(`doc_id` · `doc_type` · `effective_date` …) 형식의 JSON. `manifest.json` 이라는 이름을 읽는 코드는 있으나(`app/services/data_guide.py` · `data_status.py` 등) 이 파일을 읽는지는 확인하지 못했다 — 바꾸기 전에 `grep -rn manifest.json app scripts` 로 사용처부터 본다 |

## git 에 올라가지 않는 것 (`.gitignore`)

`collector/`(수집 DB · 상태 파일) · `hf_export/` · `local-run/`(시험 결과 · 점검 기록) · `paper_journal/`(그림자 일지 내보내기) · `app.db` · `vectors-cache.json` 등. 이 PC 에서 만들어지는 자료라 PC 마다 날짜가 다를 수 있습니다 (`python scripts/hf_sync.py status` 로 원격과 견준다).

## 약속

- **원자료 · 수집 DB · 일지 내보내기를 커밋하지 않는다.** 이용 조건이 재배포를 막는 자료가 있고, 일지 원본은 HF 비공개에 있다
- 수집 DB 는 이 PC 에서 열지 않는다 (앱이 읽기 전용으로 붙인 WAL DB 라 마지막 연결을 닫으면 앱이 멈출 수 있다). 칸은 데이터 사전으로 본다
- 새 파일을 이 폴더에 두기 전에 `git check-ignore -v <경로>` 로 무시 규칙이 덮는지 본다

## 관련 문서

[데이터 사전](../docs/phase-3/02-design/data/데이터사전.md) · [수집기](../collector/README.md) · [폴더 지도](../docs/README.md)
