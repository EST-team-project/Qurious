<#
.SYNOPSIS
  점검 계정(smoke-check@example.com)에 .env 의 KIS 모의투자 키를 넣는다 — 값은 보내기만 하고 화면 · 로그 · 파일에 남기지 않는다.
.DESCRIPTION
  check.ps1 의 「KIS」 묶음(연동 상태 · 원클릭 준비 상태 · 모의 잔고)은 점검 계정에 KIS 키가 있어야 돈다.
  이 스크립트는 앱의 사용자별 KIS 키 저장 길(POST /api/broker/settings · ADR-0004 「KIS 키는 사용자마다」)로
  .env 의 모의투자 칸을 그 계정에 넣는다. 화면 「증권사 API 설정」 에 손으로 넣는 것과 같은 길이다.

  지키는 것
    1) 값은 읽어서 보내기만 한다 — 키 · 시크릿 · 계좌번호를 화면 · 로그 · 파일에 쓰지 않는다.
       확인도 응답의 「연결됨 · 증권사 · 모의」 세 칸만 본다(설정 조회 응답에는 계좌번호가 들어 있어 본문을 찍지 않는다).
       넣기가 실패해도 서버 오류 본문은 찍지 않는다 — 입력 검사 오류(422) 본문에는 보낸 값이 되돌아올 수 있다.
    2) 모의(paper)만 — paper=true 로 넣고 실거래 관문(QURIOUS_ALLOW_LIVE_TRADING)은 건드리지 않는다.
       관문이 닫혀 있으면 키를 넣어도 주문 · 잔고는 KIS 모의(Testbed) 서버로만 간다(tests\test_live_trading_guard.py 6절).
    3) 이 PC 의 점검 계정에만 — 모의 계좌 하나를 여러 계정이 쓰면 서로의 자동매매 주문이 한 계좌에 섞인다.
    4) 증권사는 부르지 않는다 — 넣기와 확인은 우리 앱 안에서 끝난다(증권사 호출은 check.ps1 -Group KIS 의 잔고 1회).
    5) 다시 돌려도 결과가 같다 — 같은 값을 다시 넣을 뿐이다(.env 를 바꿨으면 새 값으로 바뀐다).

  .env 에서 읽는 칸(이름만 적는다)
    KIS_MOCK_APP_KEY · KIS_MOCK_APP_SECRET · KIS_MOCK_ACCOUNT_NO · KIS_MOCK_ACCOUNT_PRODUCT_CODE(계좌번호가 8자리일 때 뒤 2자리)
    실전 칸(KIS_APP_KEY · KIS_APP_SECRET · KIS_ACCOUNT_NO)은 읽지 않는다.
.PARAMETER BaseUrl
  앱 주소. 이 PC(localhost · 127.0.0.1)만 받는다.
.PARAMETER Remove
  점검 계정의 KIS 키를 지우고 증권사를 모의 브로커(mock)로 되돌린다.
.EXAMPLE
  .\scripts\personal\kis-link.ps1
.EXAMPLE
  .\scripts\personal\check.ps1 -Group KIS
.EXAMPLE
  .\scripts\personal\kis-link.ps1 -Remove
#>
[CmdletBinding()]
param(
  [string]$BaseUrl = 'http://127.0.0.1:8966',
  [switch]$Remove
)

. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = 'Stop'
$BaseUrl = $BaseUrl.TrimEnd('/')
$SmokeEmail = 'smoke-check@example.com'
$SmokePassword = 'smoke-check-1234'   # check.ps1 과 같은 로컬 점검용 값(공개 저장소에 있는 시험 값)

Write-QTitle 'KIS 모의투자 키 → 점검 계정'

if ($BaseUrl -notmatch '^https?://(localhost|127\.0\.0\.1)(:\d+)?$') {
  Write-QFail "이 PC 의 앱 주소만 받습니다 — 지금 $BaseUrl"
  exit 1
}

# ------------------------------------------------------------------------------
# 1. 로그인 — check.ps1 과 같은 점검 계정(없으면 처음 한 번 가입)
# ------------------------------------------------------------------------------
Write-QStep '1/3 점검 계정 로그인'
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$login = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/login" -Body @{ email = $SmokeEmail; password = $SmokePassword } -Session $session
if ($login.Status -eq 401) {
  $null = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/register" -Body @{ name = '로컬 점검'; email = $SmokeEmail; password = $SmokePassword } -Session $session
  $login = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/login" -Body @{ email = $SmokeEmail; password = $SmokePassword } -Session $session
}
if ($login.Status -ne 200) {
  Write-QFail "로그인 실패 (상태 $($login.Status)) — 앱이 떠 있나요? .\scripts\personal\start.ps1 -Dev"
  exit 1
}
Write-QOk "$SmokeEmail"

