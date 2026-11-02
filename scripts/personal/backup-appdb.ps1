<#
.SYNOPSIS
  앱 DB(PostgreSQL) 백업 — 덤프(.dump)와 상태 키 파일(.state.csv)을 한 쌍으로 만든다(할 일 ①-29).

.DESCRIPTION
  같은 이름 규칙(appdb-<날짜-시각, 초까지>)으로 파일 둘을 만든다.
    1) appdb-<yyyyMMdd-HHmmss>.dump       pg_dump -Fc 한 파일(복원은 pg_restore). 외부 시세 캐시 표(data_cache)의 줄은 뺀다.
    2) appdb-<yyyyMMdd-HHmmss>.state.csv  data_cache 에서 **다시 만들 수 없거나 비싼 상태 키**(접두사 목록은 _appdb-state.ps1)만 골라 낸 CSV.
                                          복원은 restore-appdb-state.ps1 (pg_restore 로 표 정의를 만든 **뒤에** 돌린다).
  두 파일은 한 쌍이다. 이미 같은 이름의 파일이 있으면 만들지 않고 멈춘다(덮어쓰지 않음). 상태 파일을 못 만들면 방금 만든 덤프의 이름을
  .dump.incomplete 로 바꾸고 실패로 끝낸다 — 짝이 없는 덤프를 복원에 쓰면 상태 키가 빠진 채로 끝나기 때문이다.

  왜 data_cache 의 줄을 덤프에서 빼나
    data_cache 의 대부분은 다시 받을 수 있는 외부 시세 캐시(캔들 · 지표 · 재무)인데, 지우는 코드가 없던 때 쌓인 줄이 백업 · 옮기기에
    그대로 딸려 갔다(2026-10-25 노트북 → 데스크톱 옮김에 122줄). 그래서 **표 정의(스키마)는 두고 줄만 뺀다**(--exclude-table-data).
    덤프를 복원하면 data_cache 는 빈 표로 돌아오고, 외부 시세 캐시는 앱이 다시 채운다.

  그런데 같은 표에 다시 만들 수 없는 상태 키가 섞여 있다 — quant:cycle_log:{uid}(자동매매 사이클 이력 · 최근 50개 · 30일) ·
  quant:reconcile:baseline:{uid}:{env}(정합성 기준선 · 365일) · quant:reconcile:latest:{uid}, 그리고 계산이 비싼 model_compare:*(모델 비교 결과 · 7일).
  집 ↔ 학원으로 앱 DB 를 옮겨 자동매매를 시험할 때 이 키가 복원 뒤에도 남아야 하므로, pg_dump 에는 행 단위 필터가 없어
  **psql \copy (SELECT ... WHERE starts_with(key, 접두사) OR ...)** 로 따로 내보낸다. 형식은 CSV(\copy ... FORMAT csv, HEADER) — 값(JSON)의
  쉼표 · 따옴표 · 백슬래시를 인용 규칙으로 그대로 왕복시키고, 데이터를 PowerShell 파이프에 태우지 않아(컨테이너 /tmp 파일 + docker cp)
  한글이 깨지지 않는다. 열: key, id, data, updated_at.

  덤프에 안 들어가는 것(복원하면 빈다) — 접두사 목록 밖의 키(ai_predict:* 는 읽는 쪽이 3시간 안의 값만 쓰므로 복원 때 이미 만료) 와 외부 시세 캐시.
  -IncludeDataCache 를 주면 표 전체가 덤프에 이미 들어가므로 상태 파일은 만들지 않는다(이때 외부 시세 캐시 줄도 함께 딸려 간다).

  앱을 끄고 백업하는 것을 권장한다 — 앱 · 워커 · 비트가 도는 중이면 자동매매 사이클이 덤프와 상태 파일 사이에 끼어들 수 있다
  (덤프는 한 시점의 스냅샷이고 상태 파일은 그 직후 따로 읽는다). 켜져 있으면 경고만 하고 계속한다.

  민감한 파일 — 상태 파일(.state.csv)도 .dump 와 똑같이 민감하다. 사용자 ID · 보유 종목 · 수량 · 가격 · 평가금액 · 주문 이력이 평문으로 들어 있다.
    - 저장소 · 클라우드 동기화 폴더(OneDrive · Google Drive 등)에 두지 않는다. 저장소 안에 만들면 .gitignore 에 걸리는지 git 으로 확인하고(.dump · .state.csv · .dump.incomplete 이름 셋 모두), 안 걸리면 멈춘다.
    - USB 로 옮길 때는 파일마다 scripts\protect_database_backup.py 로 암호화한다(바이트 단위라 .state.csv 도 된다).
    - 복원은 내가 만든 파일만. 암호화 키 파일(secrets)은 백업과 같은 USB 에 두지 않는다.
    - 출력 폴더를 만들 때(또는 기본 폴더일 때) 폴더 접근 권한을 현재 사용자 · SYSTEM · Administrators 로 줄인다(icacls). 저장소 · 내 프로필 밖
      (USB · 드라이브 루트 · 네트워크)는 다른 PC 에서 같은 계정이 아니라 잠길 수 있어 건드리지 않는다.

  쓰는 것: 컨테이너 fin-ai-postgres(start.ps1 로 켜 둔 상태). DB 사용자 · 이름은 컨테이너 안의 환경변수를 쓰므로 비밀값을 읽지 않는다.
  컨테이너 /tmp 의 임시 파일은 파일 이름에 시각과 PID 를 넣고, 성공 · 실패와 상관없이 마지막에 지운다.
  출력: 기본 data\local-run\appdb-backup\appdb-<날짜-시각>.dump 와 .state.csv (data\local-run\ 은 gitignore).

