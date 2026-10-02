<#
.SYNOPSIS
  기능 점검 — 떠 있는 Qurious 에 API 를 차례로 불러, 기능별 통과/실패를 보여 준다.
  curl 로 API 를 하나씩 두드려 보던 일을 한 번에 묶은 것이다.

.DESCRIPTION
  start.ps1 로 띄운 뒤에 돌린다. 점검 하나 = 「요청 1건 + 통과 조건 + 한 줄 요약」 이다.
  아래 $Checks 목록만 읽어도 각 기능이 어떤 API 로, 무엇을 돌려주는지 알 수 있게 적었다.

  로그인
    화면과 똑같이 쿠키(fin_session) 로그인을 쓴다. 기본은 로컬 점검 전용 계정
    smoke-check@example.com 이고, 없으면 처음 한 번 가입한다. 이 계정의 모의투자 · 리밸런싱만
    바뀌므로 내 계정 데이터는 건드리지 않는다. 로컬(localhost)이 아닌 주소에는 자동 가입하지 않는다.
    점검 계정은 **관리자**다(로컬 DB 에서 역할을 올린다 · 2026-10-02) — 관리자 화면 · API 까지 점검하려고.
    관리자 API 중 지우는 것(POST /api/admin/reset)은 부르지 않는다.

  묶음 (-Group 으로 골라 돌릴 수 있다)
    기본     앱이 떠 있나 · 화면 파일 · API 목록
    로그인   로그인 · 내 정보 · 로그인 없이 막히나
    계정     임시 계정(대문자 섞인 이메일)으로 가입(C) · 조회(R) · 이름 · 비밀번호 바꾸기(U) · 탈퇴(D) ·
             로그아웃 · 토큰 방식 · 비밀번호 규칙을 차례로 — 임시 계정은 끝에 탈퇴 API 로 지운다. 로컬 주소에서만 돈다
    시세     국내 일봉(수집 DB) · 지표 · 현재가 · 차트 패턴 · 다중 시간대 신호 · 지수
    전략     지표 전략 백테스트 · 수식 지표(검사 · 계산) · 저장 지표 목록
    로보     투자 성향 질문 · 성향 점수 · 자산 배분 · 목표 달성 시뮬레이션
    용어     용어사전의 판(표가 파일과 같은가) · 분류 · 검색(약어 · 초성) · 화면 키로 한 건 · 없는 이름은 404
    데이터   데이터 상태(일일 갱신 · 표별 기준일과 늦음) · 거래일 달력(60일) · 금융 일정(파생 만기 · 배당락일)
    매매     모의투자 잔고 · 보유 · 주문 미리보기 · 자동매매 · 위험 한도 · 리밸런싱 · 증권사 설정
    연동     TradingView 웹훅 안내 · 알림 설정
    시스템   시세 동기화 · LEAN 백테스트 모드 · AI(LLM) 연결 · 벡터 DB(Qdrant) 연결
    관리     (관리자 계정일 때) DB 통계 · 감사 기록 — 읽기만. 일반 계정이 막히는지는 「계정」 묶음이 본다
    느림     (-Full) 요청마다 모델을 학습하는 ML 셋 — 하나에 15초 안팎
    쓰기     (-Write) 기록이 남는 점검 — 모의 매수 1주 → 매도 1주 · 리밸런싱 목표 저장 → 미리보기 ·
             문서 근거 RAG 왕복(작은 글 올리기 → 찾기 → 채팅 「순수 RAG」 → 지우기 → 다시 찾으면 0)

  판정
    [ OK ]    상태 코드와 내용 조건이 모두 맞다
    [주의]    동작은 한다. 다만 알아 둘 것이 있다(예: 수집 DB 대신 야후에서 옴) — 실패로 세지 않는다
    [실패]    상태 코드가 다르거나 내용 조건이 틀렸다 — 이유를 한 줄로 적는다
    [건너뜀]  전제가 없다(예: Ollama 없음 · 앞 점검 실패) — 실패로 세지 않는다
  실패가 하나라도 있으면 종료 코드 1, 없으면 0 (다른 스크립트 · 작업 스케줄러에서 판정에 쓸 수 있다).

.PARAMETER BaseUrl
  점검할 앱 주소. 기본 http://localhost:8966 (docker-compose.yml 의 app 포트).
  호스트에서 직접 띄운 개발 모드(dev.ps1)는 http://127.0.0.1:8000 이다.

.PARAMETER Email
  로그인할 계정. 생략하면 로컬 점검 전용 계정을 쓴다(없으면 만든다).

.PARAMETER Password
  -Email 과 함께 준다. -Email 만 주면 입력 창으로 묻는다(화면에 보이지 않음).

.PARAMETER Group
  이 묶음만 돌린다. 예) -Group 시세,매매

.PARAMETER Full
  느린 ML 점검 셋을 더한다(합쳐 50초 안팎).

.PARAMETER Write
  기록이 남는 점검을 더한다 — 점검 계정의 모의투자에 매수 · 매도 1주씩, 리밸런싱 목표 저장 뒤 원래대로.

.PARAMETER ShowBody
  응답 본문 앞 300자를 함께 보여 준다(무엇이 오는지 눈으로 볼 때).

.PARAMETER SaveReport
  결과를 data\local-run\check-날짜-시각.md 로 저장한다(표 형식 · .gitignore 대상).
  테스트 결과서 · 발표 자료에 「로컬에서 전 기능을 확인했다」 는 증거로 붙일 수 있다.

.EXAMPLE
  .\scripts\personal\check.ps1
  기본 묶음 전부 (10초 안팎).

.EXAMPLE
  .\scripts\personal\check.ps1 -Full -Write -SaveReport
  전부 + 결과 파일 저장 (1분 안팎).

.EXAMPLE
  .\scripts\personal\check.ps1 -Group 시세 -ShowBody
  시세 묶음만, 응답 본문까지 보며.
#>
[CmdletBinding()]
param(
  [string]$BaseUrl = 'http://localhost:8966',
  [string]$Email = '',
  [string]$Password = '',
  [string[]]$Group = @(),
  [switch]$Full,
  [switch]$Write,
  [switch]$ShowBody,
  [switch]$SaveReport
)

. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = 'Continue'
$BaseUrl = $BaseUrl.TrimEnd('/')

# ------------------------------------------------------------------------------
# 판정 도우미 — 각 점검의 Test 블록이 이 넷 중 하나를 돌려준다
# ------------------------------------------------------------------------------
function Pass([string]$Note = '') { [pscustomobject]@{ Verdict = 'OK';   Note = $Note } }
function Warn([string]$Note)      { [pscustomobject]@{ Verdict = 'WARN'; Note = $Note } }
function Fail([string]$Note)      { [pscustomobject]@{ Verdict = 'FAIL'; Note = $Note } }
function Skip([string]$Note)      { [pscustomobject]@{ Verdict = 'SKIP'; Note = $Note } }

# 개수 세기. @($null).Count 는 5.1 에서 1 이 나오므로(빈 값을 원소 하나로 본다) 따로 둔다.
function Count($x) { if ($null -eq $x) { return 0 }; return @($x).Count }
# 숫자를 천 단위 쉼표로. 값이 없으면 '-'.
function N0($x) { if ($null -eq $x -or "$x" -eq '') { return '-' }; return ('{0:N0}' -f [double]$x) }

# 점검끼리 주고받는 값(앞 점검이 알아낸 질문 목록 · 매수 전 현금 등). 해시테이블은 참조로 넘어가므로
# 점검 블록 안에서 $state.키 = 값 으로 넣으면 다음 점검이 읽을 수 있다.
$state = @{}

