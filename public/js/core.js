/* 공통 셸: GNB/LNB 내비게이션, 용어 글로서리·툴팁·사용법 가이드, 비교 트레이, 시세 티커, 동기화 배지, 모달
 * app.html 인라인 스크립트에서 분리됨. 엔트리는 main.js */
import { api, getMe, setToast, escHtml, fmt, fmtPct, colorPct } from "/js/common.js";

// ── 한국식 금액 표기 · Y축 라벨 (이슈 #220) ────────────────────
// 1억 이상은 "억", 1만 이상은 "만", 그 외 원. 9천만 ~ 1.1억 구간은 원 단위로
// 정확히 보여줘 몇천 원 움직임도 눈금끼리 구분되게 한다.
export function formatKrw(amount, opts = {}) {
  const n = Number(amount);
  if (!isFinite(n)) return "-";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1e8) {
    if (opts.compact) return `${sign}${(abs / 1e8).toFixed(2)}억 원`;
    const eok = Math.floor(abs / 1e8);
    const man = Math.floor((abs % 1e8) / 1e4);
    let s = `${eok.toLocaleString('ko-KR')}억`;
    if (man > 0) s += ` ${man.toLocaleString('ko-KR')}만`;
    return `${sign}${s} 원`;
  }
  if (abs >= 1e4) {
    if (opts.compact) return `${sign}${Math.round(abs / 1e4).toLocaleString('ko-KR')}만 원`;  // ★ 추가
    const man = Math.floor(abs / 1e4);
    const won = Math.round(abs % 1e4);
    let s = `${man.toLocaleString('ko-KR')}만`;
    if (won > 0) s += ` ${won.toLocaleString('ko-KR')}`;
    return `${sign}${s} 원`;
  }
  return `${sign}${Math.round(abs).toLocaleString('ko-KR')}원`;
}

export function formatYAxisLabel(value) {
  const n = Number(value);
  if (!isFinite(n)) return "";
  const abs = Math.abs(n);
  // 9,000만 ~ 1억 1,000만 구간은 원 단위로 정확히 (눈금끼리 구분)
  if (abs >= 9e7 && abs < 1.1e8) return Math.round(n).toLocaleString('ko-KR');
  if (abs >= 1e8) return (n / 1e8).toFixed(2) + '억';
  if (abs >= 1e4) return Math.round(n / 1e4).toLocaleString('ko-KR') + '만';
  return Math.round(n).toLocaleString('ko-KR');
}

// paper.js · robo.js · dashboard.js 어디서든 window 로 접근 가능 (import 안 건드리게)
window.formatKrw = formatKrw;
window.formatYAxisLabel = formatYAxisLabel;

// ── Navigation ────────────────────────────────────────────────────
const GNB_MENUS = {
  agent: {
    label: "<i class='fa-solid fa-robot'></i> 로보 어드바이저",
    items: [
      { key: "dashboard", icon: "fa-solid fa-gauge-high", label: "통합 대시보드" },
      { key: "agent-chat",      icon: "fa-solid fa-comments",              label: "AI 투자 상담" },
      { key: "robo-portfolio",  icon: "fa-solid fa-chart-pie",             label: "자산배분·최적화" },
      { key: "robo-rebalance",  icon: "fa-solid fa-rotate",                label: "리밸런싱 엔진" },
      { key: "robo-screening",  icon: "fa-solid fa-magnifying-glass-chart",label: "패턴 인식·종목 스크리닝" },
      { key: "robo-patterns",   icon: "fa-solid fa-chart-column",          label: "차트 패턴·지지/저항·멀티타임프레임" },
      { key: "robo-decision",   icon: "fa-solid fa-brain",                 label: "모의 투자 의사결정" },
      { key: "robo-testbed",    icon: "fa-solid fa-clipboard-check",       label: "코스콤 테스트베드 기준" },
      { key: "agent-cb",        icon: "fa-solid fa-chart-bar",             label: "재무 · 신용 위험" },
      { key: "agent-products",  icon: "fa-solid fa-coins",                 label: "투자 성향별 상품 안내" },
      { key: "agent-news",      icon: "fa-solid fa-newspaper",             label: "투자 정보 리서치" },
    ],
  },
  // 데이터(옛 「크롤링」 · 2026-10-02 화면 결정 ①) — 맨 위에 데이터 관제(js/datahub.js). 아래 셋은 데이터 수집 화면
  // (2026-10-08 · js/collect.js · 화면 키는 옛 크롤링 그대로) — 관리자에게만 보인다(css/collect.css 의 body.q-admin).
  crawl: {
    label: "<i class='fa-solid fa-database'></i> 데이터",
    items: [
      { key: "data-status",   icon: "fa-solid fa-gauge-high",      label: "데이터 관제" },
      { key: "data-guide",    icon: "fa-solid fa-compass",         label: "자료 안내" },   // 모든 로그인 사용자 · js/dataguide.js (2026-10-08)
      { key: "crawl-auto",    icon: "fa-solid fa-list-check",      label: "수집 일정 · 단계" },
      { key: "crawl-manual",  icon: "fa-solid fa-download",        label: "자료 직접 받기" },
      { key: "crawl-ingest",  icon: "fa-solid fa-cloud-arrow-up",  label: "적재 · 백업" },
    ],
  },
  trading: {
    label: "<i class='fa-solid fa-chart-line'></i> 직접매매",
    items: [
      { key: "trading-chart",     icon: "fa-solid fa-chart-candlestick", label: "주가 차트" },
      { key: "trading-portfolio", icon: "fa-solid fa-briefcase",         label: "포트폴리오" },
      { key: "trading-order",     icon: "fa-solid fa-arrows-rotate",     label: "주문/매매" },
    ],
  },
  paper: {
    label: "<i class='fa-solid fa-graduation-cap'></i> 모의투자",
    items: [
      { key: "paper-dashboard",   icon: "fa-solid fa-wallet",          label: "모의계좌 현황" },
      { key: "paper-stock",       icon: "fa-solid fa-building-columns",label: "국내주식 모의주문" },
      { key: "paper-crypto",      icon: "fa-brands fa-bitcoin",        label: "코인 모의매매" },
      { key: "paper-alternative", icon: "fa-solid fa-cubes",           label: "대체자산 (선물·옵션·금·부동산)" },
      { key: "paper-openapi",     icon: "fa-solid fa-key",             label: "Open API · 외부 연동" },
    ],
  },
  quant: {
    label: "<i class='fa-solid fa-bolt'></i> 퀀트자동매매",
    items: [
      { key: "quant-dashboard", icon: "fa-solid fa-gauge-high",      label: "퀀트 대시보드" },
      { key: "quant-auto",      icon: "fa-solid fa-robot",           label: "자동매매 현황" },
      { key: "quant-backtest",  icon: "fa-solid fa-flask",           label: "전략 분석" },
      { key: "quant-lean",      icon: "fa-brands fa-docker",         label: "LEAN 백테스트 (QuantConnect)" },
      { key: "settings",        icon: "fa-solid fa-sliders",         label: "증권사 API 설정" },
      { key: "notification-settings", icon: "fa-solid fa-bell",      label: "알림 설정" },
    ],
  },
  us: {
    label: "<i class='fa-solid fa-flag-usa'></i> 미국주식",
    items: [
      { key: "us-dashboard",  icon: "fa-solid fa-gauge",            label: "대시보드" },
      { key: "us-chart",      icon: "fa-solid fa-chart-area",       label: "주가 차트" },
      { key: "us-order",      icon: "fa-solid fa-arrow-right-arrow-left", label: "주문/매매" },
      { key: "us-portfolio",  icon: "fa-solid fa-wallet",           label: "포트폴리오" },
    ],
  },
  company: {
    label: "<i class='fa-solid fa-chart-pie'></i> 투자 인디케이터",
    items: [
      { key: "indicator-strategy",  icon: "fa-solid fa-chart-line",     label: "기본 인디케이터 전략" },
      { key: "indicator-custom",    icon: "fa-solid fa-code",           label: "커스텀 인디케이터 개발" },
      { key: "indicator-formula",   icon: "fa-solid fa-square-root-variable", label: "자유 산식 지표 (DSL·버전)" },
      { key: "indicator-backtest",  icon: "fa-solid fa-flask",          label: "성과 검증 (Python)" },
      { key: "indicator-api",       icon: "fa-solid fa-plug",           label: "증권사 API 자동화" },
      { key: "indicator-tradingview", icon: "fa-solid fa-satellite-dish", label: "TradingView 연동 (Webhook·교차검증)" },
      { key: "company-dashboard",   icon: "fa-solid fa-gauge",          label: "지표 대시보드" },
      { key: "company-compare",     icon: "fa-solid fa-table-columns",  label: "지표 비교 분석" },
      { key: "company-sector",      icon: "fa-solid fa-layer-group",    label: "섹터 인디케이터" },
    ],
  },
  ml: {
    label: "<i class='fa-solid fa-microchip'></i> ML·딥러닝",
    items: [
      { key: "ml-compare",     icon: "fa-solid fa-scale-balanced",  label: "모델 비교" },
      { key: "ml-regression",  icon: "fa-solid fa-chart-line",      label: "회귀 분석" },
      { key: "ml-cluster",     icon: "fa-solid fa-circle-nodes",    label: "종목 군집화" },
      { key: "ml-tune",        icon: "fa-solid fa-sliders",         label: "하이퍼파라미터 튜닝" },
      { key: "ml-deeplearning",icon: "fa-solid fa-brain-circuit",   label: "딥러닝 (LSTM·Transformer)" },
    ],
  },
  invest: {
    label: "<i class='fa-solid fa-magnifying-glass-dollar'></i> 투자분석 기초",
    items: [
      { key: "macro-dashboard",   icon: "fa-solid fa-globe",           label: "거시경제 지표" },
      { key: "macro-industry",    icon: "fa-solid fa-industry",        label: "산업 분석" },
      { key: "invest-fundamental",icon: "fa-solid fa-file-invoice-dollar", label: "재무제표 분석" },
      { key: "invest-technical",  icon: "fa-solid fa-chart-candlestick",  label: "기술적 분석" },
      // 일정 (2026-10-02 화면 결정 ②) — 월 달력 + 다가오는 일정 · 좁은 화면은 목록(js/calendar.js)
      { key: "market-calendar",   icon: "fa-solid fa-calendar-days",   label: "일정" },
    ],
  },
  // 학습 (2026-10-20 안 A · 사용자 「개념 학습과 금융 필수 지식을 위에 학습이라고 되어 있는 목차 하나로 통합」) — 학습 홈 아래에
  // 네 갈래: 금융 필수 지식(강의실 + 주제 아홉 · 요약 셋 · 용어사전 — js/finlearn.js) · 개발 개념 · 파이썬 중급 · 특강(js/conceptlearn.js).
  // 전에는 「금융 필수 지식」 · 「개념 학습」 두 묶음이 따로 있어 목차의 금융 장과 강의실이 겹쳐 헷갈렸다. 묶음 키는 위 탭 단추와 같은
  // finance 그대로 · heading 은 클릭되지 않는 소제목, sub 는 강의실 아래 들여쓴 주제다(lnbItem). 장은 메뉴에 하나하나 두지 않고
  // 갈래 목차가 고른다(장 한 편 · 부 목차는 메뉴 줄 없이 — VIEW_PARENT) · /learn/ 은 관리자의 팀 자료 받기 · 원문 확인용으로 남는다.
  finance: {
    label: "<i class='fa-solid fa-book-open'></i> 학습",
    items: [
      { key: "learn-home", icon: "fa-solid fa-house", label: "학습 홈" },
      { heading: "금융 필수 지식" },
      { key: "fin-lectures",         icon: "fa-solid fa-chalkboard-user",  label: "강의실 (전체 과정)" },
      { key: "fin-topic-futures",    icon: "fa-solid fa-scale-unbalanced", label: "선물과 옵션", sub: true },
      { key: "fin-topic-funds",      icon: "fa-solid fa-basket-shopping",  label: "펀드와 ETF", sub: true },
      { key: "fin-topic-bonds",      icon: "fa-solid fa-landmark",         label: "채권 · 금리 · 코인", sub: true },
      { key: "fin-topic-allocation", icon: "fa-solid fa-chart-pie",        label: "자산배분과 퀀트", sub: true },
      { key: "fin-topic-company",    icon: "fa-solid fa-building",         label: "회사 구조 · 세무회계", sub: true },
      { key: "fin-topic-stocks",     icon: "fa-solid fa-chart-simple",     label: "산업 분석과 공시", sub: true },
      { key: "fin-topic-technical",  icon: "fa-solid fa-chart-line",       label: "기술적 분석 · 재무제표", sub: true },
      { key: "fin-topic-industry",   icon: "fa-solid fa-industry",         label: "퀀트 사례 · 배당 · ETF", sub: true },
      { key: "fin-topic-macro",      icon: "fa-solid fa-globe",            label: "거시경제와 시장", sub: true },
      { key: "fin-products",   icon: "fa-solid fa-layer-group",   label: "금융상품 이해" },
      { key: "fin-allocation", icon: "fa-solid fa-pie-chart",     label: "자산배분 모델" },
      { key: "quant-seasonal", icon: "fa-solid fa-calendar-days", label: "계절성 분석" },
      // 용어사전 (2026-10-02 화면 설계 결정 ① — 찾기 첫 화면 → 용어 한 장 · js/glossary.js)
      { key: "fin-glossary",   icon: "fa-solid fa-book",          label: "용어사전" },
      { heading: "개념 학습" },
      { key: "learn-dev",     icon: "fa-solid fa-microchip",          label: "개발 개념" },
      { key: "learn-python",  icon: "fa-solid fa-code",               label: "파이썬 중급" },
      { key: "learn-special", icon: "fa-solid fa-person-chalkboard",  label: "특강" },   // 장 한 편 · 부 목차는 메뉴 줄 없이(VIEW_PARENT)
      { heading: "도움" },
      { key: "learn-videos",  icon: "fa-solid fa-circle-play",        label: "사용법 영상" },   // 2026-10-20 D132 — 영상이 없는 PC 에서는 숨김(helpvideos.css)
    ],
  },
  sysadmin: {
    label: "<i class='fa-solid fa-gear'></i> 시스템관리",
    items: [
      { key: "sysadmin-dashboard", icon: "fa-solid fa-server",      label: "서버 대시보드" },
      { key: "sysadmin-logs",      icon: "fa-solid fa-scroll",      label: "감사 로그" },
      // API 문서(2026-10-06) — 별도 HTML(public/api-docs/) · OpenAPI 명세를 앱 디자인으로 + Swagger UI 시험 호출
      { key: "sysadmin-api",       icon: "fa-solid fa-plug",        label: "API 문서",   href: "/api-docs/" },
    ],
  },
  // 내 계정 (2026-09-30) — 왼쪽 「전체 메뉴」 트리 맨 아래 · 머리글 아바타 ▾ 메뉴에서도 온다(js/gnbmore.js · js/mypage.js)
  account: {
    label: "<i class='fa-solid fa-user-gear'></i> 내 계정",
    items: [
      { key: "mypage", icon: "fa-solid fa-id-card", label: "내 정보 (마이페이지)" },
    ],
  },
};

