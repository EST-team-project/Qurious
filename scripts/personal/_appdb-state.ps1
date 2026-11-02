<#
.SYNOPSIS
  앱 DB 상태 키 백업 · 복원이 함께 쓰는 정의와 도우미(할 일 ①-29 후속) — 직접 실행하지 않는다.

.DESCRIPTION
  backup-appdb.ps1 · restore-appdb-state.ps1 이 첫머리에서 아래처럼 불러 쓴다(dot-source). _common.ps1 을 먼저 부른 뒤에 부른다.

      . "$PSScriptRoot\_appdb-state.ps1"

  접두사 목록 · CSV 머리글 · SQL 조건을 만드는 함수를 한곳에 둔다 — 백업과 복원이 따로 들고 있으면 한쪽만 고쳐 어긋난다.
  이 목록은 외부 시세 캐시 정리의 허용 목록(app/services/data_cache.py)과 겹치면 안 된다 — tests/test_data_cache_prune.py (TC-DCP-08)가 지킨다.

  이름 규칙 — 이 파일이 만드는 변수 · 함수는 Q 로 시작한다(_common.ps1 과 같은 규칙). PowerShell 변수는 대소문자를 구분하지 않아
  부른 스크립트의 매개변수(예: $StateFile)와 이름이 겹치면 덮어쓰므로, 겹칠 일이 없게 접두 글자를 붙여 둔다.

  Windows PowerShell 5.1 에서 돌아야 한다 — && · || · 삼항 · ?? 를 쓰지 않는다. 이 폴더의 .ps1 은 UTF-8 BOM 으로 저장한다.
#>

# ------------------------------------------------------------------------------
# 1. 상태 키 접두사 — 이 줄이 유일한 정의다
# ------------------------------------------------------------------------------
# 다시 만들 수 없거나 만드는 데 비싼 상태 · 결과 키만 담는다.
#   quant:          자동매매 사이클 이력(quant:cycle_log:*) · 정합성 기준선(quant:reconcile:baseline:*) · 최신 점검 결과 등. 다시 만들 수 없다.
#   model_compare:  모델 비교 계산 결과(model_compare:v1:*). 한 번에 10 ~ 30초가 들고, 앱은 7일 안의 것만 쓴다
#                   (app/services/model_compare_jobs.py 의 CACHE_TTL_HOURS = 24 * 7) — 복원해도 7일이 지난 값은 쓰이지 않는다.
# 일부러 뺀 것
#   ai_predict:     AI 예측. 읽는 쪽이 3시간(max_age_hours=3 — app/routes/ml.py · app/routes/stocks.py) 안의 값만 쓰므로
#                   옮겨 와 복원할 즈음에는 이미 만료된 값이다. 만료된 값을 옮겨 봐야 쓰이지 않고 파일만 커진다.
#   candles: · indicators: · fundamentals: 와 시세 키 — 외부 시세 캐시라 앱이 다시 받는다(정리 허용 목록).
# 접두사는 영문 · 숫자 · 밑줄 · 하이픈과 콜론만 쓴다(SQL 에 그대로 들어가므로 Test-QStateKeyPrefixes 가 검사한다).
$QStateKeyPrefixes = @('quant:', 'model_compare:')

# 상태 파일 첫 줄(열 이름). 백업의 \copy (SELECT key, id, data, updated_at ...) ... HEADER 가 만들고, 복원이 첫 줄로 확인한다.
$QStateCsvHeader = 'key,id,data,updated_at'
$QStateCsvColumns = $QStateCsvHeader.Replace(',', ', ')

# 백업 파일 이름의 시각(초까지) 형식과 모양. appdb-<시각>.dump · appdb-<시각>.state.csv 가 한 쌍이다. -cmatch 로 쓴다.
$QAppDbStampFormat = 'yyyyMMdd-HHmmss'
$QAppDbStampPattern = '\A\d{8}-\d{6}\z'

# 이 크기(MB)를 넘는 상태 파일은 알려 준다 — model_compare: 값이 커질 수 있다.
$QStateFileWarnMB = 20

