<#
.SYNOPSIS
  Qurious 를 내 PC 에서 도커로 띄운다 — 저장소(DB) → 앱 순서로, 준비될 때까지 기다린 뒤 브라우저를 연다.

.DESCRIPTION
  Claude 없이 혼자서 프로젝트 전체를 로컬에서 돌려 보기 위한 스크립트다.
  (팀 합의: 로컬에서 전체 기능을 먼저 확인하고, AWS 배포는 강사님 안내가 나온 뒤에 한다.)

  하는 일 — 순서대로
    1. 사전 점검   Docker Desktop 이 켜져 있는가
    2. 설정 파일   .env 가 없으면 .env.example 을 복사해 로컬 기본값으로 만든다
    3. 네트워크    docker-compose.yml 이 요구하는 외부 네트워크 shared-net 이 없으면 만든다
    4. 충돌 점검   같은 이름의 다른 프로젝트 컨테이너 · 이미 쓰이는 포트가 있는가
    5. 저장소      postgres · redis · neo4j · qdrant 를 먼저 띄우고 준비될 때까지 기다린다
    6. 앱          코드가 이미지보다 새로우면 이미지를 다시 만들고, app · celery 를 띄워
                   /api/health 가 답할 때까지 기다린다 (앱은 켜질 때 DB 마이그레이션을 스스로 적용한다)
    7. 마무리      (선택) 강사님 CSV 적재 · 수집 DB · AI(Ollama) 안내 · 브라우저 열기

  다시 실행해도 안전하다(멱등). 이미 떠 있는 컨테이너는 그대로 두고, 빠진 것만 띄운다.

.PARAMETER Dev
  개발 모드 — 코드를 고치면 바로 반영된다. 내 PC 의 코드 폴더(app · public · prompts · alembic)를
  컨테이너에 연결하고(scripts\personal\compose.dev.yml), 앱은 uvicorn --reload · Celery 는 watchfiles 로 돌린다.
    app\*.py 저장  → 앱 · Celery 가 몇 초 안에 스스로 다시 켜진다 (logs.ps1 -Service app -Follow 로 보인다)
    public\ 저장   → 브라우저 새로고침(F5)만
  이미지는 requirements.txt · Dockerfile 이 바뀔 때만 다시 만든다. 호스트 파이썬 패키지가 필요 없다(dev.ps1 과 다른 점).
  보통 모드로 돌아가려면 -Dev 없이 start.ps1 — 앱 · Celery 를 이미지 코드로 다시 만든다(DB 데이터는 그대로).

.PARAMETER Build
  이미지를 무조건 다시 만든다. 보통은 필요 없다 — 코드가 이미지보다 새로우면 자동으로 다시 만든다.

.PARAMETER NoCelery
  Celery 워커 · 비트를 띄우지 않는다. 가볍게 화면만 볼 때. 대신 자동매매(10분) ·
  리밸런싱(1시간) 같은 예약 작업이 돌지 않는다.

.PARAMETER Ingest
  강사님 CSV(개인 · 기업 CB 통계, 은행 · 펀드 상품)를 DB 에 한 번 넣는다.
  data\09.* · data\10.* · data\12.* 폴더가 있어야 한다(저장소에는 없다 — 재배포 조건 확인 전).

.PARAMETER NoBrowser
  끝나고 브라우저를 열지 않는다.

.PARAMETER TimeoutSec
  저장소 준비 · 앱 응답을 각각 기다릴 최대 초. 기본 180초.

.EXAMPLE
  .\scripts\personal\start.ps1
  처음이든 매일이든 이 한 줄. 처음에는 이미지를 받고 만드느라 몇 분 걸린다.

.EXAMPLE
  .\scripts\personal\start.ps1 -NoCelery -NoBrowser
  예약 작업 없이 가볍게 띄우고, 브라우저는 직접 연다.

.EXAMPLE
  .\scripts\personal\start.ps1 -Dev
  개발 모드 — 코드를 고치며 화면을 볼 때. 저장하면 앱이 스스로 다시 켜진다.

.NOTES
  끄기: .\scripts\personal\stop.ps1   · 상태: status.ps1   · 로그: logs.ps1   · 기능 점검: check.ps1
  PowerShell 5.1 기준(Windows 기본). 실행이 막히면 README.md 의 「실행 정책」 을 보라.