// ── 용어 글로서리 (용어 설명 모달에서 사용) ──────────────────────────
const TERMS = {
  shap:             { title: "SHAP 기여도 (XAI)", body: "각 입력 지표(RSI, MACD, 이동평균 비율 등)가 모델의 최종 판단을 얼마나 밀어 올렸는지(+) 또는 끌어내렸는지(−)를 게임이론의 Shapley 값으로 공정하게 배분한 설명 기법입니다. 이 앱은 LightGBM의 TreeSHAP(pred_contrib)을 사용해 매수·관망·매도 판단의 근거를 사람이 읽을 수 있는 문장으로 풀어 보여줍니다." },
  confidence:       { title: "신호 신뢰도", body: "여러 타임프레임(분봉·일봉·주봉)이 같은 방향을 가리키는 정도(일치도)와 종합 점수의 크기를 절반씩 섞어 0~100으로 표시합니다. 확률이 아니라 신호의 강도·일관성을 나타내는 상대 지표입니다." },
  rebalancing:      { title: "리밸런싱", body: "시간이 지나며 가격 변동으로 흐트러진 자산 비중을 처음 정한 목표 비중으로 되돌리는 작업입니다. 오른 자산을 일부 팔고 내린 자산을 사게 되어 자연스럽게 '고점 매도·저점 매수'가 이뤄집니다. 주기(시간), 허용 이탈률, 입출금·배당 발생을 기준으로 실행합니다." },
  drift:            { title: "이탈률 (Drift)", body: "현재 비중과 목표 비중의 차이(%p)입니다. 예: 목표 30%인 종목이 36%가 되면 이탈 +6%p. 허용 이탈률(예: 5%p)을 넘으면 리밸런싱을 실행합니다." },
  rsi:              { title: "RSI (상대강도지수)", body: "일정 기간의 상승폭·하락폭 평균을 비교해 0~100 사이 값으로 나타내는 모멘텀 지표입니다. 통상 70 이상이면 과매수, 30 이하면 과매도로 해석합니다." },
  ma:               { title: "이동평균선 (MA)", body: "최근 N일 종가의 평균을 이어 그린 선입니다. 단기선(MA5)이 장기선(MA20) 위로 뚫고 올라가면 골든크로스(매수 신호), 아래로 내려가면 데드크로스(매도 신호)로 봅니다." },
  macd:             { title: "MACD", body: "단기(12일)·장기(26일) 지수이동평균의 차이(MACD선)와 그 신호선(9일 EMA)의 교차로 추세 전환을 포착하는 지표입니다. MACD가 신호선을 상향 돌파하면 매수 신호로 해석합니다." },
  bollinger:        { title: "볼린저밴드", body: "20일 이동평균을 중심으로 표준편차의 ±2배 범위를 그린 밴드입니다. 가격이 하단 밴드에 닿으면 과매도, 상단 밴드에 닿으면 과매수 구간으로 봅니다." },
  atr:              { title: "ATR (평균진폭)", body: "일정 기간 동안의 고가-저가 변동폭 평균으로, 변동성의 크기를 나타내는 지표입니다. 값이 클수록 가격 변동이 큰 종목입니다." },
  sharpe:           { title: "샤프지수", body: "전략 수익률을 수익률 변동성으로 나눈 뒤 연환산한, 위험 대비 수익을 나타내는 대표 성과지표입니다. 값이 높을수록 같은 위험에서 더 많은 수익을 낸 것입니다." },
  mdd:              { title: "MDD (최대낙폭)", body: "전략 운용 기간 중 고점 대비 최대로 떨어진 비율입니다. 손실을 얼마나 견뎌야 하는지 보여주는 리스크 지표로, 절댓값이 작을수록 안전합니다." },
  win_rate:         { title: "승률", body: "보유 기간(또는 거래) 중 수익이 난 비율입니다. 승률이 높아도 손익비가 나쁘면 전체 수익은 마이너스일 수 있습니다." },
  cost_bps:         { title: "매매비용 (bps)", body: "1bp = 0.01%. 국내주식 비용은 매수와 매도가 대칭이 아닙니다 — 위탁수수료(0.0140527%)와 유관기관 제비용(0.0036396%)은 양쪽에 붙지만, 증권거래세+농어촌특별세는 매도에만 붙고 세율이 해마다 바뀝니다(2024년 0.18% · 2025년 0.15% · 2026년 0.20%). 실전에서는 반드시 차감해야 현실적인 수익률이 나옵니다." },
  slippage:         { title: "슬리피지", body: "주문을 낸 가격과 실제 체결된 가격의 차이입니다. 호가 데이터가 없으면 직접 측정할 수 없어 가정값(편도 10bp)을 씁니다. 실증 추정치는 대형주 약 11bp · 소형주 약 21bp로, 소형주는 이 화면 값보다 비용이 더 큽니다." },
  lightgbm:         { title: "LightGBM", body: "여러 개의 약한 결정트리를 순차적으로 결합하는 그래디언트 부스팅 알고리즘입니다. 이 앱에서는 며칠 뒤 방향성(매수/관망/매도)을 3-class로 분류하는 데 사용합니다." },
  mlp:              { title: "MLP (다층 퍼셉트론)", body: "입력층-은닉층(64→32)-출력층으로 구성된 기본적인 신경망 구조입니다. scikit-learn의 MLPClassifier로 경량 딥러닝을 구현했습니다." },
  kmeans:           { title: "KMeans 군집화", body: "유사한 특징(수익률·변동성 패턴)을 가진 종목끼리 K개의 그룹으로 자동 분류하는 비지도학습 알고리즘입니다." },
  gridsearch:       { title: "GridSearchCV", body: "지정한 하이퍼파라미터 조합을 모두 교차검증으로 시험해 가장 성능이 좋은 조합을 자동으로 찾는 튜닝 기법입니다." },
  cross_validation: { title: "교차검증 (K-Fold)", body: "데이터를 K개로 나눠 K-1개로 학습하고 나머지 1개로 검증하는 과정을 K번 반복해, 모델 성능을 더 신뢰성 있게 추정하는 방법입니다." },
  dbscan:           { title: "DBSCAN", body: "밀도가 높은 지역을 하나의 군집으로 묶고, 어디에도 속하지 않는 점은 이상치(outlier)로 분류하는 군집화 알고리즘입니다. 군집 개수를 미리 정하지 않아도 됩니다." },
  stacking:         { title: "스태킹 앙상블", body: "여러 개별 모델(SVM, RF, GB 등)의 예측 결과를 다시 입력값으로 삼아 최종 메타모델이 종합 판단하게 하는 앙상블 기법입니다." },
  regression:       { title: "회귀분석", body: "과거 데이터를 기반으로 연속적인 수치(예: 향후 5일 수익률)를 예측하는 통계 기법입니다. 선형회귀가 가장 기본형입니다." },
  ridge_lasso:      { title: "Ridge / Lasso", body: "일반 선형회귀에 가중치 크기를 제한하는 규제(penalty)를 추가한 모델입니다. 과적합을 줄이고 변수가 많을 때도 안정적으로 작동합니다." },
  seasonality:      { title: "계절성 효과", body: "특정 월(연말 랠리), 요일, 분기 등 시기에 따라 반복적으로 나타나는 수익률 패턴입니다. 통계적 경향일 뿐 항상 재현되지는 않습니다." },
  covariance_opt:   { title: "공분산 최적화", body: "종목 간 수익률의 공분산(함께 움직이는 정도)을 계산해, 분산투자 효과가 가장 큰 포트폴리오 비중을 찾는 방법입니다." },
  black_litterman:  { title: "블랙-리터만 모델", body: "시장 균형 수익률에 투자자의 주관적 전망(view)을 결합해 더 안정적인 자산배분 비중을 산출하는 모델입니다." },
  risk_parity:      { title: "리스크 패리티", body: "각 자산의 '금액 비중'이 아니라 '위험 기여도'가 똑같아지도록 배분하는 자산배분 방식입니다." },
  mvo:              { title: "평균-분산 최적화 (MVO)", body: "마코위츠의 포트폴리오 이론입니다. 기대수익률과 분산(위험)을 동시에 고려해 동일 위험에서 최대 수익을 내는 효율적 포트폴리오를 찾습니다." },
  dcf:              { title: "DCF (현금흐름할인법)", body: "기업이 미래에 벌어들일 현금흐름을 적정 할인율로 현재가치화해 내재가치를 추정하는 절대가치평가 방법입니다." },
  eva:              { title: "EVA (경제적 부가가치)", body: "세후 영업이익에서 투하자본에 대한 자본비용을 차감한 값으로, 자본비용을 넘어서는 '진짜' 이익을 측정합니다." },
  fcf:              { title: "FCF (잉여현금흐름)", body: "영업활동으로 벌어들인 현금에서 설비투자 등 필수 지출을 뺀, 기업이 자유롭게 쓸 수 있는 현금입니다. 배당·자사주매입 여력을 가늠하는 지표입니다." },
  pine_script:      { title: "PineScript", body: "트레이딩뷰(TradingView) 플랫폼에서 커스텀 지표·전략을 코딩할 때 쓰는 전용 스크립트 언어입니다. '커스텀 인디케이터' 화면에서 파라미터를 조정하면 대응하는 코드를 자동 생성해줍니다." },
  alpaca:           { title: "Alpaca API", body: "미국 주식 모의투자(Paper Trading)를 REST API로 실행할 수 있는 브로커 서비스입니다. 실제 자금 없이 실전과 동일한 주문 구조를 검증할 수 있습니다." },
  paper_trading:    { title: "모의투자 (Paper Trading)", body: "실제 자금을 쓰지 않고 가상의 잔고로 매매를 체결해보는 것입니다. 전략을 실전에 투입하기 전 위험 없이 검증하는 단계입니다." },
  broker_api:       { title: "증권사 Open API", body: "증권사가 제공하는 REST/OCX 인터페이스로, 앱이 사용자의 계좌 시세 조회·잔고 확인·주문 체결을 자동으로 수행할 수 있게 해줍니다. 앱키·시크릿키 발급이 필요합니다." },
  rag:              { title: "RAG (검색 증강 생성)", body: "LLM이 답변하기 전에 벡터DB에서 관련 문서를 검색해 그 내용을 근거로 답변을 생성하는 방식입니다. 최신 정보·사내 문서 기반 답변의 정확도를 높입니다." },
  embedding:        { title: "임베딩", body: "텍스트를 의미가 비슷할수록 가까운 위치에 놓이는 숫자 벡터로 변환하는 과정입니다. 이 앱은 nomic-embed-text 모델로 768차원 벡터를 만듭니다." },
  qdrant:           { title: "Qdrant (벡터DB)", body: "임베딩 벡터를 저장하고 유사도 기반으로 빠르게 검색하는 전용 데이터베이스입니다. 크롤링한 문서를 저장해 AI 상담이 참고하게 합니다." },
  cb_score:         { title: "신용정보(CB) 통계", body: "개인·기업의 신용등급, 연체율 등을 집계한 통계로, 투자 리스크를 가늠하는 참고 지표로 활용합니다." },
  debt_ratio:       { title: "부채비율", body: "부채총계를 자본총계로 나눈 값(%)입니다. 업종마다 보통 수준이 달라 같은 업종의 회사끼리 견줘야 뜻이 있습니다." },
  current_ratio:    { title: "유동비율", body: "1년 안에 돈이 되는 자산(유동자산)을 1년 안에 갚을 빚(유동부채)으로 나눈 값(%)입니다. 100% 아래면 빚이 더 많습니다." },
  equity_ratio:     { title: "자기자본비율", body: "자본총계를 자산총계로 나눈 값(%)입니다. 자산 가운데 빚이 아닌 몫이 얼마인지 봅니다 — 7% 면 자산 100원 가운데 7원이 빚이 아닌 몫입니다." },
  credit_spread:    { title: "신용 스프레드", body: "같은 날 회사채 금리와 국고채 금리의 차이입니다. 벌어지면 돈을 빌려주는 쪽이 회사에 더 많은 이자를 요구한다는 뜻입니다." },
  golden_cross:     { title: "골든크로스", body: "단기 이동평균선이 장기 이동평균선을 아래에서 위로 돌파하는 순간입니다. 추세 전환(상승) 신호로 해석됩니다." },
  dead_cross:       { title: "데드크로스", body: "단기 이동평균선이 장기 이동평균선을 위에서 아래로 돌파하는 순간입니다. 추세 전환(하락) 신호로 해석됩니다." },
  signal:           { title: "매매 시그널", body: "지표·모델 계산 결과를 매수(BUY)/관망(HOLD)/매도(SELL) 중 하나로 요약한 최종 판단입니다." },
  backtest:         { title: "백테스트", body: "과거 시세 데이터에 전략 규칙을 그대로 적용해봤을 때 어떤 성과가 났을지 검증하는 과정입니다. 미래 수익을 보장하지 않으며, 과거 데이터에만 맞춰진 과적합에 유의해야 합니다." },
  virtual_account:  { title: "모의계좌", body: "실제 증권 계좌와 분리된, 앱 내부(MongoDB)에만 존재하는 가상의 잔고입니다. 자동매매 로직을 실 자금 없이 검증할 때 사용합니다." },
  auto_trade_cycle: { title: "자동매매 사이클", body: "정해진 주기(기본 10분)마다 지표를 다시 계산하고, 시그널에 따라 자동으로 매수/매도를 실행하는 반복 루프입니다." },
  notification_channel: { title: "알림 채널", body: "매매 체결·오류 등 이벤트가 발생했을 때 사용자에게 알려주는 통로(텔레그램/슬랙/이메일/카카오/SMS)입니다. 채널별로 토큰·API키를 등록해야 발송됩니다." },
  audit_log:        { title: "감사 로그", body: "누가 언제 어떤 주문·설정 변경을 했는지 기록해두는 이력입니다. 문제 발생 시 원인을 추적하는 데 사용합니다." },
  vix:              { title: "VIX (변동성 지수)", body: "S&P500 옵션 가격으로 산출하는 '공포 지수'입니다. 값이 높을수록 시장이 앞으로 크게 흔들릴 것이라는 불안 심리가 큰 상태입니다." },
  dxy:              { title: "달러 인덱스 (DXY)", body: "유로·엔 등 주요 6개 통화 대비 미 달러의 상대적 가치를 나타내는 지수입니다. 상승하면 달러 강세이며 신흥국·원자재에는 통상 부담 요인입니다." },
  sector_etf:       { title: "섹터 ETF", body: "특정 산업군(반도체, 금융, 에너지 등) 종목들을 묶어 하나의 상품으로 만든 상장지수펀드입니다. 산업 전체의 흐름을 한 번에 보여줍니다." },
  macro_indicator:  { title: "거시경제 지표", body: "금리·물가·유가·환율 등 한 나라 경제 전체의 상태를 보여주는 통계입니다. 개별 종목보다 시장 전체 방향에 영향을 줍니다." },
  custom_indicator: { title: "커스텀 인디케이터", body: "RSI·이동평균 등 기본 지표를 사용자가 원하는 방식(기간, 임계값, 조합)으로 재조합해 만든 나만의 매매 규칙입니다." },
  position_sizing:  { title: "포지션 사이징", body: "신호가 났을 때 자산 중 얼마를 그 거래에 투입할지 정하는 방법입니다. 같은 전략이라도 사이징에 따라 리스크·수익이 크게 달라집니다." },
  drawdown:         { title: "드로우다운", body: "특정 시점부터 현재까지 고점 대비 얼마나 하락했는지를 나타내는 값입니다. MDD는 이 드로우다운의 역사적 최댓값입니다." },
  broker_catalog:   { title: "증권사 카탈로그", body: "앱이 지원하는 증권사 목록과 각 사의 연동 상태(실연동 가능/준비중)를 보여주는 정보입니다." },
};

