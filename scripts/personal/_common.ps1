# ==============================================================================
# _common.ps1 — scripts/personal/ 의 스크립트들이 함께 쓰는 도우미 함수 모음
# ==============================================================================
#
# 이 파일은 직접 실행하지 않는다. 다른 스크립트가 첫머리에서 아래처럼 불러 쓴다.
#
#     . "$PSScriptRoot\_common.ps1"
#
#   맨 앞의 점(.)과 공백은 PowerShell 의 「dot-source(점 소싱)」 문법이다.
#   이 파일을 새 범위(scope)가 아니라 **부른 스크립트의 범위 안에서** 실행해,
#   여기서 만든 함수 · 변수를 그 스크립트가 그대로 쓰게 한다.
#   (점 없이 `& .\_common.ps1` 로 부르면, 실행이 끝나는 순간 함수가 사라진다.)
#
# 왜 따로 두나
#   색 있는 출력 · HTTP 호출 · 포트 확인 · 도커 확인은 start · check · status · stop 이 똑같이 한다.
#   한곳에 두면 고칠 때 한 번만 고치면 되고, 스크립트 본문은 「무엇을 하는지」 만 남는다.
#
# Windows PowerShell 5.1 에서 돌아야 한다 (Windows 기본 · PowerShell 7 이 없어도 된다)
#   - `&&` · `||` · 삼항 연산자(a ? b : c) · `??` 는 5.1 에 없다 → if / else 로만 쓴다.
#   - 이 폴더의 .ps1 은 전부 **UTF-8 BOM** 으로 저장한다. 5.1 은 BOM 이 없는 파일을
#     시스템 코드페이지(한국어 Windows = cp949)로 읽어 한글 주석 · 문자열이 깨지고,
#     깨진 글자가 따옴표를 삼키면 문법 오류까지 난다.
#   - 도커 같은 외부 프로그램(native command)은 `$?` 대신 `$LASTEXITCODE`(종료 코드)로 성패를 본다.
#     5.1 은 외부 프로그램이 stderr 에 글을 쓰기만 해도 `$?` 를 false 로 만든다
#     (docker compose 는 진행 상황을 stderr 로 쓴다 → 성공해도 false 가 된다).
# ==============================================================================

# 진행 막대 끄기 — 5.1 의 Invoke-WebRequest 는 진행 막대를 그리느라 요청이 눈에 띄게 느려진다.
$ProgressPreference = 'SilentlyContinue'

# ------------------------------------------------------------------------------
# 1. 경로 · 주소 · 포트 (docker-compose.yml 과 맞춰 둔 값)
# ------------------------------------------------------------------------------

# 저장소 루트. 이 파일은 <루트>\scripts\personal\ 에 있으므로 두 단계 위다.
# $PSScriptRoot 는 「지금 읽고 있는 .ps1 파일이 있는 폴더」 (dot-source 해도 이 파일 기준).
$QRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

# 브라우저 · 점검이 부르는 앱 주소. compose 가 컨테이너의 8000 번을 호스트의 8966 번으로 연다.
$QAppUrl = 'http://localhost:8966'

# compose 서비스 ↔ 컨테이너 이름 ↔ 호스트 포트.
# ⚠️ docker-compose.yml 의 ports · container_name 을 바꾸면 여기도 같이 바꾼다.
$QServices = @(
  [pscustomobject]@{ Service = 'postgres';      Container = 'fin-ai-postgres';      Ports = @(15432);      What = 'PostgreSQL — 사용자 · 주문 · 모의투자 장부 · 리밸런싱' }
  [pscustomobject]@{ Service = 'redis';         Container = 'fin-ai-redis';         Ports = @(16379);      What = 'Redis — 로그인 세션 · 캐시 · Celery 메시지 통로' }
  [pscustomobject]@{ Service = 'neo4j';         Container = 'fin-ai-neo4j';         Ports = @(17474, 7687); What = 'Neo4j — 종목 관계 그래프 (선택 기능)' }
  [pscustomobject]@{ Service = 'app';           Container = 'fin-ai-app';           Ports = @(8966);       What = '앱 — 화면(public/) + API(FastAPI)' }
  [pscustomobject]@{ Service = 'celery-worker'; Container = 'fin-ai-celery-worker'; Ports = @();           What = 'Celery 워커 — 예약 작업을 실제로 실행' }
  [pscustomobject]@{ Service = 'celery-beat';   Container = 'fin-ai-celery-beat';   Ports = @();           What = 'Celery 비트 — 자동매매 10분 · 리밸런싱 1시간 같은 예약 시계' }
)

