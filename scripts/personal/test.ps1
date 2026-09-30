<#
.SYNOPSIS
  자동 시험(pytest) 돌리기 — 일회용 시험 DB 를 띄워 DB 시험까지 전부 돌리고, 끝나면 지운다.

.DESCRIPTION
  check.ps1 이 「떠 있는 앱을 밖에서 두드려 보는」 점검이라면, 이것은 코드 안쪽을 재는 자동 시험이다
  (tests\ 폴더 · 지표 계산 · 비용 · 장부 불변식 · 계정 · 용어사전 · 문서 스캐너 등 · 2026-09-30 기준 367건 · 3분 안팎).

  순서
    1. 준비       파이썬 · pytest 가 있는가, 12:30 일일 갱신이 지금 도는 중인가(시험이 수집 DB 를 읽는다)
    2. 시험 DB    pgvector/pgvector:pg16 컨테이너를 빈 포트(후보 25432 · 35432 · 45432 · 55432)에
                  새로 띄운다(qurious-test-pg) — Windows 예약 포트 범위는 피해서 고른다
    3. 시험       python -m pytest (DB 주소는 QURIOUS_TEST_DATABASE_URL 로만 넘긴다)
    4. 치우기     시험 DB 컨테이너를 지우고, 바꾼 환경 변수를 원래대로 되돌린다

  ⚠️ 왜 일회용 DB 인가 — 모의 장부 시험(tests\test_paper_ledger_i14.py)은 그 DB 의 표 아홉 개를
     **지우고 다시 만든다.** 그래서 앱 개발 DB(15432 · fin_ai)는 절대 넘기지 않는다. 이 스크립트는
     그런 주소가 환경 변수에 들어 있으면 멈춘다.

.PARAMETER Path
  이 파일(들)만 시험한다. 예) -Path tests\test_rebalance.py

.PARAMETER NoDb
  시험 DB 를 띄우지 않는다. DB 가 필요한 시험(모의 장부 · 계정 · 용어사전 적재 — 2026-09-30 기준 18건)은 건너뛴다(도커 없이도 돈다).

.PARAMETER KeepDb
  끝나도 시험 DB 컨테이너를 남긴다(여러 번 연달아 돌릴 때 기동 시간을 아낀다).

.EXAMPLE
  .\scripts\personal\test.ps1
.EXAMPLE
  .\scripts\personal\test.ps1 -Path tests\test_formula.py -NoDb
#>
[CmdletBinding()]
param(
  [string[]]$Path = @(),
  [switch]$NoDb,
  [switch]$KeepDb
)

. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = 'Continue'

$TestDbName = 'qurious-test-pg'
# 시험 DB 포트 후보. 15432(앱 개발 DB)는 절대 쓰지 않는다. 고정 번호가 아니라 후보인 이유는
# Windows 가 부팅마다 예약하는 포트 범위를 피해야 해서다(_common.ps1 의 Find-QFreePort 설명).
# 시험 파일 머리말(tests\test_paper_ledger_i14.py)의 예시 55432 는 이 PC 에서 예약 범위 안이라 막혔다.
$TestDbPortCandidates = @(25432, 35432, 45432, 55432)

Write-QTitle 'Qurious 자동 시험 (pytest)'

# ------------------------------------------------------------------------------
# 1. 준비
# ------------------------------------------------------------------------------
Write-QStep '1/4 준비 — 파이썬 · pytest · 일일 갱신'
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-QFail 'python 이 없습니다 — Python 3.12 를 설치하고 pip install -r requirements-dev.txt'
  exit 1
}
$null = & python -c "import pytest" 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-QFail 'pytest 가 없습니다 — pip install -r requirements-dev.txt'
  exit 1
}
$pyVer = & python --version
Write-QOk "$pyVer · pytest 있음"