// ── 화면별 사용법 가이드 (43개 view 전체) ────────────────────────────
const VIEW_GUIDES = {
  // 투자 대시보드(2026-10-03 · 강사님 기초 코드 9478811 의 첫 화면 — 강사님 판에는 안내가 없다)
  "dashboard":       { summary: "로보 어드바이저와 투자 인디케이터의 상태와 바로가기를 한 화면에서 봅니다.", steps: ["KIS 모의투자를 쓰려면 먼저 「증권사 API 설정」 에 내 모의투자 키를 넣으세요. 키가 있으면 「KIS 모의투자 시작」 이 열립니다.", "「투자 사이트별 현재 투자액」 의 탭을 누르면 계좌마다 투자액 · 현금 · 총자산을 봅니다.", "「기본 전략 성능」 은 과거 백테스트이며 내 계좌의 실제 수익과 다릅니다. 매매가 없던 기간은 수익률을 매기지 않습니다."], relatedTerms: ["mdd", "sharpe"] },
  "agent-chat":     { summary: "금융 지식·데이터를 학습한 AI 로보 어드바이저에게 자유롭게 투자 관련 질문을 합니다.", steps: ["궁금한 내용을 채팅창에 입력 후 전송 버튼(또는 Enter)을 누르세요.", "신용점수, 금융상품, 퀀트 전략 등 여러 주제를 한 대화에서 섞어 물어봐도 됩니다.", "AI 답변은 참고용이며, 실제 투자 결정 전 반드시 스스로 데이터를 검증하세요."], relatedTerms: ["rag", "cb_score"] },
  "robo-portfolio":  { summary: "성향·투자기간 규칙으로 자산군 비중을 계산하고, 지표·모델 분석으로 국내주식 후보와 종목 비중을 산출합니다.", steps: ["위험 성향(안정/중립/공격)과 투자 기간, 투자금액을 선택하세요.", "'배분 계산' 버튼을 누르면 자산군별 비중과 분석 대상 종목이 표시됩니다.", "기대수익률·MDD는 과거 데이터 기반 추정치이며 미래 수익을 보장하지 않습니다."], relatedTerms: ["covariance_opt", "mvo", "risk_parity", "mdd", "sharpe"] },
  "robo-screening":  { summary: "패턴 인식 모델로 대표 종목들을 매수/매도/관망으로 스크리닝합니다.", steps: ["모델(RSI/이동평균/볼린저/앙상블)과 신호 필터, 최소 신뢰도를 선택하세요.", "결과 카드에서 종목별 신호·점수·근거를 확인하세요.", "신뢰도가 높다고 100% 적중을 의미하지 않으니 다른 지표와 함께 판단하세요."], relatedTerms: ["signal", "lightgbm", "rsi", "golden_cross"] },
  "robo-decision":   { summary: "자동매매 로직이 만든 모의투자 의사결정 과정을 로그로 확인합니다.", steps: ["시작 버튼을 누르면 10분 주기로 모의계좌 매매가 진행됩니다.", "로그에서 매수/매도 이유와 계좌 평가금액 변화를 확인하세요.", "실제 자금이 아닌 가상계좌이므로 전략을 안전하게 검증할 수 있습니다."], relatedTerms: ["virtual_account", "auto_trade_cycle", "signal"] },
  "robo-testbed": {
    summary: "코스콤 로보어드바이저 테스트베드 기준에 맞춘 운용 성과 분석입니다.",
    steps: [
      "기준가 · 매매회전율 · 평균대비분석 · 위험지표를 한눈에 확인하세요.",
      "KOSPI200 대비 초과 성과와 위험조정 수익률을 비교합니다.",
      "표준편차·샤프·젠센알파·정보비율로 전략의 질을 평가합니다.",
    ],
    relatedTerms: ["sharpe", "mdd", "cost_bps", "slippage", "backtest"],
  },
  "agent-cb":        { summary: "상장사의 재무 건전성(전자공시 재무제표)과 시장 전체의 신용 위험(한국은행 시장금리)을 숫자 · 그림 · 쉬운 말로 봅니다.", steps: ["회사 이름이나 6자리 종목코드로 회사를 고르세요. 예시 회사를 눌러도 됩니다.", "「회사 재무 건전성」 탭은 점검 일곱을 먼저 보이고, 숫자를 누르면 흐름 그림이 바뀝니다.", "맨 위 「시장 신용」 띠는 회사채와 국고채의 금리 차이입니다 — 「그림 · 읽는 법」 으로 자세히 봅니다. 투자 권유가 아닙니다."], relatedTerms: ["debt_ratio", "current_ratio", "credit_spread"] },
  "agent-products":  { summary: "자산 배분 결과의 자산군마다 공시된 상품 정보(ETF · 예금 · 적금 · 연금저축)를 같은 기준으로 모아 봅니다 — 추천이 아니라 정해진 기준의 목록입니다.", steps: ["화면을 열면 「자산배분·최적화」 에서 저장한 배분(없으면 진단한 성향의 기본 비중)을 저절로 불러와 탭을 비중 큰 순으로 놓습니다 — 비중을 바꾸려면 그 화면에서 다시 계산하세요.", "자산군 탭을 고르면 거래소 유형 순서의 묶음마다 순자산 큰 순 다섯 줄이 보입니다 — 「n개 모두 보기」 로 전체 목록과 정렬을 엽니다.", "레버리지 · 인버스는 맨 끝 탭에 따로 모았습니다 — 실제로 사려면 필요한 사전교육 · 기본예탁금을 함께 보세요.", "현금성 탭 아래에서 예금 · 적금 · 연금저축을 금융감독원 공시로 그때그때 불러옵니다."], relatedTerms: ["mdd"] },
  "agent-news":      { summary: "전자공시 공시 · 정책뉴스 · 언론사 기사 제목을 낱말 · 종목 · 주제 · 기간으로 찾습니다(AI 가 답을 쓰지 않는 검색 화면).", steps: ["낱말(예: 반도체, 유상증자)을 넣고 검색하세요 — 낱말이 있으면 관련도순, 없으면 최신순입니다.", "왼쪽 거름 칸에서 종류 · 주제 · 기간을 고르면 종류마다 몇 건인지 함께 바뀝니다.", "종목을 고르면 그 종목의 공시 · 기사 · 일정이 날짜 한 줄(시간표)로 바뀝니다. 근거를 단 답은 「AI 투자 상담」 에서 물어보세요."], relatedTerms: [] },
  // 데이터 관제 · 일정 (2026-10-02) — js/datahub.js · js/calendar.js
  "data-status":     { summary: "모은 자료가 며칠 것까지 있는지, 매일 낮 12시 30분 갱신이 돌았는지 한 화면에서 봅니다.", steps: ["위의 카드 넷에서 판정 · 주식 시세 기준일 · 낮 갱신 · 팀 공유 저장소를 먼저 보세요.", "「자료별 기준일」 표에서 늦은 자료가 있는지 보세요 — 「정상」 은 하루 밀림(시세는 다음 날 낮에 들어옵니다)입니다.", "어느 화면에서든 위 메뉴의 「자료 MM-DD · 판정」 을 누르면 요약이 열립니다."], relatedTerms: [] },
  "market-calendar": { summary: "휴장 · 파생 만기 · 금통위 · FOMC · 보고서 기한 · 배당 · 주주총회 · 실적 발표를 한 달 달력으로 봅니다.", steps: ["‹ › 로 달을 옮기고, 위의 종류 단추로 보고 싶은 일정만 고르세요.", "칸에는 시장 전체 일정은 이름, 종목 일정은 종류별 개수(주총 731)가 보입니다 — 날짜나 숫자를 누르면 오른쪽에 그날 목록이 50건씩 열립니다(휴대폰은 서랍).", "그날 목록에서 회사 이름 · 종목 코드로 찾고, 줄을 누르면 날짜 · 어떻게 정했는지 · 풀이가 열립니다. 모의계좌에 가진 종목은 맨 위에 ★ 로 올립니다."], relatedTerms: [] },
  "data-guide":      { summary: "우리가 모으는 자료의 구성 · 모으는 길 · 읽을 자료를 한 화면에서 봅니다.", steps: ["위의 숫자 띠에서 자료 묶음 · 출처 · 모은 기간 · 매일 낮 수집 · 모은 줄을 먼저 보세요 — 칸을 누르면 그 절로 내려갑니다.", "「연도별로 얼마나 있나」 의 칸이나 「자료 목록」 의 줄을 누르면 오른쪽에 그 자료 한 장이 열립니다. 닫기 · Esc 로 닫습니다.", "「무엇을 읽나」 에서 하려는 일을 찾아 「어디서」 의 화면으로 가세요. 지금 자료가 며칠 것까지 있는지는 데이터 관제에서 봅니다."], relatedTerms: [] },
  // 데이터 수집 화면 셋 (2026-10-08) — js/collect.js · 관리자 화면
  "crawl-auto":      { summary: "매일 낮 12시 30분 수집 회차가 자료를 받고 · 계산하고 · 백업한 결과를 단계마다 봅니다(관리자).", steps: ["위의 카드 넷에서 마지막 회차 · 결과 · 자료 기준일 · 다음 회차를 먼저 보세요.", "회차 고르기에서 지난 회차를 고르면 그 회차의 단계 표로 바뀝니다 — 한 단계만 다시 돌린 기록은 따로 표시됩니다.", "한 단계만 다시 돌리려면 그 줄의 「이 단계만 다시」 를 눌러 나오는 명령을 이 PC 에서 돌리세요. 수집이 도는 동안(12:30 ~ 13:30)에는 막힙니다."], relatedTerms: [] },
  "crawl-manual":    { summary: "매일 수집이 빠뜨린 날이나 과거분을 메웁니다 — 받을 범위를 먼저 보고, 받는 명령을 이 PC 에서 돌립니다(관리자).", steps: ["자료 종류와 기간을 고르고 「받을 범위 보기」 를 누르세요 — 이미 받은 날은 건너뛰고 빈 날만 받습니다.", "빈 날이 있으면 「받기」 를 눌러 나오는 명령을 이 PC 에서 돌린 뒤 범위를 다시 보세요.", "주소로 받을 때는 허용 목록에 있는 곳만 받습니다 — 먼저 「주소 검사」 를 누르세요."], relatedTerms: [] },
  "crawl-ingest":    { summary: "수집 자료를 Hugging Face 비공개 데이터셋에 백업한 상태와 이 PC 용량을 봅니다(관리자).", steps: ["점검 줄이 모두 「통과」 여야 로컬 원본을 지워도 된다고 판정합니다.", "원격 다시 확인 · 복원 리허설은 단추를 눌러 나오는 명령을 이 PC 에서 돌리세요 — 다음 판정에 그 결과가 들어갑니다."], relatedTerms: [] },
  "trading-chart":   { summary: "종목 시세와 캔들 차트를 조회합니다.", steps: ["'종목 검색'으로 원하는 종목을 선택하세요.", "기간을 바꿔가며 캔들 차트와 현재가·등락률을 확인하세요."], relatedTerms: ["ma", "rsi"] },
  "trading-portfolio": { summary: "직접 보유 종목을 등록해 나만의 포트폴리오를 관리합니다.", steps: ["종목명·수량·평균단가를 입력해 보유 내역을 추가하세요.", "평가손익은 조회할 때의 시세로 자동 계산됩니다."], relatedTerms: [] },
  "paper-dashboard": { summary: "주식·코인·대체자산이 공유하는 모의투자 계좌(초기 1억원)의 현금·평가액·손익을 확인합니다.", steps: ["각 자산군의 평가액과 총 손익을 확인하세요.", "'계좌 초기화'로 모든 포지션·이력을 지우고 처음부터 다시 연습할 수 있습니다."], relatedTerms: ["paper_trading"] },
  "paper-stock":     { summary: "KRX 종목(또는 해외 티커)을 조회한 시세로 모의 매수/매도합니다.", steps: ["종목코드(예: 005930)를 입력하고 '시세 조회'를 누르세요.", "수량을 넣고 '미리보기'로 체결 가능 여부와 잔고 변화를 확인한 뒤 매수/매도하세요.", "체결은 직접매매 포트폴리오와 같은 잔고를 사용합니다."], relatedTerms: ["paper_trading"] },
  "paper-crypto":    { summary: "Upbit KRW 마켓 현재가로 코인을 금액(매수)/수량(매도) 기준으로 모의 거래합니다.", steps: ["마켓을 고르면 현재가와 국내 거래소(Upbit·Bithumb·Korbit) 가격 비교가 표시됩니다.", "매수는 원화 금액, 매도는 코인 수량으로 입력합니다."], relatedTerms: ["paper_trading"] },
  "paper-alternative": { summary: "선물·옵션·파생 ETN·금·은·부동산 지분을 교육용 기준가/지연 시세로 모의 주문합니다.", steps: ["상품 카드를 클릭하면 차트와 주문 대상이 바뀝니다.", "선물은 증거금(marginRate)만큼만 현금이 차감됩니다."], relatedTerms: ["paper_trading"] },
  "paper-openapi":   { summary: "외부 시스템에서 모의계좌를 조회·주문할 수 있는 Open API 키를 발급하고, Alpaca Paper 연결을 테스트합니다.", steps: ["라벨을 입력하고 키를 발급하세요. 키 원문은 발급 직후 한 번만 표시됩니다.", "curl 예시처럼 Authorization: Bearer 헤더로 /openapi/v1 엔드포인트를 호출하세요.", "Alpaca Paper 키를 넣으면 계정 상태를 읽기 전용으로 확인합니다."], relatedTerms: ["broker_api", "paper_trading"] },
  "quant-lean":      { summary: "Yahoo Finance 일봉을 QuantConnect LEAN 엔진(Docker)에서 실행해 전략 수익률·MDD·샤프를 검증합니다.", steps: ["예시를 고르거나 전략·티커·기간을 직접 입력하세요.", "'검증 실행'을 누르면 LEAN 컨테이너가 실행되고(수 분 소요) pandas 지표와 함께 결과가 표시됩니다.", "LEAN이 연결되지 않은 환경에서는 pandas 계산 결과만 표시됩니다."], relatedTerms: ["backtest", "sharpe", "mdd"] },
  "trading-order":   { summary: "가상 잔고로 매수/매도 주문을 내고 체결 내역을 확인합니다.", steps: ["매수/매도, 수량, 가격을 입력해 주문하세요.", "증권사 API를 연동하면 실제 계좌 데이터로도 확인할 수 있습니다."], relatedTerms: ["broker_api", "paper_trading"] },
  "quant-dashboard": { summary: "대표 종목들의 시세와 퀀트 시그널을 한눈에 봅니다.", steps: ["시장 지수 카드와 종목별 매수/매도 시그널 카드를 확인하세요.", "차트에서 종목을 바꿔가며 지표 흐름을 살펴보세요."], relatedTerms: ["signal", "rsi", "ma"] },
  "quant-auto":      { summary: "10분 주기 자동매매를 시작/중지하고 실행 로그를 확인합니다.", steps: ["'시작'을 누르면 설정된 종목·전략으로 자동매매가 실행됩니다.", "로그에서 각 사이클의 매매 내역과 사유를 확인하세요.", "실거래 전 반드시 '증권사 API 설정'에서 모의(paper) 모드로 충분히 검증하세요."], relatedTerms: ["auto_trade_cycle", "virtual_account", "paper_trading"] },
  "quant-backtest":  { summary: "선택한 종목에 규칙 기반 시그널을 적용해 10년치 백테스트 성과를 확인합니다.", steps: ["종목을 선택하고 '백테스트 실행'을 누르세요.", "누적수익률·샤프지수·MDD·승률을 Buy&Hold와 비교해보세요."], relatedTerms: ["backtest", "sharpe", "mdd", "win_rate"] },
  "settings":        { summary: "실거래를 위한 증권사 API 키(앱키/시크릿키/계좌번호)를 등록합니다.", steps: ["증권사를 선택하고 발급받은 앱키·시크릿키를 입력하세요.", "'연결 테스트'로 정상 연동 여부를 먼저 확인한 뒤 저장하세요.", "모의(paper) 모드로 충분히 테스트한 후 실거래로 전환하는 것을 권장합니다."], relatedTerms: ["broker_api", "broker_catalog", "paper_trading"] },
  "notification-settings": { summary: "매매 체결·오류 등을 텔레그램/슬랙/이메일/카카오/SMS로 받을 채널을 설정합니다.", steps: ["채널별 토큰/웹훅 등 필요한 값을 입력 후 저장하세요.", "'테스트 발송'으로 실제 수신 여부를 확인하세요."], relatedTerms: ["notification_channel"] },
  "us-dashboard":    { summary: "미국 대형주 시세와 시장 지수를 확인합니다.", steps: ["시장 카드에서 주요 지수 등락을, 종목 카드에서 개별 시세를 확인하세요."], relatedTerms: ["dxy", "vix"] },
  "us-chart":        { summary: "미국 종목의 캔들 차트를 조회합니다.", steps: ["티커(예: AAPL)를 입력해 차트를 불러오세요."], relatedTerms: ["ma"] },
  "us-order":        { summary: "미국 주식을 원화 모의 계좌로 매수하고 체결 내역을 확인합니다.", steps: ["종목코드와 수량을 넣고 '매수 (Buy)' 를 누르세요 — 시장가로, 그때 시세와 환율로 원화 체결가가 정해집니다.", "지정가 주문과 해외 종목 매도는 아직 열지 않았습니다.", "Alpaca API 키를 등록하면 실제 페이퍼트레이딩 계좌와 연동할 수 있습니다."], relatedTerms: ["alpaca", "paper_trading"] },
  "us-portfolio":    { summary: "미국 주식 보유를 원화 모의 계좌 기준으로 확인합니다.", steps: ["평균단가 · 평가금액 · 손익은 원화(환율을 곱한 체결가)이고, 현재가 아래 작은 글이 달러 시세입니다.", "표 아래 환율 글에서 어떤 환율을 썼는지(받은 환율 · 대체 환율) 확인하세요."], relatedTerms: ["virtual_account"] },
  "indicator-strategy": { summary: "MA·RSI 등 기본 인디케이터로 매매 전략을 직접 설계하고 신호를 확인합니다.", steps: ["종목·기간을 선택하고 사용할 인디케이터를 체크하세요.", "'분석 실행'으로 지표값과 매수/매도 판단 근거를 확인하세요."], relatedTerms: ["rsi", "ma", "macd", "bollinger", "golden_cross", "dead_cross"] },
  "robo-rebalance": { summary: "모의투자 계좌를 목표 비중으로 되돌리는 리밸런싱 엔진입니다. 시간·이탈률·입출금/배당 3가지 트리거를 설정할 수 있습니다.", steps: ["종목코드와 목표 비중(%)을 추가하고 '플랜 저장'을 누르세요. 합계가 100% 미만이면 나머지는 현금 비중입니다.", "① 시간 기반: 월·분기·연 주기 도래 시, ② 이탈률 기반: 현재 비중이 목표에서 허용 %p 이상 벗어나면, ③ 현금흐름 기반: 입금·출금·배당이 최소금액 이상 발생하면 리밸런싱합니다.", "'자동 체결'을 끄면 트리거 충족 시 제안만 생성되고, 실행 이력에서 '승인·체결'로 직접 확정합니다.", "'주문 산출' → '제안 체결'로 언제든 수동 리밸런싱할 수 있습니다."], relatedTerms: ["rebalancing", "drift", "mdd"] },
  "indicator-tradingview": { summary: "TradingView 알림을 Webhook으로 받아 모의계좌 체결·알림 전달하고, Strategy Tester 성과를 LEAN 백테스트와 교차 검증합니다.", steps: ["모의투자 › Open API에서 API 키를 발급받아 알림 메시지의 token에 넣습니다.", "TradingView 알림 생성 시 Webhook URL과 메시지 템플릿을 붙여 넣으면 buy/sell 알림이 모의계좌에 체결됩니다.", "Strategy Tester 성과를 입력(또는 거래 목록 CSV)하고 LEAN과 비교해 수익률·MDD·거래 횟수 차이와 원인을 확인합니다."], relatedTerms: ["pine_script", "sharpe", "mdd"] },
  "robo-patterns": { summary: "캔들 패턴·지지/저항선·돌파 이벤트를 탐지하고 분봉·일봉·주봉을 종합한 매수·매도·관망 신호와 신뢰도를 보여줍니다.", steps: ["종목코드를 입력하고 분석을 실행하세요 (60분봉 1개월 · 일봉 1년 · 주봉 5년).", "종합 점수는 타임프레임별 지표 점수를 20/50/30% 가중 평균한 값이고, 신뢰도는 방향 일치도와 점수 크기를 반반 섞은 값입니다.", "지지·저항선은 피벗 고점/저점을 1% 허용 범위로 군집화해 터치 횟수로 강도를 매깁니다."], relatedTerms: ["rsi", "ma", "bollinger", "macd"] },
  "indicator-formula": { summary: "함수 조합 산식(DSL)으로 커스텀 지표와 매수·매도 조건을 정의하고, 버전 이력과 계산 결과를 저장·재사용합니다.", steps: ["템플릿을 불러오거나 indicator 산식을 직접 쓰고 '검증'으로 문법·이름을 확인합니다 (함수 레퍼런스 참고).", "'계산 실행'으로 차트·백테스트를 보고, 마음에 들면 이름을 붙여 저장합니다. 산식이 바뀌면 자동으로 새 버전이 생깁니다.", "버전 이력에서 과거 산식을 복원하고, 결과 이력에서 (버전·종목·기간)별 저장 결과를 다시 봅니다. Pine/Python 코드로 내보낼 수 있습니다."], relatedTerms: ["rsi", "bollinger", "sharpe", "mdd"] },
  "indicator-custom": { summary: "나만의 파라미터로 커스텀 인디케이터를 만들고 PineScript/Python 코드를 생성합니다.", steps: ["기준 조합(RSI+MA, MACD+BB 등)과 기간·임계값을 조정하세요.", "생성된 PineScript는 트레이딩뷰에, Python 코드는 직접 백테스트에 활용할 수 있습니다.", "'백테스트 실행'으로 이 앱에서 바로 성과를 검증할 수 있습니다.", "마음에 드는 조합은 '저장'해두면 다음에 목록에서 바로 불러올 수 있습니다."], relatedTerms: ["custom_indicator", "pine_script", "backtest"] },
  "indicator-backtest": { summary: "설계한 전략(기본/커스텀)의 파이썬 기반 성과를 검증합니다.", steps: ["종목과 전략을 선택하면 자동으로 백테스트가 실행됩니다.", "수익률·샤프지수·MDD·승률로 전략의 위험 대비 성과를 판단하세요.", "'비교에 추가'로 여러 전략의 성과를 나란히 비교할 수 있습니다."], relatedTerms: ["backtest", "sharpe", "mdd", "win_rate", "cost_bps", "slippage"] },
  "indicator-api":   { summary: "완성한 인디케이터 전략을 증권사 API와 연결해 자동화하는 방법을 안내합니다.", steps: ["3단계 아키텍처(신호 계산→주문 생성→증권사 API 전송)를 확인하세요.", "하단에서 증권사 키를 등록하고 연결을 테스트하세요."], relatedTerms: ["broker_api", "custom_indicator"] },
  "company-dashboard": { summary: "기업의 개요·밸류에이션·수익성 지표를 한 화면에서 확인합니다.", steps: ["상단에서 기업을 선택하세요.", "개요/밸류에이션/수익성 탭과 분기·재무상태표 데이터를 확인하세요."], relatedTerms: ["dcf", "fcf"] },
  "company-compare": { summary: "여러 기업의 핵심 지표를 표로 나란히 비교합니다.", steps: ["비교 표에서 기업별 지표 값을 확인하며 상대적 위치를 파악하세요."], relatedTerms: ["dcf", "eva"] },
  "company-sector":  { summary: "산업 섹터별 대표 지표와 흐름을 카드로 확인합니다.", steps: ["섹터 카드를 둘러보며 산업별 상대 강도를 비교하세요."], relatedTerms: ["sector_etf"] },
  "ml-compare":      { summary: "지난 시세로 학습한 모델들이 5거래일 뒤 오름 · 관망 · 내림을 얼마나 맞히는지, 아무것도 배우지 않은 기준선과 견줍니다(과거로 학습하고 바로 뒤 구간으로 시험).", steps: ["종목 · 기간을 고르고 '비교하기'를 누르세요 — 처음 계산은 10 ~ 30초, 한 번 계산한 결과는 저장돼 바로 보입니다.", "맨 위 문장과 카드로 「기준선을 뚜렷이 넘은 모델이 있나」 를 먼저 보세요 — 순위보다 이 판정이 중요합니다.", "'자세히'에서 겹마다 점수 · 표를 보고, '비교에 추가'로 여러 결과를 모아 볼 수 있습니다."], relatedTerms: ["cross_validation", "lightgbm", "mlp", "stacking"] },
  "ml-regression":   { summary: "선형회귀·Ridge·Lasso·SVR로 향후 수익률을 예측하고 오차를 비교합니다.", steps: ["종목·기간을 선택해 실행하면 모델별 예측값과 RMSE/MAE가 표시됩니다.", "오차가 작을수록 해당 구간에서 예측력이 높았다는 의미입니다."], relatedTerms: ["regression", "ridge_lasso"] },
  "ml-cluster":      { summary: "지난 기간에 서로 비슷하게 움직인 종목끼리 묶어 봅니다 — 「같이 움직임」(시장 몫을 뺀 수익률 상관) 또는 「위험 · 수익 특성」(수익률 · 변동성 · 시장 민감도 · 최대 낙폭).", steps: ["대상 · 기간 · 묶는 법을 고르세요(묶음 수는 자동이 기본입니다).", "종목 지도에서 가까운 점은 비슷하게 움직인 종목입니다 — 점에 마우스를 올리면 이름이 보입니다.", "묶음 카드의 특징 낱말 · 네 숫자로 묶음을 읽고, 31종목은 「같이 움직인 정도」 탭에서 상관 표를 보세요."], relatedTerms: ["kmeans", "dbscan"] },
  "ml-tune":         { summary: "GridSearchCV로 모델의 하이퍼파라미터를 자동 튜닝합니다.", steps: ["모델(SVM/RF/GB)을 선택하고 '튜닝 실행'을 누르세요.", "최적 파라미터 조합과 교차검증 점수를 확인하세요."], relatedTerms: ["gridsearch", "cross_validation"] },
  "ml-deeplearning": { summary: "시계열 딥러닝(LSTM·Transformer)의 구조와 활용법을 학습하는 참고 자료입니다.", steps: ["아키텍처 다이어그램과 비교표, 코드 예시를 통해 개념을 익히세요.", "이 화면은 학습용 정적 자료로 별도 실행 버튼은 없습니다."], relatedTerms: ["regression"] },
  "macro-dashboard": { summary: "금리·유가·환율 등 주요 거시경제 지표를 확인합니다.", steps: ["지표 카드에서 최신 값과 변동을 확인하세요.", "하단 프레임워크 카드로 거시경제 분석 방법을 함께 학습하세요."], relatedTerms: ["macro_indicator", "vix", "dxy"] },
  "macro-industry":  { summary: "미국 11개 섹터 ETF의 상대적 강도를 비교합니다.", steps: ["등락률 순으로 정렬된 섹터 카드를 통해 자금이 몰리는 산업을 파악하세요."], relatedTerms: ["sector_etf"] },
  "invest-fundamental": { summary: "DCF·EVA·FCF 개념과 함께 종목의 밸류에이션을 조회합니다.", steps: ["종목을 선택하고 '분석 실행'을 누르세요.", "카드에 표시된 개념 설명과 함께 산출된 값을 참고하세요 (교육용 근사치)."], relatedTerms: ["dcf", "eva", "fcf"] },
  "invest-technical": { summary: "캔들 패턴·엘리어트파동·되돌림 등 기술적 분석 개념을 학습하는 참고 자료입니다.", steps: ["패턴별 설명과 예시를 보며 실제 차트에 적용해보세요.", "이 화면은 학습용 정적 자료로 별도 실행 버튼은 없습니다."], relatedTerms: ["golden_cross", "dead_cross"] },
  "fin-products":    { summary: "주식/ETF·채권·파생상품의 개요와 운용 전략을 학습합니다.", steps: ["카드별 설명을 읽으며 상품 유형별 특징과 리스크를 비교해보세요."], relatedTerms: [] },
  "fin-allocation":  { summary: "MVO·블랙-리터만·리스크패리티 등 자산배분 모델의 이론을 학습합니다.", steps: ["각 모델의 수식과 설명을 통해 '로보 어드바이저 > 자산배분' 결과의 원리를 이해하세요."], relatedTerms: ["mvo", "black_litterman", "risk_parity"] },
  "quant-seasonal":  { summary: "달 · 요일 · 연말에 값이 어떻게 움직였는지 지난 기록으로 봅니다 — 코스피 · 코스닥(1995 · 2003 ~) 또는 종목, 끝난 달만 셉니다.", steps: ["대상(코스피 · 코스닥 · 종목)과 값(배당 포함 · 가격만)을 고르세요 — 시장 지수는 가격 지수뿐이라 배당이 빠집니다.", "달마다 평균 막대보다 「해마다 표」 의 흩어짐과 맨 아래 「판정」 줄을 먼저 보세요 — 평균이 높아도 내린 해가 많습니다.", "「한 해 흐름」 탭에서 올해가 지난 해들과 어떻게 다른지, 아래 카드에서 요일 · 산타 랠리 · 반년 비교를 보세요."], relatedTerms: ["seasonality"] },
  // 금융 강의 (2026-10-01) — js/finlearn.js
  "fin-lectures":    { summary: "4일 과정과 교재 단원 가운데 읽을 강의를 고릅니다. 표시한 이해도가 카드에 쌓입니다.", steps: ["카드를 누르면 그 주제의 강의 화면으로 갑니다.", "강의 절마다 이해도(0~5)를 눌러 두면 다음에 「이어 읽기」 로 돌아옵니다.", "「퀀트 · AI 실습 모음」 에서 배운 개념을 분석 화면으로 바로 돌려 봅니다."], relatedTerms: [] },
  "fin-topic-futures":    { summary: "선물 · 옵션의 구조와 증거금 · 만기 · 헤지를 강의와 계산기로 익힙니다.", steps: ["위의 「이 강의에서 답하는 질문」 부터 훑어보세요.", "본문의 밑줄 친 용어를 누르면 풀이가 열립니다."], relatedTerms: [] },
  "fin-topic-funds":      { summary: "펀드 · ETF · 리츠 · ETN 의 구조와 비용, NAV 괴리율을 강의로 익힙니다.", steps: ["위의 질문부터 훑어보고, ETF 탐색표에서 기간 수익률을 바꿔 보세요."], relatedTerms: [] },
  "fin-topic-bonds":      { summary: "채권 가격과 금리의 관계, 코인 거래의 기본을 강의로 익힙니다.", steps: ["금리와 주가를 함께 그린 그림에서 기간을 바꿔 보세요."], relatedTerms: [] },
  "fin-topic-allocation": { summary: "자산배분 · 리밸런싱 · 위험 지표와 퀀트의 기초를 강의로 익힙니다.", steps: ["계산기의 막대를 움직여 비중과 위험이 어떻게 바뀌는지 보세요."], relatedTerms: [] },
  "fin-topic-company":    { summary: "법인과 회사의 구조, 자금 조달과 세무 · 회계의 관계를 교재로 읽습니다.", steps: ["왼쪽 목차에서 절을 골라 읽으세요."], relatedTerms: [] },
  "fin-topic-stocks":     { summary: "주식시장의 구조와 투자 기초 — 시장 · 기업 · 기초자산을 교재로 읽습니다.", steps: ["왼쪽 목차에서 절을 골라 읽으세요."], relatedTerms: [] },
  "fin-topic-technical":  { summary: "캔들 · 거래량 · 이동평균 · 차트 패턴을 교재로 읽습니다.", steps: ["왼쪽 목차에서 절을 골라 읽으세요.", "읽은 패턴은 「투자분석 기초 › 기술적 분석」 과 차트 화면에서 찾아보세요."], relatedTerms: [] },
  "fin-topic-industry":   { summary: "산업 경쟁과 기업 재무 · 공시를 연결해 교재로 읽습니다.", steps: ["왼쪽 목차에서 절을 골라 읽으세요."], relatedTerms: [] },
  "fin-topic-macro":      { summary: "금리 · 물가 · 환율과 주식시장의 연결, 계절성 이야기를 교재로 읽습니다.", steps: ["왼쪽 목차에서 절을 골라 읽으세요.", "계절성은 「계절성 분석」 화면에서 데이터로 확인해 보세요."], relatedTerms: [] },
  "sysadmin-dashboard": { summary: "서버 자원(CPU/메모리/디스크)과 연동 서비스 상태를 모니터링합니다.", steps: ["호스트/서비스/컨테이너 카드에서 이상 여부를 확인하세요.", "응답이 느리거나 실패로 표시되면 해당 서비스(Ollama/Qdrant/Redis) 상태를 점검하세요."], relatedTerms: ["qdrant"] },
  "sysadmin-logs":   { summary: "주문·설정 변경 등 주요 이벤트의 감사 로그를 조회합니다.", steps: ["이벤트 유형·기간으로 필터링해 이력을 확인하세요.", "이상 거래나 설정 변경 원인을 추적할 때 활용하세요."], relatedTerms: ["audit_log"] },
  "fin-glossary":    { summary: "금융 · 투자 용어를 이름 · 약어 · 영어 · 초성으로 찾고, 풀이와 이어진 개념을 봅니다.", steps: ["검색창에 PER · 샤프 · ㅅㄱㅊㅇ 처럼 쳐 보세요 — 줄마다 무엇으로 찾았는지 보여 줍니다.", "분류 카드를 누르면 그 분류의 용어를 가나다순으로 봅니다.", "다른 화면에서 용어를 눌렀을 때 뜨는 창의 모양은 내 계정 › 화면 설정에서 바꿉니다."], relatedTerms: [] },
  "learn-videos":    { summary: "찍어 둔 사용법 영상을 차례대로 봅니다 — 로보 어드바이저를 처음부터 끝까지 쓰는 여정과 기능마다 한 편.", steps: ["오른쪽 차례에서 볼 편을 고르세요 — 끝까지 본 편에는 ✓ 가 붙습니다(이 브라우저에만).", "장 단추를 누르면 그 장면부터 봅니다.", "「이 화면 열기」 를 누르면 그 화면으로 가서 사용법 창을 엽니다."], relatedTerms: [] },
  "learn-home":      { summary: "학습 홈 — 금융 필수 지식 · 개발 개념 · 파이썬 중급 · 특강 네 갈래에서 고르고, 읽던 장을 이어 읽습니다.", steps: ["갈래 카드를 눌러 그 갈래의 목차로 갑니다.", "「이어 읽기」 는 이 브라우저에서 마지막으로 읽은 장입니다.", "준비 중인 장은 다룰 질문과 참고 자료를 먼저 볼 수 있습니다."], relatedTerms: [] },
  "learn-dev":       { summary: "개발 개념 — 수집 · 근거 답 · 차트 · 서버 · AI 에이전트 · 백테스트처럼 Qurious 기능이 움직이는 원리를 부마다 장으로 읽습니다.", steps: ["부 카드를 누르면 그 부의 장 목록이 열립니다.", "장 머리의 「먼저 읽을 장」 부터 읽으면 이어집니다.", "카드의 「읽은 장」 은 이 브라우저에서 연 장의 수입니다."], relatedTerms: [] },
  "learn-python":    { summary: "파이썬 중급 — 우리 코드에 쓰인 import · 타입 힌트 · 데이터 그릇 · 인터페이스 · 예외 처리 · 문자열을 차례로 읽습니다.", steps: ["장 카드를 누르면 바로 읽습니다.", "6.1 부터 차례로 읽으면 앞 장이 다음 장의 바탕이 됩니다."], relatedTerms: [] },
  "learn-special":   { summary: "특강 — 날짜 · 교시마다 특강 내용을 정리한 장입니다. 강의 자료와 다르게 적은 곳은 장마다 출처와 함께 밝혀 두었습니다.", steps: ["날짜 카드를 누르면 그날의 교시 목록이 열립니다.", "장 끝 「강의 자료와 다르게 적은 곳」 에서 바로잡은 내용을 확인하세요."], relatedTerms: [] },
  "learn-part":      { summary: "부 목차 — 한 부(특강은 하루)의 장을 차례대로 보고 골라 읽습니다.", steps: ["「첫 장부터 읽기」 · 「이어 읽기」 는 아직 열지 않은 첫 장으로 갑니다.", "맨 아래에서 앞뒤 부로 옮기거나 갈래 전체로 돌아갑니다."], relatedTerms: [] },
  "learn-page":      { summary: "장 한 편을 읽습니다 — 머리에 부 · 번호 · 먼저 읽을 장, 왼쪽에 이 장의 차례가 있습니다.", steps: ["왼쪽 차례를 누르면 그 절로 내려갑니다.", "코드 상자의 「복사」 로 예제를 옮겨 직접 돌려 보세요.", "맨 아래 앞뒤 장으로 이어 읽고, 머리의 「←」 로 목차에 돌아갑니다."], relatedTerms: [] },
  "mypage":          { summary: "내 계정 정보를 보고 이름 · 비밀번호를 바꾸거나 탈퇴합니다.", steps: ["이메일(로그인 ID)은 대소문자를 가리지 않으며 바꿀 수 없습니다.", "비밀번호를 바꾸면 지금 기기를 뺀 다른 기기는 모두 로그아웃됩니다.", "탈퇴하면 모의투자 · 자동매매 장부와 설정이 즉시 삭제되어 되돌릴 수 없습니다."], relatedTerms: [] },
};

