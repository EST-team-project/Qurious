const result=document.createElement('pre');result.id='rebalance-portfolio-result';document.body.append(result);
const checks=[];
const check=(name,ok)=>{if(!ok)throw Error(name);checks.push(name);};
const $=id=>document.getElementById(id);
const tick=()=>new Promise(resolve=>setTimeout(resolve,50));
// 실제 차트 라이브러리의 렌더링 대신 전달한 계열·범주를 기록한다. 표와 조작은 실제 DOM이다.
let chart,chartDestroyed=false;
window.ApexCharts=class {constructor(el,opts){chart=opts;}render(){}updateOptions(opts){chart=opts;}destroy(){chartDestroyed=true;}};
const plan={name:'검증 플랜',targets:[{symbol:'005930.KS',name:'목표 A',weight_pct:40},{symbol:'000660.KS',name:'목표 B',weight_pct:40}],time_period:'monthly',next_run_at:'2026-11-02T03:30:00Z',drift_enabled:true,drift_threshold_pct:5,drift_check_mode:'always',cashflow_enabled:true,cashflow_min_amount:100000,min_order_amount:10000,exclude_unplanned:true,is_active:true,auto_execute:false};
const snapshot={total_asset:1000000,excluded_asset:1000000,cash:300000,cash_weight_pct:30,cash_target_pct:20,cash_drift_pct:10,cash_excess:100000,pending_budget:50000,cashflow_available:50000,max_drift_pct:20,drift_exceeded:true,valuation_date:'2026-10-16',excluded_prices_unavailable:[],rows:[
 {symbol:'005930.KS',name:'목표 A <b>문자</b>',quantity:500,price:1000,current_amount:500000,current_weight_pct:50,target_weight_pct:40,drift_pct:10,in_plan:true,managed:true},
 {symbol:'000660.KS',name:'목표 B',quantity:200,price:1000,current_amount:200000,current_weight_pct:20,target_weight_pct:40,drift_pct:-20,in_plan:true,managed:true},
 {symbol:'123450.KS',name:'계획 밖 종목',quantity:1000,price:1000,current_amount:1000000,current_weight_pct:0,target_weight_pct:0,drift_pct:0,in_plan:false,managed:false}]};
