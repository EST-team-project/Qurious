// 서버의 증권사 확인 근거를 표시한다. 가상 수량·가격은 체결가로 표현하지 않는다.
export function renderTradeExecution(trade, escHtml, fmt) {
  const e = trade.execution || { label: '주문 상태 미확인', level: 'warning', detail: '증권사 주문 내역을 확인해 주세요.' };
  const color = { error: 'var(--red)', warning: 'var(--amber)', success: 'var(--green)', info: 'var(--text-dim)' }[e.level] || 'var(--text-dim)';
  const side = trade.action === 'buy' ? '매수' : '매도';
  const virtual = ` · ${e.virtual_status === 'filled' ? '가상 기록' : '주문 요청'} ${fmt(trade.quantity)}주 @${fmt(trade.price)}`;
  const fill = e.filled_quantity > 0 ? ` · 증권사 확인 ${fmt(e.filled_quantity)}주 @${fmt(e.avg_filled_price)}` : '';
  return `<div class="ml-3" style="color:${color};"><b>${escHtml(e.label)}</b> · ${side} ${escHtml(trade.name || trade.symbol || '')}${virtual}${fill}
    <div class="text-xs">${escHtml(e.ledger || '')} — ${escHtml(e.detail || '')}</div></div>`;
}