# 이 도구가 만든 암호화 파일의 머리(scripts\protect_database_backup.py 의 PREFIX = b"QDB1\x00").
$QEncryptedBackupMagic = [byte[]](0x51, 0x44, 0x42, 0x31, 0x00)

# ------------------------------------------------------------------------------
# 2. 검사 · 조건 만들기
# ------------------------------------------------------------------------------

function Test-QStateKeyPrefixes {
  <#
  .SYNOPSIS
    접두사 목록이 SQL 에 넣어도 안전하고 서로 겹치지 않는지 본다. 맞으면 $true, 아니면 이유를 찍고 $false.
  .DESCRIPTION
    - 모양: 영문 · 숫자 · 밑줄 · 하이픈을 콜론으로 이은 뒤 콜론으로 끝난다(예: quant:, quant:cycle_log:). 따옴표 · 공백은 못 쓴다.
    - 겹침: 목록의 어떤 접두사가 다른 접두사로 시작하면 안 된다(같은 값이 두 번 있는 경우 포함) — 그러면 같은 키가 두 조건에 걸려 뜻이 흐려진다.
    -cmatch 와 \A \z 를 쓴다 — -match 는 대소문자를 가리지 않고, $ 는 끝의 개행 하나를 봐준다.
  #>
  $list = @($QStateKeyPrefixes)
  if ($list.Count -eq 0) { Write-QFail '상태 키 접두사 목록이 비어 있습니다.'; return $false }
  foreach ($p in $list) {
    if ($p -cnotmatch '\A[A-Za-z0-9_\-]+(:[A-Za-z0-9_\-]+)*:\z') {
      Write-QFail "상태 키 접두사 형식이 아닙니다(영문 · 숫자 · 밑줄 · 하이픈, 끝은 콜론): $p"
      return $false
    }
  }
  for ($i = 0; $i -lt $list.Count; $i++) {
    for ($j = 0; $j -lt $list.Count; $j++) {
      if ($i -ne $j -and $list[$i].StartsWith($list[$j], [System.StringComparison]::Ordinal)) {
        Write-QFail "상태 키 접두사가 서로 겹칩니다: $($list[$i]) 는 $($list[$j]) 로 시작합니다. 목록: $($list -join ', ')"
        return $false
      }
    }
  }
  return $true
}

function Get-QStateKeyCondition {
  <#
  .SYNOPSIS
    접두사 목록을 SQL 조건으로 만든다. 늘 괄호로 감싸므로 앞에 NOT 을 붙이거나 AND 로 이어도 뜻이 바뀌지 않는다.
  .EXAMPLE
    Get-QStateKeyCondition        # (starts_with(key,'quant:') OR starts_with(key,'model_compare:'))
  .DESCRIPTION
    starts_with 는 LIKE 와 달리 와일드카드(% _) 걱정이 없다. 접두사는 Test-QStateKeyPrefixes 를 통과한 값이라 따옴표가 없다.
  #>
  param([string]$KeyColumn = 'key')
  $parts = @($QStateKeyPrefixes | ForEach-Object { "starts_with(${KeyColumn},'$_')" })
  return '(' + ($parts -join ' OR ') + ')'
}

function Test-QAppDbName {
  <#
  .SYNOPSIS
    -Database 에 받은 이름이 규칙(소문자로 시작하는 소문자 · 숫자 · 밑줄, 63자 이하)을 지키는지 본다.
    이름은 sh 명령에 그대로 들어가므로 이 검사가 명령 끼워 넣기를 막는다.
  #>
  param([string]$Name)
  return (($Name -cmatch '\A[a-z_][a-z0-9_]*\z') -and ($Name.Length -le 63))
}

# ------------------------------------------------------------------------------
# 3. 파일 머리 읽기 — 핸들을 바로 닫는다
# ------------------------------------------------------------------------------

