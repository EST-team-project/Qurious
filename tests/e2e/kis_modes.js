const result = document.createElement('pre'); result.id = 'kis-mode-result'; document.body.append(result);
const checks = [];
const check = (name, ok) => { if (!ok) throw Error(name); checks.push(name); };
let environment = 'paper';
let cfg = { mode: 'live', broker: 'kis', paper: false, connected: true, app_key: 'TEST****', account_no: '1234567801',
  live_gateway: { configured: false, environment }, execution_policy: {}, risk: {}, managed_brokers: [], selected_symbols: [] };
let sent = []; let dialogs = [];
window.confirm = text => { dialogs.push(text); return true; };
window.fetch = async (input, options = {}) => {
  const path = String(input);
  let data = {};
  if (options.method === 'POST') {
    if (path !== '/api/quant/settings') throw Error('Unexpected mutation: ' + path);
    const body = JSON.parse(options.body); sent.push(body); cfg = {...cfg, ...body};
    data = {ok: true};
  } else if (path === '/api/quant/settings') data = cfg;
  else if (path === '/api/quant/strategies') data = {strategies: []};
  else if (path === '/api/quant/live-orders?limit=30') data = {orders: []};
  else if (path === '/api/auto-trade/status' || path === '/api/quant/auto/status') data = {running: true, log: [], signals: []};
  else if (path === '/api/dashboard/accounts') data = {tabs: [{key:'kis', label:'KIS 계좌', site:'한국투자증권', connected:true, environment, auto_trade_running:true, open_live_orders:0}]};
  else if (path === '/api/quant/kis/quickstart') data = {connected: true, already_started:true, environment, mode:'live', broker:'kis', route_detail:'시험 계좌', interval_min:10};
  return new Response(JSON.stringify(data), {status: 200, headers:{'Content-Type':'application/json'}});
};
const tick = () => new Promise(r => setTimeout(r, 30));
try {
  const {loadSettings} = await import('/js/settings.js');
  const {loadDashboard} = await import('/js/dashboard.js');
  const mode = document.getElementById('quant-mode');
  const hint = document.getElementById('quant-live-route');
  const selectedText = () => mode.selectedOptions[0]?.textContent;
  await loadSettings();
  check('legacy live/paper=false displays KIS Testbed', selectedText() === 'KIS 모의투자(Testbed)로 주문');
  check('conflicting checkbox is invisible', document.getElementById('broker-paper').getClientRects().length === 0);
  check('paper destination in hint', hint.textContent.includes('모의계좌'));
  await loadDashboard(); await tick();
  check('dashboard account uses effective paper', document.getElementById('overview-account-panel').textContent.includes('실행 중 · KIS 모의투자(Testbed)'));
  check('quickstart has no raw live label', !document.getElementById('overview-kis-status').textContent.includes('live'));
  mode.value = 'paper'; mode.dispatchEvent(new Event('change'));
  check('virtual mode does not promise broker order', hint.textContent.includes('증권사 계좌로 주문을 보내지 않습니다'));
  document.getElementById('broker-save').click(); await tick();
  check('virtual save keeps mode contract', sent.at(-1)?.mode === 'paper');
  mode.value = 'live'; mode.dispatchEvent(new Event('change'));
  document.getElementById('broker-save').click(); await tick();
  check('paper route confirmation never says real', dialogs.at(-1)?.includes('KIS 모의투자(Testbed)로 주문') && !dialogs.at(-1).includes('실전'));
  check('broker save keeps live contract', sent.at(-1)?.mode === 'live');
  environment = 'real'; cfg.live_gateway = {configured:true, environment};
  await loadSettings(); await loadDashboard(); await tick();
  check('approved real route is visibly real', selectedText() === 'KIS 실전투자로 주문' && hint.textContent.includes('실계좌'));
  check('real quickstart is not called paper', document.getElementById('overview-kis-start').textContent.includes('KIS 실전투자 실행 중'));
  cfg.live_gateway = null; await loadSettings();
  check('unknown environment disables broker option', mode.options[1].disabled && selectedText().includes('확인 필요'));
  const previous = sent.length; document.getElementById('broker-save').click(); await tick();
  check('unknown route cannot be saved as broker mode', sent.length === previous);
  result.textContent = JSON.stringify({ok:true, checks});
} catch (e) { result.textContent = JSON.stringify({ok:false, checks, error:String(e), stack:e.stack}); }
