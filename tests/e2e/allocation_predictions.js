const result = document.createElement('pre'); result.id = 'allocation-predictions-result'; document.body.append(result);
const checks = [];
const check = (name, ok) => { if (!ok) throw Error(name); checks.push(name); };
const $ = id => document.getElementById(id);
const tick = () => new Promise(resolve => setTimeout(resolve, 30));
const calls = [];
window.fetch = async (path, options = {}) => {
  // 화면 초기화의 관리자 여부 조회는 배분 계산 요청과 별도로 응답한다.
  if (path === '/api/me' && options.method === 'GET') {
    return new Response(JSON.stringify({user: {roles: []}}), {
      status: 200, headers: {'Content-Type': 'application/json'},
    });
  }
  calls.push({path, method: options.method, body: options.body ? JSON.parse(options.body) : null});
  let response;
  if (path === '/api/ml/robo/allocation/latest' && options.method === 'GET') {
    response = {id: 'old-result', saved_at: '2026-10-16T00:00:00Z', result: fixture};
  } else if (path === '/api/ml/robo/allocation' && options.method === 'POST') {
    const input = JSON.parse(options.body);
    response = {...fixture, allocation_model: input.allocation_model,
      asset_model: input.allocation_model === 'black_litterman' ? {name:'Black–Litterman',model:'black_litterman',
        as_of:'2026-10-30',observations:180,views:input.views,benchmark_source:'user',reference_allocations:input.benchmark_weights,
        benchmark_note:'사용자 기준 균형 비중',method:'ETF 가격 수익률 대용치'} : null,
      saved: {id: 'new-result', saved_at: '2026-10-19T00:00:00Z'}};
  } else throw Error('Unexpected request');
  return new Response(JSON.stringify(response), {status: 200, headers: {'Content-Type': 'application/json'}});
};
try {
  await import('/js/robo.js');
  $('robo-load-allocation').click(); await tick();
  const cards = [...$('robo-stock-picks').children];
  const text = $('robo-stock-picks').textContent;
  check('saved bounds do not appear as numeric forecasts', cards.length === 3 && cards.slice(0, 2).every(c => c.textContent.includes('모델 범위 밖')) && !text.includes('300.0%') && !text.includes('-90.0%'));
  check('composite score is not displayed as probability', !text.includes('0.31') && !text.includes('31.0%') && text.includes('모델 매수 확률 48.2%'));
  check('sub-50 probability explains three classes and is not profit probability', text.includes('매도·관망·매수 중 가장 높은') && text.includes('50% 미만') && text.includes('실제 수익이 날 확률은 아닙니다'));
  check('quality warning is visible without XAI explanation', cards[0].textContent.includes('검증 성능 기준을 충족하지 못해') && cards[0].textContent.includes('최종 판단 관망'));
  check('legacy XAI badge agrees with lowered final signal', cards[1].querySelector('.badge-hold')?.textContent.includes('관망 · 모델 매수 48.2%'));
  check('zero is a valid annualized value', cards[2].textContent.includes('AI 연환산 참고값 0.00%') && cards[2].textContent.includes('5거래일 예측을 1년으로'));
  check('untrusted text is escaped', cards[0].textContent.includes('<b>문자</b>') && !cards[0].querySelector('b'));
  check('saved date and controls survive normalization', $('robo-allocation-saved').textContent.includes('저장됨') && !$('robo-load-allocation').disabled && !$('robo-optimize-btn').disabled);
  $('robo-optimize-btn').click(); await tick();
  check('new calculation uses the same safe card display', $('robo-stock-picks').textContent === text && calls.length === 2 && !$('robo-optimize-btn').disabled);
  check('legacy allocation defaults to profile model', calls[1].body.allocation_model === 'profile');
  $('robo-allocation-model').value = 'black_litterman'; $('robo-allocation-model').dispatchEvent(new Event('change'));
  check('view editor appears only for Black-Litterman', !$('robo-bl-inputs').classList.contains('hidden'));
  $('robo-bl-add').click();
  $('robo-bl-views').querySelector('.bl-return').value = '4.5';
  $('robo-bl-custom').click();
  $('robo-optimize-btn').click(); await tick();
  const bl = calls.at(-1).body;
  check('relative view and benchmark reach API', bl.allocation_model === 'black_litterman' && bl.views[0].outperformance_pct === 4.5 && bl.views[0].relative_to === '해외주식' && bl.benchmark_weights['현금'] === 5);
  check('saved model and views restore', $('robo-allocation-model').value === 'black_litterman' && $('robo-bl-views').querySelector('.bl-return').value === '4.5' && $('robo-model-result').textContent.includes('2026-10-30'));
  const before = calls.length;
  $('robo-bl-views').querySelector('.bl-confidence').value = '100';
  $('robo-optimize-btn').click(); await tick();
  check('invalid confidence rejected before request', calls.length === before && !$('robo-optimize-btn').disabled);
  $('robo-allocation-model').value = 'regime'; $('robo-allocation-model').dispatchEvent(new Event('change'));
  $('robo-optimize-btn').click(); await tick();
  check('regime request excludes stale BL views', calls.at(-1).body.allocation_model === 'regime' && !('views' in calls.at(-1).body) && $('robo-bl-inputs').classList.contains('hidden'));
  check('calculations never submit orders or change plans', calls.every(c => c.path.startsWith('/api/ml/robo/allocation')));
  result.textContent = JSON.stringify({ok: true, checks});
} catch (e) { result.textContent = JSON.stringify({ok: false, checks, error: String(e), stack: e.stack}); }