function Read-QFileHead {
  <#
  .SYNOPSIS
    파일 맨 앞 Count 바이트만 읽고 파일 핸들을 즉시 닫는다.
  .DESCRIPTION
    [System.IO.File]::ReadLines(...) | Select-Object -First 1 은 파이프가 끝나도 열거자가 닫히기까지 핸들이 남을 수 있고,
    줄바꿈이 없는 큰 바이너리를 주면 한 줄을 통째로 읽는다. 앞 몇 바이트만 읽으면 둘 다 없다.
  #>
  param([Parameter(Mandatory = $true)][string]$Path, [int]$Count = 256)
  $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  try {
    $buf = New-Object byte[] $Count
    $n = $fs.Read($buf, 0, $Count)
    $head = New-Object byte[] $n
    [System.Array]::Copy($buf, $head, $n)
    return , $head
  } finally {
    $fs.Dispose()
  }
}

function Test-QEncryptedBackup {
  <#
  .SYNOPSIS
    scripts\protect_database_backup.py 로 암호화한 파일(머리가 QDB1 + NUL)이면 $true.
  #>
  param([Parameter(Mandatory = $true)][string]$Path)
  $head = Read-QFileHead -Path $Path -Count $QEncryptedBackupMagic.Length
  if ($head.Length -lt $QEncryptedBackupMagic.Length) { return $false }
  for ($i = 0; $i -lt $QEncryptedBackupMagic.Length; $i++) {
    if ($head[$i] -ne $QEncryptedBackupMagic[$i]) { return $false }
  }
  return $true
}

function Get-QStateFileFirstLine {
  <#
  .SYNOPSIS
    상태 파일의 첫 줄(열 이름)을 돌려준다. 앞 256바이트 안에 줄바꿈이 없으면 $null — CSV 가 아니거나 암호화된 파일이다.
  #>
  param([Parameter(Mandatory = $true)][string]$Path)
  $head = Read-QFileHead -Path $Path -Count 256
  $text = [System.Text.Encoding]::UTF8.GetString($head).TrimStart([char]0xFEFF)
  $nl = $text.IndexOf("`n")
  if ($nl -lt 0) { return $null }
  return $text.Substring(0, $nl).TrimEnd("`r")
}

# ------------------------------------------------------------------------------
# 4. 민감 파일 안내 — 백업 끝과 복원 머리 · 실행 중에 같은 말을 한다
# ------------------------------------------------------------------------------

function Write-QAppDbSensitiveNotice {
  <#
  .SYNOPSIS
    상태 파일(.state.csv)도 백업(.dump)과 똑같이 민감하다는 안내를 찍는다.
  .DESCRIPTION
    상태 파일에는 사용자 ID · 보유 종목 · 수량 · 가격 · 평가금액 · 주문 이력이 암호화 없이 들어 있다(자동매매 사이클 이력과 정합성 기준선).
    pg_dump 의 .dump 에는 증권사 설정(암호화 저장)과 사용자 정보가 들어 있다. 둘을 같은 수준으로 다룬다.
  #>
  param([ValidateSet('backup', 'restore')][string]$Mode = 'backup')
  Write-QWarn '상태 파일(.state.csv)도 백업(.dump)과 똑같이 민감한 파일입니다 — 사용자 ID · 보유 종목 · 수량 · 가격 · 평가금액 · 주문 이력이 평문(암호화 없이)으로 들어 있습니다.'
  Write-QInfo '  - .dump 와 똑같이 보관합니다: 저장소 · 클라우드 동기화 폴더(OneDrive · Google Drive 등)에 두지 않습니다.'
  Write-QInfo '  - USB 로 옮길 때는 파일마다 암호화합니다(바이트 단위라 .state.csv 도 됩니다):'
  Write-QInfo '      python scripts\protect_database_backup.py --input <파일> --output <암호화한 파일>'
  Write-QInfo '  - 복원은 내가 만든 파일만 씁니다 — 남이 준 · 출처를 모르는 파일은 쓰지 않습니다(자동매매 상태가 그 파일 값으로 바뀝니다).'
  if ($Mode -eq 'restore') {
    Write-QInfo '  - 암호화한 파일이면 먼저 복호화합니다:'
    Write-QInfo '      python scripts\protect_database_backup.py --decrypt --input <암호화한 파일> --output <복호화한 파일>'
  }
  Write-QInfo '  - 암호화 키 파일(secrets)은 백업과 같은 USB 에 두지 않습니다(같이 잃어버리면 암호화가 소용없습니다).'
}