#>
[CmdletBinding()]
param(
  [switch]$Dev,
  [switch]$Build,
  [switch]$NoCelery,
  [switch]$Ingest,
  [switch]$NoBrowser,
  [int]$TimeoutSec = 180
)

# 공용 도우미(출력 · HTTP · 도커 함수)를 이 스크립트 범위로 불러온다 — _common.ps1 머리말 참고.
. "$PSScriptRoot\_common.ps1"

# 외부 프로그램(docker)의 stderr 출력만으로 스크립트가 멈추지 않게, 오류 처리 기본값을 명시한다.
# 성패는 각 단계에서 종료 코드($LASTEXITCODE)로 직접 판단한다.
$ErrorActionPreference = 'Continue'
$started = Get-Date

# 개발 모드면 이 스크립트 안의 모든 compose 호출이 덧씌우기 파일까지 읽게 한다(_common.ps1 의 $QComposeFiles 설명).
if ($Dev) { $QComposeFiles = @('docker-compose.yml', $QComposeDevFile) }

$modeName = '보통 모드 — 이미지 코드'
if ($Dev) { $modeName = '개발 모드 — 코드 폴더 연결 · 저장하면 자동 반영' }
Write-QTitle "Qurious 로컬 실행 (도커 · $modeName)"
Write-QInfo "저장소: $QRoot"

# ------------------------------------------------------------------------------
# 1. 사전 점검 — 도커가 없으면 여기서 끝낸다(무엇을 하면 되는지까지 알려 준다)
# ------------------------------------------------------------------------------
Write-QStep '1/7 사전 점검 — Docker Desktop'
if (-not (Test-QDocker)) { exit 1 }
$dockerVer = & docker version --format '{{.Server.Version}}'
Write-QOk "Docker 엔진 $dockerVer"

# ------------------------------------------------------------------------------
# 2. 설정 파일 — compose 의 모든 앱 컨테이너가 env_file: .env 를 읽는다. 없으면 compose 가 멈춘다.
# ------------------------------------------------------------------------------
Write-QStep '2/7 설정 파일 — .env'
$envPath = Join-Path $QRoot '.env'
if (Test-Path $envPath) {
  # 값은 읽지 않는다(키 · 비밀번호가 들어 있을 수 있다). 있는지만 본다.
  Write-QOk '.env 있음 (값은 읽지 않음)'
} else {
  Copy-Item (Join-Path $QRoot '.env.example') $envPath
  Write-QWarn '.env 가 없어 .env.example 을 복사해 만들었습니다 (로컬 전용 기본값).'
  Write-QInfo '증권사 키 · 알림 토큰이 비어 있어 그 기능은 동작하지 않습니다. 화면 로그인은 쿠키 방식이라 문제없습니다.'
  Write-QInfo '.env 는 .gitignore 에 있어 커밋되지 않습니다 — 실제 키는 여기에만 적으세요.'
}

# ------------------------------------------------------------------------------
# 3. 도커 네트워크 — compose 파일이 shared-net 을 「external: true」(밖에서 이미 만든 것)로 선언한다.
#    강사님 원본이 다른 스택(외부 Redis 등)과 네트워크를 나눠 쓰려고 둔 설정이다. 없으면 compose 가 멈춘다.
# ------------------------------------------------------------------------------
Write-QStep '3/7 도커 네트워크 — shared-net'
$null = & docker network inspect shared-net 2>&1
if ($LASTEXITCODE -eq 0) {
  Write-QOk 'shared-net 있음'
} else {
  $null = & docker network create shared-net
  if ($LASTEXITCODE -ne 0) { Write-QFail 'shared-net 을 만들지 못했습니다.'; exit 1 }
  Write-QOk 'shared-net 을 새로 만들었습니다 (한 번만 하면 된다)'
}