# compose 프로젝트 이름. 지정하지 않으면 compose 가 폴더 이름(Qurious → qurious)을 쓴다.
# 같은 컨테이너 이름(fin-ai-*)을 쓰는 다른 프로젝트(예: 강사님 원본 사본)가 떠 있으면 충돌하므로
# 「이 컨테이너가 우리 것인가」 를 이 이름으로 가린다.
$QComposeProject = 'qurious'

# compose 파일 목록. 비어 있으면 compose 가 저장소 루트의 docker-compose.yml 하나만 읽는다(보통 모드).
# start.ps1 -Dev 가 여기에 개발 모드 덧씌우기(scripts/personal/compose.dev.yml)를 더한다 —
# 그러면 그 스크립트 안의 모든 Invoke-QCompose 호출이 `-f 기본 -f 덧씌우기` 로 돈다.
# ⚠️ 첫 파일이 기본 파일이어야 한다. compose 는 상대 경로(./app 등)를 첫 파일이 있는 폴더 기준으로 푼다.
$QComposeFiles = @()
$QComposeDevFile = 'scripts/personal/compose.dev.yml'

# ------------------------------------------------------------------------------
# 2. 화면 출력 — 글머리표를 고정해 두면 로그를 눈으로 훑기 쉽다
# ------------------------------------------------------------------------------
# 그림 글자(이모지)는 쓰지 않는다. 오래된 콘솔 글꼴 · cp949 로 저장한 로그에서 ? 로 깨진다.

function Write-QTitle([string]$Text) {
  Write-Host ''
  Write-Host ('=' * 72) -ForegroundColor DarkCyan
  Write-Host "  $Text" -ForegroundColor Cyan
  Write-Host ('=' * 72) -ForegroundColor DarkCyan
}

function Write-QStep([string]$Text) {
  Write-Host ''
  Write-Host ">> $Text" -ForegroundColor Cyan
}

function Write-QOk([string]$Text)   { Write-Host "  [ OK ] $Text" -ForegroundColor Green }
function Write-QWarn([string]$Text) { Write-Host "  [주의] $Text" -ForegroundColor Yellow }
function Write-QFail([string]$Text) { Write-Host "  [실패] $Text" -ForegroundColor Red }
function Write-QInfo([string]$Text) { Write-Host "         $Text" -ForegroundColor Gray }

# ------------------------------------------------------------------------------
# 3. 도커 확인
# ------------------------------------------------------------------------------

function Test-QDocker {
  <#
  .SYNOPSIS
    docker 명령이 있고, Docker Desktop(엔진)이 켜져 있는지 본다. 켜져 있으면 $true.
  .DESCRIPTION
    `docker version --format ...` 은 엔진이 꺼져 있으면 종료 코드 1 을 낸다.
    docker 명령 자체가 없으면(설치 안 됨) Get-Command 에서 걸러진다.
  #>
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-QFail 'docker 명령이 없습니다 — Docker Desktop 을 설치하세요: https://www.docker.com/products/docker-desktop/'
    return $false
  }
  # 2>&1 로 stderr 를 삼킨다. 5.1 에서는 이때 오류 레코드가 생기지만 $ErrorActionPreference 가
  # 기본값(Continue)이면 멈추지 않고, 판정은 종료 코드로만 한다.
  $null = & docker version --format '{{.Server.Version}}' 2>&1
  if ($LASTEXITCODE -ne 0) {
    Write-QFail 'Docker Desktop 이 꺼져 있습니다 — 켜고, 작업 표시줄의 고래 아이콘이 움직임을 멈춘 뒤 다시 실행하세요.'
    return $false
  }
  return $true
}

