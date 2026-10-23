<#
.SYNOPSIS
  자동 시험(pytest) 돌리기 — 일회용 시험 DB 를 띄워 DB 시험까지 전부 돌리고, 끝나면 지운다.

.DESCRIPTION
  check.ps1 이 「떠 있는 앱을 밖에서 두드려 보는」 점검이라면, 이것은 코드 안쪽을 재는 자동 시험이다
  (tests\ 폴더 · 지표 계산 · 비용 · 장부 불변식 · 계정 · 용어사전 · 문서 스캐너 등 · 2026-10-21 기준 173파일 · 2,365건 · 10분 안팎).

  순서
    1. 준비       파이썬 · pytest 가 있는가, 12:30 일일 갱신이 지금 도는 중인가(시험이 수집 DB 를 읽는다)
    2. 시험 DB    pgvector/pgvector:pg16 컨테이너를 빈 포트(후보 25432 · 35432 · 45432 · 55432)에
                  새로 띄운다(qurious-test-pg) — Windows 예약 포트 범위는 피해서 고른다
    3. 시험       python -m pytest (DB 주소는 QURIOUS_TEST_DATABASE_URL 로만 넘긴다)
    4. 치우기     시험 DB 컨테이너를 지우고, 바꾼 환경 변수를 원래대로 되돌린다

  ⚠️ 왜 일회용 DB 인가 — 모의 장부 시험(tests\test_paper_ledger_i14.py)은 그 DB 의 표 아홉 개를
     **지우고 다시 만든다.** 그래서 앱 개발 DB(15432 · fin_ai)는 절대 넘기지 않는다. 이 스크립트는
     그런 주소가 환경 변수에 들어 있으면 멈춘다.

  묶음 차례 실행(2026-10-21 · -Split · -Group) — 시험 파일을 묶음(화면 · 데이터 · 지식 · 매매 · 분석 · 나머지)으로
  나눠 **묶음마다 새 pytest 프로세스**로 돈다. 한 프로세스가 2,000건 넘게 안고 가며 메모리가 쌓이지 않게
  하려는 것이다(범위는 인자 없는 실행과 같다). 묶음 표는 _test_groups.py 한 곳에 있다.
  결과는 data\local-run\test\<시각>\ 에 남는다 — 묶음마다 JUnit XML(ui.xml …)과, 묶음이 끝날 때마다
  한 줄씩 쌓는 run.json(상태 · 묶음별 통과 · 실패 · 건너뜀 · 초 · 종료 코드). 끊겨도 끝난 묶음은 남는다.

  컨테이너 묶음(2026-10-23 · 컨테이너(ctr) · 맨 끝) — RAG · 채팅 · 올린 문서 격리 시험 셋은 호스트 파이썬에
  qdrant-client · langchain-qdrant · langchain-ollama · langgraph 가 없어 통째로 건너뛰어진다. 묶음 실행에서는 이 셋을
  앱 이미지(qurious-app:latest) 일회용 컨테이너에서 돈다 — 저장소는 읽기 전용(/w:ro)으로 붙이고, 결과 XML 만 결과
  폴더(/out)에 쓰고, pytest 는 호스트와 같은 판을 컨테이너 안에만 깐다(호스트에는 아무것도 깔지 않는다).
  Docker 가 꺼졌거나 이미지 · 네트워크가 없으면 실패가 아니라 「건너뜀」 과 까닭을 run.json(skipped_reason)에 남긴다.
  인자 없는 실행 · -Path 는 지금처럼 호스트에서만 돈다(그 셋은 건너뜀).

.PARAMETER Path
  이 파일(들)만 시험한다. 예) -Path tests\test_rebalance.py

.PARAMETER NoDb
  시험 DB 를 띄우지 않는다. DB 가 필요한 시험(모의 장부 · 계정 · 용어사전 적재 — 2026-09-30 기준 18건)은 건너뛴다(도커 없이도 돈다).

.PARAMETER KeepDb
  끝나도 시험 DB 컨테이너를 남긴다(여러 번 연달아 돌릴 때 기동 시간을 아낀다).

.PARAMETER Split
  모든 묶음을 차례로 돈다(묶음마다 새 pytest 프로세스 · 범위는 인자 없는 실행과 같다).