# ------------------------------------------------------------------------------
# 4. 충돌 점검 — compose 가 던지는 긴 오류 대신, 무엇이 막고 있는지 먼저 짚어 준다
# ------------------------------------------------------------------------------
Write-QStep '4/7 충돌 점검 — 컨테이너 이름 · 포트'
# ollama 는 앱의 depends_on 이라 앱을 띄우면 compose 가 함께 켠다(강사님 compose 2026-10-01 affb05c) — 이름 충돌도 같이 본다.
$wanted = @('postgres', 'redis', 'neo4j', 'ollama', 'app')
if (-not $NoCelery) { $wanted += @('celery-worker', 'celery-beat') }
$conflict = $false
foreach ($svc in ($QServices | Where-Object { $wanted -contains $_.Service })) {
  $st = Get-QContainerState $svc.Container
  # (가) 이름 충돌: 같은 이름의 컨테이너가 있는데 다른 compose 프로젝트 것이다.
  #     예) 강사님 원본 사본(lumina-invest)도 fin-ai-postgres 라는 이름을 쓴다.
  if ($st.State -ne 'missing' -and $st.Project -and $st.Project -ne $QComposeProject) {
    Write-QFail ("컨테이너 이름 {0} 를 다른 프로젝트 '{1}' 가 쓰고 있습니다 ({2})." -f $svc.Container, $st.Project, $st.State)
    Write-QInfo "그 프로젝트 폴더에서 docker compose down 을 하거나: docker rm -f $($svc.Container)"
    $conflict = $true
    continue
  }
  # (나) 포트 충돌: 우리 컨테이너가 아직 안 떠 있는데 그 포트를 누가 듣고 있다.
  #     (우리 컨테이너가 이미 떠 있으면 그 포트는 당연히 우리 것이라 건너뛴다.)
  if ($st.State -ne 'running') {
    foreach ($port in $svc.Ports) {
      $owner = Get-QPortOwner $port
      if ($owner) {
        $who = & docker ps --filter "publish=$port" --format '{{.Names}}'
        if ($who) { $owner = "도커 컨테이너 $who" }
        Write-QFail ("포트 {0} ({1}) 를 이미 '{2}' 가 쓰고 있습니다." -f $port, $svc.Service, $owner)
        $conflict = $true
      }
    }
  }
}
if ($conflict) {
  Write-QInfo '위 충돌을 정리한 뒤 다시 실행하세요. (로컬에 설치된 PostgreSQL · Redis 서비스가 흔한 원인)'
  exit 1
}
Write-QOk '충돌 없음'

# ------------------------------------------------------------------------------
# 5. 저장소 먼저 — 준비 확인까지 (이유는 _common.ps1 의 Start-QInfra 설명)
# ------------------------------------------------------------------------------
Write-QStep '5/7 저장소 — postgres · redis · neo4j · qdrant (처음이면 이미지를 받느라 1~2분)'
if (-not (Start-QInfra -TimeoutSec $TimeoutSec)) { exit 1 }

# ------------------------------------------------------------------------------
# 6. 앱 — 필요하면 이미지를 다시 만든 뒤 띄우고, 헬스 체크가 답할 때까지 기다린다
# ------------------------------------------------------------------------------
# 괄호가 필요하다 — 명령 인자 자리에서 `'a' + 'b'` 를 괄호 없이 쓰면 PowerShell 은 +를 글자 인자로 넘긴다.
Write-QStep ('6/7 앱 — app' + $(if ($NoCelery) { '' } else { ' · celery-worker · celery-beat' }))
$appServices = @('app')
if (-not $NoCelery) { $appServices += @('celery-worker', 'celery-beat') }

$needBuild = $Build
if ($Dev) {
  # 개발 모드는 코드를 폴더째 연결하므로, 이미지는 설치 패키지(requirements.txt) · Dockerfile 이 바뀔 때만 다시 만든다.
  if (-not $needBuild -and (Test-QImageStale -DepsOnly)) {
    Write-QInfo 'requirements.txt · Dockerfile 이 이미지보다 새로워 이미지를 다시 만듭니다 (패키지 설치 — 몇 분 걸릴 수 있다).'
    $needBuild = $true
  }
} elseif (-not $needBuild -and (Test-QImageStale)) {
  Write-QInfo '코드가 이미지보다 새로워 이미지를 다시 만듭니다 (바뀐 층만 — 보통 수십 초, 처음이면 몇 분).'
  $needBuild = $true
}
$upArgs = @('up', '-d')
if ($needBuild) { $upArgs += '--build' }
$upArgs += $appServices
$code = Invoke-QCompose $upArgs
if ($code -ne 0) {
  Write-QFail "앱 컨테이너를 띄우지 못했습니다 (docker compose 종료 코드 $code)."
  exit 1
}