const baseRun={trigger:'DRIFT',triggers:['TIME','DRIFT'],plan_kind:'full',decision_date:'2026-10-19',total_asset:1000000,max_drift_pct:20,before_weights:{'005930.KS':50,CASH:30},target_weights:{'005930.KS':40,CASH:20},after_weights:{},orders:[],note:'검증 이력 <script>문자<\/script>',context:{price_basis:'previous_close',valuation_date:'2026-10-16',scheduled_for:'2026-10-20',estimated_cost:123}};
let unavailable=false,calendarMissing=false,emptyHistory=false;
const calls=[];
window.fetch=async(path,options={})=>{
 calls.push({path,method:options.method});
 let data;
 if(path==='/api/rebalance/plan' && options.method==='PUT'){Object.assign(plan,JSON.parse(options.body));data=plan;}
 else if(options.method!=='GET')throw Error('Unexpected mutation');
 else if(path==='/api/rebalance/status')data={plan:{...plan,time_schedule_error:calendarMissing?'거래일 달력 대기':null},snapshot:unavailable?null:snapshot,triggers:{time_due:false,drift_due:true,cashflow_due:false},valuation_error:unavailable?'12:30 데이터 갱신 이후 자동 점검합니다.':null,automatic_check:{message:unavailable?'자료 갱신 완료 대기':'자동 점검 완료',state:unavailable?'waiting':'checked',last_checked_at:'2026-10-19T03:30:00Z'}};
 else if(path==='/api/rebalance/runs?limit=20')data={runs:emptyHistory?[]:[{...baseRun,id:'scheduled',status:'scheduled'},{...baseRun,id:'executed',status:'executed',after_weights:{'005930.KS':40,CASH:20},context:{...baseRun.context,fill_date:'2026-10-20',actual_cost:130},orders:[{symbol:'005930.KS',name:'목표 A',side:'SELL',quantity:100,price:1000,amount:100000,cost:{total_cost:130},status:'filled'}]},{...baseRun,id:'unfilled',status:'cancelled',context:{...baseRun.context,cancel_reason:'open_not_tradable'}}]};
 else if(path==='/api/rebalance/cashflows?limit=20')data={events:[]};
 else throw Error('Unexpected API '+path);
 return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
};
try {
 const rb=await import('/js/rebalance.js');rb.initRebalanceView();
 rb.onRebalanceViewActivated('robo-rebalance');await tick();
 const rows=[...$('rb-weight-table').querySelectorAll('tbody tr')];
 check('current target and drift columns show received values',rows[0].textContent.includes('50%') && rows[0].textContent.includes('40%') && rows[0].textContent.includes('+10') && rows[1].textContent.includes('-20'));
 check('cash is shown alongside stock allocations',rows.at(-1).textContent.includes('현금') && rows.at(-1).textContent.includes('30%') && rows.at(-1).textContent.includes('20%'));
 check('excluded position is labeled and retained in table',rows[2].textContent.includes('계획 밖 종목') && rows[2].textContent.includes('플랜 외 → 유지·계산 제외'));
 check('chart input has paired current and target series',JSON.stringify(chart.series)==='[{"name":"현재 비중","data":[50,20,30]},{"name":"목표 비중","data":[40,40,20]}]' && chart.xaxis.categories.length===3);
 check('unmanaged position is excluded from chart input',!chart.xaxis.categories.includes('계획 밖 종목'));
 check('total managed and excluded asset values are separate',($('rb-kpis').textContent.match(/1,000,000원/g)||[]).length===2);
 check('next scheduled check date is shown in Korean time', $('rb-kpis').textContent.includes('다음 시간 리밸런싱 (한국시간)') && $('rb-kpis').textContent.includes('2026. 11. 2.') && $('rb-kpis').textContent.includes('갱신 완료 후'));
 check('valuation date trigger and approval policy are shown', $('rb-trigger-badges').textContent.includes('판단 기준 2026-10-16 종가') && $('rb-trigger-badges').textContent.includes('이탈률 기준 이상') && $('rb-trigger-badges').textContent.includes('수동 승인'));
 check('history separates scheduled filled and unfilled outcomes', $('rb-runs').textContent.includes('시가 체결 대기') && $('rb-runs').textContent.includes('체결일 2026-10-20') && $('rb-runs').textContent.includes('미체결'));
 check('history shows before after target and costs', $('rb-runs').textContent.includes('50% → 40%') && $('rb-runs').textContent.includes('목표 40%') && $('rb-runs').textContent.includes('체결 비용 130'));
 const details=$('rb-run-executed').closest('details');details.open=true;
 check('order detail shows fill status and quantity',details.textContent.includes('100') && details.textContent.includes('filled') && details.textContent.includes('130.00원'));
 check('names and notes are escaped', rows[0].textContent.includes('<b>문자</b>') && !rows[0].querySelector('b') && !$('rb-runs').querySelector('script'));
 calendarMissing=true;$('rb-refresh').click();await tick();
 check('missing calendar shows pending instead of a confirmed date',!$('rb-schedule-warning').hidden && $('rb-kpis').textContent.includes('달력 확인 대기'));
 unavailable=true;$('rb-refresh').click();await tick();
 check('missing prices replaces current values with waiting and disables execution', $('rb-weight-table').querySelectorAll('tbody tr').length===3 && [...$('rb-weight-table').querySelectorAll('tbody tr')].every(r=>r.cells[1].textContent==='자료 대기') && $('rb-execute').disabled && $('rb-import-positions').disabled);
 check('waiting chart shows only saved targets and residual cash',JSON.stringify(chart.series)==='[{"name":"저장된 목표 비중","data":[40,40,20]}]' && !chart.xaxis.categories.includes('계획 밖 종목'));
 check('waiting table explains the actual readiness reason', $('rb-weight-table').textContent.includes('12:30 데이터 갱신 이후') && $('rb-weight-table').textContent.includes('주문 판단은 자료 준비 후'));
 check('waiting state still retains history and explanation', $('rb-daily-check').textContent.includes('갱신 완료 대기') && $('rb-runs').textContent.includes('시가 체결 대기'));
 const weightInput=$('rb-targets-body').querySelector('.rb-w');weightInput.value='25';weightInput.dispatchEvent(new Event('input'));
 check('unsaved edits do not replace the saved target chart',chart.series[0].data[0]===40);
 $('rb-save').click();await tick();
 check('saving while waiting refreshes target weights and cash immediately',JSON.stringify(chart.series[0].data)==='[25,40,35]' && $('rb-weight-table').textContent.includes('25.00%') && $('rb-execute').disabled);
 unavailable=false;calendarMissing=false;$('rb-refresh').click();await tick();
 check('ready data restores paired series and current values',chart.series.length===2 && chart.series[0].name==='현재 비중' && $('rb-weight-table').textContent.includes('50%') && !$('rb-weight-table').textContent.includes('자료 대기'));
 unavailable=true;plan.targets=[];$('rb-refresh').click();await tick();
 check('empty saved plan clears chart without inventing a cash allocation',chartDestroyed && $('rb-weight-table').textContent.includes('저장된 목표 종목이 없습니다') && !$('rb-weight-table').querySelector('table'));
 plan.targets=[{symbol:'005930.KS',name:'<b>문자</b>',weight_pct:100}];$('rb-refresh').click();await tick();
 check('target-only view escapes names and includes zero residual cash',!$('rb-weight-table').querySelector('b') && $('rb-weight-table').textContent.includes('<b>문자</b>') && JSON.stringify(chart.series[0].data)==='[100,0]');
 emptyHistory=true;$('rb-refresh').click();await tick();
 check('empty history is explicit', $('rb-runs').textContent.includes('아직 리밸런싱 이력이 없습니다'));
 check('screen only saves the requested plan and never executes an order',calls.filter(c=>c.method==='PUT').length===1 && calls.every(c=>c.method==='GET' || c.path==='/api/rebalance/plan'));
 result.textContent=JSON.stringify({ok:true,checks,chart_rendering:'input-only recording adapter'});
}catch(e){result.textContent=JSON.stringify({ok:false,checks,error:String(e),stack:e.stack});}
