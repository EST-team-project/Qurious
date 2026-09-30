/* 두 원본의 실제 화면을 공통 GNB/LNB 안에서 실행한다. */
(function () {
  'use strict';
  const groups = [
    ['시장·기업 분석', [['home','시장 대시보드'],['world-markets','세계 증시'],['asset-classes','기초자산'],['today-gainers','상승 종목'],['today-sobujang','소부장'],['global-capital-map','세계 자금 지도'],['volume-cloud','거래량 클라우드'],['sector-cloud','섹터 클라우드'],['macro-realtime','거시경제'],['macro-simulation','거시 시뮬레이션'],['kospi-excluded','KOSPI 제외 지수'],['industry-analysis','산업 분석'],['company-financial','기업 재무'],['financial-statement','재무제표'],['dart-company-search','DART 기업 검색'],['dart-region-search','DART 지역 검색'],['group-network','그룹사 관계'],['dart-financial-analysis','DART 재무 분석'],['valuation','밸류에이션'],['technical-chart','기술적 분석']]],
    ['포트폴리오·퀀트', [['portfolio','포트폴리오 최적화'],['portfolio-combination','종목 조합'],['portfolio-guide','포트폴리오 가이드'],['portfolio-regime','위험선호도'],['portfolio-simulation','포트폴리오 시뮬레이션'],['risk','VaR 위험 분석'],['investment-tree','투자 성향'],['financial-knowledge','금융상품·자산배분'],['backtest','전략 백테스트'],['quant-lean','LEAN 결과 리포트'],['pipeline','퀀트 파이프라인'],['tax-accounting','세무·회계'],['chart-drawing','차트 드로잉']]],
    ['AI·데이터 실습', [['cross-validation','교차 검증'],['decision-boundary','결정 경계'],['random-forest','랜덤 포레스트'],['kmeans','KMeans'],['svm','SVM'],['mlp','MLP'],['linear-regression','선형 회귀'],['text-classify','텍스트 분류'],['opencv','OpenCV'],['cnn-timeseries','CNN 시계열'],['lstm','LSTM'],['transformer','Transformer'],['huggingface','이미지 생성'],['rag-chat','근거 문서 검색'],['llm-bench','LLM 비교'],['server-resources','서버 리소스']]],
    ['퀴즈·원문', [['quiz-home','문항 관리·응시'],['vocabulary-exam','단어장 시험'],...Array.from({length:5},(_,i)=>[`quiz-day-${i+1}`,`주식 ${i+1} 퀴즈`]),...['10-1','10-2','10-3','03','05','04','06','07','10','11','voca'].map(id=>[`learn-${id}`,`학습 원문 ${id}`])]],
  ];
  const units = [
    {id:1,title:'금융 기초와 회사 구조',docs:['10-1','10-2','10-3'],labs:['financial-statement','tax-accounting'],goal:'법인·자금조달·세무회계의 관계를 원문과 계산 실습으로 익힙니다.'},
    {id:2,title:'주식시장과 투자 기초',docs:['03'],labs:['world-markets','asset-classes','dart-company-search'],goal:'시장·기업·기초자산을 구분하고 실제 종목을 검색합니다.'},
    {id:3,title:'가격·거래량과 기술적 분석',docs:['05','04'],labs:['technical-chart','volume-cloud','chart-drawing'],goal:'캔들·거래량·이동평균·위험 지표를 읽고 원문의 시뮬레이터로 확인합니다.'},
    {id:4,title:'산업·기업·재무 분석',docs:['06','07'],labs:['industry-analysis','company-financial','dart-financial-analysis','valuation'],goal:'산업 경쟁과 재무 구조를 연결하고 공시·재무제표를 분석합니다.'},
    {id:5,title:'거시경제와 시장 흐름',docs:['11'],labs:['macro-realtime','macro-simulation','kospi-excluded'],goal:'금리·물가·환율과 주식시장의 연결을 학습합니다.'},
    {id:6,title:'선물·옵션과 헤지',domainDay:1,docs:[],labs:['risk'],goal:'계약·증거금·청산·헤지 구조를 기존 상세학습과 시뮬레이션으로 확인합니다.'},
    {id:7,title:'펀드·ETF와 분산투자',domainDay:2,docs:[],labs:['portfolio-combination','portfolio-guide'],goal:'펀드·ETF 구조와 비용, 분산투자의 한계를 익힙니다.'},
    {id:8,title:'채권과 금리 위험',domainDay:3,docs:[],labs:['macro-realtime','risk'],goal:'채권 가격·금리·듀레이션의 관계를 상세학습에서 확인합니다.'},
    {id:9,title:'자산배분·리밸런싱',domainDay:4,docs:[],labs:['portfolio','portfolio-regime','portfolio-simulation'],goal:'자산배분·리밸런싱·성과 지표를 실제 분석 도구와 연결합니다.'},
    {id:10,title:'퀀트·AI·금융 지식 시스템',docs:['10'],labs:['backtest','quant-lean','pipeline','cross-validation','rag-chat'],goal:'3주 학습의 원문을 RAG로 찾고 전략 가정·백테스트·근거를 함께 검증합니다.'},
  ];
  const escape = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let currentFrame;
  function mountAnalysis(view='home') {
    document.body.classList.add('analysis-active');
    const area=document.getElementById('messages');
    area.innerHTML='<iframe id="analysisFrame" title="투자 분석 실습" class="analysis-frame"></iframe>';
    currentFrame=area.querySelector('iframe');
    currentFrame.src=`/analysis/?embedded=1&view=${encodeURIComponent(view)}`;
    history.replaceState(null,'',`/?view=analysis&tool=${encodeURIComponent(view)}`);
  }
  function bind(container) {
    container.querySelectorAll('[data-analysis-tool]').forEach(button=>button.addEventListener('click',()=>window.openInvestmentTool(button.dataset.analysisTool)));
    container.querySelectorAll('[data-curriculum-unit]').forEach(button=>button.addEventListener('click',()=>window.openCurriculumUnit(Number(button.dataset.curriculumUnit))));
  }
  function renderIndex() {
    document.getElementById('messages').innerHTML=`<article class="content-page theory-page"><header><div class="content-kicker">3주 학습 · 10단원</div><h1>나의 금융 상식 시스템</h1><p>개념 → 강의 원문과 인터랙티브 실습 → RAG 근거 확인 순서로 학습합니다.</p></header><section class="theory-index-grid">${units.map(u=>`<button class="theory-day-card" data-curriculum-unit="${u.id}"><span class="theory-day-number">${u.id}</span><h2>${escape(u.title)}</h2><p>${escape(u.goal)}</p><em>원문·상세학습·실습 열기 →</em></button>`).join('')}</section></article>`;
    bind(document.getElementById('messages'));
  }
  function unitHeader(unit) {
    return `<section class="unit-bridge"><span>${unit.id} / 10단원</span><h1>${escape(unit.title)}</h1><p>${escape(unit.goal)}</p><div class="unit-actions">${unit.docs.map(d=>`<button class="btn-primary" data-analysis-tool="learn-${d}">원문 ${d} · 시뮬레이터</button>`).join('')}${unit.labs.map(v=>`<button class="btn-secondary" data-analysis-tool="${v}">${escape(groups.flatMap(g=>g[1]).find(x=>x[0]===v)?.[1]||v)}</button>`).join('')}<a href="/?view=analysis&tool=rag-chat">학습 근거 RAG 검색</a></div></section>`;
  }
  function renderUnit(id, renderDomain) {
    const unit=units.find(u=>u.id===id);if(!unit)return;
    document.body.classList.remove('analysis-active');
    const area=document.getElementById('messages');
    if(unit.domainDay) { renderDomain(unit.domainDay); area.insertAdjacentHTML('afterbegin',unitHeader(unit)); }
    else { area.innerHTML=`<article class="content-page">${unitHeader(unit)}<p>위의 원문 버튼을 열면 전체 강의 본문과 원래의 계산기·차트·팝업을 사용할 수 있습니다.</p><iframe title="${escape(unit.title)} 강의 원문" class="curriculum-frame" src="/analysis/?embedded=1&view=learn-${unit.docs[0]}"></iframe></article>`; }
    bind(area);
  }
  function initialize() {
    const nav=document.querySelector('.topic-nav');
    nav.innerHTML=`<p class="nav-label">10단원 통합 학습</p>${units.map(u=>`<button class="topic-btn" data-curriculum-unit="${u.id}"><span class="day-menu-number">${u.id}단원</span>${escape(u.title)}</button>`).join('')}<p class="nav-label">전체 기능</p>${groups.map(([label,items])=>`<details class="integration-nav-group"><summary>${label}</summary>${items.map(([id,title])=>`<button class="topic-btn" data-analysis-tool="${id}">${title}</button>`).join('')}</details>`).join('')}<a class="topic-btn" href="/analysis/pages/youtube.html">학습 영상 자료</a>`;
    bind(nav);
    window.addEventListener('message',event=>{
      if(event.origin!==location.origin || event.source!==currentFrame?.contentWindow)return;
      if(event.data?.type==='analysis-navigation') history.replaceState(null,'',`/?view=analysis&tool=${encodeURIComponent(event.data.view)}`);
    });
  }
  window.InvestmentIntegration={mountAnalysis,renderIndex,renderUnit,units,groups,initialize};
})();
