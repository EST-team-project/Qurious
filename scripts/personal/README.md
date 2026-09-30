# scripts/personal — 내 PC 에서 직접 돌리는 스크립트

Qurious 를 **AI 도구 없이 혼자서** 로컬에서 띄우고, 기능이 도는지 확인하고, 끄는 PowerShell 스크립트 모음입니다.
팀 합의에 따라 **로컬에서 전체 기능을 먼저 확인하고, AWS 배포는 강사님 안내가 나온 뒤에** 합니다.

- 자세한 동작 원리 · 그림 · 문제 해결: [로컬 실행 안내서 v0.1](../../docs/배포/로컬실행안내서_v0.1.md)
- 여기 스크립트는 사람이 손으로 돌리는 것들입니다. `scripts/` 바로 아래의 파이썬 파일들은 문서 스캐너 ·
  일일 데이터 갱신처럼 도구 · 예약 작업이 돌리는 것들이라 따로 둡니다.

## 1. 준비물

| 무엇 | 왜 | 확인 |
|---|---|---|
| Docker Desktop | DB 셋(PostgreSQL · Redis · Neo4j)과 앱을 컨테이너로 띄운다 | `docker version` |
| PowerShell 5.1 이상 | 스크립트 실행 (Windows 기본 · PowerShell 7 이 없어도 된다) | `$PSVersionTable.PSVersion` |
| Python 3.12 + `pip install -r requirements-dev.txt` | `test.ps1` · `dev.ps1` 만 필요 (나머지는 도커만 있으면 된다) | `python --version` |