# 12:30 일일 갱신이 수집 DB 를 다시 쓰는 중이면, 그 DB 를 읽는 시험이 흔들린다 → 끝난 뒤에 돌린다.
$lock = Join-Path $QRoot 'data\collector\state\daily_update.lock'
if (Test-Path $lock) {
  $held = $null
  try { $held = Get-Content $lock -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
  if ($held -and (Get-Process -Id ([int]$held.pid) -ErrorAction SilentlyContinue)) {
    Write-QFail "일일 갱신이 지금 도는 중입니다 (PID $($held.pid)) — 끝난 뒤 다시 돌리세요. (status.ps1 로 확인)"
    exit 1
  }
}
Write-QOk '일일 갱신: 도는 중 아님'

# 환경 변수를 잠깐 바꾸고 끝에서 되돌린다 — 이 스크립트가 끝난 뒤 같은 창에 흔적을 남기지 않으려고.
#   PYTHONIOENCODING : 비우고 돌린다. 시험 가운데 cp949 콘솔에서의 출력을 재는 것이 있어,
#                      이 값이 utf-8 로 잡혀 있으면 사용자 콘솔과 다른 조건이 된다.
#   QURIOUS_TEST_DATABASE_URL : 시험 DB 주소. 이것만 DB 시험을 켠다.
$saved = @{
  PYTHONIOENCODING          = $env:PYTHONIOENCODING
  QURIOUS_TEST_DATABASE_URL = $env:QURIOUS_TEST_DATABASE_URL
}
if ($env:QURIOUS_TEST_DATABASE_URL -and ($env:QURIOUS_TEST_DATABASE_URL -match ':15432/' -or $env:QURIOUS_TEST_DATABASE_URL -match '/fin_ai')) {
  Write-QFail "환경 변수 QURIOUS_TEST_DATABASE_URL 이 앱 개발 DB 를 가리킵니다 — 시험이 그 DB 의 표를 지웁니다. 먼저 비우세요:"
  Write-QInfo 'Remove-Item Env:QURIOUS_TEST_DATABASE_URL'
  exit 1
}

$exitCode = 1
try {
  # ----------------------------------------------------------------------------
  # 2. 시험 DB
  # ----------------------------------------------------------------------------
  if ($NoDb) {
    Write-QStep '2/4 시험 DB — 건너뜀 (-NoDb · DB 가 필요한 시험은 skipped 로 나온다)'
    Remove-Item Env:QURIOUS_TEST_DATABASE_URL -ErrorAction SilentlyContinue
  } else {
    Write-QStep "2/4 시험 DB — $TestDbName (일회용 · 끝나면 지운다)"
    if (-not (Test-QDocker)) { Write-QInfo '도커 없이 돌리려면 -NoDb'; exit 1 }
    $st = Get-QContainerState $TestDbName
    if ($st.State -eq 'running') {
      # -KeepDb 로 남겨 둔 시험 DB 를 다시 쓴다 — 도커에게 그 컨테이너가 연 호스트 포트를 묻는다.
      $mapped = & docker port $TestDbName 5432/tcp
      $TestDbPort = [int](("$(@($mapped)[0])" -split ':')[-1])
    } else {
      if ($st.State -ne 'missing') { $null = & docker rm -f $TestDbName }
      $TestDbPort = Find-QFreePort $TestDbPortCandidates
      if ($TestDbPort -eq 0) {
        Write-QFail ("시험 DB 에 쓸 포트가 없습니다 (후보 {0} 모두 예약 · 사용 중)." -f ($TestDbPortCandidates -join ', '))
        exit 1
      }
      # pgvector 이미지는 벡터 확장이 든 PostgreSQL 16 이다(앱 모델이 pgvector 형식을 쓸 수 있어 같은 계열로 맞춘다).
      # 이미지가 없으면 도커가 먼저 받는다(약 600MB · 한 번만).
      $null = & docker run -d --name $TestDbName -e POSTGRES_PASSWORD=test -p "${TestDbPort}:5432" pgvector/pgvector:pg16
      if ($LASTEXITCODE -ne 0) { Write-QFail '시험 DB 컨테이너를 띄우지 못했습니다.'; exit 1 }
    }
    $TestDbUrl = "postgresql+asyncpg://postgres:test@localhost:$TestDbPort/postgres"
    Write-QInfo "포트 $TestDbPort — 접속을 받을 준비가 될 때까지 기다립니다"
    # 컨테이너 안의 pg_isready 로 「접속을 받을 준비」 를 확인한다(켜진 직후엔 초기화 중이라 거절한다).
    $deadline = (Get-Date).AddSeconds(60)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
      $null = & docker exec $TestDbName pg_isready -U postgres 2>&1
      if ($LASTEXITCODE -eq 0) { $ready = $true; break }
      Start-Sleep -Seconds 1
    }
    if (-not $ready) { Write-QFail '시험 DB 가 60초 안에 준비되지 않았습니다.'; exit 1 }
    # pg_isready 가 통과해도 첫 기동의 초기화 스크립트가 한 번 재시작하는 짧은 틈이 있다 → 2초 여유.
    Start-Sleep -Seconds 2
    $env:QURIOUS_TEST_DATABASE_URL = $TestDbUrl
    Write-QOk "시험 DB 준비됨 — $TestDbUrl"
  }

  # ----------------------------------------------------------------------------
  # 3. 시험
  # ----------------------------------------------------------------------------
  Write-QStep '3/4 시험 — python -m pytest (3분 안팎 · 끝에 「N passed」 요약 줄)'
  Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
  # -p no:cacheprovider : .pytest_cache 폴더를 만들지 않는다(저장소를 더럽히지 않게).
  # pytest.ini 에 -q 가 이미 있다 — 여기서 또 붙이면 요약 줄이 사라진다.
  $pytestArgs = @('-m', 'pytest', '-p', 'no:cacheprovider') + $Path
  Push-Location $QRoot
  try {
    & python @pytestArgs
    $exitCode = $LASTEXITCODE
  } finally {
    Pop-Location
  }
} finally {
  # ----------------------------------------------------------------------------
  # 4. 치우기 — 중간에 Ctrl+C 로 멈춰도 여기는 돈다(try/finally)
  # ----------------------------------------------------------------------------
  Write-QStep '4/4 치우기'
  foreach ($k in $saved.Keys) {
    if ($null -eq $saved[$k]) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
    else { Set-Item "Env:$k" $saved[$k] }
  }
  if (-not $NoDb -and -not $KeepDb) {
    $null = & docker rm -f $TestDbName 2>&1
    Write-QOk "시험 DB 컨테이너($TestDbName)를 지웠습니다"
  } elseif ($KeepDb) {
    Write-QInfo "시험 DB 를 남겼습니다 — 지우기: docker rm -f $TestDbName"
  }
}

if ($exitCode -eq 0) { Write-QOk '시험 전부 통과' } else { Write-QFail "실패한 시험이 있습니다 (pytest 종료 코드 $exitCode) — 위 FAILED 줄을 보세요." }
exit $exitCode