// ── 용어 모달 / 툴팁 / 사용법 패널 헬퍼 ─────────────────────────────
function openTermModal(key) {
  const term = TERMS[key];
  // (Qurious 2026-10-02) 용어사전 카드가 있으면 그 카드를 연다 — 오른쪽 서랍 · 가운데 작은 창 · 큰 창(내 계정에서 고름 · js/termcard.js).
  // 이 화면의 짧은 설명(TERMS)은 용어사전에서 못 찾거나 불러오지 못했을 때 대신 보여 줄 글로 넘긴다.
  if (window.QTerm) { window.QTerm.open(key, { fallback: term }); return; }
  if (!term) return;
  document.getElementById("tm-title").textContent = term.title;
  document.getElementById("tm-body").textContent = term.body;
  document.getElementById("term-modal").classList.add("open");
}
function closeTermModal() {
  document.getElementById("term-modal").classList.remove("open");
}
window.openTermModal = openTermModal;
window.closeTermModal = closeTermModal;

function termChip(key, label) {
  const term = TERMS[key];
  const text = label || term?.title || key;
  return `<button type="button" class="term-chip" onclick="openTermModal('${key}')" title="용어 설명 보기">${escHtml(text)} <i class="fa-solid fa-circle-info"></i></button>`;
}
window.termChip = termChip;