function Invoke-QCompose {
  <#
  .SYNOPSIS
    저장소 루트에서 `docker compose <인자>` 를 실행하고 종료 코드를 돌려준다.
  .DESCRIPTION
    compose 는 docker-compose.yml 이 있는 폴더에서 돌아야 한다. 사용자가 어느 폴더에서
    스크립트를 불렀든 루트로 잠깐 옮겨 실행하고(Push-Location), 끝나면 원래 폴더로 돌아간다(Pop-Location).
    출력은 화면에 그대로 흘려보낸다 — 이미지 받기 · 빌드처럼 오래 걸리는 일의 진행이 보여야 해서다.

    ⚠️ `| Out-Host` 가 꼭 필요하다. PowerShell 함수는 안에서 실행한 명령의 출력(stdout)까지 전부
       「반환값」 으로 내보낸다. 그대로 두면 `$code = Invoke-QCompose ...` 가 docker 가 찍은 줄들까지
       $code 에 삼켜 화면엔 아무것도 안 보이고, $code 는 종료 코드가 아니라 글줄 배열이 된다
       (logs.ps1 이 로그를 한 줄도 안 보여 줘서 찾은 일). Out-Host 로 화면에 바로 쓰고, 반환은 종료 코드 하나만.
  .EXAMPLE
    $code = Invoke-QCompose @('up', '-d', 'postgres')
  #>
  param([Parameter(Mandatory = $true)][string[]]$Arguments)
  Push-Location $QRoot
  try {
    # $QComposeFiles 가 있으면(개발 모드) 파일마다 `-f 파일` 을 앞에 붙인다. 없으면 인자 그대로.
    $fileArgs = @()
    foreach ($f in $QComposeFiles) { $fileArgs += @('-f', $f) }
    & docker compose @fileArgs @Arguments | Out-Host
    return $LASTEXITCODE
  } finally {
    Pop-Location
  }
}

function Get-QContainerState {
  <#
  .SYNOPSIS
    컨테이너 하나의 상태를 돌려준다: 'running' · 'exited' · 'missing'(없음) 등,
    그리고 그 컨테이너를 만든 compose 프로젝트 이름.
  .DESCRIPTION
    `docker inspect` 는 없는 컨테이너에 종료 코드 1 을 낸다. 그때는 State='missing'.
    Project 는 compose 가 컨테이너에 붙여 두는 라벨(com.docker.compose.project)에서 읽는다.
    Health 는 compose 파일에 healthcheck 가 있는 서비스(postgres · redis)만 값이 있다.
    DevMode 는 개발 모드(start.ps1 -Dev)로 만든 컨테이너인가 — 내 PC 의 app 폴더가 컨테이너의
    /app/app 에 연결(bind mount)돼 있으면 $true. 이 연결은 compose.dev.yml 만 만든다.

    `docker inspect --format '{{index .Config.Labels "..."}}'` 처럼 템플릿을 쓰지 않고 JSON 을
    통째로 받아 푸는 이유: 5.1 은 외부 프로그램에 인자를 넘길 때 **안쪽 큰따옴표를 벗겨 버려**
    템플릿이 깨진다(알려진 5.1 동작). JSON 으로 받으면 따옴표를 넘길 일이 없다.
  #>
  param([Parameter(Mandatory = $true)][string]$Name)
  $out = & docker inspect $Name 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $out) {
    return [pscustomobject]@{ Name = $Name; State = 'missing'; Project = ''; Health = ''; DevMode = $false }
  }
  # 외부 프로그램 출력은 줄마다 문자열 하나로 들어온다 → 한 덩어리로 이어 붙인 뒤 JSON 으로 푼다.
  $info = @(($out -join "`n") | ConvertFrom-Json)[0]
  $project = ''
  if ($info.Config.Labels -and ($info.Config.Labels.PSObject.Properties.Name -contains 'com.docker.compose.project')) {
    $project = $info.Config.Labels.'com.docker.compose.project'
  }
  $health = ''
  if ($info.State.PSObject.Properties.Name -contains 'Health' -and $info.State.Health) { $health = $info.State.Health.Status }
  $dev = [bool](@($info.Mounts) | Where-Object { $_.Type -eq 'bind' -and $_.Destination -eq '/app/app' })
  return [pscustomobject]@{ Name = $Name; State = $info.State.Status; Project = $project; Health = $health; DevMode = $dev }
}