.PARAMETER Group
  이 묶음만 차례로 돈다. 이름이나 영어 열쇠 — 화면(ui) · 데이터(data) · 지식(kb) · 매매(trade) · 분석(analysis) · 나머지(rest)
  · 컨테이너(ctr — 앱 이미지 일회용 컨테이너).
  여럿은 쉼표로. Git Bash 에서 부를 때는 한글 대신 영어 열쇠를 쓴다(인자가 깨질 수 있다).

.PARAMETER Resume
  마지막 결과 폴더(또는 -RunDir)의 run.json 에서 종료 코드 0 으로 끝난 묶음은 건너뛰고 나머지부터 돈다.

.PARAMETER LastFailed
  지난 실행에서 실패한 시험만 다시 돈다(pytest --lf · 캐시는 data\local-run\test\cache). 지난 실패가 없으면 아무것도 돌지 않고 통과.

.PARAMETER Detach
  세션 밖에서 돈다 — 같은 인자로 자기 자신을 숨은 창으로 다시 띄우고 바로 끝난다. 다 됐는지는 결과 폴더의
  run.json(status 가 done)으로 본다. 화면 출력은 같은 폴더 test.log.

.PARAMETER RunDir
  결과 폴더. 보통 비운다(새로 만든다) — -Detach 가 띄운 쪽에 넘겨줄 때 · -Resume 으로 특정 폴더를 이어 갈 때 쓴다.

.EXAMPLE
  .\scripts\personal\test.ps1
.EXAMPLE
  .\scripts\personal\test.ps1 -Path tests\test_formula.py -NoDb
.EXAMPLE
  .\scripts\personal\test.ps1 -Split -Detach        # 전체를 묶음 차례로 · 세션 밖에서
.EXAMPLE
  .\scripts\personal\test.ps1 -Group ui,kb          # 화면 · 지식 묶음만
.EXAMPLE
  .\scripts\personal\test.ps1 -Group ctr -NoDb      # RAG · 채팅 · 올린 문서 격리 셋만 앱 이미지 컨테이너로
.EXAMPLE
  .\scripts\personal\test.ps1 -Resume               # 끊긴 묶음 실행을 이어서
.EXAMPLE
  .\scripts\personal\test.ps1 -LastFailed           # 지난번 실패한 시험만
#>
[CmdletBinding()]
param(
  [string[]]$Path = @(),
  [switch]$NoDb,
  [switch]$KeepDb,
  [switch]$Split,
  [string[]]$Group = @(),
  [switch]$Resume,
  [switch]$LastFailed,
  [switch]$Detach,
  [string]$RunDir = ''
)

. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = 'Continue'

