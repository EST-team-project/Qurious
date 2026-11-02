<#
.SYNOPSIS
  백업한 상태 키 파일(appdb-*.state.csv)을 앱 DB 의 data_cache 에 되돌린다(할 일 ①-29). 기본은 확인만(-DryRun), 적용은 -Apply.

.DESCRIPTION
  backup-appdb.ps1 이 덤프(.dump)와 함께 만든 상태 파일(자동매매 사이클 이력 quant:cycle_log:* · 정합성 기준선 quant:reconcile:* ·
  모델 비교 결과 model_compare:* 등, 접두사 목록은 _appdb-state.ps1)을 읽어 data_cache 에 **upsert** 한다. 줄마다 셋 중 하나가 된다.
    - 새로 넣음      : 대상 DB 에 그 키가 없다. 파일에 적힌 id · data · updated_at 그대로 넣는다(updated_at 을 now() 로 넣으면 30일 나이 판정이 다시 시작된다).
    - 갱신           : 키가 있고 대상의 updated_at 이 파일보다 같거나 오래됐다. data · updated_at 을 파일 값으로 바꾼다. 그 줄의 id 는 그대로 둔다.
    - 대상이 더 최근이라 지킴 : 키가 있고 대상의 updated_at 이 파일보다 **더 최근**이다. 덮어쓰지 않는다(구버전 값으로 되돌아가는 오류 방지).
  지킨 줄의 키는 목록으로 보여 준다. data_cache.id 를 참조하는 외래 키는 없다(개발 DB 에서 확인).

  판정 기준을 알아 둘 것
    - quant:cycle_log:{uid} 는 최근 50개 이력이 **값 하나**에 통째로 들어 있다. 지키면 파일 쪽 사이클 이력 전체가 대상에 들어오지 않는다(두 값을 합치지 않는다).
    - 판정은 줄의 updated_at 을 비교한다. 두 PC 의 시계가 어긋나 있으면(예: 한쪽이 몇 분 느림) 어느 쪽이 더 최근인지 틀릴 수 있다.
    - 같은 파일을 두 번 -Apply 하면 두 번째에는 모든 줄이 「갱신」(값이 같으므로 바뀌는 것은 없다)으로 나온다. 같은 값이면 updated_at 도 같기 때문이다.

  순서 — 반드시 이 순서로 한다
    1) pg_restore 로 덤프를 푼다. 표 정의가 만들어지고, data_cache 는 줄이 빠진 빈 표로 돌아온다(백업이 줄을 뺐으므로).
       표가 없으면 이 스크립트는 「pg_restore 먼저」 라고 알리고 멈춘다.
    2) 이 스크립트를 -DryRun(기본)으로 돌려 몇 줄을 넣고 · 갱신하고 · 지킬지 본다. DB 안에서 -Apply 와 똑같은 INSERT 를 한 트랜잭션으로 실행한 뒤
       마지막에 ROLLBACK 한다(data_cache 는 바뀌지 않고, 제약 위반은 미리 드러난다).
    3) 맞으면 -Apply 로 적용한다(한 트랜잭션 — 하나라도 실패하면 아무것도 바뀌지 않는다).

  어느 파일을 쓰나
    - 아무것도 안 주면 BackupDir 에서 appdb-<yyyyMMdd-HHmmss>.state.csv 이름이 가장 나중인 것을 고르고, 고른 파일 이름과 시각을 보여 준다.
    - -Stamp 20261102-210015 : BackupDir 의 appdb-20261102-210015.state.csv.
    - -DumpFile <경로>\appdb-20261102-210015.dump : 그 덤프의 짝(같은 폴더의 같은 시각 .state.csv).
    - -StateFile <경로> : 파일을 직접 지정. 셋은 함께 쓸 수 없다.

  안전장치
    - 파일 첫 줄이 key,id,data,updated_at 이어야 한다. 아니면 멈춘다 — 암호화한 파일이면 먼저 복호화하라는 안내를 함께 보인다.
    - 파일의 모든 키가 접두사 목록에 들어야 한다. 하나라도 밖이면 멈춘다(엉뚱한 파일을 넣는 사고 방지 · 외부 시세 캐시를 덮지 못함).
    - 같은 키가 파일에 두 번 있으면 멈춘다. JSON 이 깨진 줄이 있으면 jsonb 로 받는 단계에서 멈춘다.
    - -DryRun 도 같은 INSERT 를 실행하므로, 앱이 같은 키를 쓰는 순간과 겹치면 ROLLBACK 까지 그 줄 잠금이 잠깐 걸린다(몇 밀리초). 앱을 끄고 돌리면 없다.
    - 집계(새로 · 갱신 · 지킴)가 실제 upsert 결과와 다르면(실행 중에 앱이 같은 키를 바꾼 경우) 멈추고 되돌린다.
    - 앱 · 워커 · 비트(fin-ai-app · fin-ai-celery-worker · fin-ai-celery-beat) 중 하나라도 켜져 있으면 -Apply 는 **멈춘다**(아무것도 바꾸지 않고 종료 코드 1).
      자동매매 사이클이 도는 중에 되돌리면 되돌린 줄과 겹쳐 쓸 수 있기 때문이다. 앱 · celery 를 끄고(.\scripts\personal\stop.ps1) 다시 실행하거나,
      겹쳐 쓸 위험을 감수하려면 -Force 를 붙인다(경고만 하고 진행). -DryRun 은 막지 않고 경고만 한다.
      컨테이너가 없거나 꺼져 있으면 막지 않고 그 상태를 한 줄로 보여 준다. -Database(임시 DB)는 앱이 쓰는 DB 가 아니라 이 점검을 하지 않는다.
    - psql 오류에서 값이 새지 않게 -v VERBOSITY=terse · SHOW_CONTEXT=never 로 부른다(깨진 JSON 줄의 내용이 오류 메시지에 찍히지 않음).

  민감한 파일 — 상태 파일(.state.csv)도 .dump 와 똑같이 민감하다. 사용자 ID · 보유 종목 · 수량 · 가격 · 평가금액 · 주문 이력이 평문으로 들어 있다.
    - 복원은 **내가 만든 파일만** 쓴다. 남이 준 · 출처를 모르는 파일은 쓰지 않는다(자동매매 상태가 그 파일 값으로 바뀐다).
    - USB 로 옮긴 파일은 scripts\protect_database_backup.py 로 암호화했을 수 있다 — 이 스크립트에 암호화한 파일을 주면 멈추므로 먼저 --decrypt 로 풀어 쓴다.
    - 암호화 키 파일(secrets)은 백업과 같은 USB 에 두지 않는다.

  쓰는 것: 컨테이너 fin-ai-postgres. DB 사용자 · 이름은 컨테이너 안의 환경변수를 쓰므로 비밀값을 읽지 않는다.
  상태 파일은 컨테이너 /tmp 로 docker cp 해서 \copy 로 읽는다(데이터를 PowerShell 파이프에 태우지 않아 한글이 깨지지 않음).
  /tmp 의 임시 파일은 성공 · 실패와 상관없이 마지막에 지운다.

