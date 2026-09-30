<#
.SYNOPSIS
  지금 무엇이 떠 있나 — 컨테이너 · 앱 응답 · 이미지 신선도 · 수집 DB · 디스크를 한 화면에.

.DESCRIPTION
  아무것도 바꾸지 않는다(읽기만). 「화면이 이상하다」 싶을 때 가장 먼저 돌린다.
    1. 컨테이너   서비스마다 켜짐/꺼짐 · 준비 상태(healthcheck) · 호스트 포트
    2. 앱         /api/health 응답과 걸린 시간
    3. 이미지     코드가 이미지보다 새로운가(그렇다면 화면은 옛 코드다 → start.ps1 이 다시 만든다)
    4. 데이터     수집 DB 파일 · 12:30 일일 갱신이 지금 도는 중인가
    5. 디스크     Qurious 이미지 · 볼륨 크기, 남은 시험 DB 컨테이너

.PARAMETER Data
  수집 DB 일일 갱신의 자세한 상태(scripts\daily_update.py status)까지 보여 준다. 파이썬이 있어야 한다.

.EXAMPLE
  .\scripts\personal\status.ps1
.EXAMPLE
  .\scripts\personal\status.ps1 -Data
#>
[CmdletBinding()]
param([switch]$Data)

. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = 'Continue'

Write-QTitle 'Qurious 상태'
if (-not (Test-QDocker)) { exit 1 }

# ------------------------------------------------------------------------------
# 1. 컨테이너 — 서비스 표(_common.ps1 의 $QServices)를 한 줄씩
# ------------------------------------------------------------------------------
Write-QStep '1. 컨테이너'
foreach ($svc in $QServices) {
  $st = Get-QContainerState $svc.Container
  $ports = ($svc.Ports | ForEach-Object { "$_" }) -join ','
  if (-not $ports) { $ports = '-' }
  $health = ''
  if ($st.Health) { $health = " ($($st.Health))" }
  $label = "{0,-13} {1,-21} 포트 {2,-11} {3}" -f $svc.Service, $svc.Container, $ports, $svc.What
  if ($st.State -eq 'running') {
    if ($st.Project -and $st.Project -ne $QComposeProject) {
      Write-QWarn "$label — 다른 프로젝트('$($st.Project)')의 컨테이너다"
    } else {
      Write-Host "  [켜짐] $label$health" -ForegroundColor Green
    }
  } elseif ($st.State -eq 'missing') {
    Write-Host "  [없음] $label" -ForegroundColor DarkGray
  } else {
    Write-Host "  [$($st.State)] $label" -ForegroundColor Yellow
  }
}

# ------------------------------------------------------------------------------
# 2. 앱 응답
# ------------------------------------------------------------------------------
Write-QStep '2. 앱 응답'
$h = Invoke-QApi -Method GET -Url "$QAppUrl/api/health" -TimeoutSec 5
if ($h.Status -eq 200) {
  Write-QOk "$QAppUrl/api/health → 200 · $($h.Ms)ms"
} else {
  Write-QFail "$QAppUrl 가 응답하지 않습니다 — .\scripts\personal\start.ps1 로 띄우세요. $($h.Error)"
}

# ------------------------------------------------------------------------------
# 3. 이미지 신선도 — 컨테이너는 이미지를 만든 순간의 코드로 돈다
# ------------------------------------------------------------------------------
Write-QStep '3. 이미지 신선도'
if (Test-QImageStale) {
  Write-QWarn '코드가 앱 이미지보다 새롭습니다 — 지금 화면은 옛 코드입니다. start.ps1 을 다시 돌리면 이미지를 다시 만듭니다.'
} else {
  Write-QOk '앱 이미지가 지금 코드와 같은 시점 이후에 만들어졌습니다'
}

# ------------------------------------------------------------------------------
# 4. 데이터 — 수집 DB(국내 일봉 · 지표의 원천)와 일일 갱신
# ------------------------------------------------------------------------------
Write-QStep '4. 수집 DB'
$collectorDb = Join-Path $QRoot 'data\collector\market.sqlite3'
if (Test-Path $collectorDb) {
  $db = Get-Item $collectorDb
  Write-QOk ("{0} — {1:N1} GB · 마지막 수정 {2:yyyy-MM-dd HH:mm}" -f 'data\collector\market.sqlite3', ($db.Length / 1GB), $db.LastWriteTime)
} else {
  Write-QWarn '수집 DB 가 없습니다 — 국내 일봉 · 지표가 외부(야후) 경로로 갑니다. 복원 방법은 README.md 참고.'
}
# 12:30 예약 작업(scripts\daily_update.py)이 잠금 파일에 자기 PID 를 적어 둔다. 그 프로세스가 살아 있으면 도는 중.
$lock = Join-Path $QRoot 'data\collector\state\daily_update.lock'
if (Test-Path $lock) {
  $held = $null
  try { $held = Get-Content $lock -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
  if ($held -and (Get-Process -Id ([int]$held.pid) -ErrorAction SilentlyContinue)) {
    Write-QWarn "일일 갱신이 지금 도는 중입니다 (PID $($held.pid) · $($held.started_at) 시작) — 시험 · 무거운 DB 작업은 끝난 뒤에."
  } else {
    Write-QInfo '잠금 파일만 남아 있습니다(비정상 종료 흔적) — 다음 실행이 치웁니다.'
  }
} else {
  Write-QOk '일일 갱신: 지금 도는 중 아님'
}
if ($Data) {
  Write-QInfo '— scripts\daily_update.py status —'
  Push-Location $QRoot
  try { & python scripts\daily_update.py status } finally { Pop-Location }
}

# ------------------------------------------------------------------------------
# 5. 디스크 — 이미지 · 볼륨 · 남은 시험 DB
# ------------------------------------------------------------------------------
Write-QStep '5. 디스크'
$images = & docker images --filter 'reference=qurious-*' --format '{{.Repository}}  {{.Size}}'
if ($images) {
  Write-QInfo ('이미지: ' + (@($images) -join ' · ') + '  (넷이 층을 나눠 써서 실제 차지는 한 개 크기 정도)')
} else {
  Write-QInfo '이미지: 아직 없음 (start.ps1 이 처음에 만든다)'
}
$volumes = & docker volume ls --filter "name=$QComposeProject" --format '{{.Name}}'
if ($volumes) { Write-QInfo ('볼륨(데이터): ' + (@($volumes) -join ' · ') + '  — stop.ps1 -DeleteData 로만 지워진다') }
$testDb = Get-QContainerState 'qurious-test-pg'
if ($testDb.State -ne 'missing') {
  Write-QWarn "시험 DB 컨테이너(qurious-test-pg)가 남아 있습니다 ($($testDb.State)) — 지우려면: docker rm -f qurious-test-pg"
}
exit 0
