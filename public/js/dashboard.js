/* 로그인 후 통합 대시보드. 개별 조회 실패는 해당 지표에만 표시한다. */
// Qurious(2026-10-03 · 화면 결정 ① C — 투자 대시보드 + 우리 서비스 맞춤): 강사님 판(9478811) 구성은 그대로 두고
// 우리 결정과 어긋나는 글 · 상태만 고쳤다 — KIS 키는 사용자마다(ADR-0004)라 「서버가 관리」 안내를 빼고,
// 거래가 0회인 기본 전략은 수익률을 0 으로 보이지 않고 「신호 없음」 이라 말한다(Figma 「투자 대시보드 · 메뉴 정리」 02 · 03).
import { api, escHtml, setToast } from '/js/common.js';
import { GNB_MENUS } from '/js/core.js';

let loading = false;
const metric = (label, value, note = '') => `<div class="overview-metric"><span>${escHtml(label)}</span><strong>${escHtml(value)}</strong><small>${escHtml(note)}</small></div>`;
const number = (value, suffix = '', digits = 1) => value !== null && value !== undefined && Number.isFinite(Number(value)) ? Number(value).toLocaleString('ko-KR', { maximumFractionDigits: digits }) + suffix : '데이터 없음';
function features(key) {
  return GNB_MENUS[key].items.filter(item => item.key !== 'dashboard').map(item => `<a class="overview-feature" href="#${item.key}"><i class="${item.icon}"></i><span>${escHtml(item.label)}</span><i class="fa-solid fa-arrow-right"></i></a>`).join('');
}
async function fill(id, request, render) {
  const el = document.getElementById(id);
  el.innerHTML = '<p class="overview-note" role="status">지표를 불러오는 중입니다…</p>';
  try {
    const data = await request();
    if (data.error) throw new Error(data.error);
    el.innerHTML = render(data);
  } catch {
    el.innerHTML = '<p class="overview-note" role="status">데이터를 불러오지 못했습니다. 새로고침으로 다시 시도하세요.</p>';
  }
}
// 거래가 한 번도 없으면 수익률 · 샤프 · 낙폭 · 승률은 「0」 이 아니라 매길 수 없는 값이다 — 이유와 비교값만 보인다
function noTradeMetric(data) {
  return `<div class="overview-metric wide"><span>최근 1년 매매</span><strong>신호 없음</strong>` +
    `<small>이 기간에 한 번도 사고팔지 않아 수익률 · 샤프 · 최대 낙폭 · 승률을 매기지 않습니다. 같은 기간 매수 후 보유 수익률은 ${escHtml(number(data.buy_hold_return_pct, '%'))} 입니다.</small></div>`;
}
export async function loadDashboard() {
  if (loading) return;
  loading = true;
  const button = document.getElementById('overview-refresh');
  button.disabled = true;
  document.getElementById('overview-robo-features').innerHTML = features('agent');
  document.getElementById('overview-indicator-features').innerHTML = features('company');
  loadKisQuickstart();
  try {
    await Promise.allSettled([
      loadAccountTabs(),
      fill('overview-decision', () => api('/api/quant/auto/status'), data =>
        metric('모의 투자 의사결정', data.running ? '실행 중' : '중지됨') + metric('현재 판단 신호', number(data.signals?.length, '개', 0))),
      fill('overview-indicator-metrics', () => api('/api/quant/pipeline?symbol=005930.KS&period=1y&strategy=rsi&cost_bps=10&slippage_bps=0'), data => Number(data.trade_count) === 0
        ? noTradeMetric(data)
        : metric('누적 수익률', number(data.total_return_pct, '%')) + metric('샤프 비율', number(data.sharpe_ratio, '', 2)) + metric('최대 낙폭 (MDD)', number(data.mdd_pct, '%')) + metric('승률', number(data.win_rate_pct, '%')) + metric('거래 횟수', number(data.trade_count, '회', 0)) + metric('매수 후 보유 수익률', number(data.buy_hold_return_pct, '%'))),
      fill('overview-saved', () => api('/api/custom-indicators'), data => metric('내 커스텀 인디케이터', number(data.items?.length, '개', 0))),
    ]);
    document.getElementById('overview-updated').textContent = '조회 완료 · ' + new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false });
  } finally { loading = false; button.disabled = false; }
}
document.getElementById('overview-refresh').addEventListener('click', loadDashboard);

