import { api } from '/js/common.js';
import { loadSettings } from '/js/settings.js';
const $ = id => document.getElementById(id);
const checks = [];
function check(name, ok) { checks.push({name, ok: !!ok}); if (!ok) throw Error(name); }
async function until(fn) { for(let i=0;i<200;i++) { if(await fn()) return; await new Promise(r=>setTimeout(r,50)); } throw Error('화면 응답 대기 초과'); }
const form = {slug:'browser-card',name:'브라우저 내 전략',symbol:'005930',short_window:10,long_window:60,
  atr_period:14,atr_mult:2.5,take_rr:2.5,risk_pct:2,max_position_pct:30,max_symbols:5,
  entry_mode:'open',exit_mode:'open',judge:'close'};
try {
  const created = await api('/api/indicator-strategy/cards', {method:'POST',body:form});
  await api('/api/indicator-strategy/cards', {method:'POST',body:{...form,slug:'unsupported',judge:'intrabar'}});
  await loadSettings();
  const options = [...$('quant-strategy').options];
  check('외부 인증 없이 내 카드 목록 표시', options.some(o=>o.dataset.cardId===created.id));
  check('미지원 카드는 이유와 함께 선택 불가', options.some(o=>o.disabled&&o.textContent.includes('종가 판단')));
  $('quant-strategy').value='local:'+created.id;
  $('quant-strategy').dispatchEvent(new Event('change'));
  check('카드와 중복되는 일반 규칙 입력 잠금', $('quant-symbol-source').disabled && $('quant-risk-pct').disabled);
  check('내 전략·가상계좌 안내', $('quant-strategy-hint').textContent.includes('합격 판정이 아닙니다'));
  $('broker-save').click();
  await until(async()=> (await api('/api/quant/settings')).strategy_card_id===created.id);
  const pinned = (await api('/api/quant/settings')).local_strategy;
  check('선택한 카드 값 고정', pinned.spec.position_sizing.risk_pct===2 && pinned.spec.stops.take_rr===2.5);
  check('선택만으로 자동 실행 켜지지 않음', !(await api('/api/auto-trade/status')).running);
  await api('/api/indicator-strategy/cards', {method:'POST',body:{...form,risk_pct:3}});
  await loadSettings();
  check('원본 변경 뒤 선택 당시 내용 유지 표시', $('quant-strategy').selectedOptions[0].textContent.includes('선택 당시 내용 유지'));
  await api('/api/indicator-strategy/cards/'+created.id, {method:'DELETE'});
  await loadSettings();
  $('quant-per-trade-budget').value='20000'; $('broker-save').click();
  await until(async()=> (await api('/api/quant/settings')).per_trade_budget===20000);
  const saved = await api('/api/quant/settings');
  check('원본 삭제 후 예산 저장에도 고정 규칙 유지', saved.local_strategy.spec_hash===pinned.spec_hash);
  $('quant-strategy').value=''; $('quant-strategy').dispatchEvent(new Event('change'));
  check('기본 규칙 선택 시 입력 복구', !$('quant-symbol-source').disabled && !$('quant-risk-pct').disabled);
} catch(error) { checks.push({name:'error',ok:false,error:String(error.stack||error)}); }
const result=document.createElement('pre'); result.id='local-flow-result';
result.textContent=JSON.stringify({ok:checks.every(c=>c.ok),checks});document.body.append(result);