.PARAMETER StateFile
  되돌릴 상태 파일(.state.csv)을 직접 지정한다. -Stamp · -DumpFile 과 함께 쓸 수 없다.

.PARAMETER BackupDir
  파일을 찾을 폴더(자동 선택 · -Stamp). 기본은 저장소 data\local-run\appdb-backup.

.PARAMETER Stamp
  백업 시각 appdb-<여기>.state.csv (형식 yyyyMMdd-HHmmss). BackupDir 에서 그 짝 파일을 찾는다.

.PARAMETER DumpFile
  덤프 파일(appdb-<시각>.dump)의 경로. 같은 폴더의 같은 시각 .state.csv 를 짝으로 쓴다(덤프 파일이 지금 없어도 이름만 맞으면 된다).

.PARAMETER Database
  되돌릴 DB 이름. 기본은 컨테이너의 $POSTGRES_DB(앱 DB). 임시 DB 로 왕복 시험을 할 때만 바꾼다(소문자 · 숫자 · 밑줄).

.PARAMETER Apply
  실제로 data_cache 에 적용한다. 없으면 확인만 하고 되돌린다.

.PARAMETER DryRun
  확인만 한다(기본 동작과 같다). -Apply 와 함께 쓸 수 없다.

.PARAMETER Force
  앱 · 워커 · 비트가 켜져 있어도 -Apply 를 멈추지 않고 경고만 한 뒤 진행한다. 자동매매 사이클이 도는 중이면 되돌린 줄과 겹쳐 쓸 수 있으니,
  끄고(.\scripts\personal\stop.ps1) 하는 것이 안전하다. -DryRun · -Database 에는 영향이 없다.

