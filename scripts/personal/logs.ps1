<#
.SYNOPSIS
  컨테이너 로그 보기 — `docker compose logs` 를 서비스 이름만으로 부를 수 있게 감싼 것.

.DESCRIPTION
  어디서 막혔는지 알고 싶을 때 쓴다. 자주 보는 곳:
    app            화면 · API 요청, 시작할 때 DB 마이그레이션(alembic), Neo4j 연결 경고
    celery-worker  예약 작업이 실제로 돈 기록(자동매매 사이클 · 리밸런싱 점검)과 그 오류
    celery-beat    예약 시계가 작업을 보낸 기록(언제 무엇을 보냈나)
    postgres       DB 자체 오류(드물다)
  수집기 예약(collector.*)이 워커 로그에 「No module named 'collector'」 로 실패하는 것은 알려진 일이다 —
  이미지에 수집기 코드를 넣지 않았고, 수집은 호스트의 작업 스케줄러(매일 12:30)가 한다.

.PARAMETER Service
  볼 서비스. app(기본) · celery-worker · celery-beat · postgres · redis · neo4j · all(전부 섞어서)

.PARAMETER Tail
  끝에서 몇 줄. 기본 100.

.PARAMETER Follow
  새 로그를 계속 따라가며 보여 준다(tail -f 와 같다). 끝내려면 Ctrl+C.

.EXAMPLE
  .\scripts\personal\logs.ps1
.EXAMPLE
  .\scripts\personal\logs.ps1 -Service celery-worker -Tail 50 -Follow
#>
[CmdletBinding()]
param(
  [ValidateSet('app', 'celery-worker', 'celery-beat', 'postgres', 'redis', 'neo4j', 'all')]
  [string]$Service = 'app',
  [int]$Tail = 100,
  [switch]$Follow
)

. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = 'Continue'
if (-not (Test-QDocker)) { exit 1 }

$args2 = @('logs', '--tail', "$Tail")
if ($Follow) { $args2 += '--follow' }
if ($Service -ne 'all') { $args2 += $Service }
Write-QInfo ("docker compose " + ($args2 -join ' ') + $(if ($Follow) { '   (끝내려면 Ctrl+C)' } else { '' }))
$code = Invoke-QCompose $args2
exit $code
