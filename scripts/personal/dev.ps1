<#
.SYNOPSIS
  개발 모드 — DB 는 도커로, 앱은 내 PC 의 파이썬으로 바로 띄운다. 코드를 저장하면 앱이 스스로 다시 켜진다.

.DESCRIPTION
  start.ps1(전부 도커)과의 차이
    start.ps1  앱도 컨테이너 — 이미지를 만든 순간의 코드로 돈다. 팀원 모두 같은 환경. 확인 · 시연용.
    dev.ps1    앱은 호스트 파이썬 — 파일을 저장하면 uvicorn --reload 가 앱을 스스로 다시 띄운다
               (시작 과정을 다시 돌아 몇 초 걸린다). 고치며 볼 때 · 디버거를 붙일 때.
    start.ps1 -Dev  앱은 컨테이너 그대로, 코드 폴더만 연결해 저장하면 자동 반영 — **호스트에 파이썬
               패키지가 없어도 된다**. 고치며 볼 때는 보통 이쪽이 쉽다(compose.dev.yml 머리 주석).

  하는 일
    1. postgres · redis · neo4j · qdrant 를 도커로 띄우고 준비를 기다린다(start.ps1 과 같은 함수)
    2. 앱 컨테이너(fin-ai-app)가 떠 있으면 멈춘다 — 두 앱이 함께 돌면 앱 안의 시세 동기화 스케줄러가
       두 벌 돌아 외부 시세 호출이 두 배가 되고, 어느 쪽 화면을 보는지 헷갈린다
    3. 환경 변수를 이 창에서만 잠깐 바꾼다 — DB 주소를 컨테이너 이름(postgres:5432)이 아니라
       호스트 포트(localhost:15432)로. 설정 파일은 도커와 같은 .env 를 읽게 한다(ENV_FILE)
    4. python -m uvicorn app.main:app --reload 를 이 창에서 돌린다 — 끝내려면 Ctrl+C
    5. 끝나면 바꾼 환경 변수를 되돌린다

  알아 둘 것
    - Celery 워커 · 비트 컨테이너는 그대로 돈다. 그 둘은 **이미지 안의 코드**로 돈다 — 예약 작업
      (자동매매 · 리밸런싱) 코드를 고쳤다면 그 확인은 start.ps1(이미지 다시 만듦)로 한다.
    - 앱은 켜질 때 DB 마이그레이션을 적용한다(도커 앱과 같은 DB 라 한쪽만 적용하면 된다).

.PARAMETER Port
  앱을 열 호스트 포트. 기본 8000 → http://127.0.0.1:8000

.PARAMETER NoReload
  코드 저장 때 다시 켜기를 끈다(조금 가볍다).

.EXAMPLE
  .\scripts\personal\dev.ps1
  다른 창에서 점검: .\scripts\personal\check.ps1 -BaseUrl http://127.0.0.1:8000
#>
[CmdletBinding()]
param(
  [int]$Port = 8000,
  [switch]$NoReload
)

. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = 'Continue'

Write-QTitle 'Qurious 개발 모드 (앱은 호스트 파이썬)'

# ------------------------------------------------------------------------------
# 1. 준비 — 도커 · 파이썬 · 앱 의존 패키지
# ------------------------------------------------------------------------------
Write-QStep '1/4 준비'
if (-not (Test-QDocker)) { exit 1 }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-QFail 'python 이 없습니다 — Python 3.12 를 설치하고 pip install -r requirements.txt'
  exit 1
}
# requirements.txt 전체를 설치 목록과 대조한다(도우미: _requirements_check.py).
# 도커 앱은 이미지 안에 전부 설치돼 있지만, 호스트 파이썬은 사람마다 다르다 — 이 PC 도 처음엔
# neo4j · qdrant-client 등 5개가 빠져 앱이 import 단계에서 멈췄다.
$reqOut = & python (Join-Path $PSScriptRoot '_requirements_check.py') 2>&1
if ($LASTEXITCODE -ne 0) {
  $missing = ("$reqOut" -replace '^.*MISSING\s*', '')
  Write-QFail "앱 패키지가 빠져 있습니다: $missing"
  Write-QInfo '설치: pip install -r requirements-dev.txt'
  Write-QInfo '공용 파이썬(anaconda 기본 환경 등)이면 다른 프로젝트 패키지와 부딪힐 수 있어 가상환경을 권합니다:'
  Write-QInfo '  python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements-dev.txt'
  Write-QInfo '설치 없이 「저장하면 자동 반영」 만 필요하면: .\scripts\personal\start.ps1 -Dev (앱은 컨테이너 · 코드 폴더 연결)'
  exit 1
}
$owner = Get-QPortOwner $Port
if ($owner) { Write-QFail "포트 $Port 를 이미 '$owner' 가 쓰고 있습니다 — -Port 로 다른 번호를 주세요."; exit 1 }
Write-QOk "$(& python --version) · 앱 패키지 있음 · 포트 $Port 비어 있음"