.EXAMPLE
  .\scripts\personal\restore-appdb-state.ps1
.EXAMPLE
  .\scripts\personal\restore-appdb-state.ps1 -Apply
.EXAMPLE
  .\scripts\personal\restore-appdb-state.ps1 -Apply -Force     # 앱이 켜져 있어도 감수하고 적용
.EXAMPLE
  .\scripts\personal\restore-appdb-state.ps1 -Stamp 20261102-210015 -Apply
.EXAMPLE
  .\scripts\personal\restore-appdb-state.ps1 -StateFile D:\appdb-20261102-210015.state.csv -Apply
#>
[CmdletBinding()]
param(
  [string]$StateFile = '',
  [string]$BackupDir = '',
  [string]$Stamp = '',
  [string]$DumpFile = '',
  [string]$Database = '',
  [switch]$Apply,
  [switch]$DryRun,
  [switch]$Force
)

. "$PSScriptRoot\_common.ps1"
. "$PSScriptRoot\_appdb-state.ps1"

$pg = 'fin-ai-postgres'
if (-not $BackupDir) { $BackupDir = Join-Path $QRoot 'data\local-run\appdb-backup' }

# 접두사 목록은 _appdb-state.ps1 한 곳에만 있다(백업도 같은 파일을 읽는다). SQL 에 그대로 들어가므로 먼저 검사한다.
if (-not (Test-QStateKeyPrefixes)) { exit 1 }
$stateCond = Get-QStateKeyCondition
$prefixText = ($QStateKeyPrefixes -join ', ')

# PowerShell 변수는 대소문자를 구분하지 않는다 — 매개변수 $Apply · $Stamp · $StateFile 과 이름만 다른 변수를 만들지 않는다.
$doApply = [bool]$Apply.IsPresent
$doForce = [bool]$Force.IsPresent
if ($doApply -and $DryRun) { Write-QFail '-Apply 와 -DryRun 은 함께 쓸 수 없습니다.'; exit 1 }
if ($Database -and -not (Test-QAppDbName $Database)) { Write-QFail "-Database 는 소문자 · 숫자 · 밑줄만 쓸 수 있습니다(63자 이하): $Database"; exit 1 }
$dbOverride = ''
if ($Database) { $dbOverride = "POSTGRES_DB=${Database}; " }
$selectors = 0
foreach ($v in @($StateFile, $Stamp, $DumpFile)) { if ($v) { $selectors++ } }
if ($selectors -gt 1) { Write-QFail '-StateFile · -Stamp · -DumpFile 은 하나만 줄 수 있습니다.'; exit 1 }
if ($Stamp -and ($Stamp -cnotmatch $QAppDbStampPattern)) { Write-QFail "-Stamp 는 yyyyMMdd-HHmmss 모양이어야 합니다(예: 20261102-210015): $Stamp"; exit 1 }

Write-QTitle '앱 DB 상태 키 복원'
Write-QAppDbSensitiveNotice -Mode restore