# ------------------------------------------------------------------------------
# 2. 넣기(또는 지우기) — 값은 이 블록 안에서만 들고 있다가 보낸 뒤 버린다
# ------------------------------------------------------------------------------
if ($Remove) {
  Write-QStep '2/3 지우기 — 증권사를 모의 브로커(mock)로'
  $save = Invoke-QApi -Method POST -Url "$BaseUrl/api/broker/settings" -Session $session `
    -Body @{ broker = 'mock'; app_key = ''; app_secret = ''; account_no = ''; paper = $true }
  if ($save.Status -ne 200) { Write-QFail "지우기 실패 (상태 $($save.Status))"; exit 1 }
  Write-QOk '지움 — 점검 계정의 KIS 키를 비웠다'
} else {
  Write-QStep '2/3 .env 의 KIS 모의투자 칸 → 앱의 사용자별 KIS 키 저장'
  $envPath = Join-Path $QRoot '.env'
  if (-not (Test-Path -LiteralPath $envPath)) { Write-QFail ".env 가 없습니다 — $envPath"; exit 1 }

  $want = @('KIS_MOCK_APP_KEY', 'KIS_MOCK_APP_SECRET', 'KIS_MOCK_ACCOUNT_NO', 'KIS_MOCK_ACCOUNT_PRODUCT_CODE')
  $vals = @{}
  foreach ($line in [IO.File]::ReadAllLines($envPath, [Text.Encoding]::UTF8)) {
    $m = [regex]::Match($line, '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
    if (-not $m.Success -or $want -notcontains $m.Groups[1].Value) { continue }
    $v = $m.Groups[2].Value.Trim()
    if ($v.Length -ge 2 -and (($v[0] -eq '"' -and $v[-1] -eq '"') -or ($v[0] -eq "'" -and $v[-1] -eq "'"))) {
      $v = $v.Substring(1, $v.Length - 2)          # 따옴표로 감싼 값
    } else {
      $cut = $v.IndexOf(' #')                      # 따옴표 없는 값 뒤의 주석(python-dotenv 와 같은 규칙)
      if ($cut -ge 0) { $v = $v.Substring(0, $cut).TrimEnd() }
    }
    $vals[$m.Groups[1].Value] = $v
  }
  $missing = @($want[0..2] | Where-Object { -not $vals[$_] })
  if ($missing.Count) {
    Write-QFail (".env 에 비어 있는 칸: " + ($missing -join ' · '))
    exit 1
  }

  # KIS 계좌 = 숫자 10자리(앞 8 = 계좌 · 뒤 2 = 상품 코드). 8자리면 상품 코드 칸을 붙인다(없으면 01 — kis.py _split_account 와 같음)
  $digits = $vals['KIS_MOCK_ACCOUNT_NO'] -replace '\D', ''
  if ($digits.Length -eq 8) {
    $prod = "$($vals['KIS_MOCK_ACCOUNT_PRODUCT_CODE'])" -replace '\D', ''
    if (-not $prod) { $prod = '01' }
    $digits += $prod.PadLeft(2, '0').Substring(0, 2)
  }
  if ($digits.Length -ne 10) {
    Write-QFail "KIS_MOCK_ACCOUNT_NO 의 꼴이 다릅니다 — 숫자 $($digits.Length) 자리(8 또는 10 자리여야 한다)"
    exit 1
  }

  $save = Invoke-QApi -Method POST -Url "$BaseUrl/api/broker/settings" -Session $session `
    -Body @{ broker = 'kis'; app_key = $vals['KIS_MOCK_APP_KEY']; app_secret = $vals['KIS_MOCK_APP_SECRET']; account_no = $digits; paper = $true }
  $vals = $null; $digits = $null   # 값을 오래 들고 있지 않는다
  if ($save.Status -ne 200) {
    Write-QFail "넣기 실패 (상태 $($save.Status)) — 본문은 찍지 않는다(보낸 값이 섞일 수 있다). 앱 로그: .\scripts\personal\logs.ps1 -Service app"
    exit 1
  }
  Write-QOk '넣음 — 점검 계정 · 증권사 kis · 모의(paper)'
}

# ------------------------------------------------------------------------------
# 3. 확인 — 응답의 세 칸 · 원클릭 경로만 본다(증권사는 부르지 않는다)
# ------------------------------------------------------------------------------
Write-QStep '3/3 확인'
$view = Invoke-QApi -Method GET -Url "$BaseUrl/api/broker/settings" -Session $session
$ready = Invoke-QApi -Method GET -Url "$BaseUrl/api/quant/kis/quickstart" -Session $session
if ($Remove) {
  if ($view.Status -eq 200 -and -not $view.Json.connected -and $view.Json.broker -eq 'mock') {
    Write-QOk '확인됨 — 연결 안 됨 · 증권사 mock'
    exit 0
  }
  Write-QFail "확인 실패 — 연결 $($view.Json.connected) · 증권사 $($view.Json.broker)"
  exit 1
}
if ($view.Status -eq 200 -and $view.Json.connected -eq $true -and $view.Json.broker -eq 'kis' -and $view.Json.paper -eq $true) {
  Write-QOk '확인됨 — 연결됨 · 증권사 kis · 모의(paper)'
} else {
  Write-QFail "확인 실패 — 연결 $($view.Json.connected) · 증권사 $($view.Json.broker) · 모의 $($view.Json.paper)"
  exit 1
}
if ($ready.Status -eq 200) {
  Write-QOk "원클릭 경로 $($ready.Json.route) · 환경 $($ready.Json.environment) · 시작 가능 $($ready.Json.ready)$(if ($ready.Json.reason) { ' (' + $ready.Json.reason + ')' })"
  if ($ready.Json.environment -ne 'paper') {
    Write-QWarn '환경이 paper 가 아닙니다 — 실거래 관문(QURIOUS_ALLOW_LIVE_TRADING)이 열려 있는지 확인하세요'
  }
} else {
  Write-QWarn "원클릭 준비 상태를 못 읽음 (상태 $($ready.Status))"
}
Write-QInfo '다음: .\scripts\personal\check.ps1 -Group KIS   (증권사 모의 서버 호출은 잔고 1회)'
