const result = document.createElement('pre'); result.id = 'risk-profile-result'; document.body.append(result);
const checks = [];
const check = (name, ok) => { if (!ok) throw Error(name); checks.push(name); };
const $ = id => document.getElementById(id);
const tick = () => new Promise(resolve => setTimeout(resolve, 30));
const key = id => 'robo_risk_profile:v1:' + encodeURIComponent(id);
const profileA = {level:'위험중립형',risk_profile:'moderate',score:21};
const profileB = {level:'안정형',risk_profile:'conservative',score:7};
let response = profileA, deferred = false, release;
const calls = [];
const questions = Array.from({length:7}, (_,i) => ({id:'q'+i,text:'질문 '+i,options:[{label:'선택',score:3}]}));
const overview = {status:'ok',total:0,as_of:'2026-10-19',classes:['국내주식','해외주식','국내채권','대체자산','현금','그 밖'].map(key=>({key,label:key,count:0,groups:[]})),derivatives:{label:'레버리지·인버스',count:0,groups:[],notes:[]}};
window.fetch = async (path, options={}) => {
  calls.push({path,method:options.method});
  let body, status=200;
  if (path === '/api/ml/robo/questions') body={questions};
  else if (path === '/api/ml/robo/risk-profile') {
    body={...response,max_score:35,description:'진단 설명',scale:[]};
    if (deferred) await new Promise(resolve=>{release=resolve;});
  } else if (path === '/api/ml/robo/allocation/latest') {status=404;body={detail:'저장 결과 없음'};}
  else if (path.startsWith('/api/ml/robo/weights?')) body={risk_profile:new URLSearchParams(path.split('?')[1]).get('risk_profile'),horizon_years:3,allocations:{'국내주식':30,'해외주식':25,'국내채권':30,'대체자산':10,'현금':5}};
  else if (path.startsWith('/api/products/etfs/overview?')) body=overview;
  else throw Error('Unexpected API: '+path);
  return new Response(JSON.stringify(body), {status,headers:{'Content-Type':'application/json'}});
};
const submit = async () => {
  $('rp-toggle').click(); await tick();
  for (const q of questions) document.querySelector(`input[name="rp-${q.id}"]`).checked=true;
  $('rp-submit').click(); await tick();
};
try {
  localStorage.clear(); localStorage.setItem('robo_risk_profile',JSON.stringify(profileB));
  const robo = await import('/js/robo.js');
  const store = await import('/js/riskprofile.js');
  const products = await import('/js/products.js');
  check('import before identity confirmation does not restore shared profile', !$('rp-result').textContent && store.readRiskProfile()===null);
  robo.initRoboRiskProfile('account-A');
  check('legacy shared profile is ignored and prompts a new diagnosis', $('rp-result').textContent.includes('이전 공용 진단') && $('robo-risk').value==='moderate' && !localStorage.getItem(key('account-A')));
  await submit();
  check('diagnosis saves only under verified account', JSON.parse(localStorage.getItem(key('account-A'))).score===21 && JSON.parse(localStorage.getItem('robo_risk_profile')).score===7);
  check('immediate result and toast use Korean labels', $('rp-result').textContent.includes('중립 (위험중립형)') && !$('rp-result').textContent.includes('moderate') && !$('_toast_el').textContent.includes('moderate'));
  robo.initRoboRiskProfile(null); robo.initRoboRiskProfile('account-A');
  check('same account restoration uses Korean label and correct selection', $('rp-result').textContent.includes('최근 진단') && $('rp-result').textContent.includes('중립 (위험중립형)') && !$('rp-result').textContent.includes('moderate') && $('robo-risk').value==='moderate');
  products.onProductsViewActivated('agent-products'); await tick();
  check('product chip and fallback weights use current account profile', document.querySelector('.pd-chip').textContent==='투자 성향 위험중립형' && calls.some(c=>c.path.includes('weights?risk_profile=moderate')));
  robo.initRoboRiskProfile('account-B');
  check('another account cannot see previous account result', !$('rp-result').textContent.includes('21점') && store.readRiskProfile()===null);
  const before = calls.length;
  products.onProductsViewActivated('agent-products'); await tick();
  check('product screen clears previous account chip and does not reuse its defaults', document.querySelector('.pd-chip').textContent==='투자 성향 진단 전' && !calls.slice(before).some(c=>c.path.includes('/weights?')));
  response=profileB; await submit();
  check('second account saves independently', JSON.parse(localStorage.getItem(key('account-B'))).score===7 && JSON.parse(localStorage.getItem(key('account-A'))).score===21);
  robo.initRoboRiskProfile('account-A');
  check('returning to original account restores its own profile', store.readRiskProfile().score===21 && $('rp-result').textContent.includes('21점'));
  response=profileB; deferred=true; await submit();
  robo.initRoboRiskProfile('account-B'); deferred=false; release(); await tick();
  check('late response after account switch changes neither account', JSON.parse(localStorage.getItem(key('account-A'))).score===21 && JSON.parse(localStorage.getItem(key('account-B'))).score===7 && $('rp-result').textContent.includes('최근 진단'));
  for (const raw of ['{', JSON.stringify({...profileA,risk_profile:'unknown'}), JSON.stringify({...profileA,score:'21'}), JSON.stringify({...profileA,level:'moderate'}), JSON.stringify({...profileA,score:99})]) {
    localStorage.setItem(key('account-B'),raw); robo.initRoboRiskProfile('account-B');
    if (store.readRiskProfile()!==null) throw Error('invalid stored profile accepted');
  }
  check('corrupt or invalid stored values are ignored', !$('rp-result').textContent.includes('moderate'));
  localStorage.removeItem(key('account-B')); robo.initRoboRiskProfile('account-B');
  const originalSet=Storage.prototype.setItem;
  Storage.prototype.setItem=function(k,v){if(k.startsWith('robo_risk_profile:v1:')) throw new DOMException('blocked','QuotaExceededError'); return originalSet.call(this,k,v);};
  try {
    response=profileB; await submit();
    check('blocked storage reports current-tab-only retention', $('rp-result').textContent.includes('현재 탭에서만 유지') && store.readRiskProfile().score===7 && localStorage.getItem(key('account-B'))===null);
    products.onProductsViewActivated('agent-products'); await tick();
    check('current-tab fallback is shared with product guidance', document.querySelector('.pd-chip').textContent==='투자 성향 안정형');
  } finally {Storage.prototype.setItem=originalSet;}
  robo.initRoboRiskProfile('account-B');
  check('unstored result is not falsely restored after reinitialization', store.readRiskProfile()===null);
  robo.initRoboRiskProfile(null);
  check('logout clears active context and rejects writes', store.readRiskProfile()===null && store.saveRiskProfile(profileA,null)==='unavailable' && !$('rp-result').textContent);
  check('UI explicitly states browser-only account storage', document.body.textContent.includes('다른 브라우저·기기에는 동기화되지 않습니다'));
  result.textContent=JSON.stringify({ok:true,checks});
} catch(e) {result.textContent=JSON.stringify({ok:false,checks,error:String(e),stack:e.stack});}