# ------------------------------------------------------------------------------
# 1. 상태 파일 고르기 — 고른 파일 이름 · 시각을 보여 준다
# ------------------------------------------------------------------------------
$pickedBy = '직접 지정'
if ($Stamp) {
  $statePath = Join-Path $BackupDir "appdb-${Stamp}.state.csv"
  $pickedBy = "-Stamp $Stamp"
} elseif ($DumpFile) {
  $dumpPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DumpFile)
  $dumpName = Split-Path -Leaf $dumpPath
  $dumpMatch = [regex]::Match($dumpName, '\Aappdb-(\d{8}-\d{6})\.dump\z')   # 대소문자를 가린다(RegexOptions 기본값)
  if (-not $dumpMatch.Success) { Write-QFail "-DumpFile 의 이름이 appdb-<yyyyMMdd-HHmmss>.dump 모양이 아닙니다: $dumpName"; exit 1 }
  $statePath = Join-Path (Split-Path -Parent $dumpPath) "appdb-$($dumpMatch.Groups[1].Value).state.csv"
  $pickedBy = "-DumpFile $dumpName 의 짝"
} elseif ($StateFile) {
  $statePath = $StateFile
} else {
  $found = @(Get-ChildItem -LiteralPath $BackupDir -Filter 'appdb-*.state.csv' -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -cmatch '\Aappdb-\d{8}-\d{6}\.state\.csv\z' } | Sort-Object Name -Descending)
  if ($found.Count -eq 0) { Write-QFail "상태 파일이 없습니다 — $BackupDir 에 appdb-<시각>.state.csv 가 없습니다. -StateFile 로 경로를 주세요."; exit 1 }
  $statePath = $found[0].FullName
  $pickedBy = "자동 선택(후보 $($found.Count)개 중 이름이 가장 나중인 것)"
  if ($found.Count -gt 1) {
    $otherNames = @($found | Select-Object -Skip 1 -First 3 | ForEach-Object { $_.Name })
    $otherMore = ''
    if ($found.Count -gt 4) { $otherMore = " 외 $($found.Count - 4)개" }
    Write-QInfo "다른 후보: $($otherNames -join ', ')$otherMore — 다른 것을 쓰려면 -Stamp 또는 -StateFile 을 주세요."
  }
}
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { Write-QFail "상태 파일을 찾을 수 없습니다: $statePath"; exit 1 }
$statePath = (Resolve-Path -LiteralPath $statePath).Path
$stateName = Split-Path -Leaf $statePath

# 파일 이름의 시각과 짝 덤프 — 이름이 규칙을 따를 때만
$nameMatch = [regex]::Match($stateName, '\Aappdb-(\d{8}-\d{6})\.state\.csv\z')
if ($nameMatch.Success) {
  $nameStamp = $nameMatch.Groups[1].Value
  $stampTime = [datetime]::MinValue
  if ([datetime]::TryParseExact($nameStamp, $QAppDbStampFormat, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::None, [ref]$stampTime)) {
    $ageHours = [math]::Round(((Get-Date) - $stampTime).TotalHours, 1)
    $ageText = "${ageHours}시간 전"
    if ($ageHours -lt 0) { $ageText = '이 PC 의 지금보다 미래 시각 — 두 PC 의 시계가 어긋났을 수 있습니다' }
    Write-QInfo "상태 파일: $stateName — 백업 시각 $($stampTime.ToString('yyyy-MM-dd HH:mm:ss')) ($ageText) · $pickedBy"
  } else {
    Write-QInfo "상태 파일: $stateName · $pickedBy"
  }
  $pairDump = Join-Path (Split-Path -Parent $statePath) "appdb-${nameStamp}.dump"
  if (Test-Path -LiteralPath $pairDump -PathType Leaf) { Write-QInfo "짝 덤프: appdb-${nameStamp}.dump 있음(같은 폴더)" }
  else { Write-QInfo "짝 덤프: appdb-${nameStamp}.dump 가 같은 폴더에 없습니다 — 덤프를 이미 풀었거나 다른 곳에 있으면 정상입니다. 같은 백업의 덤프를 pg_restore 했는지 확인하세요." }
} else {
  Write-QWarn "파일 이름이 appdb-<yyyyMMdd-HHmmss>.state.csv 모양이 아닙니다($stateName) — 백업 시각 · 짝 덤프를 확인할 수 없습니다. 내가 만든 파일인지 확인하세요."
  Write-QInfo "상태 파일: $statePath · $pickedBy"
}

# 첫 줄(열 이름) 확인 — 파일 핸들은 읽자마자 닫는다. 암호화한 파일이면 복호화하라고 알린다.
$firstLine = Get-QStateFileFirstLine -Path $statePath
if ($firstLine -cne $QStateCsvHeader) {
  if (Test-QEncryptedBackup -Path $statePath) {
    Write-QFail 'scripts\protect_database_backup.py 로 암호화한 파일입니다 — 먼저 복호화한 뒤 그 파일을 주세요:'
  } else {
    Write-QFail "상태 파일의 첫 줄이 '$QStateCsvHeader' 가 아닙니다 — backup-appdb.ps1 이 만든 .state.csv 가 맞는지 확인하세요. 암호화한 파일이면 먼저 복호화하세요:"
  }
  Write-QInfo '  python scripts\protect_database_backup.py --decrypt --input <암호화한 파일> --output <복호화한 파일>'
  exit 1
}
$sizeKb = [math]::Round((Get-Item -LiteralPath $statePath).Length / 1KB, 1)
Write-QInfo "상태 파일 크기: ${sizeKb}KB · 대상 접두사: $prefixText"
if ($doApply) { Write-QInfo '모드: -Apply (data_cache 에 적용)' } else { Write-QInfo '모드: -DryRun (기본 · 아무것도 바꾸지 않음 — 같은 INSERT 를 실행한 뒤 ROLLBACK)' }