// tt(표시라벨, 짧은힌트, 용어key) → hover 시 힌트, 클릭 시 상세 모달
function tt(label, hint, key) {
  const clickAttr = key ? ` onclick="openTermModal('${key}')"` : "";
  return `<span class="tt"${clickAttr}>${escHtml(label)}<span class="tt-bubble">${escHtml(hint)}</span></span>`;
}
window.tt = tt;

// (Qurious 2026-10-16) 화면 사용법 — 윗줄 「사용법」 단추 + 가운데 창은 js/howto.js 가 그린다(결정 안 A ·
// 설계 docs/화면/설계안/2026-10-16-사용법모달). 자료(사용법 글 · 용어 · 메뉴 이름)는 여기서 넘긴다 —
// howto.js 가 core.js 를 가져오면 화면 시작 차례가 바뀐다. 옛 접이식과 열림 기억(localStorage)은 버렸다.
function renderViewGuide(viewKey, pathKey = viewKey) {   // pathKey — 머리 경로에 쓸 메뉴 줄(메뉴 줄이 없는 화면은 따를 줄)
  const menu = Object.values(GNB_MENUS).find(m => m.items.some(it => it.key === pathKey));
  const item = menu?.items.find(it => it.key === pathKey);
  window.QHowto?.render(viewKey, VIEW_GUIDES[viewKey], {
    terms: TERMS, label: item?.label || "", group: (menu?.label || "").replace(/<[^>]+>/g, "").trim(),
  });
}

