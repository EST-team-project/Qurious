/* 자동매매 판단의 출처·시각. 점수는 매수 확률이나 체결 결과가 아니다. */
export function latestCycleSignals(signals, limit = 3) {
  const ordered = [...(signals || [])].sort((a,b) => {
    const time = s => Number.isFinite(Date.parse(s.cycle_at)) ? Date.parse(s.cycle_at) : -Infinity;
    return time(b) - time(a) || 0;
  });
  const newest = ordered[0]?.cycle_at;
  const seen = new Set();
  return ordered.filter(s => {
    const key = `${s.source || 'me'}:${s.symbol}`;
    if (s.cycle_at !== newest || seen.has(key)) return false;
    seen.add(key); return true;
  }).slice(0, limit);
}

export function renderDecisionBasis(signal, esc, time) {
  const d = signal.decision || {};
  let stamp = d.as_of;
  if (typeof stamp === 'number') {
    const date = new Date(stamp * 1000);
    stamp = Number.isFinite(date.getTime()) ? date.toISOString() : null;
  }
  const basisTime = stamp ? (String(stamp).includes('T') ? time(stamp) : stamp) : '미확인';
  return `<div class="text-xs mb-2" style="color:var(--text-mute);">
    <div>${esc(d.method || '과거 기록 · 판단 방식 미확인')}</div>
    <div>${esc(d.score_text || '점수 미확인')}</div>
    <div>판단 회차 ${esc(signal.cycle_at ? time(signal.cycle_at) : '미확인')} · 한국시간 · ${signal.source === 'batch' ? '시스템 배치' : '내 자동매매'}</div>
    <div>기준 봉 ${esc(basisTime)}${d.interval ? ' · ' + esc(d.interval) : ''}</div>
    ${d.note ? `<div>${esc(d.note)}</div>` : ''}
  </div>`;
}