# ------------------------------------------------------------------------------
# 2. SQL — stdin 으로 보낸다(ASCII 만 — 5.1 파이프 인코딩 때문. 오류 메시지는 영어로 두고 안내는 아래에서 한국어로 한다).
#    한 트랜잭션: 표 확인 → 임시 표에 올리기 → 접두사 · 중복 점검 → 줄마다 새로/갱신/지킴 판정 → upsert → 판정 대조 → 세기 → COMMIT / ROLLBACK.
#    -DryRun 도 upsert 를 실제로 실행하고 마지막만 ROLLBACK 한다(제약 위반을 미리 드러내려고).
# ------------------------------------------------------------------------------
$sql = @'
BEGIN;
DO $chk$
BEGIN
  IF to_regclass('public.data_cache') IS NULL THEN
    RAISE EXCEPTION 'data_cache table does not exist - run pg_restore first';
  END IF;
END
$chk$;
CREATE TEMP TABLE _qurious_state (key text NOT NULL, id uuid, data jsonb NOT NULL, updated_at timestamptz NOT NULL) ON COMMIT DROP;
\copy _qurious_state (key, id, data, updated_at) FROM '@REMOTE@' WITH (FORMAT csv, HEADER)
DO $chk$
BEGIN
  IF EXISTS (SELECT 1 FROM _qurious_state WHERE NOT @COND@) THEN
    RAISE EXCEPTION 'state file has keys outside the allowed prefixes - wrong file?';
  END IF;
  IF EXISTS (SELECT 1 FROM _qurious_state GROUP BY key HAVING count(*) > 1) THEN
    RAISE EXCEPTION 'state file has duplicate keys';
  END IF;
END
$chk$;
CREATE TEMP TABLE _qurious_plan ON COMMIT DROP AS SELECT s.key, CASE WHEN d.key IS NULL THEN 'new' WHEN d.updated_at <= s.updated_at THEN 'update' ELSE 'keep' END AS action FROM _qurious_state s LEFT JOIN data_cache d ON d.key = s.key;
CREATE TEMP TABLE _qurious_done (key text NOT NULL) ON COMMIT DROP;
WITH up AS (INSERT INTO data_cache (id, key, data, updated_at) SELECT COALESCE(id, gen_random_uuid()), key, data, updated_at FROM _qurious_state ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at WHERE data_cache.updated_at <= EXCLUDED.updated_at RETURNING key) INSERT INTO _qurious_done SELECT key FROM up;
DO $chk$
BEGIN
  IF EXISTS (SELECT 1 FROM _qurious_plan p WHERE (p.action = 'keep') = (p.key IN (SELECT key FROM _qurious_done))) THEN
    RAISE EXCEPTION 'target rows changed while restoring - the plan does not match the upsert; run again';
  END IF;
END
$chk$;
SELECT 'RESULT|' || count(*) || '|' || count(*) FILTER (WHERE action = 'new') || '|' || count(*) FILTER (WHERE action = 'update') || '|' || count(*) FILTER (WHERE action = 'keep') FROM _qurious_plan;
SELECT 'KEPT|' || regexp_replace(to_jsonb(key)::text, '[^ -~]', '?', 'g') FROM _qurious_plan WHERE action = 'keep' ORDER BY key LIMIT 50;
@END@
'@
# 마지막 한 줄만 다르다: -Apply 는 COMMIT, 아니면 ROLLBACK.
if ($doApply) { $endSql = 'COMMIT;' } else { $endSql = 'ROLLBACK;' }
# 컨테이너 /tmp 의 임시 파일 이름에 PID 와 시각을 넣는다(동시에 두 번 돌려도 겹치지 않게). $Stamp 매개변수와 이름이 겹치지 않게 tmpTag 를 쓴다.
$tmpTag = "$PID-$(Get-Date -Format 'yyyyMMddHHmmss')"
$remoteCsv = "/tmp/appdb-state-restore-${tmpTag}.csv"
# 5.1 의 here-string 은 파일의 줄바꿈을 따른다 — psql 에 CR 이 섞이지 않게 LF 로 맞춘다.
$sql = $sql.Replace('@COND@', $stateCond).Replace('@REMOTE@', $remoteCsv).Replace('@END@', $endSql).Replace("`r`n", "`n")
# -A -t : 표 머리글 · 정렬 없이 값만 찍는다(그래야 RESULT 줄이 줄 맨 앞에서 시작한다).
# -v VERBOSITY=terse -v SHOW_CONTEXT=never : 오류 메시지에 값(깨진 JSON 줄의 내용)이 딸려 나오지 않게 한다.
$psqlCmd = $dbOverride + 'PGCLIENTENCODING=UTF8 psql -U $POSTGRES_USER -d $POSTGRES_DB -X -A -t -v ON_ERROR_STOP=1 -v VERBOSITY=terse -v SHOW_CONTEXT=never -f -'