// ── 투자 사이트별 현재 투자액 탭 (KIS 모의투자가 가장 왼쪽) ─────────────────
let accountTabs = [];
let activeTab = 'kis';
try { activeTab = localStorage.getItem('overview.accountTab') || 'kis'; } catch {}
const money = (v, cur = 'KRW') => v === null || v === undefined || !Number.isFinite(Number(v)) ? '데이터 없음'
  : cur === 'USD' ? '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }) : Number(v).toLocaleString('ko-KR', { maximumFractionDigits: 0 }) + '원';
const signed = (v, suffix) => v === null || v === undefined || !Number.isFinite(Number(v)) ? '' : (Number(v) >= 0 ? '+' : '') + Number(v).toLocaleString('ko-KR', { maximumFractionDigits: 2 }) + suffix;
function renderAccountPanel() {
  const panel = document.getElementById('overview-account-panel');
  const tab = accountTabs.find(t => t.key === activeTab) || accountTabs[0];
  if (!panel || !tab) return;
  document.querySelectorAll('#overview-account-tabs .overview-tab').forEach(b => {
    const on = b.dataset.key === tab.key; b.classList.toggle('active', on); b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  if (tab.key === 'robo') { panel.innerHTML = tab.html || '<p class="overview-note">데이터를 불러오지 못했습니다.</p>'; return; }
  if (!tab.connected) {
    panel.innerHTML = `<div class="overview-metric wide"><span>${escHtml(tab.site)}</span><strong>미연동</strong><small>${escHtml(tab.error || tab.note || '')}</small>${tab.link ? `<a class="underline text-xs" href="${tab.link}">설정으로 이동</a>` : ''}</div>`;
    return;
  }
  const pnlNote = signed(tab.pnl_pct, '%') ? `손익 ${signed(tab.pnl, tab.currency === 'USD' ? ' USD' : '원')} (${signed(tab.pnl_pct, '%')})` : (tab.pnl !== null && tab.pnl !== undefined ? `손익 ${signed(tab.pnl, '원')}` : '');
  let html = metric('현재 투자액 (보유 평가)', money(tab.invested, tab.currency), tab.note || '') +
    metric('현금 · 예수금', money(tab.cash, tab.currency)) +
    metric('총 자산', money(tab.total, tab.currency), pnlNote) +
    metric('보유 종목', tab.positions === null || tab.positions === undefined ? '데이터 없음' : number(tab.positions, '개', 0));
  if (tab.key === 'kis') html += metric('자동매매', tab.auto_trade_running ? '실행 중 (live · KIS)' : '꺼짐', `미체결 실주문 ${number(tab.open_live_orders, '건', 0)} · ${escHtml(tab.environment === 'real' ? '실전' : '모의(Testbed)')}`);
  if (tab.key === 'paper' && tab.breakdown) html += metric('자산별 평가', `주식 ${money(tab.breakdown.stocks)}`, `코인 ${money(tab.breakdown.crypto)} · 대체 ${money(tab.breakdown.alternatives)}`);
  panel.innerHTML = html;
}
function renderAccountTabBar() {
  const bar = document.getElementById('overview-account-tabs');
  if (!bar) return;
  bar.innerHTML = accountTabs.map(t => `<button type="button" role="tab" class="overview-tab" data-key="${t.key}" aria-selected="false"><span class="dot ${t.connected ? 'on' : ''}"></span>${escHtml(t.label)}</button>`).join('');
  bar.querySelectorAll('.overview-tab').forEach(b => b.addEventListener('click', () => {
    activeTab = b.dataset.key;
    try { localStorage.setItem('overview.accountTab', activeTab); } catch {}
    renderAccountPanel();
  }));
}
async function loadAccountTabs() {
  const panel = document.getElementById('overview-account-panel');
  if (!panel) return;
  const [acc, robo] = await Promise.allSettled([api('/api/dashboard/accounts'), api('/api/rebalance/status')]);
  accountTabs = acc.status === 'fulfilled' ? (acc.value.tabs || []) : [
    { key: 'kis', label: 'KIS 모의투자', site: '한국투자증권 Testbed', connected: false, error: acc.reason?.message || '불러오지 못했습니다' },
  ];
  const roboTab = { key: 'robo', label: '로보 모의계좌', site: '리밸런싱 엔진', connected: robo.status === 'fulfilled' };
  if (robo.status === 'fulfilled') {
    const { snapshot: s, plan } = robo.value;
    roboTab.html = metric('모의계좌 총 자산', number(s.total_asset, '원', 0)) + metric('현금 비중', number(s.cash_weight_pct, '%')) + metric('최대 비중 이탈', number(s.max_drift_pct, '%p')) + metric('리밸런싱 계획', plan.is_active ? '활성' : '비활성', plan.auto_execute ? '자동 체결' : '수동 승인');
  }
  accountTabs.push(roboTab);
  if (!accountTabs.some(t => t.key === activeTab)) activeTab = 'kis';
  renderAccountTabBar();
  renderAccountPanel();
}

// ── KIS 모의투자 원클릭 ─────────────────────────────────────────────────
// Qurious: KIS 키는 사용자마다(ADR-0004) — 서버 설정 이름 대신 사용자가 할 일을 말한다
const KIS_BLOCK_TEXT = {
  not_connected: '「증권사 API 설정」 에서 내 KIS 모의투자 키(App Key · Secret · 계좌번호)를 넣으면 시작할 수 있어요.',
  real_environment: '지금 KIS 경로가 실전이라 원클릭 모의투자는 시작하지 않습니다. 「증권사 API 설정」 에서 모의투자로 바꾸세요.',
  kill_switch: '비상 정지 상태입니다. 자동매매 현황에서 해제한 뒤 시작하세요.',
};
async function loadKisQuickstart() {
  const btn = document.getElementById('overview-kis-start');
  const el = document.getElementById('overview-kis-status');
  if (!btn || !el) return;
  try {
    const st = await api('/api/quant/kis/quickstart');
    const badge = st.connected ? '<span class="badge-buy">연동됨</span>' : '<span class="badge-sell">미연동</span>';
    const link = `${badge} ${escHtml(st.route_detail || '')}`;
    if (st.already_started) {
      btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-check"></i> KIS 모의투자 실행 중';
      el.innerHTML = `${link} · 자동매매 <b>실행 중</b> (live · KIS · 10분 주기). <a href="#quant-auto" class="underline">자동매매 현황</a>`;
    } else if (st.ready) {
      btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-play"></i> KIS 모의투자 시작';
      const d = st.defaults || {};
      el.innerHTML = `${link} · 시작하면 AI 추천 ${d.quant_ai_top_n ?? 3}종목 · 1회 ${Number(d.quant_per_trade_budget ?? 300000).toLocaleString('ko-KR')}원 · 쿨다운 ${d.risk_cooldown_min ?? 30}분 · 종목 비중 ${d.risk_max_position_pct ?? 20}% 로 자동매매를 켭니다.` +
        (st.running ? ` 현재 ${escHtml(st.mode)}/${escHtml(st.broker)} 자동매매가 켜져 있어 설정이 KIS 모의투자로 바뀝니다.` : '');
    } else {
      btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-play"></i> KIS 모의투자 시작';
      // 키가 없을 때는 서버 안내(route_detail)와 같은 말을 두 번 하지 않는다
      el.innerHTML = st.reason === 'not_connected'
        ? `${badge} ${escHtml(KIS_BLOCK_TEXT.not_connected)}`
        : `${link} · ${escHtml(KIS_BLOCK_TEXT[st.reason] || '지금은 시작할 수 없습니다.')}`;
    }
  } catch (e) {
    btn.disabled = true;
    el.textContent = '연동 상태를 불러오지 못했습니다. ' + (e?.message || '');
  }
}
document.getElementById('overview-kis-start')?.addEventListener('click', async () => {
  const btn = document.getElementById('overview-kis-start');
  const el = document.getElementById('overview-kis-status');
  if (!confirm('KIS 모의투자(Testbed)를 시작합니다.\nAI 추천 종목으로 10분마다 시그널을 평가하고, 매수/매도 시 내 한국투자증권 모의투자 계좌로 주문이 나갑니다.\n\n계속하시겠습니까?')) return;
  btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 시작 중…';
  try {
    const r = await api('/api/quant/kis/quickstart', { method: 'POST' });
    setToast(r.started ? 'KIS 모의투자 자동매매를 시작했습니다. 첫 사이클을 실행합니다.' : '이미 자동매매가 켜져 있어 설정만 KIS 모의투자로 갱신했습니다.', 'ok');
    if (el) el.innerHTML = `<span class="badge-buy">시작됨</span> ${escHtml(r.route_detail || '')} · 첫 사이클 실행 중, 이후 ${r.interval_min || 10}분마다 반복. <a href="#quant-auto" class="underline">자동매매 현황</a>`;
  } catch (e) {
    setToast(e.message, 'error');
    if (el) el.textContent = '시작 실패: ' + e.message;
  } finally {
    await loadKisQuickstart();
    loadDashboard();
  }
});