Write-QInfo "앱이 응답할 때까지 기다립니다 — $QAppUrl/api/health (최대 ${TimeoutSec}초 · 10초마다 점 하나)"
if (-not (Wait-QHttp -Url "$QAppUrl/api/health" -TimeoutSec $TimeoutSec)) {
  Write-QFail "앱이 ${TimeoutSec}초 안에 응답하지 않았습니다. 마지막 로그 30줄:"
  $null = Invoke-QCompose @('logs', 'app', '--tail', '30')
  Write-QInfo '마이그레이션 오류 · 패키지 오류가 흔한 원인입니다. 고친 뒤 .\scripts\personal\start.ps1 -Build'
  exit 1
}
Write-QOk '앱 응답 확인 (/api/health = ok)'

# 앱이 Neo4j 보다 먼저 떴던 흔적이 있으면 알려 준다(이미 떠 있던 앱을 재사용한 경우 등).
$appLog = (& docker logs fin-ai-app 2>&1 | ForEach-Object { "$_" }) -join "`n"
if ($appLog -match 'Neo4j 연결 실패') {
  Write-QWarn '앱 로그에 「Neo4j 연결 실패 (그래프 기능 비활성)」 가 있습니다 — 앱이 Neo4j 보다 먼저 떴던 적이 있습니다.'
  Write-QInfo '그래프 기능이 필요하면: docker restart fin-ai-app'
}

# ------------------------------------------------------------------------------
# 7. 마무리 — 선택 작업과 알아 둘 것
# ------------------------------------------------------------------------------
Write-QStep '7/7 마무리'

if ($Ingest) {
  # 강사님 CSV 는 저장소에 없다(.gitignore 의 data/09* · data/10* · data/12*). 폴더가 있을 때만 돈다.
  $csvDirs = Get-ChildItem -Path (Join-Path $QRoot 'data') -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(09|10|12)\.' }
  if ($csvDirs) {
    Write-QInfo ('CSV 적재 — ' + (($csvDirs | ForEach-Object { $_.Name }) -join ' · '))
    $runArgs = @('run', '--rm')
    if ($needBuild) { $runArgs += '--build' }
    $runArgs += 'ingest'
    $code = Invoke-QCompose $runArgs
    if ($code -eq 0) { Write-QOk 'CSV 적재 끝' } else { Write-QFail "CSV 적재 실패 (종료 코드 $code)" }
  } else {
    Write-QWarn 'data\09.* · 10.* · 12.* 폴더가 없어 CSV 적재를 건너뜁니다 (CB 통계 · 금융상품 화면은 빈 표로 보입니다).'
  }
}

# 수집 DB — 국내 주식 일봉 · 지표의 원천. 없으면 앱이 야후(외부)로 대신 간다.
$collectorDb = Join-Path $QRoot 'data\collector\market.sqlite3'
if (Test-Path $collectorDb) {
  $db = Get-Item $collectorDb
  Write-QOk ("수집 DB 있음 — {0:N1} GB · 마지막 갱신 {1:yyyy-MM-dd HH:mm} (컨테이너에는 읽기 전용으로 붙는다)" -f ($db.Length / 1GB), $db.LastWriteTime)
} else {
  Write-QWarn '수집 DB(data\collector\market.sqlite3)가 없습니다 — 국내 일봉 · 지표가 야후 경로로 갑니다(느리고 막힐 수 있음).'
  Write-QInfo 'HF 조직 qurious-quant 의 비공개 데이터셋(권한 필요)을 받은 뒤:'
  Write-QInfo '  python scripts\hf_dataset.py restore --from <받은 폴더> --into data\collector\market.sqlite3'
}