# ------------------------------------------------------------------------------
# 3. 컨테이너 확인
# ------------------------------------------------------------------------------
if (-not (Test-QDocker)) { exit 1 }
$state = Get-QContainerState $pg
if ($state.State -ne 'running') { Write-QFail "$pg 가 켜져 있지 않습니다(상태: $($state.State)) — .\scripts\personal\start.ps1 로 먼저 켜세요."; exit 1 }
# 앱 · 워커 · 비트가 켜져 있으면 -Apply 는 멈춘다 — 자동매매 사이클이 도는 중에 되돌리면 되돌린 줄과 겹쳐 쓸 수 있다(-Force 로 감수).
# -DryRun 은 아무것도 바꾸지 않으므로 막지 않고 알리기만 한다. -Database(임시 DB)는 앱이 쓰는 DB 가 아니라 보지 않는다.
# 컨테이너가 없거나 꺼져 있으면 막지 않는다(상태를 한 줄로 보여 준다). 이 점검은 파일을 컨테이너로 보내기(docker cp) 전에 한다.
if (-not $Database) {
  $appStates = @(@('fin-ai-app', 'fin-ai-celery-worker', 'fin-ai-celery-beat') | ForEach-Object { Get-QContainerState $_ })
  $running = @($appStates | Where-Object { $_.State -eq 'running' } | ForEach-Object { $_.Name })
  $appStateText = (@($appStates | ForEach-Object { "$($_.Name)=$($_.State)" })) -join ', '
  if ($running.Count -eq 0) {
    Write-QInfo "앱 · 워커 · 비트가 켜져 있지 않아($appStateText) 되돌린 줄과 겹쳐 쓸 위험이 없습니다 — 막지 않고 진행합니다."
  } elseif ($doApply -and -not $doForce) {
    Write-QFail "앱 · 워커 · 비트가 켜져 있어 -Apply 를 멈춥니다($($running -join ', ')) — 자동매매 사이클이 도는 중에 되돌리면 되돌린 줄과 겹쳐 쓸 수 있습니다."
    Write-QInfo '  앱 · celery 를 끄고(.\scripts\personal\stop.ps1) 다시 실행하세요. 겹쳐 쓸 위험을 감수하려면 -Force 를 붙이세요.'
    Write-QInfo '  아무것도 바꾸지 않았습니다(파일도 컨테이너로 보내지 않았습니다).'
    exit 1
  } elseif ($doApply) {
    Write-QWarn "앱 · 워커 · 비트가 켜져 있지만 -Force 라 진행합니다($($running -join ', ')) — 자동매매 사이클이 도는 중이면 되돌린 줄과 겹쳐 쓸 수 있습니다."
  } else {
    Write-QWarn "앱 · 워커 · 비트가 켜져 있습니다($($running -join ', ')) — -DryRun 은 아무것도 바꾸지 않아 진행합니다. -Apply 는 앱 · celery 를 끄고(.\scripts\personal\stop.ps1) 하세요(감수하려면 -Force)."
  }
}

