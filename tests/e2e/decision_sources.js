const result=document.createElement('pre');result.id='decision-sources-result';document.body.append(result);
const checks=[];
const check=(name,ok)=>{if(!ok) throw Error(name);checks.push(name);};
const $=id=>document.getElementById(id);
const tick=()=>new Promise(resolve=>setTimeout(resolve,50));
let signals=fixture.signals,failMtf=false;
const calls=[];
window.fetch=async(path,options={})=>{
  calls.push({path,method:options.method});
  if(options.method!=='GET') throw Error('Unexpected mutation');
  let data,status=200;
  if(path==='/api/quant/auto/status') data={running:false,logs:[],signals};
  else if(path==='/api/paper/performance/metrics') data={status:'insufficient_data',message:'시험 자료 없음',snapshot_count:0};
  else if(path.startsWith('/api/stocks/mtf-signal?')) {
    status=failMtf?404:200; data=failMtf?{detail:'신호 기록 없음'}:{signal:'매도',as_of:'2026-10-14',composite:-1,explanation:{summary:'세 주기의 합산 점수 -1.0'}};
  } else if(path==='/api/auto-trade/status') data={running:false,log:[{time:fixture.strategy.cycle_at,signals:[fixture.strategy],trades:[]}]};
  else if(path==='/api/quant/risk/status') data={limits:{},guidance:null};
  else throw Error('Unexpected API '+path);
  return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
};
try {
  const robo=await import('/js/robo.js');
  const helpers=await import('/js/decision-signals.js');
  await robo.loadRoboDecision();await tick();
  const cards=[...$('robo-rationale').children];
  check('only latest cycle is shown',cards.length===3 && !$('robo-rationale').textContent.includes('이전 회차'));
  check('same symbol from account and batch has separate explanation nodes',new Set(cards.map(c=>c.querySelector('[id^="robo-rat-"]').id)).size===3 && cards.slice(0,2).every(c=>c.textContent.includes('다중 주기 점수 -1.0')));
  check('auto badge stays buy after contradictory multi-timeframe response',cards[0].querySelector('[title="자동매매 주문 전 판단"]').textContent==='자동매매 매수' && cards[0].textContent.includes('다중 주기 신호 (2026-10-14 기록): 매도'));
  check('base and multi-timeframe scores have separate names',cards[0].textContent.includes('기본 지표 점수 2.0') && cards[0].textContent.includes('다중 주기 점수 -1.0'));
  check('cycle time and basis date are distinct',cards[0].textContent.includes('판단 회차') && cards[0].textContent.includes('한국시간 · 내 자동매매') && cards[0].textContent.includes('기준 봉 2026-10-16 · 1d'));
  check('aggressive mode is not labeled daily rules',cards[1].textContent.includes('공격 모드 · 분봉') && cards[1].textContent.includes('분봉 지표 점수 5.0') && cards[1].textContent.includes('시스템 배치') && !cards[1].textContent.includes('일봉 규칙'));
  check('calculation error is not hold with zero',cards[2].textContent.includes('자동매매 판단 불가') && cards[2].textContent.includes('점수 미확인') && !cards[2].textContent.includes('점수 0.0'));
  check('untrusted name is escaped',cards[0].textContent.includes('<b>문자</b>') && !cards[0].querySelector('.font-semibold b'));
  check('difference notice allows method and timestamp differences',cards[0].textContent.includes('판단 방식·기준 시각이 달라'));
  signals=[fixture.strategy];await robo.loadRoboDecision();await tick();
  check('user strategy shows identity and normalized score', $('robo-rationale').textContent.includes('사용자 전략 s1 v3') && $('robo-rationale').textContent.includes('전략 정규화 점수 +0.70') && $('robo-rationale').textContent.includes('기본 지표 점수 2.0'));
  failMtf=true;await robo.loadRoboDecision();await tick();
  check('missing comparison retains actual auto judgment and basis', $('robo-rationale').textContent.includes('자동매매 매도') && $('robo-rationale').textContent.includes('전략 정규화 점수 +0.70') && $('robo-rationale').textContent.includes('아직 없습니다'));
  const quant=await import('/js/quant.js');await quant.loadAutoTradeStatus();await tick();
  check('auto status uses the same score names', $('auto-trade-log').textContent.includes('사용자 전략 s1 v3') && $('auto-trade-log').textContent.includes('전략 정규화 점수 +0.70'));
  const legacy=helpers.renderDecisionBasis({score:2}, s=>String(s), s=>String(s));
  check('legacy missing metadata is explicitly unknown',legacy.includes('판단 방식 미확인') && legacy.includes('점수 미확인') && !legacy.includes('일봉 규칙'));
  check('bad timestamp is safe',helpers.renderDecisionBasis({decision:{as_of:Infinity}},s=>String(s),s=>String(s)).includes('미확인'));
  check('all requests are read-only',calls.every(c=>c.method==='GET'));
  result.textContent=JSON.stringify({ok:true,checks});
} catch(e){result.textContent=JSON.stringify({ok:false,checks,error:String(e),stack:e.stack});}
