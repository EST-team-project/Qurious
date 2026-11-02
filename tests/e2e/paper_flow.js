import { api } from '/js/common.js';
import { initPaperViews } from '/js/paper.js';
import { signalCardHtml } from '/js/quant.js';
import { mountStockDrawer } from '/js/stockdrawer.js';
const $ = id => document.getElementById(id);
const checks = [];
function check(name, ok) { checks.push({name, ok: !!ok}); if (!ok) throw Error(name); }
async function until(fn) { for(let i=0;i<200;i++) { if(fn()) return; await new Promise(r=>setTimeout(r,50)); } throw Error('화면 응답 대기 초과'); }
let confirmations = 0;
const chartInputs = [];
// 차트 라이브러리는 입력 기록용 어댑터. 제품의 차트 데이터 변환·요청 코드는 그대로 실행한다.
window.LightweightCharts = {LineSeries: {}, createChart: () => ({
  addSeries: () => ({setData: points => chartInputs.push(points), createPriceLine: () => {}}),
  timeScale: () => ({fitContent: () => {}}), remove: () => {},
})};
window.confirm = () => { confirmations++; return true; };
try {
  initPaperViews();
  mountStockDrawer(document, {api, navigate: v => { document.body.dataset.activeView = v; }});
  const card = document.createElement('div'); card.id = 'flow-signal'; document.body.append(card);
  card.innerHTML = signalCardHtml({symbol:'005930.KS',name:'시험'}, {signal:{action:'매수',reasons:['합성 시험']}});
  $('ps-qty').value = '999'; $('ps-risk-kind').value = 'pct'; $('ps-risk-budget').value = '200000';
  // 입구는 모두 큰 모달로 바로 열린다(2026-11-02 · 서랍은 거치지 않는다)
  card.querySelector('[data-hub-open]').click();
  await until(()=>$('hub-modal') && !$('hub-modal').hidden && document.querySelector('#hub-modal [data-hub-go="paper-stock"]'));
  check('신호에서 종목 근거가 큰 모달로 바로 열림', !$('hub-modal').hidden && (!$('hub-drawer') || $('hub-drawer').hidden));
  document.querySelector('#hub-modal [data-hub-modal-close]').click();
  check('모달 닫기', $('hub-modal').hidden);
  // 서랍이 필요한 입구(data-hub-mode="drawer")는 서랍으로 열리고 크게 보기로 같은 모달에 간다
  const drawerEntry = document.createElement('button');
  drawerEntry.type = 'button';
  drawerEntry.dataset.hubOpen = card.querySelector('[data-hub-open]').dataset.hubOpen;
  drawerEntry.dataset.hubName = '시험'; drawerEntry.dataset.hubMode = 'drawer';
  card.append(drawerEntry);
  drawerEntry.click();
  await until(()=>$('hub-drawer') && !$('hub-drawer').hidden && document.querySelector('#hub-drawer [data-hub-expand]'));
  check('서랍 입구는 서랍으로 열림', !$('hub-drawer').hidden);
  document.querySelector('#hub-drawer [data-hub-expand]').click();
  await until(()=>$('hub-modal') && !$('hub-modal').hidden);
  check('서랍에서 크게 보기 모달 열림', !$('hub-modal').hidden && $('hub-drawer').hidden);
  document.querySelector('#hub-modal [data-hub-modal-close]').click();
  card.querySelector('[data-hub-open]').click();
  await until(()=>!$('hub-modal').hidden && document.querySelector('#hub-modal [data-hub-go="paper-stock"]'));
  document.querySelector('#hub-modal [data-hub-go="paper-stock"]').click();
  check('이전 수량 지움', $('ps-qty').value === '');
  await until(()=>$('ps-qty').value !== '');
  check('PAPER 계좌 기준 19주 계산', $('ps-qty').value === '19' && $('ps-risk-result').textContent.includes('PAPER'));
  check('스탑 자동 등록하지 않음을 표시', $('ps-risk-result').textContent.includes('자동 등록하지 않습니다'));
  $('ps-symbol').value = '시험'; $('ps-symbol').dispatchEvent(new Event('input'));
  $('ps-risk-calc').click(); await until(()=>$('ps-qty').value === '19');
  check('종목 이름 검색 후에도 같은 PAPER 수량', $('ps-symbol').value === '005930.KS');
  let history = await api('/api/paper/stocks/orders/history');
  check('계산만으로는 주문 없음', history.history.length === 0);
  $('ps-preview-buy').click();
  await until(()=>$('ps-preview').textContent.includes('체결 가능'));
  $('ps-buy').click();
  await until(()=>$('ps-history').textContent.includes('주문번호'));
  history = await api('/api/paper/stocks/orders/history');
  const logs = await api('/api/notification/history');
  check('주문 전 확인 한 번', confirmations === 1);
  check('체결 내역 한 건', history.history.length === 1 && history.history[0].quantity === 19);
  const order = history.history[0];
  check('화면에 주문번호 표시', $('ps-history').textContent.includes(order.order_id));
  const rows = logs.events;
  check('알림과 주문번호 일치', rows.length === 1 && rows[0].ref === order.order_id && rows[0].delivery_status === 'delivered');
  check('주문 비용과 정산액 저장', order.total_cost > 0 && order.net_amount > order.amount);
  const stops = await api('/api/paper/stocks/orders/stop');
  check('수량 계산이 스탑을 만들지 않음', stops.orders.length === 0);
  $('ps-stop-symbol').value = '005930'; $('ps-stop-price').value = '';
  $('ps-stop-quote-btn').click(); await until(()=>$('ps-stop-quote').textContent.includes('시험'));
  check('현재가가 스탑가에 자동 입력되지 않음', $('ps-stop-price').value === '');
  await until(()=>chartInputs.length > 0);
  check('통합 차트에 일봉 데이터 전달', chartInputs.every(points => points.length === 2));
} catch(error) { checks.push({name:'error',ok:false,error:String(error.stack||error)}); }
const result=document.createElement('pre');result.id='paper-flow-result';
result.textContent=JSON.stringify({ok:checks.every(c=>c.ok),checks});document.body.append(result);
