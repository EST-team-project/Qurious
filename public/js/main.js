/* 엔트리: 부트스트랩, 뷰 활성화 디스패치
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, redirectToLogin, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";
import { loadMarketTicker, loadSyncStatus, navigate, registerViewActivation } from "/js/core.js";
import { loadCrawlList } from "/js/agent.js";
import { loadCompanyCompare, loadCompanyDashboard, loadCompanySector } from "/js/company.js";
import { loadIndicatorBacktest, loadSavedIndicators } from "/js/indicator.js";
import { resolveView } from "/js/viewalias.js";   // 옛 주소 → 합친 화면(성과 검증 = 전략 분석의 탭 2)
import { renderBaselineNotice } from "/js/baselinenotice.js";   // 전략 분석 · 성과 검증 — 탭 띠 + 기준 전략 카드 (2026-10-30 · ①-18)
import { loadMacroDashboard, loadMacroIndustry } from "/js/ml.js";
import { initPaperViews, onPaperViewActivated } from "/js/paper.js";
import { loadAutoTradeStatus, loadQuantDashboard } from "/js/quant.js";
import { initRebalanceView, onRebalanceViewActivated } from "/js/rebalance.js";
import { initRoboRiskProfile, loadPatternAnalysis, loadRoboDecision, loadRoboTestbed, loadRoboScreening, loadRoboPerformanceMetrics } from "/js/robo.js";
import { loadNotificationSettings } from "/js/settings.js";
import { loadAuditLog, loadSystemDashboard } from "/js/sysadmin.js";
import { loadBrokerStatus, loadOrderHistory, loadPortfolio, loadStockChart } from "/js/trading.js";
import { initTradingViewView, onTradingViewViewActivated } from "/js/tradingview.js";
import { initFormulaView, onFormulaViewActivated } from "/js/formula.js";
import { loadUsChart, loadUsDashboard, loadUsPortfolio, renderUsOrders } from "/js/us.js";
import { initCompletionIndicator } from "/js/completion.js";
import { onMyPageActivated } from "/js/mypage.js";
import { onFinLearnViewActivated } from "/js/finlearn.js";
import { onConceptLearnViewActivated } from "/js/conceptlearn.js";   // 개념 학습 — 앱 안 목차 · 장 읽기(2026-10-19) · #learn/<장> 주소를 먼저 받는다
import { onHelpVideosViewActivated } from "/js/helpvideos.js";         // 개념 학습 › 사용법 영상 — 영상 목록 · 차례(2026-10-20 · D132)
import { initDataBadge, onDataHubViewActivated } from "/js/datahub.js";   // 데이터 관제 · 위 메뉴 표시 (2026-10-02)
import { onCalendarViewActivated } from "/js/calendar.js";             // 일정 · 다가오는 일정 카드 (2026-10-02)
import { onResearchViewActivated } from "/js/research.js";             // 투자 정보 리서치 — 수집 자료 검색 · 종목 시간표 (2026-10-06)
import { onCollectViewActivated } from "/js/collect.js";               // 데이터 수집 화면 셋 — 옛 크롤링 세 화면 자리 (2026-10-08)
import { onDataGuideViewActivated } from "/js/dataguide.js";           // 자료 안내 — 데이터 관제 바로 아래 · 모든 로그인 사용자 (2026-10-08)
import { onProductsViewActivated } from "/js/products.js";             // 투자 성향별 상품 안내 — 옛 「맞춤 상품 추천」 자리 (2026-10-12)
import { onRiskViewActivated } from "/js/riskcb.js";                   // 재무 · 신용 위험 — 옛 「신용 리스크 분석」 자리 (2026-10-13)
import { onClusterViewActivated } from "/js/clusters.js";              // 종목 군집화 — 옛 강사님 KMeans 칸 자리 (2026-10-14)
import { onSeasonalViewActivated } from "/js/seasonal.js";            // 계절성 분석 — 옛 강사님 계절성 칸 자리 (2026-10-14)
import { onModelCompareViewActivated } from "/js/mlcompare.js";      // 모델 비교 — 옛 강사님 5-Fold 칸 자리 (2026-10-15)
import { openStockSearch } from "/js/company.js";
import { mountStockFind } from "/js/stockfind.js";                      // 종목 입력칸 옆 「찾기」 단추 (2026-10-31)
import { initGnbMore } from "/js/gnbmore.js";                         // 아바타 메뉴 · 동기화 점 글 (2026-10-14 · DF-109 · 2026-10-18 D129 로 더보기 없앰)

import { loadDashboard } from "/js/dashboard.js";

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
  initRoboRiskProfile(user.clientId);
  document.getElementById("user-name").textContent = user.name;
  const avatar = document.getElementById("user-avatar");
  if (avatar) avatar.textContent = (user.name || "U").charAt(0).toUpperCase();
  // 아바타 메뉴(이름 · 내 정보 · 로그아웃) · 동기화 점 글 — DF-109 · 2026-10-18 D129 로 「더보기」 는 없앰(js/gnbmore.js)
  initGnbMore();
  mountStockFind(document, openStockSearch);
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
    navigate(hash && document.querySelector(`[data-view="${resolveView(hash)}"]`) ? hash : "dashboard");
  } catch (err) {
    console.error(err);
    setToast(`화면을 준비하다 오류가 났습니다: ${err.message}`, "error");
  }
}

document.getElementById("logout-btn").addEventListener("click", async () => {
  initRoboRiskProfile(null);
  await api("/api/auth/logout", { method: "POST" }).catch(() => { });
  // replace — 로그아웃 뒤 뒤로가기로 앱 화면 기록이 다시 뜨지 않게
  location.replace("/login.html");
});

// ── View Activation ───────────────────────────────────────────────
function onViewActivated(view, tab = view) {   // view = 화면 키 · tab = 탭 키(합친 화면의 별칭 · 아니면 같다)
  if (view === "dashboard") loadDashboard();
  onPaperViewActivated(view); // 모의투자 · LEAN 백테스트 (js/paper.js)
  onRebalanceViewActivated(view); // 리밸런싱 엔진 (js/rebalance.js)
  onTradingViewViewActivated(view); // TradingView 연동 (js/tradingview.js)
  onFormulaViewActivated(view); // 자유 산식 지표 (js/formula.js)
  onMyPageActivated(view);      // 내 계정 — 마이페이지 (js/mypage.js)
  onFinLearnViewActivated(view); // 금융 필수 지식 — 강의실 · 주제 화면 · 요약 화면의 강의 입구 (js/finlearn.js)
  onConceptLearnViewActivated(view); // 개념 학습 — 전체 목차 · 장 읽기 (js/conceptlearn.js)
  onHelpVideosViewActivated(view);   // 개념 학습 › 사용법 영상 — 표는 한 번 받고 메뉴 줄을 보이거나 숨김 (js/helpvideos.js)
  onDataHubViewActivated(view);  // 데이터 관제 (js/datahub.js)
  onCalendarViewActivated(view); // 일정 · 「거시경제 지표」 오른쪽 다가오는 일정 카드 (js/calendar.js)
  onResearchViewActivated(view); // 투자 정보 리서치 (js/research.js)
  onCollectViewActivated(view);  // 수집 일정 · 단계 / 자료 직접 받기 / 적재 · 백업 (js/collect.js · 관리자)
  onDataGuideViewActivated(view); // 자료 안내 — 화면이 바뀌면 서랍을 닫는다 (js/dataguide.js)
  onProductsViewActivated(view);  // 투자 성향별 상품 안내 (js/products.js)
  onRiskViewActivated(view);      // 재무 · 신용 위험 (js/riskcb.js)
  onClusterViewActivated(view);   // 종목 군집화 (js/clusters.js)
  onSeasonalViewActivated(view);  // 계절성 분석 (js/seasonal.js)
  onModelCompareViewActivated(view); // 모델 비교 (js/mlcompare.js)
  if (view === "trading-chart") loadStockChart();
  if (view === "trading-portfolio") loadPortfolio();
  if (view === "trading-order") { loadOrderHistory(); loadBrokerStatus(); }
  if (view === "quant-dashboard") { loadQuantDashboard(); }
  if (view === "quant-auto") loadAutoTradeStatus();
  if (view === "notification-settings") loadNotificationSettings();
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
  if (view === "robo-testbed") loadRoboTestbed();
  if (view === "robo-patterns") { if (!document.getElementById("pt-mtf").innerHTML) loadPatternAnalysis(); }
  // 투자 인디케이터 신규 뷰
  if (view === "indicator-custom") loadSavedIndicators();
  if (view === "quant-backtest") { renderBaselineNotice(tab); if (tab === "indicator-backtest") loadIndicatorBacktest(); }   // 탭 칸 · 탭 띠 + 기준 전략 카드(js/baselinenotice.js) · 성과 검증 탭은 들어올 때 실행(옛 화면 #indicator-backtest)
  // ML·딥러닝
  if (view === "macro-dashboard") loadMacroDashboard();
  if (view === "macro-industry") loadMacroIndustry();
  if (view === "invest-fundamental") { } // 버튼 클릭으로 실행
}


registerViewActivation(onViewActivated);
boot();
