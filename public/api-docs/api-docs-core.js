/* API 문서 — 순수 함수 (2026-10-06)
 *
 * 화면(api-docs.js)과 Node 시험(tests/test_api_docs.py · TC-AD)이 함께 쓴다. DOM · fetch 를 쓰지 않는다.
 *
 * 두 자료를 하나로 합친다
 *   ① /openapi.json — 앱(FastAPI)이 실제로 내놓는 명세. 인자 · 본문 · 응답 모양과 시험 호출(Swagger UI)은 여기서 온다.
 *   ② catalog.json — scripts/api_scan.py --catalog 가 소스를 읽어 만든 우리 칸(API ID · 인증 · 닿는 곳 · 부르는 화면 ·
 *      파트 · 요구 · 코드 위치). OpenAPI 에는 없는 칸이다(API 명세서 4절 표와 같은 출처).
 *   둘은 「메서드 + 경로」 로 잇는다. 한쪽에만 있는 것도 버리지 않는다 — 카탈로그에만 있으면 명세에서 일부러 뺀 API
 *   (include_in_schema=False)이거나 카탈로그를 만든 뒤에 사라진 API 이고, 명세에만 있으면 카탈로그를 다시 만들어야 하는
 *   새 API 다(화면에 그렇게 적는다).
 */

export const METHODS = ["get", "post", "put", "patch", "delete"];

// 라우터(app/routes/*.py) → 화면에 보일 이름. 스캐너 차례(앱에 붙인 차례)와 같은 스물아홉.
export const ROUTER_LABELS = {
  auth: "계정 · 로그인", ingest: "문서 넣기", health: "서버 상태", chat: "AI 대화", stocks: "시세 · 종목 · 주문",
  library: "자료 찾기(옛 리서치)", admin: "관리자", system: "시스템", quant: "퀀트 자동매매", ml: "머신러닝",
  macro: "거시 지표", documents: "문서", notification: "알림", graph: "관계 그래프", conversations: "대화 기록",
  tasks: "작업", paper: "모의투자", dashboard: "투자 대시보드", openapi: "외부 Open API", lean: "LEAN 백테스트",
  rebalance: "리밸런싱", tradingview: "TradingView", formula: "수식 지표", glossary: "용어사전", learn: "개념 학습",
  lectures: "금융 강의", data: "수집 자료", calendar: "금융 일정", kb: "근거 문서 · 근거 답",
};

// 인증 칸(스캐너 이름표) → 거름 묶음 넷. 모르는 이름표는 「기타」.
export const AUTH_GROUPS = [
  ["none", "로그인 없음"], ["session", "로그인"], ["admin", "관리자"], ["apikey", "API 키"],
];

export function authGroup(auth) {
  const a = String(auth || "");
  if (!a) return "";
  if (a === "없음") return "none";
  if (a.includes("관리자") || a.includes("역할")) return "admin";
  if (a.includes("API 키")) return "apikey";
  if (a.includes("세션") || a.includes("JWT")) return "session";
  return "other";
}