.PARAMETER OutDir
  백업 파일을 둘 폴더. 기본은 저장소 data\local-run\appdb-backup. 상대 경로는 지금 PowerShell 위치 기준이다.

.PARAMETER IncludeDataCache
  data_cache 의 줄도 덤프에 함께 담는다(이때 상태 파일은 따로 만들지 않는다).

.PARAMETER Database
  백업할 DB 이름. 기본은 컨테이너의 $POSTGRES_DB(앱 DB). 임시 DB 로 왕복 시험을 할 때만 바꾼다(소문자 · 숫자 · 밑줄).

.PARAMETER DryRun
  실행하지 않고 어떤 명령을 쓸지만 보여 준다(출력 폴더 점검은 한다 — 읽기만 한다).

.EXAMPLE
  .\scripts\personal\backup-appdb.ps1
.EXAMPLE
  .\scripts\personal\backup-appdb.ps1 -IncludeDataCache
#>
[CmdletBinding()]
param(
  [string]$OutDir = '',
  [switch]$IncludeDataCache,
  [string]$Database = '',
  [switch]$DryRun
)

. "$PSScriptRoot\_common.ps1"
. "$PSScriptRoot\_appdb-state.ps1"

$pg = 'fin-ai-postgres'
$defaultOutDir = Join-Path $QRoot 'data\local-run\appdb-backup'
if (-not $OutDir) { $OutDir = $defaultOutDir }
# 상대 경로는 PowerShell 의 현재 위치 기준으로 푼다(.NET 의 GetFullPath 는 프로세스 작업 폴더를 쓰므로 다를 수 있다).
$OutDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutDir)
if ($OutDir.Length -gt 3) { $OutDir = $OutDir.TrimEnd('\') }   # 드라이브 루트(D:\)는 끝의 \ 를 두어야 한다 — D: 는 그 드라이브의 현재 폴더라는 뜻이다
$isDefaultOutDir = ($OutDir -ieq $defaultOutDir)

# 접두사 목록은 _appdb-state.ps1 한 곳에만 있다(복원도 같은 파일을 읽는다). SQL 에 그대로 들어가므로 먼저 검사한다.
if (-not (Test-QStateKeyPrefixes)) { exit 1 }
$stateCond = Get-QStateKeyCondition
$prefixText = ($QStateKeyPrefixes -join ', ')

# -Database 는 sh 명령에 그대로 들어가므로 이름 규칙을 지킨 것만 받는다. 컨테이너 안에서 POSTGRES_DB 를 덮어써 풀리게 한다(호스트로 읽어 오지 않음).
if ($Database -and -not (Test-QAppDbName $Database)) { Write-QFail "-Database 는 소문자 · 숫자 · 밑줄만 쓸 수 있습니다(63자 이하): $Database"; exit 1 }
$dbOverride = ''
if ($Database) { $dbOverride = "POSTGRES_DB=${Database}; " }

# ------------------------------------------------------------------------------
# 출력 폴더 점검 — 읽기만 한다(-DryRun 에서도 한다)
# ------------------------------------------------------------------------------

function Get-QSyncFolderHit {
  # 동기화 폴더(OneDrive · Google Drive · Dropbox 등)로 보이면 걸린 이름을, 아니면 빈 문자열을 돌려준다.
  param([string]$Path)
  foreach ($root in @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial)) {
    if ($root -and (($Path + '\').StartsWith($root.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase))) { return "OneDrive($root)" }
  }
  $m = [regex]::Match($Path, '(?i)(OneDrive|Google\s?Drive|구글\s?드라이브|내\s?드라이브|My\s?Drive|Dropbox|iCloud|pCloud|Nextcloud|MYBOX|Box\s?Sync|Sync\.com)')
  if ($m.Success) { return $m.Value }
  return ''
}

function Test-QUnderPath {
  param([string]$Path, [string]$Root)
  if (-not $Root) { return $false }
  return (($Path + '\').StartsWith($Root.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase))
}

$syncHit = Get-QSyncFolderHit $OutDir
if ($syncHit) {
  Write-QWarn "출력 폴더가 클라우드 동기화 폴더로 보입니다($syncHit) — 백업 파일(사용자 ID · 보유 종목 · 주문 이력이 평문)이 클라우드로 올라갑니다. 동기화 밖 폴더를 -OutDir 로 주세요."
}

# 저장소 안에 만들면 .gitignore 에 걸리는지 확인한다 — 걸리지 않으면 git add . 한 번에 Public 저장소로 올라갈 수 있다.
# 폴더가 아니라 실제 파일 이름(슬래시 없음)으로 묻는다: 폴더 경로에 슬래시를 붙이면 가짜 매치가 날 수 있다(.gitignore 의 주석 참고).
if (Test-QUnderPath $OutDir $QRoot) {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-QWarn 'git 명령이 없어 출력 폴더가 .gitignore 에 걸리는지 확인하지 못했습니다 — 저장소 안이면 직접 확인하세요.'
  } else {
    # .dump.incomplete(상태 내보내기가 실패했을 때 덤프가 바뀌는 이름)도 같은 평문 덤프이므로 함께 묻는다 — *.dump 에는 걸리지 않는다.
    foreach ($sample in @('appdb-00000000-000000.dump', 'appdb-00000000-000000.state.csv', 'appdb-00000000-000000.dump.incomplete')) {
      $rel = (Join-Path $OutDir $sample).Substring($QRoot.Length + 1)
      & git -C $QRoot check-ignore -q -- $rel
      $ignoreCode = $LASTEXITCODE
      if ($ignoreCode -ne 0) {
        if ($ignoreCode -eq 1) { Write-QFail "출력 폴더가 저장소 안인데 이 이름이 .gitignore 에 걸리지 않습니다($rel) — 커밋될 수 있어 멈춥니다. 기본 폴더(data\local-run\appdb-backup)를 쓰거나 저장소 밖을 -OutDir 로 주세요." }
        else { Write-QFail "git check-ignore 가 실패했습니다(종료 코드 $ignoreCode) — 출력 폴더가 .gitignore 에 걸리는지 확인하지 못해 멈춥니다." }
        exit 1
      }
    }
  }
}

# 덤프에서 뺀 줄을 어떻게 다루는지 · 컨테이너 안 임시 파일 이름. 시각은 한 번만 계산해 두 파일 이름과 임시 파일에 같이 쓴다
# (따로 계산하면 초가 넘어갈 때 짝이 어긋난다).
$stamp = Get-Date -Format $QAppDbStampFormat
$outDump = Join-Path $OutDir "appdb-${stamp}.dump"
$outState = Join-Path $OutDir "appdb-${stamp}.state.csv"
$remoteDump = "/tmp/appdb-${stamp}-${PID}.dump"
$remoteState = "/tmp/appdb-${stamp}-${PID}.state.csv"

# 줄을 뺄 표. 외부 시세 캐시 정리(app/services/data_cache.py)와 같은 표다 — 이름을 바꾸면 tests/test_data_cache_prune.py 가 알려 준다.
$dumpArgs = '-Fc'
if (-not $IncludeDataCache) { $dumpArgs += ' --exclude-table-data=data_cache' }
# $POSTGRES_USER · $POSTGRES_DB 는 컨테이너 안에서 풀리도록 작은따옴표로 넘긴다(호스트에서 풀면 비어 버린다).
$remoteCmd = 'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB ' + $dumpArgs + ' -f ' + $remoteDump
$remoteCmd = $dbOverride + $remoteCmd

# 상태 키 내보내기 — 덤프에서 뺀 data_cache 의 줄 가운데 접두사 목록에 드는 것만. SQL 은 stdin 으로 보낸다(ASCII 만 — 5.1 파이프 인코딩 때문).
# starts_with 는 LIKE 와 달리 와일드카드(% _) 걱정이 없다. \copy 는 한 줄이어야 한다. 접두사별 줄 수(PFX)를 먼저 찍는다.
# -v VERBOSITY=terse · SHOW_CONTEXT=never : 오류 메시지에 값(JSON)이 딸려 나오지 않게 한다.
$exportState = -not $IncludeDataCache
$stateSql = @'
@PFXSQL@
\copy (SELECT @COLS@ FROM data_cache WHERE @COND@ ORDER BY key) TO '@REMOTE@' WITH (FORMAT csv, HEADER)
'@
$pfxLines = @($QStateKeyPrefixes | ForEach-Object { "SELECT 'PFX|${_}|' || count(*) FROM data_cache WHERE starts_with(key, '${_}');" })
$stateSql = $stateSql.Replace('@PFXSQL@', ($pfxLines -join "`n")).Replace('@COLS@', $QStateCsvColumns).Replace('@COND@', $stateCond).Replace('@REMOTE@', $remoteState).Replace("`r`n", "`n")
$stateCmd = $dbOverride + 'PGCLIENTENCODING=UTF8 psql -U $POSTGRES_USER -d $POSTGRES_DB -X -A -t -v ON_ERROR_STOP=1 -v VERBOSITY=terse -v SHOW_CONTEXT=never -f -'

Write-QTitle '앱 DB 백업'
if ($IncludeDataCache) {
  Write-QWarn 'data_cache 의 줄도 덤프에 함께 담습니다(-IncludeDataCache) — 외부 시세 캐시 줄이 딸려 갑니다.'
  Write-QInfo '표 전체가 덤프에 들어가므로 상태 파일(.state.csv)은 따로 만들지 않습니다.'
} else {
  Write-QInfo "data_cache 의 줄은 덤프에서 뺍니다(표 정의만 둠) — 대신 상태 키($prefixText)만 .state.csv 로 따로 내보냅니다."
  Write-QInfo 'ai_predict:* (읽는 쪽이 3시간 안의 값만 씀 — 복원 때 이미 만료) 와 외부 시세 캐시는 복원하면 빈 채로 돌아옵니다(앱이 다시 채움).'
}
Write-QInfo "출력 폴더: $OutDir"
$fileNames = "appdb-${stamp}.dump"
if ($exportState) { $fileNames += " + appdb-${stamp}.state.csv" }
Write-QInfo "파일 이름: $fileNames"
Write-QInfo '앱을 끄고(.\scripts\personal\stop.ps1) 백업하는 것을 권장합니다 — 자동매매 사이클이 도는 중이면 덤프와 상태 파일의 시점이 어긋날 수 있습니다.'
Write-QInfo "컨테이너 안 명령(덤프): $remoteCmd"
if ($exportState) {
  Write-QInfo "컨테이너 안 명령(상태 키): $stateCmd"
  $stateSqlOneLine = $stateSql.Replace("`n", ' ')
  Write-QInfo "  stdin SQL: $stateSqlOneLine"
}
if ($DryRun) { Write-QOk '-DryRun — 실행하지 않았습니다.'; exit 0 }

if (-not (Test-QDocker)) { exit 1 }
$state = Get-QContainerState $pg
if ($state.State -ne 'running') { Write-QFail "$pg 가 켜져 있지 않습니다(상태: $($state.State)) — .\scripts\personal\start.ps1 로 먼저 켜세요."; exit 1 }
if (-not $Database) {
  $running = @(@('fin-ai-app', 'fin-ai-celery-worker', 'fin-ai-celery-beat') | Where-Object { (Get-QContainerState $_).State -eq 'running' })
  if ($running.Count -gt 0) {
    Write-QWarn "앱 · 워커 · 비트가 켜져 있습니다($($running -join ', ')) — 앱을 끄고(.\scripts\personal\stop.ps1) 백업하는 것을 권장합니다. 사이클이 도는 중이면 덤프와 상태 파일의 시점이 어긋날 수 있습니다."
  }
}

# ------------------------------------------------------------------------------
# 출력 폴더 만들기 · 권한 줄이기 · 이름 충돌 확인
# ------------------------------------------------------------------------------
$outDirExisted = Test-Path -LiteralPath $OutDir -PathType Container
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# 폴더 권한을 현재 사용자 · SYSTEM · Administrators 로 줄인다. 계정은 이름이 아니라 SID(*S-...)로 준다 — 도메인 · 표시 언어와 상관없이 풀린다.
# 만든 직후이거나 기본 폴더일 때만 한다(내가 쓰던 다른 폴더의 권한을 건드리지 않음). 저장소 · 내 프로필 밖(USB · 드라이브 루트 · 네트워크)은
# 다른 PC 에서 같은 계정(SID)이 아니라 잠길 수 있고 exFAT 은 권한이 없으므로 건드리지 않는다. 실패하면 경고만 한다.
$aclTarget = ((-not $outDirExisted) -or $isDefaultOutDir) -and ((Test-QUnderPath $OutDir $QRoot) -or (Test-QUnderPath $OutDir $env:USERPROFILE))
if ($aclTarget) {
  $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  & icacls $OutDir /inheritance:r /grant:r "*${me}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
  if ($LASTEXITCODE -ne 0) { Write-QWarn "출력 폴더 권한을 줄이지 못했습니다(icacls 종료 코드 $LASTEXITCODE) — 폴더가 다른 사용자에게 열려 있을 수 있습니다: $OutDir" }
  else { Write-QInfo '출력 폴더 권한: 현재 사용자 · SYSTEM · Administrators 만 접근(상속 끊음)' }
} else {
  Write-QInfo '출력 폴더 권한은 건드리지 않았습니다(기존 폴더이거나 저장소 · 내 프로필 밖) — 민감한 파일이 들어가는 폴더이니 접근 권한을 직접 확인하세요.'
}

foreach ($f in @($outDump, $outState, "$outDump.incomplete")) {
  if (Test-Path -LiteralPath $f) { Write-QFail "이미 있는 파일입니다 — 덮어쓰지 않습니다: $f (잠시 뒤 다시 실행하세요)"; exit 1 }
}

# ------------------------------------------------------------------------------
# 실행 — 컨테이너 /tmp 의 임시 파일은 성공 · 실패와 상관없이 마지막에 지운다
# ------------------------------------------------------------------------------
$stateOut = @()
try {
  & docker exec $pg sh -c $remoteCmd
  if ($LASTEXITCODE -ne 0) { Write-QFail "pg_dump 가 실패했습니다(종료 코드 $LASTEXITCODE)."; exit 1 }
  & docker cp "${pg}:${remoteDump}" $outDump | Out-Null
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $outDump)) {
    Write-QFail '백업 파일을 컨테이너 밖으로 꺼내지 못했습니다(docker cp).'
    Remove-Item -LiteralPath $outDump -Force -ErrorAction SilentlyContinue
    exit 1
  }

  if ($exportState) {
    $stateOut = @($stateSql | & docker exec -i $pg sh -c $stateCmd)
    $exportCode = $LASTEXITCODE
    $cpCode = 0
    if ($exportCode -eq 0) {
      & docker cp "${pg}:${remoteState}" $outState | Out-Null
      $cpCode = $LASTEXITCODE
    }
    if ($exportCode -ne 0 -or $cpCode -ne 0 -or -not (Test-Path -LiteralPath $outState)) {
      # 덤프는 만들어졌지만 상태 키가 빠지면 이 백업의 목적(상태 보존)을 못 채운다 → 덤프를 .incomplete 로 바꿔 복원에 못 쓰게 하고 실패로 끝낸다.
      Remove-Item -LiteralPath $outState -Force -ErrorAction SilentlyContinue
      try {
        Rename-Item -LiteralPath $outDump -NewName "appdb-${stamp}.dump.incomplete" -ErrorAction Stop
        $renamed = "덤프는 appdb-${stamp}.dump.incomplete 로 이름을 바꿔 두었습니다(복원에 쓰지 마세요)."
      } catch {
        $renamed = "덤프 이름을 바꾸지 못했습니다 — $outDump 는 상태 키가 없는 불완전한 백업이니 지우세요."
      }
      if ($exportCode -ne 0) { Write-QFail "백업 실패 — 상태 키 내보내기가 실패했습니다(종료 코드 $exportCode). 위 psql 오류를 보세요." }
      else { Write-QFail '백업 실패 — 상태 키 파일을 컨테이너 밖으로 꺼내지 못했습니다(docker cp).' }
      Write-QInfo $renamed
      exit 1
    }
  }
} finally {
  & docker exec $pg rm -f $remoteDump $remoteState | Out-Null
}

# ------------------------------------------------------------------------------
# 결과 — 두 파일이 모두 만들어진 뒤에만 「백업 완료」
# ------------------------------------------------------------------------------
$kb = [math]::Round((Get-Item -LiteralPath $outDump).Length / 1KB, 1)
Write-QOk "덤프 — $outDump (${kb}KB)"
if ($exportState) {
  # 줄 수는 psql 이 알려 주는 「COPY n」 에서 읽는다(CSV 는 따옴표 안에 개행이 있을 수 있어 호스트에서 줄을 세면 틀린다).
  $outText = ($stateOut -join "`n")
  $copyMatch = [regex]::Match($outText, '(?m)^COPY (\d+)')
  $stateBytes = (Get-Item -LiteralPath $outState).Length
  $skb = [math]::Round($stateBytes / 1KB, 1)
  if ($copyMatch.Success) { $rowsText = "$($copyMatch.Groups[1].Value) 줄" } else { $rowsText = '줄 수 미확인' }
  Write-QOk "상태 키 파일 — $outState ($rowsText, ${skb}KB)"
  foreach ($pm in [regex]::Matches($outText, '(?m)^PFX\|([^|]+)\|(\d+)\s*$')) {
    Write-QInfo "  $($pm.Groups[1].Value)* : $($pm.Groups[2].Value) 줄"
  }
  if ($copyMatch.Success -and $copyMatch.Groups[1].Value -eq '0') {
    Write-QWarn "접두사($prefixText)로 시작하는 줄이 없습니다 — 자동매매를 한 번도 안 돌린 DB 이면 정상입니다."
  }
  if ($stateBytes -gt ($QStateFileWarnMB * 1MB)) {
    Write-QWarn "상태 파일이 ${QStateFileWarnMB}MB 를 넘습니다(${skb}KB) — model_compare:* 값이 큰지 줄 수와 크기를 보세요."
  }
  Write-QOk "백업 완료 — 한 쌍: appdb-${stamp}.dump + appdb-${stamp}.state.csv"
  Write-QInfo '복원 순서: 1) pg_restore 로 덤프 풀기  2) .\scripts\personal\restore-appdb-state.ps1 (확인) → -Apply (적용)'
} else {
  Write-QOk "백업 완료 — appdb-${stamp}.dump (data_cache 전체 포함 — 상태 파일은 따로 없음)"
}
Write-QAppDbSensitiveNotice -Mode backup
exit 0
