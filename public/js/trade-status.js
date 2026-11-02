// 서버의 증권사 확인 근거를 표시한다. 가상 수량·가격은 체결가로 표현하지 않는다.
export function renderTradeExecution(trade, escHtml, fmt) {
  const e = trade.execution || { label: '주문 상태 미확인', level: 'warning', detail: '증권사 주문 내역을 확인해 주세요.' };
  const color = { error: 'var(--red)', warning: 'var(--amber)', success: 'var(--green)', info: 'var(--text-dim)' }[e.level] || 'var(--text-dim)';
  const side = trade.action === 'buy' ? '매수' : '매도';
  const virtual = ` · ${e.virtual_status === 'filled' ? '가상 기록' : '주문 요청'} ${fmt(trade.quantity)}주 @${fmt(trade.price)}`;
  const fill = e.filled_quantity > 0 ? ` · 증권사 확인 ${fmt(e.filled_quantity)}주 @${fmt(e.avg_filled_price)}` : '';
  const sizing = trade.price_basis?.sizing;
  const labels = {risk: '위험 금액', cash: '현금', budget: '1회 예산', position: '종목 비중', broker: '증권사 가능 수량', requested: '요청 수량'};
  const limits = sizing ? `<div class="text-xs">수량 제한: ${(sizing.binding_limits || []).map(k => escHtml(labels[k] || k)).join(' · ')} · 예상 손실 ${fmt(sizing.estimated_loss)}원 · 손절선 ${fmt(sizing.stop_price)}원</div>` : '';
  const stop = trade.price_basis?.stop;
  const stopText = stop ? `<div class="text-xs">${stop.origin === 'transition' ? '전환 시 고정' : '진입 시 고정'} 손절 ${fmt(stop.stop_price)}원 (${escHtml(stop.stop_kind)})</div>` : '';
  const instrument = trade.price_basis?.instrument || {};
  const warnings = (instrument.warnings || []).map(w => `<div class="text-xs" style="color:var(--amber);">${escHtml(w)}</div>`).join('');
  const premium = Number.isFinite(instrument.close_nav_premium_pct)
    ? `<div class="text-xs">ETF 종가/NAV 괴리 ${fmt(instrument.close_nav_premium_pct, 2)}% · ${escHtml(instrument.premium_as_of)} 기준 · 장중 iNAV 아님</div>` : '';
  const code = String(trade.symbol || '').split('.')[0];
  const hub = /^[0-9A-Z]{6}$/.test(code) ? ` <button type="button" class="sd-open-btn text-xs" data-hub-open="${escHtml(code)}" data-hub-name="${escHtml(trade.name || '')}">종목 근거 →</button>` : '';
  return `<div class="ml-3" style="color:${color};"><b>${escHtml(e.label)}</b> · ${side} ${escHtml(trade.name || trade.symbol || '')}${virtual}${fill}
    ${hub}<div class="text-xs">${escHtml(e.ledger || '')} — ${escHtml(e.detail || '')}</div>${limits}${stopText}${warnings}${premium}</div>`;
}