// ── 백테스트/모델 비교 트레이 (localStorage, 프론트 전용) ────────────
const COMPARE_TRAY_KEY = "compare_tray";
const COMPARE_TRAY_MOUNTS = ["bt-compare-tray", "ibt-compare-tray", "mlc-compare-tray", "ql-compare-tray"];

function compareTrayGet() {
  try { return JSON.parse(localStorage.getItem(COMPARE_TRAY_KEY) || "[]"); } catch { return []; }
}
function compareTraySet(list) {
  localStorage.setItem(COMPARE_TRAY_KEY, JSON.stringify(list.slice(-15)));
}
function compareTrayAdd(entry) {
  const list = compareTrayGet();
  list.push({ id: `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, addedAt: new Date().toLocaleString("ko-KR"), ...entry });
  compareTraySet(list);
  renderCompareTrayAll();
  setToast("결과 비교에 추가했습니다", "ok");
}
function compareTrayRemove(id) {
  compareTraySet(compareTrayGet().filter(x => x.id !== id));
  renderCompareTrayAll();
}
function compareTrayClear() {
  compareTraySet([]);
  renderCompareTrayAll();
}
window.compareTrayAdd = compareTrayAdd;
window.compareTrayRemove = compareTrayRemove;
window.compareTrayClear = compareTrayClear;

function renderCompareTray(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const list = compareTrayGet();
  if (!list.length) { el.innerHTML = ""; return; }
  el.innerHTML = `
    <div class="card" style="margin-top:12px;">
      <div class="flex items-center justify-between mb-2">
        <h3 class="font-semibold text-sm">⚖️ 결과 비교 (${list.length})</h3>
        <button type="button" class="btn-secondary text-xs" onclick="compareTrayClear()">전체 지우기</button>
      </div>
      <p class="text-xs mb-2" style="color:var(--text-mute);">서로 다른 화면에서 '비교에 추가'한 백테스트·모델 결과를 한 표에서 비교합니다 (이 브라우저에만 저장됨).</p>
      <div class="overflow-x-auto">
        <table><thead><tr><th>추가된 곳</th><th>이름</th><th>요약 지표</th><th style="text-align:right;">시각</th><th></th></tr></thead>
        <tbody>${list.map(x => `
          <tr>
            <td style="color:var(--text-mute);font-size:12.5px;white-space:nowrap;">${escHtml(x.source)}</td>
            <td style="font-weight:600;">${escHtml(x.label)}</td>
            <td>${escHtml(x.summary)}</td>
            <td style="text-align:right;color:var(--text-mute);font-size:12.5px;white-space:nowrap;">${escHtml(x.addedAt)}</td>
            <td style="text-align:right;"><button type="button" class="btn-secondary text-xs" onclick="compareTrayRemove('${x.id}')">삭제</button></td>
          </tr>`).join("")}</tbody>
        </table>
      </div>
    </div>`;
}
function renderCompareTrayAll() {
  COMPARE_TRAY_MOUNTS.forEach(renderCompareTray);
}
window.renderCompareTrayAll = renderCompareTrayAll;

let currentGnb = "agent";
let currentView = "agent-chat";

// ── 메뉴 짜임 — 위 고정 탭 여섯 + 왼쪽 「전체 메뉴」 트리 (2026-10-18 화면 결정 D129 안 가 · Figma 「Qurious · 메뉴 개편」 05 시안) ──
// 위 메뉴는 늘 보이는 여섯 묶음만 둔다 — 폭에 따라 탭을 하나씩 숨기지 않는다(다 보이거나, 다 안 들어가면 탭 줄을 통째로
// 접는다 · fitGnbTabs). 모든 묶음은 왼쪽 트리에 늘 있고(지금 묶음만 펼침), 좁은 화면은 ☰ 가 같은 트리를 연다.
// 그래서 옛 「더보기 N ▾」 · 오른쪽 서랍 「전체 메뉴」(DF-109 · 2026-10-14 결정 D84 융합안 D)는 없앴다 — 숨은 묶음이 없다.
// 근거: 사용자 10-18 「위의 메뉴바에는 필요한 기능만 넣고 옆 사이드에 전체 메뉴」 · 조사(KRX 정보데이터시스템의 통계 트리 ·
//       강사님 fe-vanilla 의 좌측 트리) · NN/g 「Hamburger Menus and Hidden Navigation Hurt UX Metrics」(2016 — 데스크톱에서
//       숨긴 메뉴 27% · 보이는 메뉴 48%).
// 탭 「학습」 = 한 묶음(누르면 학습 홈 · 2026-10-20 금융 필수 지식 · 개발 개념 · 파이썬 중급 · 특강을 합침) — Schwab · Webull · Coinbase 가 위 메뉴에 두는
//       「Learn」 을 다른 탭처럼 우리말 명사로(2026-10-18 각 첫 화면 메뉴 글 확인 · 사용자 「가장 범용적인 이름」).
const MENU_TOP = ["agent", "company", "paper", "quant", "finance", "crawl"];   // app.html 위 탭과 같은 차례(TC-NV-01)
// 메뉴 줄이 없는 화면 → 따를 메뉴 줄 — 장 한 편 · 부 목차는 학습 갈래 목차에서 들어온다(메뉴 줄 「장 읽기」 는 뺐다 · 사용자 10-20
// 「굳이 필요 없는 화면」). 위 탭 · 왼쪽 트리 · 머리 경로가 이 줄을 따르고, 화면이 그린 뒤 들어온 갈래로 바꾼다(showUnder)
const VIEW_PARENT = { "learn-page": "learn-home", "learn-part": "learn-home" };
const TAB_OF = {};   // 위 탭이 따로 없는 묶음 → 불을 켤 위 탭(2026-10-20 「학습」 을 한 묶음으로 합쳐 지금은 없음 · 생기면 여기 · TC-CLV-02)
const MENU_TREE = ["agent", "company", "paper", "quant", "trading", "us", "invest", "ml",
  "finance", "crawl", "sysadmin", "account"];   // 왼쪽 트리 차례 — 모든 묶음이 한 번씩(TC-NV-02 · 2026-10-20 개념 학습은 「학습」 안으로)
const menuIcon = label => (label.match(/class='([^']+)'/) || [])[1] || "fa-solid fa-folder";
const menuText = label => label.replace(/<[^>]+>/g, "").trim();
// 트리 항목 하나 — 소제목(heading)은 누를 수 없는 글, 바깥 주소(href)는 링크, 그 밖은 화면 단추(키보드로 닿게 button)
function lnbItem(it) {
  if (it.heading) return `<div class="lnb-heading">${it.heading}</div>`;
  const cls = `lnb-item${it.sub ? " lnb-sub" : ""}`;
  if (it.href) {
    return `<a class="${cls}" href="${it.href}" data-menu-href="${it.key}" title="${it.label} (새 화면)"><i class="${it.icon}" aria-hidden="true"></i>` +
      `<span>${it.label}</span><i class="fa-solid fa-arrow-up-right-from-square lnb-out" aria-hidden="true"></i><span class="sr-only">(새 화면)</span></a>`;
  }
  return `<button type="button" class="${cls}" data-view="${it.key}" title="${it.label}"><i class="${it.icon}" aria-hidden="true"></i><span>${it.label}</span></button>`;
}
// 트리는 한 번만 그린다(메뉴는 고정) — 화면을 옮길 때는 펼침 · 지금 표시만 바꾼다(syncLnbTree)
function renderLnbTree() {
  const nav = document.getElementById("lnb-nav");
  if (!nav) return;
  nav.innerHTML = MENU_TREE.filter(key => GNB_MENUS[key]).map(key => {
    const menu = GNB_MENUS[key];
    const outOnly = menu.items.every(it => it.heading || it.href);   // 모두 바깥 주소인 묶음(지금은 없음 — 개념 학습은 2026-10-19 앱 안으로)
    const name = menuText(menu.label);
    return `<details class="lnb-group" data-lnb-group="${key}">` +
      `<summary class="lnb-group-head" title="${name}"><i class="${menuIcon(menu.label)}" aria-hidden="true"></i><span>${name}</span>` +
      `${outOnly ? '<span class="lnb-tag">새 화면</span>' : ""}<i class="fa-solid fa-chevron-down lnb-chevron" aria-hidden="true"></i></summary>` +
      `<div class="lnb-group-items">${menu.items.map(lnbItem).join("")}</div></details>`;
  }).join("");
  nav.addEventListener("click", event => {
    const item = event.target.closest("button.lnb-item[data-view]");
    if (item) { navigate(item.dataset.view); setMobileLnb(false); return; }
    if (event.target.closest("[data-menu-href]")) setMobileLnb(false);   // 바깥 주소는 링크가 연다 — ☰ 트리만 닫는다
  });
}
let treeGnb = null;   // 트리에서 마지막으로 펼쳐 준 지금 묶음 — 묶음이 바뀔 때만 다른 묶음을 접는다
function syncLnbTree(gnbKey, viewKey) {
  const nav = document.getElementById("lnb-nav");
  if (!nav) return;
  const moved = gnbKey !== treeGnb;
  treeGnb = gnbKey;
  nav.querySelectorAll("details.lnb-group").forEach(group => {
    const here = group.dataset.lnbGroup === gnbKey;
    group.classList.toggle("active", here);
    if (moved) group.open = here;   // 다른 묶음으로 옮기면 지금 묶음만 펼친다(같은 묶음 안 이동은 사용자가 펼친 그대로 · 사용자 S124)
  });
  let current = null;
  nav.querySelectorAll(".lnb-item[data-view]").forEach(el => {
    const active = el.dataset.view === viewKey;
    el.classList.toggle("active", active);
    if (active) { el.setAttribute("aria-current", "page"); current = el; } else el.removeAttribute("aria-current");
  });
  // 트리가 길어 지금 항목이 칸 밖이면 트리 칸만 굴린다(창 전체를 굴리지 않게 scrollIntoView 를 쓰지 않음)
  if (current && moved) {
    const r = current.getBoundingClientRect(), n = nav.getBoundingClientRect();
    if (n.height && (r.top < n.top || r.bottom > n.bottom)) nav.scrollTop += r.top - n.top - n.height / 3;
  }
}
renderLnbTree();

// 위 메뉴 폭 — 탭 여섯은 하나씩 숨기지 않는다. 다 안 들어가면 로고 부제 → 탭 아이콘 → 탭 줄 통째(gnb-notabs — 같은 메뉴가
// 왼쪽 트리 · ☰ 에 있다) 차례로 접는다. 폭 경계(@media)가 아니라 실제 폭으로 잰다 — 경계로 접으면 경계에서 넓어지는데 탭이
// 준다(1020 → 1040 실측 · S112). 탭 칸 폭이 바뀔 때(창 크기 · 늦게 채워지는 자료 표시 · 글꼴이 늦게 읽힐 때) 다시 잰다.
function fitGnbTabs() {
  const gnb = document.getElementById("gnb");
  const bar = gnb?.querySelector(".gnb-tabs");
  if (!bar) return;
  const tabs = [...bar.querySelectorAll(".gnb-item[data-gnb]")];
  gnb.classList.remove("gnb-noicons", "gnb-notagline", "gnb-notabs");
  const fitsAll = () => tabs.reduce((sum, t) => sum + t.offsetWidth, 0) <= bar.clientWidth;
  if (!fitsAll()) gnb.classList.add("gnb-notagline");
  if (!fitsAll()) gnb.classList.add("gnb-noicons");
  if (!fitsAll()) gnb.classList.add("gnb-notabs");   // 반만 잘린 탭 · 일부만 보이는 탭 줄은 두지 않는다
}
(function () {
  const bar = document.querySelector("#gnb .gnb-tabs");
  let queued = false;
  const refit = () => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; fitGnbTabs(); }); };
  if (bar && "ResizeObserver" in window) new ResizeObserver(refit).observe(bar);
  window.addEventListener("resize", refit);
  document.fonts?.ready?.then(refit);
  refit();
})();

// LNB 토글 (접기/펼치기)
document.getElementById("lnb-toggle-btn")?.addEventListener("click", () => {
  const lnb = document.getElementById("lnb");
  const icon = document.getElementById("lnb-toggle-icon");
  lnb.classList.toggle("collapsed");
  const isCollapsed = lnb.classList.contains("collapsed");
  icon.className = isCollapsed ? "fa-solid fa-chevron-right" : "fa-solid fa-chevron-left";
});

function navigate(viewKey) {
  const navKey = VIEW_PARENT[viewKey] || viewKey;   // 메뉴 줄이 없는 화면은 따를 줄로 묶음 · 트리 · 머리 경로를 고른다
  // Find gnb section for this view
  for (const [gnbKey, menu] of Object.entries(GNB_MENUS)) {
    if (menu.items.some(it => it.key === navKey)) {
      currentGnb = gnbKey;
      break;
    }
  }
  const moved = currentView !== viewKey;   // 다른 화면으로 옮기나(같은 화면을 다시 부르면 스크롤 자리를 둔다)
  currentView = viewKey;

  // 위 탭 — 지금 묶음이 여섯 안이면 그 탭에 불 · 위 탭이 따로 없는 묶음은 TAB_OF 의 탭에(개념 학습 → 「학습」)
  const tabGnb = TAB_OF[currentGnb] || currentGnb;
  document.querySelectorAll("[data-gnb]").forEach(el => {
    el.classList.toggle("active", el.dataset.gnb === tabGnb);
  });
  fitGnbTabs();   // 지금 탭은 굵은 글이라 폭이 조금 바뀐다 — 다시 잰다

  // 왼쪽 트리 — 지금 묶음 펼침 · 지금 화면 표시
  syncLnbTree(currentGnb, navKey);

  // Show/hide views
  document.querySelectorAll(".view").forEach(el => {
    el.classList.toggle("active", el.dataset.view === viewKey);
  });
  // 다른 화면으로 옮기면 내용 칸을 맨 위로 — 굴러가는 칸이 창이 아니라 #main-content 라 브라우저가 자리를 되돌려 주지 않아,
  // 앞 화면에서 내려간 자리를 물려받아 새 화면 중간에 떨어졌다(DF-134 · 2026-10-18 시연 영상을 찍다가 찾음)
  if (moved) document.getElementById("main-content")?.scrollTo(0, 0);

  // 사용법 안내 패널 (전체 화면 공통)
  renderViewGuide(viewKey, navKey);
  renderCompareTrayAll();

  location.hash = viewKey;
  document.dispatchEvent(new CustomEvent("lumina:view-changed", { detail: { view: viewKey } }));
  _viewActivated(viewKey);
}

// 메뉴 줄이 없는 화면이 그린 뒤 「들어온 갈래」 를 알린다 — 왼쪽 트리 표시 · 머리 경로가 그 메뉴 줄로 바뀐다
// (장의 갈래는 목록을 받아야 안다 · 그사이 다른 화면으로 옮겼으면 그대로 둔다)
function showUnder(viewKey, parentKey) {
  if (currentView !== viewKey || !VIEW_PARENT[viewKey]) return;
  syncLnbTree(currentGnb, parentKey);
  renderViewGuide(viewKey, parentKey);
}

// GNB click — 묶음의 첫 화면으로(위 탭이 부른다)
function openGnbGroup(gnbKey) {
  const first = GNB_MENUS[gnbKey].items.find(it => it.key);   // 소제목(heading)은 건너뛴다
  if (first.href) { location.href = first.href; return; }   // 첫 항목이 바깥 주소인 묶음 — 별도 HTML 로(지금은 없음)
  navigate(first.key);
}
document.querySelectorAll("[data-gnb]").forEach(el => {
  el.addEventListener("click", () => openGnbGroup(el.dataset.gnb));
});

// ── Market Ticker ─────────────────────────────────────────────────
async function loadMarketTicker() {
  try {
    const { indices } = await api("/api/stocks/market");
    const el = document.getElementById("market-ticker");
    el.innerHTML = indices.map(idx => {
      const pct = idx.change_pct;
      const sign = pct >= 0 ? "+" : "";
      const color = pct >= 0 ? "var(--green)" : "var(--red)";
      return `
        <div class="ticker-item">
          <span class="ticker-name">${escHtml(idx.name)}</span>
          <span class="ticker-val" style="color:${color};">${fmt(idx.price)} <small style="font-weight:400;">${sign}${pct?.toFixed(2)}%</small></span>
        </div>`;
    }).join("");
  } catch {}
}

// ── Sync Status Badge ──────────────────────────────────────────────
async function loadSyncStatus() {
  const badge = document.getElementById("sync-badge");
  const txt   = document.getElementById("sync-badge-text");
  if (!badge || !txt) return;
  try {
    const st = await api("/api/system/sync-status");
    const sch = st.scheduler || {};
    if (sch.syncing) {
      badge.className = "syncing";
      txt.textContent = "동기화 중…";
    } else if (st.online) {
      badge.className = "online";
      const lastSync = sch.last_sync ? new Date(sch.last_sync) : null;
      if (lastSync) {
        const mins = Math.round((Date.now() - lastSync) / 60000);
        txt.textContent = mins < 60
          ? `${mins}분 전 동기화`
          : `${Math.round(mins/60)}시간 전 동기화`;
      } else {
        txt.textContent = "온라인";
      }
    } else {
      badge.className = "offline";
      const cache = st.cache || {};
      const anyFresh = Object.values(cache).some(v => v && v.age_minutes < 120);
      txt.textContent = anyFresh ? "캐시 사용 중" : "오프라인";
    }
  } catch {
    badge.className = "offline";
    txt.textContent = "오프라인";
  }
}

async function triggerSync() {
  const badge = document.getElementById("sync-badge");
  const txt   = document.getElementById("sync-badge-text");
  if (!badge || badge.className === "syncing") return;
  badge.className = "syncing";
  txt.textContent = "동기화 중…";
  try {
    const result = await api("/api/system/sync", { method: "POST" });
    if (result.ok) {
      setToast("데이터 동기화 완료", "success");
    } else {
      setToast(result.reason === "offline" ? "인터넷 연결 없음 — 동기화 불가" : "동기화 실패", "error");
    }
  } catch {
    setToast("동기화 요청 실패", "error");
  }
  await loadSyncStatus();
}

// ── 좁은 화면 — ☰ 가 왼쪽 「전체 메뉴」 트리를 연다(같은 트리 한 벌 · 2026-10-18 사용자 S124) ─────────────
// 어두운 막 누름 · Esc · 메뉴 고름 · 화면이 바뀌면 닫는다(IA I12 남은 것 — 바깥 누름 닫기). 열면 초점은 지금 항목, 닫으면 ☰ 로.
const lnbBackdrop = document.createElement("div");
lnbBackdrop.id = "lnb-backdrop";
document.body.appendChild(lnbBackdrop);
function setMobileLnb(open) {
  const lnb = document.getElementById("lnb");
  const btn = document.getElementById("hamburger-btn");
  if (!lnb || lnb.classList.contains("mobile-open") === open) return;
  if (open && lnb.classList.contains("collapsed")) document.getElementById("lnb-toggle-btn")?.click();   // 넓은 화면에서 접어 둔 띠는 펴서 연다
  lnb.classList.toggle("mobile-open", open);
  lnbBackdrop.classList.toggle("open", open);
  btn?.setAttribute("aria-expanded", String(open));
  if (open) (document.querySelector("#lnb-nav .lnb-item.active") || document.querySelector("#lnb-nav .lnb-group-head"))?.focus();
}
(function () {
  const btn = document.getElementById("hamburger-btn");
  if (!btn) return;
  btn.setAttribute("aria-controls", "lnb");
  btn.setAttribute("aria-expanded", "false");
  btn.addEventListener("click", () => setMobileLnb(!document.getElementById("lnb")?.classList.contains("mobile-open")));
  lnbBackdrop.addEventListener("click", () => { setMobileLnb(false); btn.focus(); });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && document.getElementById("lnb")?.classList.contains("mobile-open")) { setMobileLnb(false); btn.focus(); }
  });
  document.addEventListener("lumina:view-changed", () => setMobileLnb(false));
})();

// ── Footer 연도 ───────────────────────────────────────────────────
const footerYear = document.getElementById("footer-year");
if (footerYear) footerYear.textContent = new Date().getFullYear();

// ══════════════════════════════════════════════════════════════════
// ML·딥러닝 — 모델 비교
// ══════════════════════════════════════════════════════════════════
// ── 용어 설명 모달 ────────────────────────────────────────────────
(function () {
  const modal = document.getElementById("term-modal");
  document.getElementById("tm-close").addEventListener("click", closeTermModal);
  modal.addEventListener("click", e => { if (e.target === modal) closeTermModal(); });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && modal.classList.contains("open")) closeTermModal();
  });
})();

// 주소창 해시가 바뀌면(북마크·뒤로가기·같은 문서 내 링크) 해당 뷰로 전환한다. navigate()가 스스로 바꾼 해시는 무시.
window.addEventListener("hashchange", () => {
  const key = location.hash.replace("#", "");
  if (key && key !== currentView && document.querySelector(`.view[data-view="${key}"]`)) navigate(key);
});

// 뷰 활성화 훅 — main.js 가 도메인 모듈들의 load* 를 조합해 등록한다 (core → 도메인 순환 의존 방지)
let _viewActivated = () => {};
export function registerViewActivation(fn) { _viewActivated = fn; }


export { GNB_MENUS, MENU_TOP, MENU_TREE, compareTrayAdd, fitGnbTabs, loadMarketTicker, loadSyncStatus, navigate, openGnbGroup, renderCompareTrayAll, showUnder, tt };
