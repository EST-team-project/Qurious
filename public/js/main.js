/* 엔트리: 부트스트랩, 뷰 활성화 디스패치
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, redirectToLogin, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";
import { loadMarketTicker, loadSyncStatus, navigate, registerViewActivation } from "/js/core.js";
import { loadCrawlList } from "/js/agent.js";
import { loadCompanyCompare, loadCompanyDashboard, loadCompanySector } from "/js/company.js";
import { loadIndicatorApiSettings, loadIndicatorBacktest, loadSavedIndicators } from "/js/indicator.js";
import { loadMacroDashboard, loadMacroIndustry } from "/js/ml.js";
import { initPaperViews, onPaperViewActivated } from "/js/paper.js";
import { loadAutoTradeStatus, loadQuantDashboard } from "/js/quant.js";
import { initRebalanceView, onRebalanceViewActivated } from "/js/rebalance.js";
import { loadPatternAnalysis, loadRoboDecision, loadRoboScreening, loadRoboPerformanceMetrics } from "/js/robo.js";
import { loadNotificationSettings, loadSettings } from "/js/settings.js";
import { loadAuditLog, loadSystemDashboard } from "/js/sysadmin.js";
import { loadBrokerStatus, loadOrderHistory, loadPortfolio, loadStockChart } from "/js/trading.js";
import { initTradingViewView, onTradingViewViewActivated } from "/js/tradingview.js";
import { initFormulaView, onFormulaViewActivated } from "/js/formula.js";
import { loadUsChart, loadUsDashboard, loadUsPortfolio, renderUsOrders } from "/js/us.js";
import { initCompletionIndicator } from "/js/completion.js";
import { onMyPageActivated } from "/js/mypage.js";
import { onFinLearnViewActivated } from "/js/finlearn.js";
import { initDataBadge, onDataHubViewActivated } from "/js/datahub.js";   // 데이터 관제 · 위 메뉴 표시 (2026-10-02)
import { onCalendarViewActivated } from "/js/calendar.js";             // 일정 · 다가오는 일정 카드 (2026-10-02)

// ── Boot ──────────────────────────────────────────────────────────
// 로그인 화면으로 보내는 것은 **로그인이 풀렸을 때(401)만**이다. 예전에는 아래 어느 줄에서든 오류가 나면
// 로그인 화면으로 보내서, 화면 초기화 오류 · 서버 재시작 중의 연결 실패도 「로그아웃된 것」 처럼 보였다.
async function boot() {
  initCompletionIndicator();
  let user;
  for (let attempt = 0; ; attempt++) {
    try {
      ({ user } = await getMe());
      break;
    } catch (err) {
      // 401 이면 api() 가 이미 로그인 화면으로 보냈다(돌아올 주소 ?next= 를 붙여서 · 강사님 289bfb5).
      // 여기서 한 번 더 location 을 바꾸면 ?next= 가 사라지므로 같은 함수를 부른다(두 번째 호출은 아무것도 안 한다).
      if (err.status === 401) { redirectToLogin(); return; }
      // 연결 실패 · 서버 오류는 한 번만 다시 시도한다(개발 모드에서 앱이 다시 켜지는 몇 초 사이일 수 있다).
      if (attempt >= 1) { setToast(`내 정보를 불러오지 못했습니다 — 새로고침해 주세요. (${err.message})`, "error"); return; }
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  document.getElementById("user-name").textContent = user.name;
  const avatar = document.getElementById("user-avatar");
  if (avatar) avatar.textContent = (user.name || "U").charAt(0).toUpperCase();
  // 머리글의 이름 · 아바타를 누르면 마이페이지로
  document.getElementById("gnb-user")?.addEventListener("click", () => navigate("mypage"));
  try {
    loadMarketTicker();
    loadSyncStatus();
    setInterval(loadSyncStatus, 60_000);   // refresh sync badge every minute
    initDataBadge();                       // 위 메뉴의 「자료 MM-DD · 판정」 — 1분마다 (js/datahub.js)
    initPaperViews();                      // 모의투자 · LEAN 백테스트 버튼 바인딩 (js/paper.js)
    initRebalanceView();                   // 리밸런싱 엔진 버튼 바인딩 (js/rebalance.js)
    initTradingViewView();                 // TradingView 연동 (js/tradingview.js)
    initFormulaView();                     // 자유 산식 지표 (js/formula.js)
    const hash = location.hash.replace("#", "");
    navigate(hash && document.querySelector(`[data-view="${hash}"]`) ? hash : "agent-chat");
  } catch (err) {
    console.error(err);
    setToast(`화면을 준비하다 오류가 났습니다: ${err.message}`, "error");
  }
}

document.getElementById("logout-btn").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => { });
  // replace — 로그아웃 뒤 뒤로가기로 앱 화면 기록이 다시 뜨지 않게
  location.replace("/login.html");
});

// ── View Activation ───────────────────────────────────────────────
function onViewActivated(view) {
  onPaperViewActivated(view); // 모의투자 · LEAN 백테스트 (js/paper.js)
  onRebalanceViewActivated(view); // 리밸런싱 엔진 (js/rebalance.js)
  onTradingViewViewActivated(view); // TradingView 연동 (js/tradingview.js)
  onFormulaViewActivated(view); // 자유 산식 지표 (js/formula.js)
  onMyPageActivated(view);      // 내 계정 — 마이페이지 (js/mypage.js)
  onFinLearnViewActivated(view); // 금융 필수 지식 — 강의실 · 주제 화면 · 요약 화면의 강의 입구 (js/finlearn.js)
  onDataHubViewActivated(view);  // 데이터 관제 (js/datahub.js)
  onCalendarViewActivated(view); // 일정 · 「거시경제 지표」 오른쪽 다가오는 일정 카드 (js/calendar.js)
  if (view === "trading-chart") loadStockChart();
  if (view === "trading-portfolio") loadPortfolio();
  if (view === "trading-order") { loadOrderHistory(); loadBrokerStatus(); }
  if (view === "quant-dashboard") { loadQuantDashboard(); }
  if (view === "quant-auto") loadAutoTradeStatus();
  if (view === "settings") loadSettings();
  if (view === "notification-settings") loadNotificationSettings();
  if (view === "crawl-manual") loadCrawlList();
  if (view === "us-dashboard") loadUsDashboard();
  if (view === "us-chart") loadUsChart();
  if (view === "us-order") renderUsOrders();
  if (view === "us-portfolio") loadUsPortfolio();
  if (view === "company-dashboard") loadCompanyDashboard();
  if (view === "company-compare") loadCompanyCompare();
  if (view === "company-sector") loadCompanySector();
  if (view === "sysadmin-dashboard") loadSystemDashboard();
  if (view === "sysadmin-logs") loadAuditLog();
  // 로보 어드바이저 신규 뷰
  if (view === "robo-screening") loadRoboScreening();
  if (view === "robo-decision") loadRoboDecision();
  if (view === "robo-patterns") { if (!document.getElementById("pt-mtf").innerHTML) loadPatternAnalysis(); }
  // 투자 인디케이터 신규 뷰
  if (view === "indicator-custom") loadSavedIndicators();
  if (view === "indicator-backtest") loadIndicatorBacktest();
  if (view === "indicator-api") loadIndicatorApiSettings();
  // ML·딥러닝
  if (view === "macro-dashboard") loadMacroDashboard();
  if (view === "macro-industry") loadMacroIndustry();
  if (view === "invest-fundamental") { } // 버튼 클릭으로 실행
}


registerViewActivation(onViewActivated);
boot();