# AI 채팅 · RAG 의 답변 모델. 강사님 compose(2026-10-01 affb05c)부터 앱 컨테이너의 Ollama 주소 · 모델은
# docker-compose.yml 의 environment 가 정한다 — .env 의 OLLAMA_BASE_URL · LLM_MODEL 보다 우선한다.
#   .env 에 COMPOSE_OLLAMA_URL · COMPOSE_LLM_MODEL 이 없으면 → 컨테이너 Ollama(fin-ai-ollama) + qwen2.5:1.5b
#   있으면 → 그 값. 이 PC 의 Ollama 는 http://host.docker.internal:11434 로 가리킨다
#   (컨테이너 안의 127.0.0.1 은 컨테이너 자신이라 이 PC 에 닿지 않는다).
# 그래서 .env 를 읽지 않고, 앱 컨테이너가 실제로 받은 두 값(주소 · 모델 이름 — 비밀값 아님)만 물어 본다.
$appOllama = "$(& docker exec fin-ai-app printenv OLLAMA_BASE_URL 2>$null)".Trim()
$appModel  = "$(& docker exec fin-ai-app printenv LLM_MODEL 2>$null)".Trim()
if ($appOllama -and $appModel) {
  Write-QInfo "AI 답변 모델: $appModel · Ollama 주소: $appOllama"
  if ($appOllama -match '://ollama:') {
    # 컨테이너 Ollama 는 비어서 시작한다 — 모델 받기(model-pull)는 start.ps1 이 대신 돌리지 않는다(1GB 넘게 받는다).
    $pulled = (& docker exec fin-ai-ollama ollama list 2>$null) -join "`n"
    if ($pulled -notmatch [regex]::Escape($appModel)) {
      Write-QWarn "컨테이너 Ollama 에 $appModel 모델이 아직 없습니다 — AI 채팅이 「모델을 찾을 수 없습니다」 로 답합니다 (다른 기능은 무관)."
      Write-QInfo '  처음 한 번 모델 받기:  docker compose up -d model-pull   (진행: docker compose logs -f model-pull)'
      Write-QInfo '  이 PC 의 Ollama 를 쓰려면 .env 에 COMPOSE_OLLAMA_URL=http://host.docker.internal:11434 · COMPOSE_LLM_MODEL=llama3.1 을 넣고 start.ps1 다시'
    }
  } elseif ($appOllama -match 'host\.docker\.internal') {
    # localhost 가 아니라 127.0.0.1 로 묻는다 — Ollama 는 IPv4(127.0.0.1)에만 떠 있는데, 5.1 은 localhost 를
    # IPv6(::1)로 먼저 붙었다가 실패한 뒤 IPv4 로 돌아와 2초쯤 늦는다(직접 잼: localhost 2,087ms · 127.0.0.1 6ms).
    $ollama = Invoke-QApi -Method GET -Url 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
    if ($ollama.Status -ne 200) {
      Write-QWarn '앱은 이 PC 의 Ollama 를 가리키는데, 이 PC 에서 Ollama 가 응답하지 않습니다 — Ollama 를 켜면 AI 채팅이 동작합니다.'
    } elseif ($ollama.Text -notmatch [regex]::Escape($appModel)) {
      Write-QWarn "이 PC 의 Ollama 에 $appModel 모델이 없습니다 — ollama pull $appModel"
    }
  }
} else {
  Write-QInfo '앱 컨테이너의 Ollama 설정을 읽지 못했습니다 — AI 채팅 · 문서 검색(RAG)만 영향이 있습니다 (다른 기능은 무관).'
}

$elapsed = [int]((Get-Date) - $started).TotalSeconds
Write-QTitle "준비 끝 (${elapsed}초 · $modeName)"
Write-Host "  화면       $QAppUrl"
Write-Host "  API 문서   $QAppUrl/docs      (모든 API 를 눌러 볼 수 있는 FastAPI 자동 문서)"
Write-Host '  Neo4j      http://localhost:17474   (neo4j / finagent123 — docker-compose.yml 기본값)'
Write-Host ''
if ($Dev) {
  Write-Host '  개발 모드에서 코드를 고치면'
  Write-Host '    app\*.py 저장   앱 · Celery 가 몇 초 안에 스스로 다시 켜진다 — 화면에서 다시 요청하면 새 코드'
  Write-Host '    public\ 저장    브라우저 새로고침(F5)만'
  Write-Host '    다시 켜지는 모습 보기   .\scripts\personal\logs.ps1 -Service app -Follow   (「Reloading」 줄)'
  Write-Host '    보통 모드로 돌아가기    .\scripts\personal\start.ps1   (-Dev 없이)'
  Write-Host ''
}
Write-Host '  다음에 할 것'
Write-Host '    .\scripts\personal\check.ps1     기능 점검 — curl 처럼 API 를 차례로 불러 통과/실패를 표로'
Write-Host '    .\scripts\personal\status.ps1    지금 무엇이 떠 있나'
Write-Host '    .\scripts\personal\logs.ps1      로그 보기 (-Service app · -Follow)'
Write-Host '    .\scripts\personal\stop.ps1      끄기 (데이터는 남는다)'

if (-not $NoBrowser) { Start-Process $QAppUrl }
exit 0