# ------------------------------------------------------------------------------
# 4. 포트 · HTTP
# ------------------------------------------------------------------------------

function Get-QPortOwner {
  <#
  .SYNOPSIS
    호스트에서 그 포트를 듣고(LISTEN) 있는 프로세스 이름을 돌려준다. 아무도 없으면 빈 문자열.
  .DESCRIPTION
    Get-NetTCPConnection 은 Windows 8 이상 기본 명령이다. 도커가 연 포트는 대개
    com.docker.backend · wslrelay 같은 도커 쪽 프로세스 이름으로 보인다.
  #>
  param([Parameter(Mandatory = $true)][int]$Port)
  $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $conn) { return '' }
  $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
  if ($proc) { return $proc.ProcessName }
  # 소켓 주인으로 적힌 PID 가 이미 없다 — 그 PID 가 만든 자식이 소켓을 물려받아 쥐고 있는 경우다.
  # dev.ps1 의 uvicorn --reload 가 그렇다: 실제 서버는 multiprocessing 자식이고, 그 명령줄에는
  # 'uvicorn' 대신 'spawn_main(parent_pid=<부모 PID>' 만 있다. 창을 Ctrl+C 없이 닫으면 자식만 남는다.
  $child = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "parent_pid=$($conn.OwningProcess)\b" } | Select-Object -First 1
  if ($child) { return "python (PID $($child.ProcessId) — 이미 끝난 PID $($conn.OwningProcess) 가 남긴 자식 · stop.ps1 -KillDev 로 정리)" }
  return "PID $($conn.OwningProcess)"
}

function Find-QFreePort {
  <#
  .SYNOPSIS
    후보 포트 가운데 「Windows 예약 범위 밖」 이고 「아무도 듣지 않는」 첫 번째를 돌려준다. 없으면 0.
  .DESCRIPTION
    Hyper-V · WSL · Docker Desktop 이 켜진 Windows 는 부팅할 때마다 포트 수백 개를 묶음으로 예약한다
    (`netsh interface ipv4 show excludedportrange protocol=tcp` 로 보인다). 예약 범위 안의 포트는
    아무도 안 쓰는데도 도커가 열지 못한다 — 「An attempt was made to access a socket in a way forbidden」.
    이 PC 에서는 55367~55466 이 예약돼 있어 시험 DB 를 55432 에 띄우다 실패했다. 범위는 PC 마다,
    부팅마다 달라지므로 고정 번호 대신 후보를 차례로 따져 고른다.
  #>
  param([Parameter(Mandatory = $true)][int[]]$Candidates)
  # netsh 출력의 머리글은 Windows 언어마다 다르다 → 「숫자 두 개로 시작하는 줄」 만 범위로 읽는다.
  $ranges = @()
  foreach ($line in (& netsh interface ipv4 show excludedportrange protocol=tcp 2>$null)) {
    if ("$line" -match '^\s*(\d+)\s+(\d+)') { $ranges += , @([int]$Matches[1], [int]$Matches[2]) }
  }
  foreach ($p in $Candidates) {
    $reserved = $false
    foreach ($r in $ranges) { if ($p -ge $r[0] -and $p -le $r[1]) { $reserved = $true; break } }
    if ($reserved) { continue }
    if (Get-QPortOwner $p) { continue }
    return $p
  }
  return 0
}

