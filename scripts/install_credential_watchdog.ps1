<# Windows 독립 감시 설치. 현재 사용자 로그인 중 5분마다 실행하며 Docker/WSL을 시작하지 않는다.
   1) -PrepareOnly: 호스트에 도구 복사·폴더 ACL 적용
   2) 복사한 credential_watchdog.py --config <폴더>\config.json --configure (웹훅은 stdin)
   3) 이 도구 다시 실행: 예약 작업 등록. -RemoveTask는 작업만 제거하고 설정은 보존.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'QuriousCredentialWatchdog'),
    [string]$PythonPath = '',
    [switch]$PrepareOnly,
    [switch]$RemoveTask
)
$ErrorActionPreference = 'Stop'
$taskName = 'Qurious-Credential-Watchdog'
if ($RemoveTask) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output '{"status":"task_removed","configuration_preserved":true}'
    exit 0
}
if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Python executable is unavailable.' }
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$acl = New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$acl.SetOwner($identity.User)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity.User, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $InstallDir -AclObject $acl
foreach ($file in @('credential_watchdog.py', 'check_credential_storage_logs.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination (Join-Path $InstallDir $file) -Force
}
$runner = @'
param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
try {
    $output = & $PythonPath (Join-Path $PSScriptRoot 'credential_watchdog.py') --config (Join-Path $PSScriptRoot 'config.json')
    $result = $LASTEXITCODE
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'last-run.json'), ($output -join "`n"), (New-Object System.Text.UTF8Encoding($false)))
    exit $result
} catch { exit 3 }
'@
[System.IO.File]::WriteAllText((Join-Path $InstallDir 'run.ps1'), $runner, (New-Object System.Text.UTF8Encoding($true)))
if ($PrepareOnly) {
    [pscustomobject]@{status='prepared'; directory=$InstallDir; task_registered_this_run=$false} | ConvertTo-Json -Compress
    exit 0
}
if (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'config.json'))) { throw 'Configure the dedicated DPAPI webhook first; no task registered.' }
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $InstallDir 'run.ps1') + '" -PythonPath "' + $PythonPath + '"'
$action = New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'powershell.exe') -Argument $arguments -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 90) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 7
$principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
[pscustomobject]@{status='registered'; task=$taskName; interval_minutes=5; logged_in_user_only=$true; docker_restart=$false} | ConvertTo-Json -Compress