# 로컬 점검 전용 계정 — 비밀번호가 여기 공개돼 있으므로 로컬 DB 에서만 쓴다(아래 가드).
$SmokeEmail = 'smoke-check@example.com'
$SmokePassword = 'smoke-check-1234'
$isLocal = $BaseUrl -match '^https?://(localhost|127\.0\.0\.1)(:\d+)?$'
if (-not $Email) {
  if (-not $isLocal) {
    Write-QFail "로컬이 아닌 주소($BaseUrl)에는 점검 계정을 자동으로 만들지 않습니다 — -Email · -Password 를 주세요."
    exit 1
  }
  $Email = $SmokeEmail
  $Password = $SmokePassword
} elseif (-not $Password) {
  $secure = Read-Host -AsSecureString "$Email 의 비밀번호"
  $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

# ==============================================================================
# 점검 목록 — 한 줄이 곧 「curl 한 번」 이다
#   G = 묶음 · Name = 무엇을 보나 · M = 메서드 · P = 경로 · Auth = 로그인 쿠키를 보내나
#   Expect = 기대 상태 코드 · Body = 보낼 JSON(해시테이블 또는 실행 때 만드는 블록)
#   Needs = 앞 점검이 $state 에 넣어 둬야 하는 값 · Timeout = 초
#   Test = 응답($r)을 받아 Pass / Warn / Fail / Skip 중 하나를 돌려주는 블록
#          $r.Status(상태 코드) · $r.Json(풀어 둔 응답) · $r.Text(본문 글) · $r.Ms(걸린 밀리초)
# ==============================================================================
$Checks = @(
  # ── 기본 ────────────────────────────────────────────────────────────────────
  @{ G = '기본'; Name = '앱이 살아 있다 (헬스 체크)'; M = 'GET'; P = '/api/health'; Auth = $false
     Test = { param($r) if ($r.Json.status -eq 'ok') { Pass "service = $($r.Json.service)" } else { Fail 'status 가 ok 가 아니다' } } }
  @{ G = '기본'; Name = '화면 파일을 내준다 (로그인 화면)'; M = 'GET'; P = '/login.html'; Auth = $false
     Test = { param($r) if ($r.Text -match '<html') { Pass ("HTML {0:N0}자" -f $r.Text.Length) } else { Fail 'HTML 이 아니다' } } }
  @{ G = '기본'; Name = 'API 목록 (OpenAPI 문서)'; M = 'GET'; P = '/openapi.json'; Auth = $false
     Test = { param($r)
       $n = Count $r.Json.paths.PSObject.Properties.Name
       if ($n -ge 100) { Pass "경로 $n 개 — 브라우저로 $BaseUrl/docs 를 열면 눌러 볼 수 있다" } else { Fail "경로가 $n 개뿐이다" } } }

  # ── 로그인 ──────────────────────────────────────────────────────────────────
  @{ G = '로그인'; Name = '내 정보 (쿠키 로그인 유지)'; M = 'GET'; P = '/api/me'; Auth = $true
     Test = { param($r)
       if ($r.Json.user.email -ne $Email) { return (Fail "다른 사용자: $($r.Json.user.email)") }
       if (@($r.Json.user.roles) -contains 'admin') { $state.is_admin = $true }   # 아래 「관리」 묶음이 본다
       Pass "$Email · 역할 $(@($r.Json.user.roles) -join ',')" } }
  @{ G = '로그인'; Name = '로그인 없이는 막힌다'; M = 'GET'; P = '/api/me'; Auth = $false; Expect = 401
     Test = { param($r) Pass "401 — $($r.Json.detail)" } }

  # ── 시세 · 지표 ─────────────────────────────────────────────────────────────
  @{ G = '시세'; Name = '국내 일봉 — 수집 DB 에서 오나'; M = 'GET'; P = '/api/stocks/candles?symbol=005930.KS&period=1mo&interval=1d'; Auth = $true
     Test = { param($r)
       $n = Count $r.Json.candles
       if ($n -lt 5) { return (Fail "봉이 $n 개뿐이다") }
       $msg = "봉 $n 개 · 출처 $($r.Json.source) · 기준일 $($r.Json.as_of)"
       if ($r.Json.source -eq 'collector') { Pass $msg } else { Warn "$msg — 수집 DB 가 아니라 외부에서 왔다(data\collector 확인)" } } }
  @{ G = '시세'; Name = '기술 지표 (RSI · 이동평균 · 볼린저 · 신호)'; M = 'GET'; P = '/api/stocks/quant/indicators?symbol=005930.KS&period=6mo'; Auth = $true
     Test = { param($r)
       if ((Count $r.Json.rsi) -lt 20) { return (Fail 'RSI 값이 20개 미만') }
       Pass "RSI $($r.Json.current_rsi) · 신호 $($r.Json.signal.action) · 종가 $(N0 $r.Json.current_price) · 기준일 $($r.Json.as_of)" } }
  @{ G = '시세'; Name = '현재가 (외부 시세 — 인터넷 필요)'; M = 'GET'; P = '/api/stocks/quote?symbol=005930.KS'; Auth = $true
     Test = { param($r) if ([double]$r.Json.price -gt 0) { Pass "$($r.Json.name) $(N0 $r.Json.price) 원 ($($r.Json.change_pct)%)" } else { Fail '가격이 0 이하' } } }
  @{ G = '시세'; Name = '차트 패턴 · 지지/저항'; M = 'GET'; P = '/api/stocks/patterns?symbol=005930.KS&period=6mo'; Auth = $true
     Test = { param($r) Pass "패턴 $(Count $r.Json.patterns) 개 · 성향 $($r.Json.pattern_bias) · 점수 $($r.Json.pattern_score)" } }
  @{ G = '시세'; Name = '다중 시간대 신호 (분봉 · 일봉 · 주봉)'; M = 'GET'; P = '/api/stocks/mtf-signal?symbol=005930.KS'; Auth = $true; Timeout = 60
     Test = { param($r) if ($r.Json.action) { Pass "$($r.Json.action) · 시간대 $(Count $r.Json.timeframes) 개 · 합의 $($r.Json.agreement)" } else { Fail 'action 이 없다' } } }
  @{ G = '시세'; Name = '시장 지수'; M = 'GET'; P = '/api/stocks/market'; Auth = $true
     Test = { param($r) if ((Count $r.Json.indices) -ge 1) { Pass "지수 $(Count $r.Json.indices) 개 · 캐시에서 $($r.Json.from_cache)" } else { Warn '지수가 비어 있다 — 시세 동기화 전일 수 있다' } } }

  # ── 전략 · 백테스트 ─────────────────────────────────────────────────────────
  # 비용 인자를 안 주면 「실제 요율(real)」 모델 — 연도별 매도세 + 수수료 + 유관기관비 + 슬리피지.
  # 그 요율은 응답의 cost 칸에 있다(costs.commission_bps 는 flat 모델의 입력값이라 real 에서는 0 이다).
  @{ G = '전략'; Name = '지표 전략 백테스트 (RSI+이평 · 실제 비용 요율)'; M = 'GET'; P = '/api/quant/pipeline?symbol=005930.KS&period=2y&base=rsi_ma'; Auth = $true; Timeout = 60
     Test = { param($r)
       if ($null -eq $r.Json.cost) { return (Fail '비용 모델(cost) 항목이 없다') }
       # return_total · return_buy_hold 는 비율이다(3.3703 = +337.03%) — 그대로 뒤에 % 를 붙이면 100배 작게 읽힌다.
       Pass ("거래 {0} 회 · 전략 {1:N2}% · 보유만 {2:N2}% · 비용 모델 {3} · 슬리피지 {4}bp" -f $r.Json.trade_count,
             ([double]$r.Json.return_total * 100), ([double]$r.Json.return_buy_hold * 100), $r.Json.cost.model, $r.Json.cost.slippage_bps) } }
  @{ G = '전략'; Name = '수식 지표 — 쓸 수 있는 함수 · 템플릿'; M = 'GET'; P = '/api/formula-indicators/reference'; Auth = $true
     Test = { param($r)
       $tpl = @($r.Json.templates)[0]
       if ($tpl) { $state.formula = @{ indicator_expr = $tpl.indicator_expr; buy_expr = $tpl.buy_expr; sell_expr = $tpl.sell_expr; params = $tpl.params } }
       Pass "함수 $(Count $r.Json.functions) 개 · 템플릿 $(Count $r.Json.templates) 개 (첫 템플릿: $($tpl.name))" } }
  @{ G = '전략'; Name = '수식 지표 — 식 검사'; M = 'POST'; P = '/api/formula-indicators/validate'; Auth = $true; Needs = 'formula'
     Body = { $state.formula }
     Test = { param($r) if ($r.Json.ok) { Pass "변수 $(@($r.Json.variables) -join ',') · 함수 $(@($r.Json.functions) -join ',')" } else { Fail "검사 불합격: $($r.Text)" } } }
  @{ G = '전략'; Name = '수식 지표 — 계산 · 백테스트 (저장 안 함)'; M = 'POST'; P = '/api/formula-indicators/compute'; Auth = $true; Needs = 'formula'; Timeout = 60
     Body = { $b = $state.formula.Clone(); $b.symbol = '005930.KS'; $b.period = '1y'; $b.use_cache = $false; $b }
     Test = { param($r)
       if ($null -eq $r.Json.backtest) { return (Fail 'backtest 항목이 없다') }
       Pass "$($r.Json.rows) 행 · 최근 신호 $($r.Json.latest_signal) · 수익 $($r.Json.backtest.total_return_pct)% · 기준일 $($r.Json.as_of)" } }
  @{ G = '전략'; Name = '저장한 커스텀 지표 목록'; M = 'GET'; P = '/api/custom-indicators'; Auth = $true
     Test = { param($r) Pass "저장된 지표 $(Count $r.Json.items) 개" } }

  # ── 로보어드바이저 ──────────────────────────────────────────────────────────
  @{ G = '로보'; Name = '투자 성향 질문'; M = 'GET'; P = '/api/ml/robo/questions'; Auth = $true
     Test = { param($r)
       $qs = @($r.Json.questions)
       if ($qs.Count -lt 1) { return (Fail '질문이 없다') }
       # 모든 질문에 첫 번째 선택지(0번)를 고른 답안을 만들어 다음 점검에 넘긴다.
       $answers = @{}
       foreach ($q in $qs) { $answers[$q.id] = 0 }
       $state.robo_answers = $answers
       Pass "질문 $($qs.Count) 개 · 성향 단계 $(Count $r.Json.levels) 개" } }
  @{ G = '로보'; Name = '투자 성향 점수 (계산만 · 저장 안 함)'; M = 'POST'; P = '/api/ml/robo/risk-profile'; Auth = $true; Needs = 'robo_answers'
     Body = { @{ answers = $state.robo_answers } }
     Test = { param($r) Pass "$($r.Json.level) ($($r.Json.risk_profile)) · $($r.Json.score)/$($r.Json.max_score) 점" } }
  @{ G = '로보'; Name = '자산 배분 · 추천 종목'; M = 'POST'; P = '/api/ml/robo/allocation'; Auth = $true; Timeout = 90
     Body = @{ risk_profile = 'moderate'; horizon_years = 3; amount_manwon = 5000 }
     Test = { param($r)
       $sum = 0.0
       foreach ($p in $r.Json.allocations.PSObject.Properties) { $sum += [double]$p.Value }
       if ([math]::Abs($sum - 100) -gt 0.5) { return (Fail "비중 합이 100 이 아니다 ($sum)") }
       Pass ("자산군 {0} 개 합 {1}% · 추천 종목 {2} 개" -f (Count $r.Json.allocations.PSObject.Properties.Name), $sum, (Count $r.Json.stock_picks)) } }
  @{ G = '로보'; Name = '목표 달성 확률 (몬테카를로 500회)'; M = 'POST'; P = '/api/ml/robo/goal-simulation'; Auth = $true
     Body = @{ amount_manwon = 5000; horizon_years = 3; target_return_pct = 8.0; n_paths = 500 }
     Test = { param($r) Pass "목표 달성 확률 $($r.Json.probability_pct)% · 손실 확률 $($r.Json.loss_probability_pct)%" } }

  # ── 용어사전 ────────────────────────────────────────────────────────────────
  # 로그인 없이 읽는 참조 자료다(Auth = $false). 용어는 파일(app\services\glossary_data\terms.json)이 원본이고
  # 앱이 켜질 때 표에 넣는다 — 첫 점검이 「표가 지금 파일과 같은 판인가」 를 본다.
  @{ G = '용어'; Name = '용어사전의 판 — 표가 파일과 같은가'; M = 'GET'; P = '/api/glossary/meta'; Auth = $false
     Test = { param($r)
       if (-not $r.Json.loaded) { return (Fail '표가 비어 있다 — 앱 로그(logs.ps1)에서 「용어사전」 줄을 본다') }
       $state.glossary_terms = [int]$r.Json.terms
       $msg = "용어 $(N0 $r.Json.terms) · 이름 $(N0 $r.Json.aliases) · 판 $("$($r.Json.checksum)".Substring(0, 12))"
       if ($r.Json.in_sync) { Pass $msg } else { Warn "$msg — 표가 지금 파일과 다르다. 앱을 다시 켜면 맞춰진다" } } }
  @{ G = '용어'; Name = '분류와 분류마다의 용어 수'; M = 'GET'; P = '/api/glossary/categories'; Auth = $false; Needs = 'glossary_terms'
     Test = { param($r)
       $n = Count $r.Json.categories
       if ($n -lt 5) { return (Fail "분류가 $n 개뿐이다") }
       if ([int]$r.Json.total_terms -ne $state.glossary_terms) { return (Fail "분류별 합 $($r.Json.total_terms) 이 용어 수 $($state.glossary_terms) 와 다르다") }
       Pass "분류 $n 개 · 합 $(N0 $r.Json.total_terms) 용어 · 가장 많은 분류 $(@($r.Json.categories | Sort-Object terms -Descending)[0].name)" } }
  @{ G = '용어'; Name = '검색 — 약어 (정확히 같은 이름이 맨 위)'; M = 'GET'; P = '/api/glossary?q=PER&limit=5'; Auth = $false
     Test = { param($r)
       $top = @($r.Json.items)[0]
       if ($top.id -eq 'per') { Pass "$($r.Json.total) 건 · 맨 위 $($top.term) — $($top.summary)" } else { Fail "맨 위가 PER 이 아니다: $($top.term)" } } }
  @{ G = '용어'; Name = '검색 — 초성 (ㅅㄱㅊㅇ)'; M = 'GET'; P = '/api/glossary?q=ㅅㄱㅊㅇ'; Auth = $false
     Test = { param($r)
       $top = @($r.Json.items)[0]
       if ($top.term -eq '시가총액') { Pass "$($top.term) · 맞은 곳 $($top.match)" } else { Fail "시가총액이 나오지 않았다 (결과 $($r.Json.total) 건)" } } }
  @{ G = '용어'; Name = '용어 한 건 — 화면의 용어 키(sharpe)로'; M = 'GET'; P = '/api/glossary/sharpe'; Auth = $false
     Test = { param($r)
       if ($r.Json.matched.kind -ne '화면 키') { return (Fail "화면 키로 찾지 못했다: $($r.Json.matched.kind)") }
       Pass "$($r.Json.term) ($($r.Json.english)) · 분류 $($r.Json.category.name) · 자료 $(Count $r.Json.sources) 곳 · 다른 이름 $(Count $r.Json.aliases) 개" } }
  @{ G = '용어'; Name = '없는 용어는 404'; M = 'GET'; P = '/api/glossary/없는용어'; Auth = $false; Expect = 404
     Test = { param($r) Pass "404 — $($r.Json.detail)" } }

  # ── 데이터 상태 · 거래일 달력 (2026-10-02) ──────────────────────────────────
  # 상태는 로그인 뒤(수집 자료의 양 · 이 PC 의 작업 기록), 달력 · 일정은 로그인 없이 읽는다.
  # 달력은 수집기가 매일 12:30 에 다시 만든다 — 없으면 503 과 할 일(python -m collector.market_calendar build).
  @{ G = '데이터'; Name = '데이터 상태 — 일일 갱신 · 표별 기준일'; M = 'GET'; P = '/api/data/status'; Auth = $true
     Test = { param($r)
       $late = @($r.Json.tables | Where-Object { $_.verdict -in @('late', 'stale', 'missing') } | ForEach-Object { "$($_.label) $($_.verdict_label)" })
       $msg = "$($r.Json.verdict_label) · 시세 기준일 $($r.Json.as_of) · 일일 갱신 $($r.Json.runner.label)"
       if ($r.Json.verdict -eq 'ok') { Pass $msg }
       elseif ($r.Json.verdict -eq 'warning') { Warn ("$msg — " + ($late -join ' · ')) }
       else { Fail ("$msg — " + ($late -join ' · ')) } } }
  @{ G = '데이터'; Name = '거래일 달력 — 오늘부터 60일'; M = 'GET'; P = '/api/calendar/trading-days'; Auth = $false
     Test = { param($r)
       $next = @($r.Json.days | Where-Object { -not $_.is_trading_day -and $_.weekday -notin @('토', '일') })[0]
       $msg = "거래일 $($r.Json.trading_days) · 휴장 $($r.Json.closed_days) · 달력 끝 $($r.Json.calendar.end)"
       if ($next) { $msg += " · 다음 평일 휴장 $($next.date) $($next.reason)" }
       Pass $msg } }
  @{ G = '데이터'; Name = '금융 일정 — 파생 만기 · 배당락일'; M = 'GET'; P = '/api/calendar/events?kind=deriv_expiry,dividend_ex'; Auth = $false
     Test = { param($r)
       $exp = @($r.Json.events | Where-Object { $_.kind -eq 'deriv_expiry' })[0]
       if (-not $exp) { return (Fail '60일 안에 파생 만기가 없다 — 달력이 짧거나 일정이 비었다') }
       Pass "다음 만기 $($exp.date) $($exp.title) · 배당락일 $(Count @($r.Json.events | Where-Object { $_.kind -eq 'dividend_ex' })) 건" } }
  # OHLCV 규격 자료(ohlcv-v1 · 2026-10-02) — HF krx-ohlcv 와 같은 줄 모양을 한 종목씩. 로그인 뒤.
  @{ G = '데이터'; Name = 'OHLCV — 삼성전자 수정 일봉 1년'; M = 'GET'; P = '/api/data/ohlcv?symbol=005930'; Auth = $true
     Test = { param($r)
       if ($r.Json.contract -ne 'ohlcv-v1' -or $r.Json.count -lt 200) { return (Fail "줄 $($r.Json.count) · 규격 $($r.Json.contract)") }
       $last = $r.Json.rows[-1]
       Pass "$($r.Json.count) 줄 · $($r.Json.basis) · 마지막 $($last.trade_date) 종가 $(N0 $last.close) · 받은 시각 $($last.fetched_at)" } }
  @{ G = '데이터'; Name = 'OHLCV — 코스피 200 주봉 · 진행 중인 주'; M = 'GET'; P = '/api/data/ohlcv?symbol=KOSPI:%EC%BD%94%EC%8A%A4%ED%94%BC%20200&timeframe=1w'; Auth = $true
     Test = { param($r)
       $last = $r.Json.rows[-1]
       Pass "$($r.Json.count) 주 · 마지막 $($last.trade_date) 종가 $($last.close) · 진행 중 $($r.Json.partial)" } }

  # ── 매매: 모의투자 · 자동매매 · 위험 한도 · 리밸런싱 · 증권사 ─────────────────
  @{ G = '매매'; Name = '모의투자 잔고'; M = 'GET'; P = '/api/paper/account'; Auth = $true
     Test = { param($r) Pass "현금 $(N0 $r.Json.cash) · 주식 평가 $(N0 $r.Json.stockEval) · 총자산 $(N0 $r.Json.totalAsset) 원" } }
  @{ G = '매매'; Name = '모의투자 보유 종목'; M = 'GET'; P = '/api/paper/stocks/positions'; Auth = $true
     Test = { param($r) Pass "보유 $(Count $r.Json.positions) 종목" } }
  @{ G = '매매'; Name = '주문 미리보기 (잔고는 안 바뀜)'; M = 'POST'; P = '/api/paper/stocks/orders/preview'; Auth = $true
     Body = @{ symbol = '005930'; side = 'BUY'; quantity = 1 }
     Test = { param($r)
       $state.preview_amount = $r.Json.estimatedAmount
       if ($r.Json.executable) { Pass "삼성전자 1주 예상 $(N0 $r.Json.estimatedAmount) 원 · 주문 뒤 현금 $(N0 $r.Json.cashAfter) 원" } else { Warn "주문 불가: $($r.Json.reason)" } } }
  @{ G = '매매'; Name = '자동매매 상태 (Celery 비트 10분 주기)'; M = 'GET'; P = '/api/auto-trade/status'; Auth = $true
     Test = { param($r)
       $msg = "실행 중 $($r.Json.running) · 예약 $($r.Json.scheduler) · 주기 $($r.Json.interval_sec)초"
       if ("$($r.Json.scheduler)" -match 'celery') { Pass $msg } else { Warn "$msg — 예약기가 Celery 가 아니다" } } }
  @{ G = '매매'; Name = '위험 한도 (일 손실 · 종목 비중 · 주문 수 · 비상 정지)'; M = 'GET'; P = '/api/quant/risk/status'; Auth = $true
     Test = { param($r)
       if ($null -eq $r.Json.limits) { return (Fail 'limits 가 없다') }
       $l = $r.Json.limits
       $msg = "일 손실 한도 $($l.daily_loss_limit_pct)% · 종목 한도 $($l.max_position_pct)% · 남은 주문 $($r.Json.orders_remaining) · 비상 정지 $($r.Json.kill_switch)"
       if ($r.Json.kill_switch) { Warn "$msg — 비상 정지가 켜져 있다" } else { Pass $msg } } }
  @{ G = '매매'; Name = '리밸런싱 상태 (목표 비중 · 이탈)'; M = 'GET'; P = '/api/rebalance/status'; Auth = $true
     Test = { param($r) Pass "목표 종목 $(Count $r.Json.plan.targets) 개 · 현금 목표 $($r.Json.plan.cash_weight_pct)% · 시간 트리거 $($r.Json.triggers.time_due) · 이탈 트리거 $($r.Json.triggers.drift_due)" } }
  @{ G = '매매'; Name = '증권사 설정 (모의 / 실전)'; M = 'GET'; P = '/api/broker/settings'; Auth = $true
     Test = { param($r)
       $msg = "증권사 $($r.Json.broker) · 모의 $($r.Json.paper) · 연결 $($r.Json.connected)"
       if ($r.Json.paper -eq $false) { Warn "$msg — 실전 모드다(실거래 주문은 코드에서 막혀 있지만 설정을 확인하라)" } else { Pass $msg } } }

  # ── 연동 ────────────────────────────────────────────────────────────────────
  @{ G = '연동'; Name = 'TradingView 웹훅 안내'; M = 'GET'; P = '/api/tradingview/webhook-info'; Auth = $true
     Test = { param($r) if ($r.Json.webhook_url) { Pass "웹훅 주소 $($r.Json.webhook_url)" } else { Fail 'webhook_url 이 없다' } } }
  @{ G = '연동'; Name = '알림 설정 (텔레그램 · 슬랙 · 메일 · 카카오)'; M = 'GET'; P = '/api/notification/settings'; Auth = $true
     Test = { param($r) Pass "켜진 채널 $(Count $r.Json.channels) 개" } }

  # ── 시스템 ──────────────────────────────────────────────────────────────────
  @{ G = '시스템'; Name = '시세 동기화 스케줄러'; M = 'GET'; P = '/api/system/sync-status'; Auth = $true
     Test = { param($r) Pass "온라인 $($r.Json.online) · 스케줄러 실행 중 $($r.Json.scheduler.running) · 마지막 동기화 $($r.Json.scheduler.last_sync)" } }
  @{ G = '시스템'; Name = 'LEAN 백테스트 엔진 모드'; M = 'GET'; P = '/api/backtests/lean/status'; Auth = $true
     Test = { param($r)
       $msg = "모드 $($r.Json.mode) · 전략 $(Count $r.Json.strategies) 개"
       if ($r.Json.mode -eq 'docker') {
         # docker 모드에서 백테스트를 실제로 돌리면 quantconnect/lean 이미지(약 14GB)를 받기 시작한다.
         $null = & docker image inspect quantconnect/lean:latest 2>$null
         if ($LASTEXITCODE -ne 0) { return (Warn "$msg — LEAN 이미지(약 14GB)가 없다. 실행하면 받기 시작한다. 로컬 점검은 .env 에 LEAN_MODE=local 권장") }
       }
       Pass $msg } }
  @{ G = '시스템'; Name = 'AI(LLM) 연결 — AI 채팅 · 문서 검색의 전제'; M = 'GET'; P = '/api/system/status'; Auth = $true
     Test = { param($r)
       $llm = $r.Json.llm_provider
       if ($llm.ok) { Pass "$($llm.provider) 연결됨 ($($llm.target) · $($llm.ms)ms)" }
       else { Skip "$($llm.provider) 에 닿지 않음 ($($llm.target)) — AI 채팅 · RAG 는 제외(설계상 동결 기능). 컨테이너 Ollama 면 처음 한 번 docker compose up -d model-pull · 이 PC 의 Ollama 를 쓰려면 .env 에 COMPOSE_OLLAMA_URL=http://host.docker.internal:11434 (docker-compose.yml 이 .env 의 OLLAMA_BASE_URL 보다 우선)" } } }

  @{ G = '시스템'; Name = '벡터 DB(Qdrant) 연결 — 문서 근거 RAG · 크롤링 적재의 전제'; M = 'GET'; P = '/api/system/status'; Auth = $true
     Test = { param($r)
       $q = @($r.Json.services) | Where-Object { $_.name -eq 'Qdrant' } | Select-Object -First 1
       if (-not $q) { return (Fail '상태 응답에 Qdrant 줄이 없다') }
       if ($q.ok) { Pass "Qdrant 연결됨 ($($q.url) · $($q.ms)ms)" }
       else { Fail "Qdrant 에 닿지 않음 ($($q.url)) — .\scripts\personal\logs.ps1 -Service qdrant · compose 의 qdrant 서비스(2026-10-02~ 늘 켬)" } } }

  # ── 관리 (관리자 전용 · 읽기만) ─────────────────────────────────────────────────
  # ⚠️ POST /api/admin/reset(금융 · 사용자 표 전부 삭제)은 점검에 넣지 않는다 — 읽기 API 둘만.
  @{ G = '관리'; Name = 'DB 통계 (관리자 전용)'; M = 'GET'; P = '/api/admin/stats'; Auth = $true; Needs = 'is_admin'
     NeedsNote = '관리자가 아닌 계정이라 건너뜀 — 로컬 점검 계정은 자동으로 관리자다(-Email 로 다른 계정을 주면 그 계정의 역할을 따른다)'
     Test = { param($r)
       $n = @($r.Json.stats.PSObject.Properties).Count
       Pass "표 $n 개 · 대화 $(N0 $r.Json.stats.'postgres.chats') 건 · 주문 $(N0 $r.Json.stats.'postgres.orders') 건 · 감사 기록 $(N0 $r.Json.stats.'postgres.audit_events') 건" } }
  @{ G = '관리'; Name = '감사 기록 (관리자 전용 · 최근 5건)'; M = 'GET'; P = '/api/admin/audit-log?limit=5'; Auth = $true; Needs = 'is_admin'
     NeedsNote = '관리자가 아닌 계정이라 건너뜀'
     Test = { param($r)
       $first = @($r.Json.events) | Select-Object -First 1
       Pass "최근 $($r.Json.count) 건 · 맨 위 $($first.event_type) ($($first.created_at))" } }
)

# ── 느림: 요청마다 모델을 학습한다 (-Full) ──────────────────────────────────────
if ($Full) {
  $Checks += @(
    @{ G = '느림'; Name = '종목 신호 스캔 (31종목 · RSI 모델)'; M = 'GET'; P = '/api/stocks/signals?signal=all&model=rsi'; Auth = $true; Timeout = 180
       Test = { param($r) Pass "신호 $($r.Json.count) 건" } }
    @{ G = '느림'; Name = 'XAI — LightGBM 판단 근거 (SHAP)'; M = 'GET'; P = '/api/ml/explain?symbol=005930.KS'; Auth = $true; Timeout = 180
       Test = { param($r) Pass "예측 신호 $($r.Json.prediction.signal) · 설명 방법 $($r.Json.explanation.method) · 기여 요인 $(Count $r.Json.explanation.contributions) 개" } }
    @{ G = '느림'; Name = 'ML 모델 비교 (5겹 교차검증)'; M = 'GET'; P = '/api/ml/compare?symbol=005930.KS'; Auth = $true; Timeout = 180
       Test = { param($r) Pass "모델 $(Count $r.Json.models) 개 · 최고 $($r.Json.best_model) · 데이터 $($r.Json.data_rows) 행" } }
  )
}

# ── 쓰기: 기록이 남는다 (-Write) — 점검 계정 안에서만, 순서대로 ────────────────────
if ($Write) {
  $Checks += @(
    @{ G = '쓰기'; Name = '매수 전 현금 기억'; M = 'GET'; P = '/api/paper/account'; Auth = $true
       Test = { param($r) $state.cash0 = [double]$r.Json.cash; Pass "현금 $(N0 $r.Json.cash) 원" } }
    @{ G = '쓰기'; Name = '모의 매수 — 삼성전자 1주'; M = 'POST'; P = '/api/paper/stocks/orders/buy'; Auth = $true; Needs = 'cash0'
       Body = @{ symbol = '005930'; side = 'BUY'; quantity = 1 }
       Test = { param($r) Pass ("체결 — 응답 키: {0}" -f ((@($r.Json.PSObject.Properties.Name) | Select-Object -First 6) -join ', ')) } }
    @{ G = '쓰기'; Name = '보유에 들어왔나'; M = 'GET'; P = '/api/paper/stocks/positions'; Auth = $true
       Test = { param($r)
         $pos = @($r.Json.positions) | Where-Object { "$($_.symbol)$($_.code)" -match '005930' } | Select-Object -First 1
         if ($pos) { Pass "005930 보유 확인" } else { Fail '005930 이 보유 목록에 없다' } } }
    @{ G = '쓰기'; Name = '현금이 줄었나 — 미리보기와 비교 (비용 포함 여부)'; M = 'GET'; P = '/api/paper/account'; Auth = $true; Needs = 'cash0'
       Test = { param($r)
         $spent = $state.cash0 - [double]$r.Json.cash
         if ($spent -le 0) { return (Fail "현금이 줄지 않았다 (차이 $(N0 $spent))") }
         $msg = "현금 $(N0 $state.cash0) → $(N0 $r.Json.cash) 원 (빠진 돈 $(N0 $spent))"
         if ($state.preview_amount) {
           $gap = $spent - [double]$state.preview_amount
           # 미리보기는 주문 전 가격 · 비용 없이 계산하고, 실제 체결은 그 순간 가격 + 수수료 · 세금을 뺀다.
           $msg += " · 미리보기 $(N0 $state.preview_amount) 와 차이 $(N0 $gap) 원"
         }
         Pass $msg } }
    @{ G = '쓰기'; Name = '모의 매도 — 삼성전자 1주'; M = 'POST'; P = '/api/paper/stocks/orders/sell'; Auth = $true
       Body = @{ symbol = '005930'; side = 'SELL'; quantity = 1 }
       Test = { param($r) Pass '매도 체결' } }
    @{ G = '쓰기'; Name = '주문 이력에 남았나'; M = 'GET'; P = '/api/paper/stocks/orders/history?limit=5'; Auth = $true
       Test = { param($r) if ((Count $r.Json.history) -ge 2) { Pass "최근 이력 $(Count $r.Json.history) 건" } else { Fail '이력이 2건 미만' } } }
    @{ G = '쓰기'; Name = '리밸런싱 목표 저장 (삼성전자 10%)'; M = 'PUT'; P = '/api/rebalance/plan'; Auth = $true
       Body = @{ targets = @(@{ symbol = '005930.KS'; name = '삼성전자'; weight_pct = 10 }) }
       Test = { param($r) Pass "목표 $(Count $r.Json.targets) 개 저장" } }
    @{ G = '쓰기'; Name = '리밸런싱 미리보기 (주문안 · 실행 안 함)'; M = 'POST'; P = '/api/rebalance/preview'; Auth = $true
       Body = @{}
       Test = { param($r) Pass ("응답 키: {0}" -f ((@($r.Json.PSObject.Properties.Name) | Select-Object -First 6) -join ', ')) } }
    @{ G = '쓰기'; Name = '리밸런싱 목표 되돌리기 (비움)'; M = 'PUT'; P = '/api/rebalance/plan'; Auth = $true
       Body = @{ targets = @() }
       Test = { param($r) Pass '목표 비움' } }
    # 문서 근거 RAG 왕복 — 임베딩(Ollama nomic-embed-text) · 벡터 저장(Qdrant)이 실제로 되는지. 끝에 지워 흔적을 남기지 않는다.
    # 예전에는 저장이 늘 실패하면서 「0청크 저장」 이 성공(200)으로 보였다(DF-38) — 그래서 청크 수까지 본다.
    @{ G = '쓰기'; Name = 'RAG — 작은 글 올리기 (임베딩 · 벡터 저장)'; M = 'POST'; P = '/api/documents/upload'; Auth = $true; Timeout = 120
       File = @{ Name = 'file'; FileName = 'qurious-rag-check.txt'
                 Text = "괴리율은 ETF 가 거래소에서 거래되는 가격과 순자산가치(NAV)의 차이를 비율로 나타낸 값이다.`niNAV 는 장중에 실시간으로 계산한 추정 순자산가치다." }
       Test = { param($r)
         if ([int]$r.Json.chunks -lt 1) { return (Fail "청크 $($r.Json.chunks) 개 저장 — 벡터 저장이 안 됐다") }
         $state.rag_doc = "$($r.Json.doc_id)"
         Pass "청크 $($r.Json.chunks) 개 저장 · 문서 $($r.Json.doc_id)" } }
    @{ G = '쓰기'; Name = 'RAG — 올린 글 찾기'; M = 'POST'; P = '/api/documents/search'; Auth = $true; Needs = 'rag_doc'
       Body = @{ query = 'ETF 괴리율'; top_k = 3 }
       Test = { param($r)
         $top = @($r.Json.hits) | Select-Object -First 1
         if (-not $top) { return (Fail '찾은 청크가 없다') }
         if ($top.title -ne 'qurious-rag-check.txt') { return (Warn "맨 위가 다른 글: $($top.title)") }
         Pass ("맨 위 {0} · 유사도 {1:N3}" -f $top.title, [double]$top.score) } }
    @{ G = '쓰기'; Name = 'RAG — 채팅 「순수 RAG」 모드 (LLM 없이 청크만)'; M = 'POST'; P = '/api/chat'; Auth = $true; Needs = 'rag_doc'; Timeout = 60
       Body = @{ question = 'ETF 괴리율'; llm_mode = 'rag' }
       Test = { param($r)
         if ($r.Json.mode -ne 'rag') { return (Fail "모드 $($r.Json.mode)") }
         if ((Count $r.Json.chunks) -lt 1) { return (Fail '청크 0 개 — 채팅이 저장한 글을 못 찾는다') }
         Pass "청크 $(Count $r.Json.chunks) 개" } }
    @{ G = '쓰기'; Name = 'RAG — 올린 글 지우기 (메타 · 벡터)'; M = 'DELETE'; P = { "/api/documents/$($state.rag_doc)" }; Auth = $true; Needs = 'rag_doc'
       Test = { param($r) Pass "$($r.Json.message)" } }
    @{ G = '쓰기'; Name = 'RAG — 지운 뒤 다시 찾기 → 0'; M = 'POST'; P = '/api/documents/search'; Auth = $true; Needs = 'rag_doc'
       Body = @{ query = 'ETF 괴리율'; top_k = 3 }
       Test = { param($r)
         $left = @($r.Json.hits) | Where-Object { $_.title -eq 'qurious-rag-check.txt' }
         if ((Count $left) -gt 0) { return (Fail "지운 글이 $(Count $left) 청크 남았다 — 벡터 삭제가 안 됐다") }
         Pass '남은 청크 0' } }
  )
}

# -Group 으로 고른 묶음만 남긴다. 모르는 이름이면 쓸 수 있는 이름을 알려 준다.
# 「계정」 묶음은 $Checks 목록이 아니라 아래 따로 도는 블록이라(이유는 그 블록 머리) 이름만 더한다.
$allGroups = @($Checks | ForEach-Object { $_.G } | Select-Object -Unique) + @('계정')
$runAccount = ($Group.Count -eq 0) -or ($Group -contains '계정')
if ($Group.Count -gt 0) {
  $unknown = @($Group | Where-Object { $allGroups -notcontains $_ })
  if ($unknown.Count -gt 0) {
    Write-QFail ("모르는 묶음: {0} — 쓸 수 있는 묶음: {1}" -f ($unknown -join ', '), ($allGroups -join ', '))
    Write-QInfo '「느림」 은 -Full, 「쓰기」 는 -Write 를 함께 줘야 목록에 생긴다.  예) -Write -Group 쓰기'
    exit 1
  }
  $Checks = @($Checks | Where-Object { $Group -contains $_.G })
}

# ==============================================================================
# 실행
# ==============================================================================
Write-QTitle "Qurious 기능 점검 — $BaseUrl"
$runStart = Get-Date
$results = New-Object System.Collections.Generic.List[object]

function Add-Result($c, $status, $ms, $v) {
  $results.Add([pscustomobject]@{ Group = $c.G; Name = $c.Name; Method = $c.M; Path = $c.P; Status = $status; Ms = $ms; Verdict = $v.Verdict; Note = $v.Note })
  $tag = @{ OK = '[ OK ]'; WARN = '[주의]'; FAIL = '[실패]'; SKIP = '[건너뜀]' }[$v.Verdict]
  $color = @{ OK = 'Green'; WARN = 'Yellow'; FAIL = 'Red'; SKIP = 'DarkGray' }[$v.Verdict]
  Write-Host ("  {0} [{1}] {2}" -f $tag, $c.G, $c.Name) -ForegroundColor $color
  Write-Host ("         {0} {1}  → {2} · {3}ms" -f $c.M, $c.P, $status, $ms) -ForegroundColor DarkGray
  if ($v.Note) { Write-Host ("         {0}" -f $v.Note) -ForegroundColor Gray }
}

# 앱이 떠 있는지부터 — 안 떠 있으면 점검 수십 개가 전부 「응답 없음」 으로 도배되므로 여기서 끝낸다.
$ping = Invoke-QApi -Method GET -Url "$BaseUrl/api/health" -TimeoutSec 5
if ($ping.Status -ne 200) {
  Write-QFail "앱이 응답하지 않습니다 ($BaseUrl) — 먼저 .\scripts\personal\start.ps1"
  if ($ping.Error) { Write-QInfo $ping.Error }
  exit 1
}

# 로그인 — 화면과 같은 쿠키 방식. 세션 객체가 curl 의 쿠키 저장소(-c · -b) 구실을 한다.
$session = $null
if (@($Checks | Where-Object { $_.Auth }).Count -gt 0) {
  $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $loginCheck = @{ G = '로그인'; Name = '로그인 (쿠키 fin_session 받기)'; M = 'POST'; P = '/api/auth/login' }
  $login = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/login" -Body @{ email = $Email; password = $Password } -Session $session
  $how = '기존 계정'
  if ($login.Status -eq 401 -and $Email -eq $SmokeEmail) {
    # 점검 계정이 아직 없다(새 DB) → 한 번 가입한다. 가입도 쿠키를 준다.
    $login = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/register" -Body @{ name = '로컬 점검'; email = $Email; password = $Password } -Session $session
    $how = '처음이라 가입함'
  }
  # 점검 계정은 관리자다 — 관리자만 쓰는 화면 · API(감사 기록 · DB 통계)까지 점검하려고(2026-10-02 사용자 요청).
  # 역할은 **가입할 때만** 정해지므로(설정 ADMIN_EMAILS · app/routes/auth.py 의 register) 이미 있는 점검 계정은
  # 로컬 DB 에서 한 번 올린다. 로컬 주소 · 점검 계정일 때만 — 비밀번호가 이 파일에 공개된 계정이라 다른 곳에선 안 된다.
  # 세션에는 로그인 때의 역할이 복사되므로, 올린 뒤 다시 로그인해야 새 역할이 실린다.
  if ($login.Status -eq 200 -and $isLocal -and $Email -eq $SmokeEmail) {
    $me0 = Invoke-QApi -Method GET -Url "$BaseUrl/api/me" -Session $session
    if ($me0.Status -eq 200 -and -not (@($me0.Json.user.roles) -contains 'admin')) {
      $sql = "UPDATE users SET roles = array_append(roles, 'admin'::varchar) WHERE lower(email) = '$SmokeEmail' AND NOT ('admin' = ANY(roles));"
      $out = (& docker exec fin-ai-postgres psql -U fin_user -d fin_ai -c $sql 2>&1 | ForEach-Object { "$_" }) -join ' '
      $login = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/login" -Body @{ email = $Email; password = $Password } -Session $session
      if ($out -match 'UPDATE 1') { $how += ' · 관리자 역할을 올림(로컬 DB)' } else { $how += " · 관리자 역할을 못 올림($out)" }
    }
  }
  if ($login.Status -eq 200) {
    Add-Result $loginCheck $login.Status $login.Ms (Pass "$Email · $how")
  } else {
    Add-Result $loginCheck $login.Status $login.Ms (Fail "로그인 실패: $($login.Text) $($login.Error)")
    Write-QInfo '로그인이 없으면 나머지 점검이 모두 401 이 됩니다 — 여기서 멈춥니다.'
    exit 1
  }
}

# ==============================================================================
# 계정 묶음 — 가입(C) · 조회(R) · 수정(U) · 탈퇴(D) · 로그아웃 · 토큰 · 대소문자 · 비밀번호 규칙 (기본 포함 · -Group 계정)
# ==============================================================================
# 왜 $Checks 목록이 아니라 따로 도나
#   위 목록은 모두 「점검 계정 하나의 로그인 쿠키」 를 나눠 쓴다. 계정 점검은 가입 → 로그아웃 → 다시
#   로그인 → 비밀번호 변경 → 탈퇴처럼 **쿠키 상태를 바꾸는 순서** 자체를 보는 것이라, 자기 세션(기기 둘)을
#   따로 쥐고 차례로 돈다.
# 임시 계정
#   Crud-Check-<시각>@Example.COM (일부러 대문자를 섞어 가입) — 끝에 **탈퇴 API 로** 지운다. 탈퇴가 실패해
#   남은 계정만 docker exec 로 로컬 DB 에서 지운다(로컬 전용 · 이 묶음이 만든 이메일만).
# 규칙과 근거는 app/services/account.py 머리말 · 문서 「기능별 동작 원리서」 2절.
if ($runAccount) {
  $acctGroup = '계정'
  function Add-Acct([string]$Name, [string]$M, [string]$P, $r, $v) {
    $st = '-'; $ms = 0
    if ($null -ne $r) { $st = $r.Status; $ms = $r.Ms }
    Add-Result @{ G = $acctGroup; Name = $Name; M = $M; P = $P } $st $ms $v
  }
  # 기대 상태 코드 하나만 보는 단계의 판정 — 맞으면 OK(메모), 다르면 실패(상태 · 서버 메시지)
  function Expect-Status($r, [int]$want, [string]$okNote) {
    if ($r.Status -eq $want) { return (Pass $okNote) }
    $detail = "$($r.Text)"
    if ($r.Json -and $r.Json.detail) { $detail = "$($r.Json.detail)" }
    if ($detail.Length -gt 160) { $detail = $detail.Substring(0, 160) + '…' }
    return (Fail ("상태 {0} (기대 {1}) — {2}" -f $r.Status, $want, $detail))
  }
  if (-not $isLocal) {
    Add-Acct '계정 점검 전체' '-' '-' $null (Skip "로컬이 아닌 주소($BaseUrl)에는 임시 계정을 만들지 않는다")
  } else {
    $stamp = Get-Date -Format 'yyyyMMddHHmmss'
    $typed = "Crud-Check-$stamp@Example.COM"      # 사람이 친 모양 — 대문자가 섞였다
    $acctEmail = $typed.ToLower()                   # 서버가 저장하는 모양
    $acctPw = 'crud-check-1234'
    $newPw = 'crud-check-5678'
    $made = New-Object System.Collections.Generic.List[string]
    $acct = New-Object Microsoft.PowerShell.Commands.WebRequestSession    # 이 기기
    $other = New-Object Microsoft.PowerShell.Commands.WebRequestSession   # 다른 기기

    # 1. 가입(C) — 대문자 섞인 이메일로. 가입도 로그인 쿠키를 준다(화면은 가입 직후 바로 앱으로 들어간다).
    $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/register" -Body @{ name = '계정 점검'; email = $typed; password = $acctPw } -Session $acct
    if ($r.Status -eq 200) {
      $made.Add($acctEmail)
      if ("$($r.Json.user.email)" -eq $acctEmail) { $v = Pass "친 글자 $typed → 저장 $acctEmail(전부 소문자)" }
      else { $v = Fail "저장된 이메일이 소문자가 아니다: $($r.Json.user.email)" }
    } else { $v = Fail "상태 $($r.Status) — $($r.Text)" }
    Add-Acct '가입 (C) — 대문자 섞인 이메일' 'POST' '/api/auth/register' $r $v
    $joined = ($r.Status -eq 200)

    if ($joined) {
      # 2. 조회(R) — 가입 때 받은 쿠키 그대로 · 가입일까지
      $r = Invoke-QApi -Method GET -Url "$BaseUrl/api/me" -Session $acct
      if ($r.Status -eq 200 -and $r.Json.user.email -eq $acctEmail) { $v = Pass "이름 $($r.Json.user.name) · 가입일 $($r.Json.user.createdAt)" } else { $v = Fail "상태 $($r.Status) · 이메일 $($r.Json.user.email)" }
      Add-Acct '내 정보 (R)' 'GET' '/api/me' $r $v

      # 2-1. 일반 계정은 관리자 API 가 막힌다 → 403 (점검 계정이 관리자라 「관리」 묶음만으로는 못 보는 쪽)
      $r = Invoke-QApi -Method GET -Url "$BaseUrl/api/admin/stats" -Session $acct
      Add-Acct '일반 계정으로 관리자 API → 막힘' 'GET' '/api/admin/stats' $r (Expect-Status $r 403 "403 — $($r.Json.detail)")

      # 3. 소문자로 다시 가입 → 400 (대소문자만 다른 두 번째 가입을 막는다)
      $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/register" -Body @{ name = '중복'; email = $acctEmail; password = $acctPw }
      Add-Acct '대소문자만 다른 이메일로 다시 가입 → 거절' 'POST' '/api/auth/register' $r (Expect-Status $r 400 "400 — $($r.Json.detail)")

      # 4. 로그아웃 → 5. 방금 그 쿠키로 내 정보 → 401 (서버 쪽 세션이 정말 지워졌나)
      $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/logout" -Session $acct
      Add-Acct '로그아웃' 'POST' '/api/auth/logout' $r (Expect-Status $r 200 '세션 지움 · 쿠키 삭제')
      $r = Invoke-QApi -Method GET -Url "$BaseUrl/api/me" -Session $acct
      Add-Acct '로그아웃 뒤 내 정보 → 막힘' 'GET' '/api/me' $r (Expect-Status $r 401 '401 — 로그아웃한 쿠키는 더 못 쓴다')

      # 6. 틀린 비밀번호 → 401 · 7. 가입 때 친 글자 그대로 → 200 · 8. 전부 대문자(다른 기기) → 200
      $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/login" -Body @{ email = $typed; password = 'wrong-password' }
      Add-Acct '틀린 비밀번호 로그인 → 거절' 'POST' '/api/auth/login' $r (Expect-Status $r 401 "401 — $($r.Json.detail)")
      $acct = New-Object Microsoft.PowerShell.Commands.WebRequestSession
      $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/login" -Body @{ email = $typed; password = $acctPw } -Session $acct
      Add-Acct '가입 때 친 글자 그대로 로그인' 'POST' '/api/auth/login' $r (Expect-Status $r 200 "$typed 로 로그인 — 대소문자를 가리지 않는다")
      $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/login" -Body @{ email = $typed.ToUpper(); password = $acctPw } -Session $other
      Add-Acct '전부 대문자로 로그인 (다른 기기)' 'POST' '/api/auth/login' $r (Expect-Status $r 200 '두 번째 기기 세션')

      # 9~12. 토큰 방식(JWT) — 발급 → Bearer 로 내 정보 → 폐기 → 같은 토큰은 401
      #        화면은 쿠키만 쓴다. 토큰은 앱 밖 프로그램(API 클라이언트)용이다.
      $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/token" -Body @{ email = $acctEmail; password = $acctPw }
      $access = ''; $refresh = ''
      if ($r.Status -eq 200 -and $r.Json.access_token) { $access = $r.Json.access_token; $refresh = $r.Json.refresh_token; $v = Pass "액세스 $($r.Json.expires_in)초 · 리프레시 함께" } else { $v = Fail "상태 $($r.Status)" }
      Add-Acct '토큰 발급 (JWT · API 클라이언트용)' 'POST' '/api/auth/token' $r $v
      if ($access) {
        $r = Invoke-QApi -Method GET -Url "$BaseUrl/api/me" -Bearer $access
        Add-Acct '내 정보 — Bearer 토큰으로' 'GET' '/api/me' $r (Expect-Status $r 200 'Authorization: Bearer 머리글로 통과')
        $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/token/revoke" -Body @{ access_token = $access; refresh_token = $refresh } -Bearer $access
        Add-Acct '토큰 폐기 (JWT 로그아웃)' 'POST' '/api/auth/token/revoke' $r (Expect-Status $r 200 "폐기 $($r.Json.revoked) 개 (액세스 · 리프레시)")
        $r = Invoke-QApi -Method GET -Url "$BaseUrl/api/me" -Bearer $access
        Add-Acct '폐기한 토큰 → 막힘' 'GET' '/api/me' $r (Expect-Status $r 401 "401 — $($r.Json.detail)")
      }

      # 13. 이름 바꾸기(U) → 내 정보에 바로 보이나
      $r = Invoke-QApi -Method PATCH -Url "$BaseUrl/api/me" -Body @{ name = '계정 점검 (바뀜)' } -Session $acct
      if ($r.Status -eq 200) {
        $r2 = Invoke-QApi -Method GET -Url "$BaseUrl/api/me" -Session $acct
        if ($r2.Json.user.name -eq '계정 점검 (바뀜)') { $v = Pass '이름을 바꾸자 내 정보에 곧바로 보인다' } else { $v = Fail "내 정보의 이름이 그대로다: $($r2.Json.user.name)" }
      } else { $v = Expect-Status $r 200 '' }
      Add-Acct '이름 바꾸기 (U)' 'PATCH' '/api/me' $r $v

      # 14. 비밀번호 바꾸기 — 현재 비밀번호가 틀리면 400 (재인증)
      $r = Invoke-QApi -Method PUT -Url "$BaseUrl/api/me/password" -Body @{ current_password = 'wrong-password'; new_password = $newPw } -Session $acct
      Add-Acct '비밀번호 바꾸기 — 현재 비밀번호 틀림' 'PUT' '/api/me/password' $r (Expect-Status $r 400 "400 — $($r.Json.detail)")

      # 15. 비밀번호 바꾸기 (U) → 16. 다른 기기는 로그아웃 · 이 기기는 유지
      $r = Invoke-QApi -Method PUT -Url "$BaseUrl/api/me/password" -Body @{ current_password = $acctPw; new_password = $newPw } -Session $acct
      Add-Acct '비밀번호 바꾸기 (U)' 'PUT' '/api/me/password' $r (Expect-Status $r 200 "다른 기기 $($r.Json.other_sessions_revoked) 곳 로그아웃 · 이 기기는 새 세션")
      $r = Invoke-QApi -Method GET -Url "$BaseUrl/api/me" -Session $other
      $r2 = Invoke-QApi -Method GET -Url "$BaseUrl/api/me" -Session $acct
      if ($r.Status -eq 401 -and $r2.Status -eq 200) { $v = Pass '다른 기기 401 · 이 기기 200' } else { $v = Fail "다른 기기 $($r.Status) · 이 기기 $($r2.Status) (기대 401 · 200)" }
      Add-Acct '비밀번호를 바꾼 뒤 — 다른 기기만 로그아웃' 'GET' '/api/me' $r $v
      $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/login" -Body @{ email = $acctEmail; password = $newPw }
      Add-Acct '새 비밀번호로 로그인' 'POST' '/api/auth/login' $r (Expect-Status $r 200 '새 비밀번호 통과(옛 비밀번호는 거절)')

      # 17. 탈퇴 — 확인 문구가 틀리면 422 → 18. 탈퇴(D) → 19. 탈퇴 뒤 로그인 401
      $r = Invoke-QApi -Method DELETE -Url "$BaseUrl/api/me" -Body @{ password = $newPw; confirm = '아니오' } -Session $acct
      Add-Acct '탈퇴 — 확인 문구 틀림' 'DELETE' '/api/me' $r (Expect-Status $r 422 "422 — $($r.Json.detail)")
      $r = Invoke-QApi -Method DELETE -Url "$BaseUrl/api/me" -Body @{ password = $newPw; confirm = '탈퇴' } -Session $acct
      if ($r.Status -eq 200 -and $r.Json.deleted.users -eq 1) {
        [void]$made.Remove($acctEmail)
        $v = Pass ("지운 표 " + ((@($r.Json.deleted.PSObject.Properties) | ForEach-Object { "$($_.Name) $($_.Value)" }) -join ' · '))
      } else { $v = Expect-Status $r 200 '' }
      Add-Acct '탈퇴 (D) — 데이터 파기' 'DELETE' '/api/me' $r $v
      $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/login" -Body @{ email = $acctEmail; password = $newPw }
      Add-Acct '탈퇴 뒤 로그인 → 거절' 'POST' '/api/auth/login' $r (Expect-Status $r 401 '401 — 계정이 없다')
    }

    # 20. 비밀번호 규칙 — 가입 화면과 같은 규칙을 API 도 지키나 (서버가 거절하므로 계정이 생기지 않는다)
    $shortEmail = "short-check-$stamp@example.com"
    $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/register" -Body @{ name = '짧은 암호'; email = $shortEmail; password = '1' }
    if ($r.Status -eq 200) { $made.Add($shortEmail) }
    Add-Acct '1글자 비밀번호 가입 → 거절' 'POST' '/api/auth/register' $r (Expect-Status $r 422 "422 — $($r.Json.detail)")

    # 21. 아주 긴 비밀번호로 로그인 — 서버 오류(500)가 아니라 「틀림」(401)이어야 한다(bcrypt 72바이트 한계)
    $r = Invoke-QApi -Method POST -Url "$BaseUrl/api/auth/login" -Body @{ email = $acctEmail; password = ('p' * 100) }
    Add-Acct '100자 비밀번호로 로그인 → 500 아님' 'POST' '/api/auth/login' $r (Expect-Status $r 401 '401 — 예외 없이 「틀림」')

    # 22. 정리 — 탈퇴 API 로 못 지운 임시 계정만 로컬 DB 에서 지운다.
    $pg = Get-QContainerState 'fin-ai-postgres'
    if ($made.Count -eq 0) {
      Add-Acct '정리 — 남은 임시 계정' 'SQL' '-' $null (Pass '남은 계정 없음 (탈퇴 API 로 지움)')
    } elseif ($pg.State -eq 'running' -and $pg.Project -eq $QComposeProject) {
      # 탈퇴가 실패한 경우라 자식 표에 행이 있을 수 있다 — 가입 직후 계정은 users 한 행뿐이라 보통은 지워진다.
      $list = (@($made) | Select-Object -Unique | ForEach-Object { "'" + ($_ -replace "'", "''") + "'" }) -join ','
      $sql = "DELETE FROM users WHERE lower(email) IN ($list);"
      $out = (& docker exec fin-ai-postgres psql -U fin_user -d fin_ai -c $sql 2>&1 | ForEach-Object { "$_" }) -join ' '
      if ($out -match 'DELETE (\d+)') { $v = Warn "탈퇴 API 로 못 지운 임시 계정 $($Matches[1]) 개를 DB 에서 지움 — 위 탈퇴 줄을 보라" }
      else { $v = Warn "임시 계정을 못 지웠다: $out — 남은 이메일: $(@($made) -join ', ')" }
      Add-Acct '정리 — 남은 임시 계정' 'SQL' 'DELETE FROM users' $null $v
    } else {
      Add-Acct '정리 — 남은 임시 계정' 'SQL' '-' $null (Warn "DB 컨테이너가 이 프로젝트 것이 아니거나 꺼져 있어 못 지웠다 — 남은 이메일: $(@($made) -join ', ')")
    }
  }
}

foreach ($c in $Checks) {
  # 앞 점검이 넘겨줘야 하는 값이 없으면 건너뛴다(그 앞 점검이 이미 실패로 표시됐다).
  if ($c.Needs -and -not $state.ContainsKey($c.Needs)) {
    $why = "앞 점검이 준비해야 하는 값($($c.Needs))이 없어 건너뜀"
    if ($c.NeedsNote) { $why = $c.NeedsNote }
    Add-Result $c '-' 0 (Skip $why)
    continue
  }
  $body = $c.Body
  if ($body -is [scriptblock]) { $body = & $body }
  $path = $c.P
  if ($path -is [scriptblock]) { $path = & $path; $c.P = $path }   # 앞 점검이 알아낸 값으로 경로를 만들 때(예: 지울 문서 ID)
  $expect = 200
  if ($c.Expect) { $expect = $c.Expect }
  $timeout = 30
  if ($c.Timeout) { $timeout = $c.Timeout }
  $sess = $null
  if ($c.Auth) { $sess = $session }

  $r = Invoke-QApi -Method $c.M -Url ($BaseUrl + $path) -Body $body -Session $sess -TimeoutSec $timeout -File $c.File

  if ($r.Status -eq 0) {
    $v = Fail ("응답 없음 — " + $r.Error)
  } elseif ($r.Status -ne $expect) {
    # FastAPI 오류는 {"detail": "..."} 모양이다. 422(입력 검증)는 detail 이 목록이라 JSON 으로 줄여 보인다.
    $detail = $r.Text
    if ($r.Json -and $r.Json.detail) { $detail = ($r.Json.detail | ConvertTo-Json -Compress -Depth 4) }
    if ($detail.Length -gt 200) { $detail = $detail.Substring(0, 200) + '…' }
    $v = Fail ("상태 {0} (기대 {1}) — {2}" -f $r.Status, $expect, $detail)
  } else {
    try {
      $v = & $c.Test $r
      if ($null -eq $v) { $v = Pass '' }
    } catch {
      $v = Fail ("통과 조건을 확인하다 오류: " + $_.Exception.Message)
    }
  }
  Add-Result $c $r.Status $r.Ms $v
  if ($ShowBody -and $r.Text) {
    $snip = $r.Text
    if ($snip.Length -gt 300) { $snip = $snip.Substring(0, 300) + '…' }
    Write-Host ("         본문: {0}" -f $snip) -ForegroundColor DarkCyan
  }
}

# ==============================================================================
# 요약 · 보고서
# ==============================================================================
$sec = [math]::Round(((Get-Date) - $runStart).TotalSeconds, 1)
$cnt = @{ OK = 0; WARN = 0; FAIL = 0; SKIP = 0 }
foreach ($x in $results) { $cnt[$x.Verdict]++ }
Write-QTitle ("결과 — 통과 {0} · 주의 {1} · 실패 {2} · 건너뜀 {3}  ({4}초)" -f $cnt.OK, $cnt.WARN, $cnt.FAIL, $cnt.SKIP, $sec)
$groupsDone = @($results | ForEach-Object { $_.Group } | Select-Object -Unique)
foreach ($g in $groupsDone) {
  $rows = @($results | Where-Object { $_.Group -eq $g })
  $ok = @($rows | Where-Object { $_.Verdict -eq 'OK' -or $_.Verdict -eq 'WARN' }).Count
  $bad = @($rows | Where-Object { $_.Verdict -eq 'FAIL' }).Count
  $skip = @($rows | Where-Object { $_.Verdict -eq 'SKIP' }).Count
  $color = 'Green'
  if ($bad -gt 0) { $color = 'Red' }
  $tail = ''
  if ($skip -gt 0) { $tail = " (건너뜀 $skip — 전제 없음, 실패 아님)" }
  Write-Host ("  {0,-6} 동작 {1}/{2}{3}" -f $g, $ok, $rows.Count, $tail) -ForegroundColor $color
}
foreach ($x in @($results | Where-Object { $_.Verdict -eq 'FAIL' })) {
  Write-QFail ("[{0}] {1} — {2}" -f $x.Group, $x.Name, $x.Note)
}

if ($SaveReport) {
  $dir = Join-Path $QRoot 'data\local-run'
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $path = Join-Path $dir "check-$stamp.md"
  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add("# 기능 점검 결과 — $(Get-Date -Format 'yyyy-MM-dd HH:mm') (KST)")
  $lines.Add('')
  $lines.Add("- 대상: $BaseUrl · 계정: $Email · 옵션: " + $(if ($Full) { '-Full ' } else { '' }) + $(if ($Write) { '-Write' } else { '' }))
  $lines.Add(("- 결과: 통과 {0} · 주의 {1} · 실패 {2} · 건너뜀 {3} · {4}초" -f $cnt.OK, $cnt.WARN, $cnt.FAIL, $cnt.SKIP, $sec))
  $lines.Add('- 만든 도구: `scripts/personal/check.ps1`')
  $lines.Add('')
  $lines.Add('| 판정 | 묶음 | 점검 | 요청 | 상태 | ms | 요약 |')
  $lines.Add('|---|---|---|---|---:|---:|---|')
  foreach ($x in $results) {
    $note = ($x.Note -replace '\|', '/')
    $lines.Add(("| {0} | {1} | {2} | ``{3} {4}`` | {5} | {6} | {7} |" -f $x.Verdict, $x.Group, $x.Name, $x.Method, $x.Path, $x.Status, $x.Ms, $note))
  }
  Save-QUtf8Bom -Path $path -Text (($lines -join "`r`n") + "`r`n")
  Write-QOk "보고서 저장: $path"
}

if ($cnt.FAIL -gt 0) { exit 1 }
exit 0
