const result = document.createElement('pre'); result.id = 'rebalance-trigger-result'; document.body.append(result);
const checks = [];
const check = (name, ok) => { if (!ok) throw Error(name); checks.push(name); };
const $ = id => document.getElementById(id);
const tick = () => new Promise(resolve => setTimeout(resolve, 30));
const choose = (id, value) => { $(id).value = value; $(id).dispatchEvent(new Event('change')); };
const enter = (id, value) => { $(id).value = value; $(id).dispatchEvent(new Event('input')); };
const visible = id => $(id).getClientRects().length > 0;
let plan = {targets: [], time_period: 'none', drift_enabled: true, drift_threshold_pct: 5,
  cashflow_enabled: true, cashflow_min_amount: 100000, min_order_amount: 10000, is_active: true};
const sent = [];
const unexpected = [];
window.fetch = async (input, options = {}) => {
  const path = String(input);
  let data;
  if (options.method === 'PUT' && path === '/api/rebalance/plan') {
    const body = JSON.parse(options.body); sent.push(body); plan = {...plan, ...body}; data = {ok: true};
  } else if (options.method && options.method !== 'GET') { unexpected.push(path); throw Error('Unexpected mutation: ' + path); }
  else if (path === '/api/rebalance/status') data = {plan, snapshot: null, triggers: {}};
  else if (path === '/api/rebalance/runs?limit=20') data = {runs: []};
  else if (path === '/api/rebalance/cashflows?limit=20') data = {events: []};
  else { unexpected.push(path); throw Error('Unexpected API: ' + path); }
  return new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json'}});
};
try {
  const {initRebalanceView, onRebalanceViewActivated} = await import('/js/rebalance.js');
  initRebalanceView();
  check('first plan receives preset defaults', $('rb-drift').value === '3' && $('rb-cf-min').value === '0');
  check('initial preset has no duplicate numeric fields', !visible('rb-drift') && !visible('rb-cf-min'));
  $('rb-save').click(); await tick();
  check('first plan saves finite defaults', sent.at(-1)?.drift_threshold_pct === 3 && sent.at(-1)?.cashflow_min_amount === 0);
  plan = {...plan, drift_threshold_pct: 5, cashflow_min_amount: 100000};
  onRebalanceViewActivated('robo-rebalance'); await tick();
  check('saved presets load without duplicate fields', $('rb-drift-preset').value === '5' && $('rb-cf-preset').value === '100000' && !visible('rb-drift') && !visible('rb-cf-min'));
  for (const [selectId, inputId, unit] of [['rb-drift-preset', 'rb-drift', '%p'], ['rb-cf-preset', 'rb-cf-min', '원']]) {
    choose(selectId, 'custom');
    check(inputId + ' custom is visible and focused', visible(inputId) && document.activeElement === $(inputId));
    check(inputId + ' has associated name, unit and help', [...$(inputId).labels].some(l => l.textContent.includes('직접 입력') && l.textContent.includes(unit)) && !!$($(inputId).getAttribute('aria-describedby'))?.textContent);
  }
  enter('rb-drift', '5'); enter('rb-cf-min', '100000');
  check('typing a preset value does not hide custom editor', visible('rb-drift') && visible('rb-cf-min') && $('rb-drift-preset').value === 'custom' && $('rb-cf-preset').value === 'custom');
  enter('rb-drift', '5.5'); enter('rb-cf-min', '120000');
  $('rb-save').click(); await tick();
  check('custom values survive save and reload', sent.at(-1)?.drift_threshold_pct === 5.5 && sent.at(-1)?.cashflow_min_amount === 120000 && visible('rb-drift') && visible('rb-cf-min') && $('rb-drift').value === '5.5' && $('rb-cf-min').value === '120000');
  choose('rb-drift-preset', '10'); choose('rb-cf-preset', '50000');
  check('returning to presets updates values and hides custom fields', !visible('rb-drift') && !visible('rb-cf-min') && $('rb-drift').value === '10' && $('rb-cf-min').value === '50000');
  $('rb-drift-enabled').checked = false; $('rb-cf-enabled').checked = false;
  $('rb-save').click(); await tick();
  check('disabled criteria preserve numeric values on save', sent.at(-1)?.drift_enabled === false && sent.at(-1)?.cashflow_enabled === false && sent.at(-1)?.drift_threshold_pct === 10 && sent.at(-1)?.cashflow_min_amount === 50000);
  choose('rb-drift-preset', 'custom'); enter('rb-drift', '');
  const previous = sent.length; $('rb-save').click(); await tick();
  check('empty custom value is rejected before saving', sent.length === previous && $('_toast_el').textContent.includes('설정 금액과 이탈률을 입력하세요'));
  check('all API calls use the expected isolated fixtures', unexpected.length === 0);
  result.textContent = JSON.stringify({ok: true, checks});
} catch (e) { result.textContent = JSON.stringify({ok: false, checks, error: String(e), stack: e.stack}); }
