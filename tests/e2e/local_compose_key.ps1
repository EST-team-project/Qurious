# Windows PowerShell 5.1. Synthetic key, temporary project; production containers are never selected.
param([string]$RepoRoot, [string]$Image = 'qurious-app:integration-20261029')
$ErrorActionPreference = 'Stop'
. (Join-Path $RepoRoot 'scripts\personal\_common.ps1')
$ErrorActionPreference = 'Stop'
$fixture = Join-Path $env:TEMP ('qurious-key-415-' + [guid]::NewGuid().ToString('N'))
$project = 'qurious-key-415-' + [guid]::NewGuid().ToString('N').Substring(0,12)
$dockerExe = (Get-Command docker.exe).Source
$checks = @()
$runtimeStarted = $false
function Assert-QTest($Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}
function Write-QTestFile([string]$Path, [string]$Text) {
  [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}
function Invoke-QTestDocker([string[]]$DockerArgs) {
  $ErrorActionPreference = 'Continue' # PowerShell 5.1 treats native stderr as an error record.
  $result = & $dockerExe @DockerArgs 2>&1
  if ($LASTEXITCODE -ne 0) { throw ('Docker test failed: ' + ($result -join "`n")) }
  return $result
}
try {
  $null = New-Item -ItemType Directory -Path (Join-Path $fixture 'scripts\personal') -Force
  $QRoot = $fixture
  $local = Join-Path $fixture 'scripts\personal\compose.local.yml'
  $tokens = $null; $parseErrors = $null
  $startAst = [Management.Automation.Language.Parser]::ParseFile((Join-Path $RepoRoot 'scripts\personal\start.ps1'), [ref]$tokens, [ref]$parseErrors)
  Assert-QTest ($parseErrors.Count -eq 0) 'start.ps1 syntax'
  $assignment = $startAst.Find({param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq '$QComposeFiles'}, $true)
  Assert-QTest ($null -ne $assignment) 'start compose selection missing'
  $expectedDev = @('docker-compose.yml', 'scripts/personal/compose.dev.yml')
  Assert-QTest (@(Get-QStartComposeFiles).Count -eq 0) 'no local / normal changed'
  Assert-QTest ((@(Get-QStartComposeFiles -Dev) -join '|') -eq ($expectedDev -join '|')) 'no local / dev changed'
  $checks += 'absent_local_preserves_both_modes'
  Copy-Item (Join-Path $RepoRoot 'scripts\personal\compose.local.example.yml') $local
  $normal = @(Get-QStartComposeFiles)
  $dev = @(Get-QStartComposeFiles -Dev)
  Assert-QTest (($normal -join '|') -eq 'docker-compose.yml|scripts/personal/compose.local.yml') 'normal order'
  Assert-QTest (($dev -join '|') -eq 'docker-compose.yml|scripts/personal/compose.dev.yml|scripts/personal/compose.local.yml') 'dev order'
  $checks += 'present_local_is_last_in_both_modes'

  # Verify Invoke-QCompose passes the chosen files and propagates failure, without invoking Docker.
  function docker {
    $script:captured = @($args)
    $global:LASTEXITCODE = 17
  }
  foreach ($mode in @($false, $true)) {
    $Dev = $mode
    $QComposeFiles = @(Invoke-Expression $assignment.Right.Extent.Text)
    $code = Invoke-QCompose @('up', '-d', 'app', 'celery-worker', 'celery-beat')
    $expected = @('compose')
    foreach ($file in $QComposeFiles) { $expected += @('-f', $file) }
    $expected += @('up', '-d', 'app', 'celery-worker', 'celery-beat')
    Assert-QTest ($code -eq 17 -and ($script:captured -join '|') -eq ($expected -join '|')) 'compose arguments/exit code'
  }
  Remove-Item Function:\docker
  $checks += 'compose_arguments_and_exit_code'

  # Render the real team Compose files using an empty environment file (no user secrets).
  Copy-Item (Join-Path $RepoRoot 'docker-compose.yml') (Join-Path $fixture 'docker-compose.yml')
  Copy-Item (Join-Path $RepoRoot 'scripts\personal\compose.dev.yml') (Join-Path $fixture 'scripts\personal\compose.dev.yml')
  Write-QTestFile (Join-Path $fixture '.env') ''
  Push-Location $fixture
  try {
    foreach ($mode in @($false, $true)) {
      $files = @(Get-QStartComposeFiles -Dev:$mode)
      $arguments = @('compose', '-p', $project)
      foreach ($file in $files) { $arguments += @('-f', $file) }
      $config = (Invoke-QTestDocker ($arguments + @('config', '--format', 'json'))) -join "`n" | ConvertFrom-Json
      foreach ($svc in @('app', 'celery-worker', 'celery-beat')) {
        $s = $config.services.$svc
        $keyMount = @($s.volumes | Where-Object { $_.target -eq '/run/secrets/broker-credentials.json' })
        Assert-QTest ($keyMount.Count -eq 1 -and $keyMount[0].read_only -and -not $keyMount[0].bind.create_host_path) 'key mount config'
        Assert-QTest ($s.environment.BROKER_CREDENTIAL_KEY_FILE -eq '/run/secrets/broker-credentials.json') 'key env config'
        Assert-QTest ($s.environment.DATABASE_URL) 'base environment lost'
      }
      if ($mode) { Assert-QTest ($config.services.app.command -contains '--reload') 'dev command lost' }
    }
    $checks += 'real_compose_config_three_services_both_modes'

    # A minimal, network-disabled project tests bind/recreate/run with the real encryption module.
    $services = @{}
    foreach ($svc in @('app', 'celery-worker', 'celery-beat')) {
      $services[$svc] = @{image=$Image; network_mode='none'; command=@('python','-c','import time; time.sleep(300)')}
    }
    Write-QTestFile (Join-Path $fixture 'docker-compose.yml') (@{services=$services} | ConvertTo-Json -Depth 8)
    Write-QTestFile (Join-Path $fixture 'scripts\personal\compose.dev.yml') '{"services":{"app":{"environment":{"KEY_TEST_MODE":"dev"}},"celery-worker":{"environment":{"KEY_TEST_MODE":"dev"}},"celery-beat":{"environment":{"KEY_TEST_MODE":"dev"}}}}'
    $null = New-Item -ItemType Directory -Path (Join-Path $fixture 'secrets\broker') -Force
    $keyPath = Join-Path $fixture 'secrets\broker\broker-credentials.json'
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes); $rng.Dispose()
    Write-QTestFile $keyPath (@{active='test'; keys=@{test=[Convert]::ToBase64String($bytes)}} | ConvertTo-Json)
    $QComposeFiles = @(Get-QStartComposeFiles)
    Assert-QTest (Test-QStartKeyFiles) 'valid key preflight'
    $encrypt = 'from app.lib.broker_secrets import encrypt;print(encrypt(''synthetic-probe'', ''app_key''))'
    $decrypt = 'import sys;from app.lib.broker_secrets import decrypt;assert decrypt(sys.argv[1], ''app_key'') == ''synthetic-probe'';print(''ok'')'
    $cipher = $null
    foreach ($mode in @($false, $true, $false)) {
      $arguments = @('compose', '-p', $project)
      foreach ($file in @(Get-QStartComposeFiles -Dev:$mode)) { $arguments += @('-f', $file) }
      $runtimeStarted = $true
      $null = Invoke-QTestDocker ($arguments + @('up', '-d', '--force-recreate', '--no-build', '--pull', 'never'))
      if (-not $cipher) { $cipher = (Invoke-QTestDocker ($arguments + @('exec','-T','app','python','-c',$encrypt))) -join '' }
      foreach ($svc in @('app', 'celery-worker', 'celery-beat')) {
        $answer = Invoke-QTestDocker ($arguments + @('exec','-T',$svc,'python','-c',$decrypt,$cipher))
        Assert-QTest (($answer -join '') -eq 'ok') 'decryption after recreate'
        $id = (Invoke-QTestDocker ($arguments + @('ps','-q',$svc))) -join ''
        $container = ((Invoke-QTestDocker @('inspect', $id)) -join "`n" | ConvertFrom-Json)[0]
        $mount = @($container.Mounts | Where-Object { $_.Destination -eq '/run/secrets/broker-credentials.json' })
        Assert-QTest ($mount.Count -eq 1 -and -not $mount[0].RW) 'actual key mount writable'
      }
    }
    $checks += 'recreate_normal_dev_normal_keeps_key_three_services'
    $answer = Invoke-QTestDocker ($arguments + @('run','--rm','--no-deps','app','python','-c',$decrypt,$cipher))
    Assert-QTest (@($answer | Where-Object { "$_".Trim() -eq 'ok' }).Count -eq 1) 'one-off migration service key'
    $checks += 'one_off_app_uses_same_key'
    # Use a never-mounted missing path: Docker Desktop can retain a bind to an already-open file.
    $missingPath = Join-Path $fixture 'secrets\broker\missing-key.json'
    $missingLocal = [IO.File]::ReadAllText($local).Replace('source: ./secrets/broker/broker-credentials.json', 'source: ./secrets/broker/missing-key.json')
    Write-QTestFile $local $missingLocal
    $QComposeFiles = @(Get-QStartComposeFiles)
    Assert-QTest (-not (Test-QStartKeyFiles)) 'missing key preflight accepted'
    Assert-QTest (-not (Test-Path $missingPath)) 'missing key directory created'
    $checks += 'missing_key_fails_without_creating_directory'
  } finally { Pop-Location }
  @{ok=$true; powershell=$PSVersionTable.PSVersion.ToString(); checks=$checks; production_changed=$false} | ConvertTo-Json -Depth 5
} finally {
  $ErrorActionPreference = 'Continue'
  if ($runtimeStarted) {
    Push-Location $fixture
    try { $null = & $dockerExe compose -p $project -f docker-compose.yml -f scripts/personal/compose.local.yml down 2>&1 }
    finally { Pop-Location }
  }
  if (Test-Path $fixture) { Remove-Item -LiteralPath $fixture -Recurse -Force }
}
