/* 전략 카드 → Pine v6 strategy() 내려받기 화면 판단 — DOM 없이 글 · 표시만 정한다(node 로 시험 · TC-PCD · 2026-10-29 · 화면 벤치마킹 S3).
 *
 * 서버 `GET /api/strategy-cards`(목록) · `GET /api/strategy-cards/{id}/pine`(코드)가 준 값을 **그대로** 보인다.
 * 코드 · 지문 · 설정은 생성기(pine_strategy.py)가 준 것 — 화면은 짓지 않고, 값이 없으면 줄표 + 까닭을 보인다.
 *
 * 규칙
 *   1. 만들 수 없는 카드는 목록에서 막고(disabled) 서버가 준 까닭을 옆에 보인다.
 *   2. 코드 위에 「이 코드는 strategy()라 Strategy Report 에 데이터가 나온다 / 설정을 같이 맞춰야 한다」 를 먼저 — indicator 코드(표시용)와 혼동하지 않게.
 *   3. TradingView Properties(속성)에 맞출 값(초기 자본 · 수수료 · 슬리피지 · 체결 시점)을 표로 — 서버 `properties` 그대로.
 *   4. 판 지문을 코드 첫머리 곁에 보여 어느 카드 · 판에서 나온 코드인지 알게 한다. 파일 이름에도 넣는다.
 */

const DASH = "—";
const isNum = v => typeof v === "number" && Number.isFinite(v);

/** 카드 고르기 `<option>` 들 — 만들 수 없으면 disabled + 까닭. */
export function cardOptions(list, esc) {
  const cards = (list && Array.isArray(list.cards)) ? list.cards : [];
  if (!cards.length) return `<option value="" disabled selected>카드 파일을 찾지 못했습니다</option>`;
  return cards.map((c, i) => {
    const label = `${c.card_id || c.id} 판 ${c.version ?? DASH}${c.generatable ? "" : ` — 만들 수 없음: ${c.reason || "까닭 없음"}`}`;
    return `<option value="${esc(c.id)}" data-universe="${esc((c.universe || []).join(","))}"${c.generatable ? "" : " disabled"}${i === 0 && c.generatable ? " selected" : ""}>${esc(label)}</option>`;
  }).join("");
}

/** 요청 문자열 — 비어 있거나 숫자가 아닌 칸은 보내지 않는다(서버 기본값 · 경고를 그대로 받는다). */
export function pineQuery({ symbol, refPrice, mintick, slippageBp, capital } = {}) {
  const q = new URLSearchParams();
  const sym = String(symbol || "").trim();
  if (sym) q.set("symbol", sym);
  const add = (k, v) => { const n = Number(v); if (v !== "" && v != null && Number.isFinite(n)) q.set(k, String(n)); };
  add("ref_price", refPrice); add("mintick", mintick); add("slippage_bp", slippageBp); add("capital", capital);
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** 내려받을 파일 이름 — 카드 · 판 · 종목 · 판 지문. 파일 이름에 못 쓰는 글자는 뺀다. */
export function fileName(res) {
  const safe = s => String(s ?? "").replace(/[^0-9A-Za-z._-]+/g, "-").replace(/^[-.]+|[-.]+$/g, "") || "x";   // 앞뒤의 점 · 하이픈도 뺀다(「..」 가 이름에 남지 않게)
  return `${safe(res && res.card_id)}_v${safe(res && res.version)}_${safe(res && res.symbol)}_${safe(res && res.fingerprint)}.pine`;
}

const row = (k, v, esc, note = "") =>
  `<tr><td class="pr-3">${esc(k)}</td><td><strong>${esc(v)}</strong>${note ? ` <span class="text-xs" style="color:var(--text-mute);">${esc(note)}</span>` : ""}</td></tr>`;

/** TradingView 속성(Properties)에 맞출 설정 표. */
export function propertiesTable(p, esc) {
  const x = p || {};
  const won = v => (isNum(v) ? `${v.toLocaleString("ko-KR")}원` : DASH);
  const rows = [
    row("초기 자본 (Initial capital)", won(x.initial_capital), esc),
    row("수수료 (Commission)", x.commission_value != null ? `${x.commission_value}${x.commission_type === "percent" ? "%" : ` (${x.commission_type})`}` : DASH, esc,
      x.commission_round_trip_pct ? `편도 근사 · 왕복 ${x.commission_round_trip_pct}%` : ""),
    row("슬리피지 (Slippage)", isNum(x.slippage_ticks) ? `${x.slippage_ticks}틱` : DASH, esc,
      isNum(x.slippage_effective_bp) && x.slippage_ticks ? `약 ${Number(x.slippage_effective_bp.toFixed(1))}bp` : (x.slippage_ticks === 0 ? "기준가 · 호가 단위를 넣지 않으면 0" : "")),
    row("피라미딩 (Pyramiding)", isNum(x.pyramiding) ? String(x.pyramiding) : DASH, esc),
    row("체결 시점", x.process_orders_on_close === true ? "같은 봉 종가에 체결" : x.process_orders_on_close === false ? "다음 봉 시가에 체결" : DASH, esc,
      x.process_orders_on_close === true ? "현실에서는 불가한 가정" : ""),
    row("주기", x.timeframe === "1d" ? "일봉(1D)만" : (x.timeframe || DASH), esc),
  ];
  return `<table class="text-sm">${rows.join("")}</table>`;
}

/** 결과 전체 — 안내 · 지문 · 설정 표 · 경고 · 코드. 코드는 `<pre>` 에 이스케이프해 넣는다. */
export function renderPine(res, esc) {
  if (!res || !res.code) return `<div class="text-sm">코드를 받지 못했습니다.</div>`;
  const warn = (res.warnings || []).length
    ? `<div class="text-xs mt-2"><strong>경고</strong><ul class="list-disc ml-5">${res.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>` : "";
  return `<div class="text-xs mb-2" data-pine-strategy>이 코드는 <strong>strategy()</strong> 입니다 — TradingView 에 붙이면 Strategy Report 에 거래 목록이 나옵니다.
      아래 설정을 TradingView 의 속성(Properties)에도 같게 맞춰야 LEAN 과 비교할 수 있습니다.</div>`
    + `<div class="text-xs mb-2">카드 ${esc(res.card_id)} · 판 ${esc(res.version)} · 종목 ${esc(res.symbol)} · 판 지문 <code>${esc(res.fingerprint)}</code> · Pine v${esc(res.pine_version ?? DASH)}</div>`
    + propertiesTable(res.properties, esc) + warn
    + `<pre id="pc-code" class="text-xs rounded-lg p-4 overflow-x-auto mt-2" style="background:var(--surf2);border:1px solid var(--border);color:var(--text-dim);">${esc(res.code)}</pre>`
    + (res.note ? `<div class="text-xs mt-1" style="color:var(--text-mute);">${esc(res.note)}</div>` : "");
}

/** 실패 글 — 서버 까닭(422 의 detail 등)을 그대로, 없으면 일반 글. */
export function failText(err) {
  const m = err && err.message;
  if (err && err.status === 401) return "로그인이 풀렸습니다. 다시 로그인해 주세요.";
  return m || "코드를 만들지 못했습니다.";
}