function Invoke-QApi {
  <#
  .SYNOPSIS
    HTTP 요청을 한 번 보내고, 결과를 늘 같은 모양의 객체로 돌려준다 — curl 한 번과 같은 일.
  .DESCRIPTION
    Invoke-WebRequest(PowerShell 판 curl)를 그대로 쓰면 걸리는 세 가지를 여기서 푼다.
      1) 한글 깨짐 — 5.1 은 Content-Type 에 charset 이 없는 JSON(FastAPI 기본)을 ISO-8859-1 로
         읽어 `.Content` 의 한글이 깨진다. 그래서 받은 **바이트**(RawContentStream)를 UTF-8 로 직접 푼다.
         보내는 본문도 UTF-8 바이트로 바꿔 보낸다(문자열로 넘기면 5.1 이 한글을 ? 로 바꾼다).
      2) 4xx · 5xx 가 예외가 됨 — 예외를 잡아 상태 코드를 숫자로 담는다. 점검에서는 401 · 422 도
         「기대한 결과」 일 수 있기 때문이다. 오류 본문은 ErrorDetails.Message 에 들어 있다
         (5.1 은 응답 스트림을 이미 읽어 버려서 스트림을 다시 읽으면 빈 문자열이 나온다 — 직접 시험함).
      3) 서버 무응답 — 앱이 꺼졌거나 포트가 틀리면 응답 자체가 없다. 그때 Status 는 0, Error 에 이유.
    Session 에 로그인 세션(WebRequestSession)을 넘기면 쿠키(fin_session)를 주고받는다 —
    curl 의 `-b` · `-c`(쿠키 저장소)와 같다.
    Bearer 에 JWT 액세스 토큰을 주면 `Authorization: Bearer <토큰>` 머리글을 붙인다 —
    화면은 쿠키만 쓰고, 토큰 방식은 API 클라이언트(앱 밖 프로그램)용이다.
  .OUTPUTS
    [pscustomobject] Status(int · 0=무응답) · Ms(걸린 밀리초) · Text(본문 글) · Json(풀어 둔 객체 또는 $null) · Error
  .EXAMPLE
    $r = Invoke-QApi -Method GET -Url "$QAppUrl/api/health"
    if ($r.Status -eq 200 -and $r.Json.status -eq 'ok') { '앱이 살아 있다' }
  #>
  param(
    [Parameter(Mandatory = $true)][string]$Method,
    [Parameter(Mandatory = $true)][string]$Url,
    $Body = $null,          # 해시테이블 · 객체를 넘기면 JSON 으로 바꿔 보낸다
    $Session = $null,       # 로그인 세션 (Microsoft.PowerShell.Commands.WebRequestSession)
    [string]$Bearer = '',   # JWT 액세스 토큰 (있으면 Authorization 머리글)
    [int]$TimeoutSec = 30
  )
  $result = [pscustomobject]@{ Status = 0; Ms = 0; Text = ''; Json = $null; Error = '' }

  # Invoke-WebRequest 에 넘길 인자를 해시테이블로 모은다 — 이것을 「스플래팅(splatting)」 이라 한다.
  # `Invoke-WebRequest @params` 처럼 @ 로 넘기면 키가 인자 이름, 값이 인자 값이 된다.
  $params = @{
    Method          = $Method
    Uri             = $Url
    UseBasicParsing = $true      # 5.1 에서 Internet Explorer 엔진 없이 응답을 읽게 한다
    TimeoutSec      = $TimeoutSec
    ErrorAction     = 'Stop'     # 4xx · 5xx 를 catch 로 보내기 위해
  }
  if ($null -ne $Session) { $params.WebSession = $Session }
  if ($Bearer) { $params.Headers = @{ Authorization = "Bearer $Bearer" } }
  if ($null -ne $Body) {
    $json = $Body | ConvertTo-Json -Depth 10 -Compress
    $params.Body = [System.Text.Encoding]::UTF8.GetBytes($json)
    $params.ContentType = 'application/json; charset=utf-8'
  }

  $watch = [System.Diagnostics.Stopwatch]::StartNew()
  try {
    $resp = Invoke-WebRequest @params
    $result.Status = [int]$resp.StatusCode
    $result.Text = [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray())
  } catch {
    $httpResp = $null
    if ($_.Exception.PSObject.Properties.Name -contains 'Response') { $httpResp = $_.Exception.Response }
    if ($null -ne $httpResp) {
      # 서버가 응답은 했다 (4xx · 5xx). 5.1 = HttpWebResponse · 7 = HttpResponseMessage — 둘 다 StatusCode 가 있다.
      $result.Status = [int]$httpResp.StatusCode
      if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $result.Text = $_.ErrorDetails.Message }
    } else {
      # 응답 자체가 없다 — 연결 거부 · 시간 초과 · 주소 오류.
      $result.Error = $_.Exception.Message
    }
  }
  $watch.Stop()
  $result.Ms = [int]$watch.ElapsedMilliseconds

  # 본문이 JSON 이면 풀어 둔다. 5.1 의 ConvertFrom-Json 은 약 2MB 가 넘는 글을 못 푼다 —
  # 그래서 점검은 기간을 짧게(1개월 · 6개월) 잡아 응답을 작게 받는다.
  if ($result.Text) {
    try { $result.Json = $result.Text | ConvertFrom-Json -ErrorAction Stop } catch { $result.Json = $null }
  }
  return $result
}