// 첫 줄만 — FastAPI 는 summary 를 따로 주지 않으면 함수 이름(영어 · 「Kb Search Route」)을 넣는다.
// 그래서 우리 summary= → 함수 설명(docstring) 첫 줄 → FastAPI summary 차례로 고른다.
export function firstLine(text) {
  const line = String(text || "").split(/\r?\n/).map(s => s.trim()).find(Boolean) || "";
  return line.replace(/`|\*\*|__/g, "").slice(0, 120);   // 마크다운 표시(코드 · 굵게)는 목록 글에서 뺀다
}

export function titleOf(cat, op) {
  return (cat && cat.summary) || firstLine(op && op.description) || (op && op.summary) || "";
}

function routerOf(path, op) {
  const seg = String(path).split("/").filter(Boolean);
  return (op && op.tags && op.tags[0]) || (seg[0] === "api" ? seg[1] : seg[0]) || "기타";
}

/** 명세 + 카탈로그 → 화면 줄. 차례 = 카탈로그 차례(라우터 등록 차례), 명세에만 있는 것은 그 라우터 끝. */
export function mergeOps(spec, catalog) {
  const routes = (catalog && catalog.routes) || [];
  const cat = new Map();
  const order = new Map();
  const routerOrder = new Map();
  routes.forEach((r, i) => {
    const key = `${String(r.method).toUpperCase()} ${r.path}`;
    cat.set(key, r);
    order.set(key, i);
    if (!routerOrder.has(r.router)) routerOrder.set(r.router, routerOrder.size);
  });
  const rows = [];
  const seen = new Set();
  for (const [path, item] of Object.entries((spec && spec.paths) || {})) {
    for (const m of METHODS) {
      const op = item && item[m];
      if (!op) continue;
      const key = `${m.toUpperCase()} ${path}`;
      const c = cat.get(key) || null;
      seen.add(key);
      rows.push({ key, method: m.toUpperCase(), path, op, cat: c, id: c ? c.id : "",
        router: c ? c.router : routerOf(path, op), title: titleOf(c, op), auth: c ? c.auth : "", inSpec: true });
    }
  }
  for (const [key, c] of cat) {
    if (seen.has(key)) continue;
    rows.push({ key, method: String(c.method).toUpperCase(), path: c.path, op: null, cat: c, id: c.id,
      router: c.router, title: titleOf(c, null), auth: c.auth, inSpec: false });
  }
  const big = Number.MAX_SAFE_INTEGER;
  const rk = r => (routerOrder.has(r.router) ? routerOrder.get(r.router) : big);
  const ok = r => (order.has(r.key) ? order.get(r.key) : big);
  return rows.sort((a, b) => rk(a) - rk(b) || ok(a) - ok(b) || a.key.localeCompare(b.key));
}

// 찾기 글은 띄어쓰기 · 대소문자를 접는다(「근거 찾기」 = 「근거찾기」 · 「KB/ASK」 = 「kb/ask」).
export function fold(s) {
  return String(s || "").toLowerCase().replace(/\s+/g, "");
}

export function haystack(r) {
  return fold([r.method, r.path, r.id, r.title, r.router, ROUTER_LABELS[r.router] || "",
    ((r.op && r.op.tags) || []).join(" "), r.cat ? (r.cat.screens || []).join(" ") : ""].join(" "));
}

/** 거름 — 낱말(모두 들어 있어야) · 메서드 · 라우터 · 인증 묶음 · 화면이 부르는 것만. */
export function filterOps(rows, { q = "", methods = null, router = "", auth = "", screensOnly = false } = {}) {
  const words = String(q || "").split(/\s+/).map(fold).filter(Boolean);
  return rows.filter(r => {
    if (methods && methods.size && !methods.has(r.method)) return false;
    if (router && r.router !== router) return false;
    if (auth && authGroup(r.auth) !== auth) return false;
    if (screensOnly && !(r.cat && r.cat.screens && r.cat.screens.length)) return false;
    if (!words.length) return true;
    const hay = haystack(r);
    return words.every(w => hay.includes(w));
  });
}

/** 라우터별 묶음 — [[라우터, 줄들], …] 차례 그대로. */
export function groupByRouter(rows) {
  const groups = new Map();
  for (const r of rows) {
    if (!groups.has(r.router)) groups.set(r.router, []);
    groups.get(r.router).push(r);
  }
  return [...groups];
}

/** Swagger UI 에 넘길 명세 — 고른 오퍼레이션 하나만 남기고 스키마(components)는 그대로(본문 · 응답이 참조한다). */
export function oneOpSpec(spec, path, method) {
  const m = String(method || "").toLowerCase();
  const item = spec && spec.paths && spec.paths[path];
  if (!item || !item[m]) return null;
  const keep = { [m]: item[m] };
  if (item.parameters) keep.parameters = item.parameters;   // 경로 공통 인자
  return { openapi: spec.openapi, info: { ...(spec.info || {}) }, components: spec.components || {}, paths: { [path]: keep } };
}

/** 시험 호출을 허용할 메서드 — 기본은 읽기(GET)만. 쓰기는 사용자가 켤 때만(주문 · 삭제가 실제로 실행되므로). */
export function submitMethods(allowWrite) {
  return allowWrite ? METHODS.slice() : ["get"];
}

/** 주소의 # 뒤 — 「GET /api/kb/search」 를 그대로 싣는다(새로 고침 · 링크 공유 때 같은 API 를 연다). */
export function keyToHash(key) {
  return "#" + encodeURIComponent(key);
}

export function hashToKey(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  if (!raw) return "";
  try {
    const key = decodeURIComponent(raw);
    return /^(GET|POST|PUT|PATCH|DELETE) \/\S*$/.test(key) ? key : "";
  } catch {
    return "";
  }
}

/** Swagger 원본(/docs) 의 같은 오퍼레이션 주소 — /docs#/{태그}/{operationId}. 태그가 없으면 default. */
export function swaggerDeepLink(op) {
  if (!op || !op.operationId) return "/docs";
  const tag = (op.tags && op.tags[0]) || "default";
  return `/docs#/${encodeURIComponent(tag)}/${encodeURIComponent(op.operationId)}`;
}

/** 머리의 숫자 — 명세 · 카탈로그 · 둘 다 · 한쪽에만 · 화면이 부르는 것. */
export function stats(rows) {
  const s = { total: rows.length, inSpec: 0, both: 0, specOnly: 0, catOnly: 0, screens: 0 };
  for (const r of rows) {
    if (r.inSpec) s.inSpec += 1;
    if (r.inSpec && r.cat) s.both += 1;
    if (r.inSpec && !r.cat) s.specOnly += 1;
    if (!r.inSpec) s.catOnly += 1;
    if (r.cat && r.cat.screens && r.cat.screens.length) s.screens += 1;
  }
  return s;
}