# 결과 폴더 · pytest 캐시 · 잠금 — data\local-run\ 은 .gitignore 대상이라 저장소를 더럽히지 않는다.
$TestRunRoot  = Join-Path $QRoot 'data\local-run\test'
$TestCacheRel = 'data/local-run/test/cache'          # pytest 가 저장소 뿌리(rootdir) 기준으로 읽는다
$TestLock     = Join-Path $TestRunRoot 'test.lock'
# -File 로 넘어온 「ui,kb」 는 배열이 아니라 글자 하나다 → 쉼표로 나눈다(직접 부를 때와 같게).
$Group = @($Group | ForEach-Object { "$_" -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$Grouped = $Split -or ($Group.Count -gt 0) -or $Resume

function Get-QNow { (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz') }

# run.json 은 BOM 없는 UTF-8 로 쓴다 — 파이썬 json.load 가 BOM 에서 멈추지 않게.
function Save-QRunJson([string]$dir, $state) {
  $json = $state | ConvertTo-Json -Depth 6
  [IO.File]::WriteAllText((Join-Path $dir 'run.json'), $json, (New-Object Text.UTF8Encoding $false))
}

# pytest JUnit XML 에서 수를 읽는다(통과 = 전체 − 실패 − 오류 − 건너뜀). 파일이 없으면 0 들.
function Read-QJunit([string]$file) {
  $r = [ordered]@{ tests = 0; passed = 0; failed = 0; errors = 0; skipped = 0 }
  if (-not (Test-Path $file)) { return $r }
  try {
    [xml]$x = Get-Content -Raw -Encoding UTF8 $file
    $suites = @($x.testsuites.testsuite) | Where-Object { $_ }
    if (-not $suites) { $suites = @($x.testsuite) | Where-Object { $_ } }
    foreach ($s in $suites) {
      $r.tests += [int]$s.tests; $r.failed += [int]$s.failures; $r.errors += [int]$s.errors; $r.skipped += [int]$s.skipped
    }
    $r.passed = $r.tests - $r.failed - $r.errors - $r.skipped
  } catch { }
  return $r
}

# 다른 test.ps1 이 지금 도는가 — 같은 시험 DB 컨테이너를 함께 쓰면 먼저 끝난 쪽이 지워 버린다.
function Get-QTestLockPid {
  if (-not (Test-Path $TestLock)) { return 0 }
  $held = $null
  try { $held = Get-Content $TestLock -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
  if ($held -and [int]$held.pid -ne $PID -and (Get-Process -Id ([int]$held.pid) -ErrorAction SilentlyContinue)) { return [int]$held.pid }
  return 0
}

# 컨테이너 묶음(_test_groups.py 의 runner = container) — 앱 이미지 일회용 컨테이너에서 그 묶음 파일만 돈다.
# 저장소는 읽기 전용(/w:ro) · 결과 XML 은 결과 폴더(/out)에 · pytest 는 호스트와 같은 판을 컨테이너 안에만 깐다.
# 돌려주는 것: @{ code = pytest 종료 코드; reason = 건너뛴 까닭(돌았으면 $null) } — 건너뜀은 실패가 아니다.
function Invoke-QContainerGroup($g, [string]$dir) {
  $null = & docker version --format '{{.Server.Version}}' 2>&1
  if ($LASTEXITCODE -ne 0) { return @{ code = 0; reason = 'Docker 엔진이 꺼져 있다 — Docker Desktop 을 켠 뒤 -Group ctr' } }
  $null = & docker image inspect $g.image 2>&1
  if ($LASTEXITCODE -ne 0) { return @{ code = 0; reason = "앱 이미지 $($g.image) 가 없다 — docker compose build app 뒤 -Group ctr" } }
  $ver = "$(& python -c 'import pytest; print(pytest.__version__)')".Trim()
  # 97 = 컨테이너 안 pytest 설치 실패(대개 네트워크) — 시험 실패(1)와 가른다
  $inner = ('pip install -q --disable-pip-version-check pytest=={0} >/dev/null 2>&1 || exit 97; ' +
            'python -m pytest -p no:cacheprovider -W ignore::UserWarning --junit-xml=/out/{1}.xml {2}') -f `
    $ver, $g.key, (@($g.files) -join ' ')
  $repo = $QRoot -replace '\\', '/'
  $out = $dir -replace '\\', '/'
  & docker run --rm -v "${repo}:/w:ro" -v "${out}:/out" -w /w -e PYTHONDONTWRITEBYTECODE=1 $g.image sh -c $inner
  $code = $LASTEXITCODE
  if ($code -eq 97) { return @{ code = 0; reason = "컨테이너 안에 pytest $ver 을 깔지 못했다(네트워크?) — 이 묶음만 다시: -Group ctr" } }
  return @{ code = $code; reason = $null }
}

if ($Path.Count -gt 0 -and $Grouped) { Write-QFail '-Path 는 -Split · -Group · -Resume 과 함께 쓰지 않습니다.'; exit 2 }
if ($LastFailed -and $Grouped) { Write-QFail '-LastFailed 는 묶음 옵션과 함께 쓰지 않습니다(지난 실패 전부를 한 번에 돈다).'; exit 2 }

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

$otherPid = Get-QTestLockPid
if ($otherPid) {
  Write-QFail "다른 자동 시험이 지금 도는 중입니다 (PID $otherPid) — 같은 시험 DB 를 함께 쓰면 서로 깨뜨립니다. 끝난 뒤 다시 돌리세요."
  exit 1
}

# 묶음 실행이면 묶음 표(_test_groups.py)를 받아 고른다 — 이름(화면)과 영어 열쇠(ui) 모두 받는다.
$plan = @()
$prev = $null
if ($Grouped) {
  if ($Resume -and -not $RunDir) {
    $last = Get-ChildItem $TestRunRoot -Directory -ErrorAction SilentlyContinue |
      Where-Object { Test-Path (Join-Path $_.FullName 'run.json') } | Sort-Object Name | Select-Object -Last 1
    if (-not $last) { Write-QFail "이어 갈 결과 폴더가 없습니다 ($TestRunRoot 아래 run.json)."; exit 1 }
    $RunDir = $last.FullName
  }
  if ($Resume) {
    try { $prev = Get-Content -Raw -Encoding UTF8 (Join-Path $RunDir 'run.json') | ConvertFrom-Json } catch { }
    if (-not $prev -or -not $prev.groups) { Write-QFail "이어 갈 묶음 기록이 없습니다 — $RunDir\run.json"; exit 1 }
    # 묶음을 따로 고르지 않았으면 지난 실행이 고른 묶음 그대로 이어 간다.
    if ($Group.Count -eq 0 -and $prev.plan) { $Group = @($prev.plan) }
  }
  $tableJson = & python (Join-Path $PSScriptRoot '_test_groups.py') --json
  if ($LASTEXITCODE -ne 0) { Write-QFail '묶음 표(_test_groups.py)를 읽지 못했습니다.'; exit 1 }
  $table = @((($tableJson -join "`n") | ConvertFrom-Json).groups)
  foreach ($want in $Group) {
    if (-not ($table | Where-Object { $_.name -eq $want -or $_.key -eq $want })) {
      Write-QFail ("모르는 묶음 「{0}」 — 고를 수 있는 것: {1}" -f $want, (($table | ForEach-Object { "$($_.name)($($_.key))" }) -join ' · '))
      exit 2
    }
  }
  if ($Group.Count -gt 0) { $plan = @($table | Where-Object { $Group -contains $_.name -or $Group -contains $_.key }) }
  else { $plan = $table }
}

if (($Grouped -or $LastFailed -or $Detach) -and -not $RunDir) {
  $RunDir = Join-Path $TestRunRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
}
if ($RunDir) { $null = New-Item -ItemType Directory -Force -Path $RunDir }

# 세션 밖에서 — 같은 인자로 자기 자신을 숨은 창으로 다시 띄우고 바로 끝난다(세션은 run.json 만 나중에 읽는다).
if ($Detach) {
  # Start-Process 는 인자를 따옴표 없이 이어 붙인다 → 빈칸 든 경로를 위해 직접 감싼다(끝 \ 는 따옴표를 먹으니 뗀다).
  function ConvertTo-QArg([string]$s) { '"' + $s.TrimEnd('\') + '"' }
  $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (ConvertTo-QArg $PSCommandPath))
  foreach ($p in $Path) { $argList += @('-Path', (ConvertTo-QArg $p)) }
  if ($Group.Count -gt 0) { $argList += @('-Group', (($plan | ForEach-Object { $_.key }) -join ',')) }
  if ($Split) { $argList += '-Split' }
  if ($Resume) { $argList += '-Resume' }
  if ($LastFailed) { $argList += '-LastFailed' }
  if ($NoDb) { $argList += '-NoDb' }
  if ($KeepDb) { $argList += '-KeepDb' }
  $argList += @('-RunDir', (ConvertTo-QArg $RunDir))
  # 이어 가기면 지난 run.json 을 덮지 않는다(띄운 쪽이 그 기록으로 건너뛸 묶음을 고른다).
  if (-not $Resume) { Save-QRunJson $RunDir ([ordered]@{ status = 'starting'; detached_at = (Get-QNow); run_dir = $RunDir }) }
  $hostExe = (Get-Process -Id $PID).Path      # 지금 쓰는 PowerShell 그대로(5.1 이면 powershell.exe)
  $child = Start-Process $hostExe -ArgumentList $argList -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $RunDir 'test.log') -RedirectStandardError (Join-Path $RunDir 'test.err.log')
  Write-QOk "세션 밖에서 돕니다 (PID $($child.Id)) — 결과 폴더: $RunDir"
  Write-QInfo 'run.json 의 status 가 done 이면 끝 · 묶음별 수는 groups · 합은 totals · 화면 출력은 test.log'
  exit 0
}

# 이 실행이 시험 DB 를 쓰는 동안 잠금 — 다른 test.ps1 은 위에서 멈춘다(끝에서 지운다).
$null = New-Item -ItemType Directory -Force -Path $TestRunRoot
[IO.File]::WriteAllText($TestLock, (([ordered]@{ pid = $PID; started_at = (Get-QNow); run_dir = $RunDir }) | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
$state = $null
$runFinalized = $false

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
      # -v : pgvector 이미지가 데이터 폴더를 이름 없는 볼륨으로 잡는다 — 함께 지우지 않으면 돌릴 때마다 하나씩 쌓인다
      #      (2026-10-15 실측 — 8일 만에 47개 · 2.66 GB).
      if ($st.State -ne 'missing') { $null = & docker rm -f -v $TestDbName }
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
  Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
  # -o cache_dir=… : pytest 캐시를 저장소의 .pytest_cache 가 아니라 data\local-run\test\cache 에 둔다
  #   (저장소를 더럽히지 않으면서, 다음 -LastFailed 가 지난 실패를 알게).
  # pytest.ini 에 -q 가 이미 있다 — 여기서 또 붙이면 요약 줄이 사라진다.
  if ($Grouped) {
    Write-QStep ("3/4 시험 — 묶음 {0}개를 차례로 (묶음마다 새 pytest 프로세스 · 결과 {1})" -f $plan.Count, $RunDir)
    # 이어 가기면 지난 기록에서 종료 코드 0 으로 끝난 묶음을 그대로 옮겨 오고 건너뛴다.
    $done = @{}
    # 건너뛴 컨테이너 묶음(skipped_reason)은 끝난 것이 아니다 — 이어 가기에서 다시 돈다.
    if ($prev) { foreach ($e in @($prev.groups)) { if ($e.key -and [int]$e.exit_code -eq 0 -and -not $e.skipped_reason) { $done[$e.key] = $e } } }
    $mode = 'split'
    if ($Resume) { $mode = 'resume' } elseif ($Group.Count -gt 0) { $mode = 'group' }
    $state = [ordered]@{
      status = 'running'; pid = $PID; mode = $mode; plan = @($plan | ForEach-Object { $_.key })
      started_at = (Get-QNow); finished_at = $null; run_dir = $RunDir; current = $null
      groups = (New-Object System.Collections.ArrayList); totals = $null; exit_code = $null
    }
    foreach ($g in $plan) {
      if ($done.ContainsKey($g.key)) {
        [void]$state.groups.Add($done[$g.key])
        Write-QInfo "$($g.name)($($g.key)) — 지난 실행에서 통과 · 건너뜀"
        continue
      }
      $state.current = $g.name
      Save-QRunJson $RunDir $state
      $xml = Join-Path $RunDir "$($g.key).xml"
      $t0 = Get-Date
      $skipWhy = $null
      if ($g.runner -eq 'container') {
        # 호스트에 없는 RAG · 채팅 패키지는 앱 이미지에 있다 — 호스트에는 깔지 않는다(위 Invoke-QContainerGroup)
        $ctr = Invoke-QContainerGroup $g $RunDir
        $code = $ctr.code; $skipWhy = $ctr.reason
      } else {
        $pytestArgs = @('-m', 'pytest', '-o', "cache_dir=$TestCacheRel", "--junit-xml=$xml") + @($g.files)
        Push-Location $QRoot
        try { & python @pytestArgs; $code = $LASTEXITCODE } finally { Pop-Location }
      }
      $n = Read-QJunit $xml
      $entry = [ordered]@{
        name = $g.name; key = $g.key; files = @($g.files).Count
        tests = $n.tests; passed = $n.passed; failed = $n.failed; errors = $n.errors; skipped = $n.skipped
        seconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1); exit_code = $code
        finished_at = (Get-QNow); junit = "$($g.key).xml"
      }
      if ($g.runner -eq 'container') { $entry.runner = 'container'; $entry.image = $g.image }
      if ($skipWhy) { $entry.skipped_reason = $skipWhy }
      [void]$state.groups.Add($entry)
      $state.current = $null
      Save-QRunJson $RunDir $state
      $line = '{0}({1}) · 파일 {2} · 통과 {3} · 실패 {4} · 오류 {5} · 건너뜀 {6} · {7}초' -f `
        $g.name, $g.key, $entry.files, $n.passed, $n.failed, $n.errors, $n.skipped, $entry.seconds
      if ($skipWhy) { Write-QInfo "$($g.name)($($g.key)) — 건너뜀: $skipWhy" }
      elseif ($code -eq 0) { Write-QOk $line } else { Write-QFail "$line · 종료 코드 $code" }
    }
    $tot = [ordered]@{ tests = 0; passed = 0; failed = 0; errors = 0; skipped = 0; seconds = 0 }
    foreach ($e in $state.groups) { foreach ($k in @($tot.Keys)) { $tot[$k] += [double]$e.$k } }
    $tot.seconds = [math]::Round($tot.seconds, 1)
    $exitCode = 0
    if (@($state.groups | Where-Object { [int]$_.exit_code -ne 0 }).Count -gt 0) { $exitCode = 1 }
    $state.totals = $tot; $state.exit_code = $exitCode; $state.status = 'done'; $state.finished_at = (Get-QNow)
    Save-QRunJson $RunDir $state
    $runFinalized = $true
    Write-QInfo ('합 — 통과 {0} · 실패 {1} · 오류 {2} · 건너뜀 {3} · {4}초 · 결과 {5}\run.json' -f `
      $tot.passed, $tot.failed, $tot.errors, $tot.skipped, $tot.seconds, $RunDir)
  } else {
    if ($LastFailed) {
      Write-QStep '3/4 시험 — 지난번 실패한 시험만 (pytest --lf · 지난 실패가 없으면 아무것도 돌지 않는다)'
      $pytestArgs = @('-m', 'pytest', '-o', "cache_dir=$TestCacheRel", '--lf', '--lfnf=none') + $Path
    } else {
      Write-QStep '3/4 시험 — python -m pytest (전체는 10분 안팎 · 끝에 「N passed」 요약 줄)'
      Write-QInfo 'RAG · 채팅 · 올린 문서 격리 셋은 여기서 건너뛴다(호스트에 패키지 없음) — 앱 이미지로 돌리려면 -Split 또는 -Group ctr'
      $pytestArgs = @('-m', 'pytest', '-o', "cache_dir=$TestCacheRel") + $Path
    }
    # 결과 폴더가 있을 때(-Detach · -LastFailed)만 JUnit XML 과 run.json 을 남긴다 — 인자 없는 실행은 지금처럼 화면 출력만.
    if ($RunDir) { $pytestArgs += "--junit-xml=$(Join-Path $RunDir 'all.xml')" }
    $t0 = Get-Date
    Push-Location $QRoot
    try {
      & python @pytestArgs
      $exitCode = $LASTEXITCODE
    } finally {
      Pop-Location
    }
    # --lf --lfnf=none 은 지난 실패가 없으면 모든 시험을 빼고 「모은 시험 없음」(5)으로 끝난다 → 통과로 본다.
    if ($LastFailed -and $exitCode -eq 5) { Write-QOk '지난 실패가 없습니다 — 다시 돈 시험 0'; $exitCode = 0 }
    if ($RunDir) {
      $n = Read-QJunit (Join-Path $RunDir 'all.xml')
      $mode = 'all'
      if ($LastFailed) { $mode = 'lastfailed' }
      Save-QRunJson $RunDir ([ordered]@{
        status = 'done'; pid = $PID; mode = $mode; finished_at = (Get-QNow); run_dir = $RunDir
        seconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1); totals = $n; exit_code = $exitCode
      })
      $runFinalized = $true
    }
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
    $null = & docker rm -f -v $TestDbName 2>&1           # -v : 데이터 볼륨까지(위 2/4 의 주석)
    Write-QOk "시험 DB 컨테이너($TestDbName)와 데이터 볼륨을 지웠습니다"
  } elseif ($KeepDb) {
    Write-QInfo "시험 DB 를 남겼습니다 — 지우기: docker rm -f -v $TestDbName"
  }
  # 끝나지 못한 실행(Ctrl+C · DB 준비 실패)도 결과 폴더에 「멈춤」 을 남긴다 — 세션이 run.json 만 보고 알 수 있게.
  # 이어 가기는 지난 기록을 덮지 않는다(묶음 단계 전에 멈췄으면 지난 run.json 이 그대로 남는다).
  if ($RunDir -and -not $runFinalized) {
    if ($state) {
      $state.status = 'stopped'; $state.finished_at = (Get-QNow)
      Save-QRunJson $RunDir $state
    } elseif (-not $Resume) {
      Save-QRunJson $RunDir ([ordered]@{
        status = 'stopped'; pid = $PID; finished_at = (Get-QNow); run_dir = $RunDir
        note = '시험 단계 전에 멈췄거나 중간에 끊겼습니다 — test.log 를 보세요'
      })
    }
  }
  if ((Get-QTestLockPid) -eq 0) { Remove-Item $TestLock -ErrorAction SilentlyContinue }
}

if ($exitCode -eq 0) { Write-QOk '시험 전부 통과' } else { Write-QFail "실패한 시험이 있습니다 (pytest 종료 코드 $exitCode) — 위 FAILED 줄을 보세요." }
exit $exitCode
