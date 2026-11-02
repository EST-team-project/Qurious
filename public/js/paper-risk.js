/** PAPER 계좌에서 신규 매수 수량을 계산한다. 응답이 늦으면 다른 종목/입력에 적용하지 않는다. */
export function mountPaperRisk({ doc, api }) {
  const el = id => doc.getElementById(id);
  if (!el('ps-risk-calc')) return;
  const fields = {
    risk_pct: 'ps-risk-pct', budget: 'ps-risk-budget', position_cap_pct: 'ps-risk-cap',
    stop_kind: 'ps-risk-kind', stop_loss_pct: 'ps-risk-stop', atr_mult: 'ps-risk-atr',
    slippage_bps: 'ps-risk-slippage',
  };
  let revision = 0;
  function invalidate() {
    revision++;
    el('ps-qty').value = '';
    el('ps-risk-result').textContent = '입력값을 확인한 뒤 수량을 계산하세요.';
  }
  for (const id of ['ps-symbol', ...Object.values(fields)]) el(id)?.addEventListener('input', invalidate);
  // 사용자가 직접 수량을 바꾸면 진행 중인 계산이 덮어쓰지 않는다.
  el('ps-qty').addEventListener('input', () => { revision++; });
  el('ps-risk-calc').addEventListener('click', async () => {
    const current = ++revision;
    const symbol = el('ps-symbol').value.trim();
    const code = s => s.split('.')[0].toUpperCase();
    el('ps-qty').value = '';
    el('ps-risk-result').textContent = 'PAPER 계좌와 가격 확인 중…';
    const body = { symbol };
    for (const [key, id] of Object.entries(fields)) body[key] = key === 'stop_kind' ? el(id).value : Number(el(id).value);
    const stillCurrent = () => current === revision && code(el('ps-symbol').value.trim()) === code(symbol);
    try {
      const r = await api('/api/paper/stocks/orders/risk-preview', { method: 'POST', body });
      if (!stillCurrent()) return;
      el('ps-qty').value = r.quantity > 0 ? String(r.quantity) : '';
      const labels = { risk: '위험 예산', cash: '현금', budget: '주문 예산', position: '종목 비중' };
      const won = n => Number(n).toLocaleString('ko-KR', { maximumFractionDigits: 0 }) + '원';
      el('ps-risk-result').textContent = `PAPER 신규 매수 ${r.quantity}주 · 평가액 ${won(r.equity)} · 현금 ${won(r.cash)} · `
        + `계산 기준가 ${won(r.price)} · 손절 기준 ${won(r.stop_price)} · 예상 손실 ${won(r.estimated_loss)} · `
        + `수량 제한: ${r.binding_limits.map(k => labels[k] || k).join(', ')}. `
        + (r.basis.atr_as_of ? `ATR 확정일 ${r.basis.atr_as_of}. ` : '') + (r.quote_label || '') + ' ' + r.note;
    } catch (err) {
      if (stillCurrent()) el('ps-risk-result').textContent = `수량 계산 보류: ${err.message}`;
    }
  });
}