**실행 정책** — 처음 한 번, 스크립트 실행이 막혀 있으면(「이 시스템에서 스크립트를 실행할 수 없으므로…」):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # 내 계정에만 · 내 PC 에서 만든 스크립트는 실행 허용
# 또는 한 번만: powershell -ExecutionPolicy Bypass -File .\scripts\personal\start.ps1
```

## 2. 매일 쓰는 순서

저장소 폴더(`Qurious`)에서 PowerShell 을 열고:

```powershell
.\scripts\personal\start.ps1      # 1) 띄우기 — DB 먼저, 앱은 준비된 뒤에. 끝나면 브라우저가 열린다
.\scripts\personal\check.ps1      # 2) 기능 점검 — curl 처럼 API 56건을 차례로 불러 통과/실패 표 (30초 안팎)
.\scripts\personal\stop.ps1       # 3) 끄기 — 컨테이너만 지우고 DB 데이터는 남긴다
```

`git pull` 로 코드를 받은 뒤에도 그냥 `start.ps1` 을 돌리면 됩니다 — 코드가 이미지보다 새로우면 **이미지를 자동으로 다시 만듭니다**.

### 코드를 고치며 볼 때 — 개발 모드

```powershell
.\scripts\personal\start.ps1 -Dev                      # 코드 폴더를 컨테이너에 연결해 띄운다 (주소는 같다 · http://localhost:8966)
.\scripts\personal\logs.ps1 -Service app -Follow       # (선택) 다시 켜지는 모습 보기 — 「Reloading」 줄
```

| 무엇을 고쳤나 | 반영 | 걸리는 시간 |
|---|---|---|
| `app\*.py` (API · 서비스) | 앱(uvicorn `--reload`) · Celery(watchfiles)가 **스스로 다시 켜진다** | 몇 초 (워커 약 4초) |
| `public\` (화면 HTML · JS · CSS) | 다시 켤 것 없이 브라우저 **새로고침(F5)** | 즉시 |
| `requirements.txt` · `Dockerfile` | `start.ps1 -Dev` 를 다시 — 이미지를 다시 만든다 | 몇 분 |
| `alembic\versions\` (DB 마이그레이션) | 앱이 다시 켜질 때 적용된다(앱 시작 과정) | 몇 초 |

- 보통 모드로 돌아가기: `-Dev` 없이 `start.ps1` — 앱 · Celery 를 이미지 코드로 다시 만든다. DB 데이터는 그대로다.
- 원리: [`compose.dev.yml`](compose.dev.yml) 머리 주석 — Windows 폴더의 변화는 컨테이너에 알림이 안 가서 **폴링**(0.3초마다 훑기)으로 감시한다. 평소 CPU 는 컨테이너당 2% 안팎(2026-09-30 잼).
- `dev.ps1`(앱을 내 PC 파이썬으로)과의 차이: `-Dev` 는 **파이썬 패키지를 내 PC 에 설치할 필요가 없다**. 디버거를 붙이고 싶을 때만 `dev.ps1`.

## 3. 스크립트 목록

| 파일 | 하는 일 | 자주 쓰는 옵션 |
|---|---|---|
| `start.ps1` | 도커로 전체 실행: 사전 점검 → `.env` → 네트워크 → 충돌 점검 → DB 셋 준비 대기 → 앱 · Celery → 헬스 체크 → 브라우저 | `-Dev` 개발 모드(저장하면 자동 반영) · `-NoCelery` 가볍게 · `-Build` 이미지 강제 재빌드 · `-NoBrowser` |
| `compose.dev.yml` | 개발 모드 덧씌우기 — 코드 폴더 연결 · `--reload` (`start.ps1 -Dev` 가 쓴다 · 직접 실행하지 않음) | — |
| `check.ps1` | 기능 점검 (로그인 · **계정** · 시세 · 전략 · 로보 · 매매 · 연동 · 시스템) | `-Full` 느린 ML 셋 추가 · `-Write` 모의 매수 · 매도까지 · `-Group 계정` · `-ShowBody` · `-SaveReport` |
| `status.ps1` | 지금 무엇이 떠 있나 (컨테이너 · 앱 응답 · 이미지 신선도 · 수집 DB · 디스크) | `-Data` 일일 갱신 상세 |
| `logs.ps1` | 컨테이너 로그 | `-Service app` · `-Service celery-worker` · `-Follow` · `-Tail 200` |
| `stop.ps1` | 끄기 (데이터 유지) | `-Keep` 멈추기만 · `-DeleteData` DB 까지 삭제(확인 입력) |
| `test.ps1` | 자동 시험(pytest 약 250건) — 일회용 시험 DB 를 띄웠다 지운다 | `-Path tests\test_formula.py` · `-NoDb` |
| `dev.ps1` | 앱만 내 PC 파이썬으로(DB 는 도커) · 코드 저장 시 자동 재시작 — 패키지 설치가 필요해 보통은 `start.ps1 -Dev` 를 쓴다 | `-Port 8000` |
| `_common.ps1` | 위 스크립트들이 함께 쓰는 함수 (직접 실행하지 않음) | — |

각 스크립트의 자세한 설명은 PowerShell 도움말로도 볼 수 있습니다: `Get-Help .\scripts\personal\check.ps1 -Full`

## 4. 주소

| 무엇 | 주소 | 비고 |
|---|---|---|
| 화면 | http://localhost:8966 | 첫 화면은 로그인 — 회원가입 후 사용 |
| API 문서 | http://localhost:8966/docs | FastAPI 자동 문서 — API 를 눌러서 바로 불러 볼 수 있다 |
| Neo4j | http://localhost:17474 | `neo4j` / `finagent123` (docker-compose.yml 기본값) |
| 개발 모드 앱 | http://127.0.0.1:8000 | `dev.ps1` 로 띄웠을 때 |

## 5. 자주 막히는 곳

| 증상 | 원인 | 할 일 |
|---|---|---|
| 「Docker Desktop 이 꺼져 있습니다」 | 도커 엔진이 안 켜짐 | Docker Desktop 을 켜고 고래 아이콘이 멈춘 뒤 다시 |
| 「포트 15432 를 이미 … 가 쓰고 있습니다」 | 로컬에 설치된 PostgreSQL · 다른 도커 프로젝트 | 그 서비스를 끄거나 그 프로젝트를 `docker compose down` |
| 「컨테이너 이름 fin-ai-… 를 다른 프로젝트가 쓰고 있습니다」 | 강사님 원본 사본 등 같은 이름을 쓰는 스택 | 그 폴더에서 `docker compose down` |
| 화면에 고친 내용이 안 보인다 | 이미지가 옛 코드 | `start.ps1` 다시 (자동 재빌드) · 그래도면 `start.ps1 -Build` · 자주 고칠 때는 `start.ps1 -Dev` |
| 개발 모드인데 고친 게 안 보인다 | 화면 파일은 브라우저 캐시 · `.py` 는 다시 켜지는 중 | 화면은 새로고침(F5) · API 는 `logs.ps1 -Service app -Follow` 에서 「Application startup complete」 뒤 다시 요청 · 문법 오류면 그 로그에 오류 줄이 나오고 앱이 멈춰 있다 — 고쳐 저장하면 다시 켜진다 |
| 로그인한 채로 주소를 다시 열면 로그인 화면이 나온다 | (2026-09-30 고침) 예전 코드 — 첫 주소가 늘 로그인 화면으로 보냈다 | `git pull` 뒤 `start.ps1`(또는 `-Dev`) — 이제 세션이 살아 있으면 앱으로 간다 |
| 국내 일봉이 느리거나 「출처」 가 collector 가 아님 | 수집 DB(`data\collector\market.sqlite3`)가 없음 | 데이터 파트에 문의 — HF 비공개 데이터셋을 받아 `python scripts\hf_dataset.py restore --from <폴더> --into data\collector\market.sqlite3` |
| AI 채팅이 답하지 않는다 | Ollama 없음(설계상 동결 기능) | 쓰려면 Ollama 설치 후 `.env` 에 `OLLAMA_BASE_URL=http://host.docker.internal:11434` |
| `test.ps1` 이 「포트가 없습니다」 | Windows 가 포트 범위를 예약함 | `netsh interface ipv4 show excludedportrange protocol=tcp` 로 확인 · 후보 번호를 바꾼다 |
| 한글이 깨진다 | .ps1 을 BOM 없는 UTF-8 로 저장함 | 이 폴더 파일은 **UTF-8 BOM** 으로 저장한다(PowerShell 5.1 규칙) |

## 6. 디스크 정리

이미지(`qurious-*` 약 1.4GB · 넷이 층을 공유)는 다음 실행을 빠르게 하려고 `stop.ps1` 이 지우지 않습니다.

```powershell
docker compose down --rmi local        # 컨테이너 + 이 프로젝트가 만든 이미지 (DB 데이터는 남음)
docker compose down -v --rmi local     # 위 + DB 데이터까지 (처음 상태)
```

## 7. 이 폴더의 규칙 (스크립트를 고칠 때)

- **UTF-8 BOM** 으로 저장한다 — PowerShell 5.1 은 BOM 없는 파일을 cp949 로 읽어 한글이 깨진다.
- **PowerShell 5.1 문법**만 쓴다 — `&&` · `||` · `? :` · `??` 금지. 외부 프로그램 성패는 `$LASTEXITCODE` 로.
- 주석은 한국어로, **「무엇을」 보다 「왜」** 를 적는다. 스크립트 머리에는 도움말 블록(`<# .SYNOPSIS … #>`)을 둔다.
- 비밀 값(`.env` 내용 · 토큰)은 읽지도 찍지도 않는다. 있는지만 본다.
- 상태를 바꾸는 동작(데이터 삭제 등)은 옵션으로만, 지우는 것은 확인 입력을 받는다.