# ------------------------------------------------------------------------------
# 4. 파일을 컨테이너로 보내 SQL 실행 — 임시 파일은 성공 · 실패와 상관없이 마지막에 지운다
# ------------------------------------------------------------------------------
$out = @()
$psqlCode = 1
try {
  & docker cp $statePath "${pg}:${remoteCsv}" | Out-Null
  if ($LASTEXITCODE -ne 0) { Write-QFail '상태 파일을 컨테이너로 보내지 못했습니다(docker cp).'; exit 1 }
  $out = @($sql | & docker exec -i $pg sh -c $psqlCmd)
  $psqlCode = $LASTEXITCODE
} finally {
  & docker exec $pg rm -f $remoteCsv | Out-Null
}
if ($psqlCode -ne 0) {
  Write-QFail "복원 SQL 이 실패했습니다(종료 코드 $psqlCode) — 위 psql 오류를 보세요(값은 가려져 있습니다). 한 트랜잭션이라 data_cache 는 바뀌지 않았습니다."
  Write-QInfo '흔한 원인: data_cache 표가 없음(pg_restore 먼저) · 파일에 접두사 밖 키 또는 중복 키 · JSON 이 깨진 줄 · 열 수가 다른 파일 · 실행 중 앱이 같은 키를 바꿈.'
  exit 1
}

# ------------------------------------------------------------------------------
# 5. 결과 읽기 — RESULT|전체|새로 넣음|갱신|지킴 , KEPT|"키"
# ------------------------------------------------------------------------------
$outText = ($out -join "`n")
$m = [regex]::Match($outText, '(?m)^RESULT\|(\d+)\|(\d+)\|(\d+)\|(\d+)\s*$')
if (-not $m.Success) { Write-QFail '결과를 읽지 못했습니다(psql 출력에 RESULT 줄이 없음).'; exit 1 }
$total = [int]$m.Groups[1].Value; $newRows = [int]$m.Groups[2].Value; $updRows = [int]$m.Groups[3].Value; $keepRows = [int]$m.Groups[4].Value
$keptKeys = @([regex]::Matches($outText, '(?m)^KEPT\|(.*?)\s*$') | ForEach-Object { $_.Groups[1].Value })

if ($doApply) {
  Write-QOk "적용 완료 — 파일 ${total}줄: 새로 넣음 ${newRows} · 갱신 ${updRows} · 대상이 더 최근이라 지킴 ${keepRows}   [new=$newRows update=$updRows keep=$keepRows]"
} else {
  Write-QOk "-DryRun — 아무것도 바꾸지 않았습니다(같은 INSERT 를 실행한 뒤 ROLLBACK). 파일 ${total}줄: 새로 넣을 ${newRows} · 갱신할 ${updRows} · 대상이 더 최근이라 지킬 ${keepRows}   [new=$newRows update=$updRows keep=$keepRows]"
  Write-QInfo '적용하려면 -Apply 를 붙여 다시 실행하세요.'
}
if ($keepRows -gt 0) {
  $more = ''
  if ($keepRows -gt $keptKeys.Count) { $more = " 외 $($keepRows - $keptKeys.Count)개" }
  Write-QWarn "대상 DB 쪽이 파일보다 더 최근이라 덮어쓰지 않은 줄 ${keepRows}개 — 대상 값이 그대로입니다: $($keptKeys -join ', ')$more"
  Write-QInfo '  - quant:cycle_log:{uid} 는 최근 50개 이력이 값 하나라서, 지키면 파일 쪽 사이클 이력 전체가 들어오지 않습니다(두 값을 합치지 않습니다).'
  Write-QInfo '  - 파일 값을 꼭 쓰고 싶으면 대상 DB 의 그 줄을 직접 지운 뒤 다시 실행하세요.'
}
# 시계 어긋남은 반대 방향으로도 해를 끼친다 — 대상 PC 시계가 느리면 대상의 진짜 최근 값이 오래된 것으로 읽혀 「갱신」(덮어쓰기)으로 세어진다.
# 그래서 지킴이 없어도, 비교한 줄(갱신 + 지킴)이 있으면 늘 알린다.
if (($updRows + $keepRows) -gt 0) {
  Write-QInfo '판정은 줄의 updated_at 비교입니다. 두 PC 의 시계가 어긋나 있으면 틀릴 수 있습니다 — 대상 PC 시계가 느리면 대상의 더 최근 값이 오래된 것으로 읽혀 「갱신」(덮어쓰기)이 되고, 빠르면 파일 값이 「지킴」으로 빠집니다.'
}
exit 0
