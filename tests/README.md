# tests — 자동 시험

pytest 시험과 브라우저 손 시험이 있습니다. 설정은 루트 `pytest.ini` 입니다 (`testpaths = tests` · `python_files = test_*.py`).

## 무엇이 들어 있나

| 위치 | 역할 |
|---|---|
| `test_*.py` (직속) | 서버 · 도구 · 문서 검사 시험. 파일 하나가 시험 묶음 하나다 |
| `e2e/` | 브라우저(Playwright)로 화면을 직접 눌러 보는 손 시험. 이름이 `test_` 로 시작하지 않아 pytest 가 자동으로 모으지 않는다 |
| `fixtures/` | 시험이 쓰는 고정 자료 — 수집 기록 견본 · 휴장일 표 · 법령 견본 · 번역 견본 · 옛 러너 코드의 얼린 사본 |

## 어떻게 돌리나

- 결과서로 치는 전체 시험은 `.\scripts\personal\test.ps1` (일회용 시험 DB 를 띄운다). 그냥 `python -m pytest` 는 DB 가 필요한 시험을 건너뛴다
- 오래 걸리는 전체 시험은 `test.ps1 -Split -Detach` 로 세션 밖에서 돌리고 `data/local-run/test/<시각>/run.json` 을 읽는다
- pytest 에 `-q` 를 더하지 않는다 (`pytest.ini` 에 이미 있어 둘이면 요약 줄이 사라진다)

## 이름 규칙

- 시험 번호는 파일의 접두를 잇는다 (`test_robo_profile.py` → `TC-RP-05`). 새 접두를 지을 때는 시험-요구 대장에서 비어 있는지 먼저 본다
- 묶음 하나 = 파일 하나. 새 시험 파일은 같은 PR 에서 시험-요구 대장에 올린다 (`rtm_scan.py --check` 가 멈춘다)

## 시험이 하지 않는 것

- 이 PC 의 실제 수집 DB · 진짜 예약 작업 · 앱 컨테이너를 건드리지 않는다. 수집 DB 를 읽는 함수를 시험하면 `COLLECTOR_DB_PATH` 를 없는 경로로 돌리는 장치를 붙인다
- 실제 외부 원격(HF 등)에 닿지 않는다 (`conftest.py` 가 막는다)
- 시험 속 가짜 키는 이어 붙여 만든다 (한 덩어리면 비밀값 검사에 걸린다)

## 관련 문서

[시험 계획서](../docs/phase-3/04-testing/테스트계획서.md) · [RTM](../docs/phase-3/01-analysis/requirements/RTM.md) (요구 ↔ 시험 대응) · [폴더 지도](../docs/README.md)