# ------------------------------------------------------------------------------
# 2. 저장소 · 앱 컨테이너
# ------------------------------------------------------------------------------
Write-QStep '2/4 저장소 — postgres · redis · neo4j · qdrant'
$null = & docker network inspect shared-net 2>&1
if ($LASTEXITCODE -ne 0) { $null = & docker network create shared-net }
if (-not (Start-QInfra)) { exit 1 }
$app = Get-QContainerState 'fin-ai-app'
if ($app.State -eq 'running') {
  Write-QWarn '앱 컨테이너(fin-ai-app)를 멈춥니다 — 호스트 앱과 함께 돌면 시세 동기화가 두 벌이 됩니다. (다시 켜기: start.ps1)'
  $null = Invoke-QCompose @('stop', 'app')
}

# ------------------------------------------------------------------------------
# 3. 환경 변수 — 이 창에서만, 끝에서 되돌린다
# ------------------------------------------------------------------------------
Write-QStep '3/4 환경 변수 (이 창에서만)'
# 설정 파일: 도커 앱과 같은 .env 를 읽게 한다. 앱(app/config.py)은 ENV_FILE 이 없으면 .env.dev 를 읽는다.
$envFile = '.env'
if (-not (Test-Path (Join-Path $QRoot '.env'))) { $envFile = '.env.dev' }
$overrides = [ordered]@{
  ENV_FILE       = $envFile
  # 컨테이너끼리는 서비스 이름(postgres:5432)으로 부르지만, 호스트에서는 compose 가 연 포트로 부른다.
  DATABASE_URL   = 'postgresql+asyncpg://fin_user:fin_pass@localhost:15432/fin_ai'
  REDIS_URL      = 'redis://localhost:16379'
  NEO4J_URI      = 'bolt://localhost:7687'
  NEO4J_USER     = 'neo4j'
  NEO4J_PASSWORD = 'finagent123'
  QDRANT_URL     = 'http://localhost:16333'   # 호스트에서 돌 때는 compose 가 연 호스트 포트로
}
$saved = @{}
foreach ($k in $overrides.Keys) {
  $saved[$k] = [Environment]::GetEnvironmentVariable($k, 'Process')
  Set-Item "Env:$k" $overrides[$k]
  if ($k -match 'PASSWORD') { Write-QInfo "$k = (가림)" } else { Write-QInfo "$k = $($overrides[$k])" }
}

# ------------------------------------------------------------------------------
# 4. 앱 실행 — Ctrl+C 로 끝내면 finally 에서 환경 변수를 되돌린다
# ------------------------------------------------------------------------------
Write-QStep "4/4 앱 — http://127.0.0.1:$Port  (끝내려면 Ctrl+C)"
# --reload-dir app : app 폴더의 .py 가 바뀔 때만 다시 켠다(data 폴더의 큰 DB 파일 변화는 무시).
#                    화면 파일(public\)은 요청마다 디스크에서 읽으므로 다시 켤 필요가 없다.
$uvArgs = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port")
if (-not $NoReload) { $uvArgs += @('--reload', '--reload-dir', 'app') }
Push-Location $QRoot
try {
  & python @uvArgs
} finally {
  Pop-Location
  foreach ($k in $saved.Keys) {
    if ($null -eq $saved[$k]) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
    else { Set-Item "Env:$k" $saved[$k] }
  }
  Write-Host ''
  Write-QInfo '개발 모드를 끝냈습니다(환경 변수 되돌림). 도커 앱으로 돌아가려면: .\scripts\personal\start.ps1'
}
