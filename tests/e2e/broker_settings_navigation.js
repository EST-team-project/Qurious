const result = document.createElement('pre'); result.id = 'broker-nav-result'; document.body.append(result);
const checks = [];
const check = (name, ok) => { if (!ok) throw Error(name); checks.push(name); };
const tick = () => new Promise(r => setTimeout(r, 50));
const cfg = {broker:'kis',mode:'paper',app_key:'TEST****',account_no:'1234567801',risk:{},selected_symbols:[],managed_brokers:[]};
let saved = [];
window.fetch = async (input, options={}) => {
  const path = String(input); let data = {};
  if (options.method === 'POST') {
    if(path !== '/api/quant/settings') throw Error('Unexpected mutation');
    saved.push(JSON.parse(options.body)); data={ok:true};
  } else if(path === '/api/quant/settings') data=cfg;
  else if(path === '/api/me') data={user:{name:'Test',email:'test@example.test',roles:[]}};
  else if(path === '/api/broker/settings') data={broker:'kis',connected:true};
  else if(path === '/api/quant/strategies') data={strategies:[]};
  else if(path === '/api/sessions') data={count:1};
  return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
};
try {
  const {navigate,registerViewActivation}=await import('/js/core.js');
  const {onMyPageActivated}=await import('/js/mypage.js');
  const risk=await import('/js/riskprofile.js');
  risk.setRiskProfileUser('nav-test-a');
  risk.saveRiskProfile({level:'안정형',risk_profile:'conservative',score:7},risk.riskProfileContext());
  registerViewActivation(onMyPageActivated);
  navigate('settings'); await tick();
  check('old deep link shows broker section in mypage', location.hash==='#settings' && document.querySelector('.view[data-view="mypage"]').classList.contains('active') && document.getElementById('mp-sec-broker').classList.contains('active'));
  check('settings controls are visible and unique', document.querySelectorAll('#broker-save').length===1 && document.getElementById('broker-save').getClientRects().length>0);
  check('saved configuration loads through old deep link', document.getElementById('broker-app-key').value==='TEST****');
  document.getElementById('broker-save').click(); await tick();
  check('one click saves one unchanged configuration', saved.length===1 && saved[0].broker==='kis' && saved[0].app_key==='TEST****');
  navigate('indicator-api'); await tick();
  check('automation explanation stays and duplicate form is removed', document.querySelector('.view[data-view="indicator-api"]').textContent.includes('인디케이터 계산') && !document.getElementById('iapi-app-key'));
  document.getElementById('iapi-open-settings').click(); await tick();
  check('automation link reopens broker body', location.hash==='#settings' && document.getElementById('mp-shell').dataset.mpPane==='body');
  document.querySelector('[data-mp-go="display"]').click();
  check('risk summary uses current account', document.getElementById('mp-risk-summary').textContent.includes('안정형'));
  risk.setRiskProfileUser('nav-test-b');
  document.querySelector('[data-mp-go="display"]').click();
  check('risk summary never carries another account', !document.getElementById('mp-risk-summary').textContent.includes('안정형'));
  navigate('settings'); await tick();
  check('reopening does not bind a second save handler', (document.getElementById('broker-save').click(),await tick(),saved.length===2));
  check('no page horizontal overflow', document.documentElement.scrollWidth<=window.innerWidth);
  const terms=await import('/js/terms.js');
  const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const rendered=terms.renderTerm({id:'x',title:'<script>',clauses:[]},esc);
  check('terms renderer escapes text and uses merged consent version', !rendered.includes('<script>') && rendered.includes('&lt;script&gt;') && terms.TERMS_VERSION==='2026-10-29-v0.4');
  result.textContent=JSON.stringify({ok:true,width:window.innerWidth,checks});
} catch(e) { result.textContent=JSON.stringify({ok:false,checks,error:String(e),stack:e.stack}); }