function Wait-QHttp {
  <#
  .SYNOPSIS
    주소가 200 을 돌려줄 때까지 기다린다. 제한 시간 안에 오면 $true.
  .DESCRIPTION
    컨테이너가 「Started」 여도 안의 앱은 아직 준비 중일 수 있다(마이그레이션 · 모델 적재).
    그래서 헬스 체크 주소를 2초마다 두드려 실제로 답할 때까지 기다린다.
    10초마다 점(.)을 찍어 멈춘 게 아니라 기다리는 중임을 보여 준다.
  #>
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSec = 180
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $tick = 0
  while ((Get-Date) -lt $deadline) {
    $r = Invoke-QApi -Method GET -Url $Url -TimeoutSec 5
    if ($r.Status -eq 200) { Write-Host ''; return $true }
    Start-Sleep -Seconds 2
    $tick += 2
    if ($tick % 10 -eq 0) { Write-Host -NoNewline '.' }
  }
  Write-Host ''
  return $false
}

# ------------------------------------------------------------------------------
# 5. 저장소(DB) 먼저 띄우기 · 이미지가 코드보다 오래됐는지 보기 — start.ps1 · dev.ps1 이 함께 쓴다
# ------------------------------------------------------------------------------

function Start-QInfra {
  <#
  .SYNOPSIS
    postgres · redis · neo4j 를 띄우고, 셋 다 요청을 받을 준비가 될 때까지 기다린다. 준비되면 $true.
  .DESCRIPTION
    왜 앱보다 먼저 띄우나 —
      앱(app)은 시작할 때 한 번 Neo4j 에 붙어 보고, 실패하면 그 실행 내내 그래프 기능을 끈다
      (로그: 「Neo4j 연결 실패 (그래프 기능 비활성)」). Neo4j 는 부팅에 20초 안팎 걸리는데,
      compose 의 depends_on 은 「컨테이너가 켜졌다」 까지만 보장하고 「준비됐다」 는 보장하지 않는다.
      그래서 셋을 먼저 띄우고 준비를 확인한 뒤에 앱을 띄운다.
    무엇을 「준비됨」 으로 보나 —
      postgres · redis : compose 파일의 healthcheck(pg_isready · redis-cli ping)가 healthy
      neo4j            : 브라우저 포트(http://localhost:17474)가 200 (healthcheck 가 compose 에 없어서)
  #>
  param([int]$TimeoutSec = 180)
  $code = Invoke-QCompose @('up', '-d', 'postgres', 'redis', 'neo4j')
  if ($code -ne 0) {
    Write-QFail "저장소 컨테이너를 띄우지 못했습니다 (docker compose 종료 코드 $code) — 위 오류 줄을 보세요."
    return $false
  }
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $ready = @{ postgres = $false; redis = $false; neo4j = $false }
  while ((Get-Date) -lt $deadline) {
    if (-not $ready.postgres) { $ready.postgres = ((Get-QContainerState 'fin-ai-postgres').Health -eq 'healthy') }
    if (-not $ready.redis)    { $ready.redis    = ((Get-QContainerState 'fin-ai-redis').Health -eq 'healthy') }
    if (-not $ready.neo4j)    { $ready.neo4j    = ((Invoke-QApi -Method GET -Url 'http://localhost:17474' -TimeoutSec 3).Status -eq 200) }
    if ($ready.postgres -and $ready.redis -and $ready.neo4j) {
      Write-QOk 'postgres · redis · neo4j 준비됨'
      return $true
    }
    Start-Sleep -Seconds 2
  }
  foreach ($k in $ready.Keys) {
    if (-not $ready[$k]) { Write-QFail "$k 가 ${TimeoutSec}초 안에 준비되지 않았습니다 — .\scripts\personal\logs.ps1 -Service $k 로 로그를 보세요." }
  }
  return $false
}

function Test-QImageStale {
  <#
  .SYNOPSIS
    앱 이미지(qurious-app)가 없거나, 이미지 안에 들어가는 코드가 이미지보다 새로우면 $true.
  .DESCRIPTION
    도커 컨테이너는 **이미지를 만든 순간의 코드**로 돈다. git pull 로 코드를 받거나 파일을 고친 뒤
    이미지를 다시 만들지 않으면, 화면에는 옛 코드가 계속 보인다 — 팀 작업에서 가장 흔한 착각이다.
    그래서 Dockerfile 이 COPY 하는 것들(app · public · prompts · alembic · alembic.ini ·
    requirements.txt · Dockerfile)의 마지막 수정 시각과 이미지 생성 시각을 비교한다.
    파일 쪽이 더 새로우면 start.ps1 이 `--build` 를 붙여 다시 만든다(바뀐 층만 다시 만들어 보통 수십 초).
  .PARAMETER DepsOnly
    개발 모드용 — requirements.txt · Dockerfile 만 비교한다. 개발 모드는 코드 폴더를 컨테이너에
    직접 연결하므로 코드가 새로워도 다시 만들 필요가 없고, 설치 패키지가 바뀔 때만 필요하다.
  #>
  param([switch]$DepsOnly)
  $created = & docker image inspect qurious-app --format '{{.Created}}' 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $created) { return $true }   # 이미지가 아직 없다 → 만들어야 한다
  # 도커는 「2026-09-30T01:52:01.04638633Z」 처럼 소수점 아래 9자리까지 준다. .NET 은 7자리까지만
  # 읽으므로 초 단위까지(앞 19글자)만 잘라 UTC 로 읽는다.
  $imageUtc = [datetime]::ParseExact(([string]$created).Substring(0, 19), 'yyyy-MM-ddTHH:mm:ss',
    [System.Globalization.CultureInfo]::InvariantCulture,
    [System.Globalization.DateTimeStyles]'AssumeUniversal, AdjustToUniversal')
  $names = @('app', 'public', 'prompts', 'alembic', 'alembic.ini', 'requirements.txt', 'Dockerfile')
  if ($DepsOnly) { $names = @('requirements.txt', 'Dockerfile') }
  $sources = $names | ForEach-Object { Join-Path $QRoot $_ } | Where-Object { Test-Path $_ }
  $newest = Get-ChildItem -Path $sources -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\__pycache__\\' } |
    Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
  if ($newest -and $newest.LastWriteTimeUtc -gt $imageUtc.AddSeconds(1)) {
    Write-QInfo ("이미지보다 새 파일: {0} ({1:yyyy-MM-dd HH:mm} 수정)" -f $newest.FullName.Substring($QRoot.Length + 1), $newest.LastWriteTime)
    return $true
  }
  return $false
}

function Save-QUtf8Bom {
  <#
  .SYNOPSIS
    글을 UTF-8(BOM 포함)으로 파일에 쓴다. 5.1 의 Out-File · Set-Content 기본 인코딩이 제각각이라 따로 둔다.
  #>
  param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Text)
  $enc = New-Object System.Text.UTF8Encoding($true)   # $true = BOM 을 붙인다 (메모장 · 엑셀이 한글을 바로 읽음)
  [System.IO.File]::WriteAllText($Path, $Text, $enc)
}
