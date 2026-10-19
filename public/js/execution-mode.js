// mode는 가상매매/증권사 연동 구분이다. 실전 여부는 서버가 확인한 environment로만 읽는다.
export function kisEnvironmentLabel(environment) {
  return environment === 'paper' ? 'KIS 모의투자(Testbed)'
    : environment === 'real' ? 'KIS 실전투자' : 'KIS 주문 환경 미확인';
}

export function executionModeView({ mode = 'paper', broker = 'mock', live_gateway = null } = {}) {
  const environment = live_gateway?.environment;
  const available = broker === 'kis' && ['paper', 'real'].includes(environment);
  const brokerLabel = broker !== 'kis' ? '증권사 주문 — KIS 설정 필요'
    : available ? `${kisEnvironmentLabel(environment)}로 주문` : '증권사 주문 환경 확인 필요';
  const label = mode === 'paper' ? '앱 안 가상매매' : brokerLabel;
  const detail = mode === 'paper'
    ? '앱 가상 장부에서 체결하며 증권사 계좌로 주문을 보내지 않습니다.'
    : !available ? '증권사 KIS를 선택하고 설정을 다시 불러와 주문 환경을 확인해 주세요.'
    : environment === 'paper'
      ? '연결된 한국투자증권 모의계좌로 주문합니다. 주문 접수와 체결은 별도로 확인합니다.'
      : '연결된 한국투자증권 실계좌로 주문합니다. 실거래 승인이 적용된 경로입니다.';
  return { label, detail, brokerLabel, available };
}

export function renderExecutionMode(select, hint, config) {
  const view = executionModeView(config);
  const option = [...select.options].find(o => o.value === 'live');
  option.textContent = view.brokerLabel;
  option.disabled = !view.available;
  hint.textContent = view.detail;
  return view;
}
