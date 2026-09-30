<#
.SYNOPSIS
  Qurious 끄기 — 기본은 컨테이너만 지우고 DB 데이터(볼륨)는 남긴다. 다음 start.ps1 에 그대로 이어진다.

.DESCRIPTION
  세 가지 끄는 방법의 차이
    (기본)        docker compose down      컨테이너 삭제 · 볼륨(데이터) 유지 · 메모리 · CPU 를 돌려준다
    -Keep         docker compose stop      컨테이너를 멈추기만 한다 · 다시 켤 때 조금 빠르다
    -DeleteData   docker compose down -v   컨테이너 + 볼륨 삭제 — 가입한 계정 · 모의투자 장부 ·
                                           리밸런싱 설정 등 앱 DB 가 전부 사라진다(되돌릴 수 없다)
  어느 경우에도 지우지 않는 것
    - 수집 DB(data\collector\market.sqlite3) — 호스트 폴더라 도커와 무관하다
    - 이미지(qurious-*) — 다음 실행을 빠르게 하려고 둔다. 공간이 필요하면 README.md 의 「디스크 정리」
    - 네트워크 shared-net — 밖에서 만든(external) 네트워크라 compose 가 지우지 않는다

.PARAMETER Keep
  컨테이너를 지우지 않고 멈추기만 한다.

.PARAMETER DeleteData
  DB 데이터까지 지운다. 실행하면 「삭제」 를 직접 입력해야 진행한다.

.PARAMETER KillDev
  dev.ps1 로 호스트에서 띄운 앱(uvicorn)과 그 자식 프로세스까지 끈다. 보통은 그 창에서 Ctrl+C 로 끝내면
  되고, 창을 그냥 닫아 자식 프로세스가 포트(8000)를 쥔 채 남았을 때 쓴다.

.EXAMPLE
  .\scripts\personal\stop.ps1
.EXAMPLE
  .\scripts\personal\stop.ps1 -DeleteData      # 처음 상태로 (확인 입력 필요)
#>
[CmdletBinding()]
param(
  [switch]$Keep,
  [switch]$DeleteData,
  [switch]$KillDev
)

function Get-DevAppProcess {
  <#
  .SYNOPSIS
    dev.ps1 로 띄운 앱 프로세스를 찾는다 — uvicorn 부모(리로더) + 그 자식(실제 서버) + 남은 자식.
  .DESCRIPTION
    uvicorn --reload 는 파일을 지켜보는 부모와, 요청을 받는 자식 두 프로세스로 돈다. 자식의 명령줄에는
    'uvicorn' 이 없고 'spawn_main(parent_pid=<부모 PID>' 만 있어 부모 PID 로 짝을 찾는다.
    부모 없이 남은 자식(창을 그냥 닫은 흔적)은 dev.ps1 기본 포트 8000 을 쥐고 있을 때만 우리 것으로 본다 —
    다른 프로그램의 자식 프로세스를 잘못 끄지 않으려고.
  #>
  $all = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue)
  $roots = @($all | Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'app\.main:app' })
  $rootIds = @($roots | ForEach-Object { [int]$_.ProcessId })
  $kids = @($all | Where-Object { $_.CommandLine -match 'spawn_main\(parent_pid=(\d+)' -and $rootIds -contains [int]$Matches[1] })
  $listen = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
  $orphans = @()
  if ($listen -and -not (Get-Process -Id $listen.OwningProcess -ErrorAction SilentlyContinue)) {
    $orphans = @($all | Where-Object { $_.CommandLine -match "spawn_main\(parent_pid=$($listen.OwningProcess)\b" })
  }
  return @($roots + $kids + $orphans)
}

. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = 'Continue'

Write-QTitle 'Qurious 끄기'
if (-not (Test-QDocker)) { exit 1 }

if ($Keep -and $DeleteData) {
  Write-QFail '-Keep 과 -DeleteData 는 함께 쓸 수 없습니다.'
  exit 1
}

if ($DeleteData) {
  Write-QWarn '앱 DB(볼륨)를 지웁니다 — 계정 · 모의투자 장부 · 주문 이력 · 리밸런싱 설정이 모두 사라집니다.'
  Write-QInfo '수집 DB(data\collector)와 이미지는 지우지 않습니다.'
  # 실수로 지우는 일을 막으려고 정확한 글자를 입력하게 한다(Enter 만 치면 취소).
  $answer = Read-Host "  계속하려면 「삭제」 라고 입력하세요"
  if ($answer -ne '삭제') {
    Write-QInfo '취소했습니다. 아무것도 바꾸지 않았습니다.'
    exit 0
  }
  $code = Invoke-QCompose @('down', '-v')
} elseif ($Keep) {
  $code = Invoke-QCompose @('stop')
} else {
  $code = Invoke-QCompose @('down')
}
if ($code -ne 0) {
  Write-QFail "docker compose 가 종료 코드 $code 로 끝났습니다 — 위 줄을 보세요."
  exit $code
}

# dev.ps1 로 호스트에서 직접 띄운 앱은 도커 밖이라 compose 로는 꺼지지 않는다.
# 기본은 알려만 주고(그 창에서 Ctrl+C 가 정석), -KillDev 를 주면 여기서 끈다.
$devApps = @(Get-DevAppProcess)
if ($devApps.Count -gt 0) {
  $pids = ($devApps | ForEach-Object { $_.ProcessId }) -join ', '
  if ($KillDev) {
    # Windows 에서는 pkill 같은 이름 기반 종료가 파이썬 자식 프로세스를 놓친다 → PID 로 하나씩 끈다.
    foreach ($p in $devApps) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-QOk "dev.ps1 앱 프로세스를 껐습니다 (PID $pids)"
  } else {
    Write-QWarn "dev.ps1 로 띄운 앱이 아직 떠 있습니다 (PID $pids) — 그 창에서 Ctrl+C, 또는 stop.ps1 -KillDev"
  }
}

if ($DeleteData) { Write-QOk '컨테이너와 앱 DB 를 지웠습니다. 다음 start.ps1 은 빈 DB 에 마이그레이션부터 새로 합니다.' }
elseif ($Keep) { Write-QOk '멈췄습니다. 다시 켜기: .\scripts\personal\start.ps1' }
else { Write-QOk '껐습니다(데이터는 남음). 다시 켜기: .\scripts\personal\start.ps1' }
exit 0
