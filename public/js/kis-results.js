/**
 * KIS 모의투자 결과 (화면 키 `kis-results` · 퀀트자동매매 › 「KIS 모의투자 결과」 · 2026-11-04)
 *
 * 강사님 lumina-invest 「KIS 모의투자결과」(D1) 의 축소판이다 — 내 주문만 · 필터 · 쪽 · CSV · 상태 요약 카드.
 * 강사님 화면의 배지 · 계좌 보유 · 정합성 · 사이클 이력은 우리 서버 응답에 없거나 배치(서버 계좌 하나) 전제라 가져오지 않았다.
 *
 * 데이터는 `GET /api/quant/kis/orders?owner=me` 하나다. owner 는 "me" 로 못 박는다 — 배치(시스템) 주문과 남의 정보는
 * 요청 자체를 하지 않는다. 모니터 API 는 부르지 않는다(소유자 구분이 없어 시스템 계좌 데이터가 섞인다).
 * 읽기만 한다 — 주문 취소 · 재주문 같은 쓰기 요청은 이 파일에 없다.
 *
 * 이 파일은 node 에서 그대로 불러 시험한다(tests/test_kis_results.py · TC-KR). 그래서
 *  - 맨 위에서 `/js/...` 절대 경로를 가져오지 않는다(node 는 파일 시스템 뿌리로 읽는다) — 상대 경로 `./learnnotice.js` 만 쓴다.
 *  - `document` 는 함수 안에서만 만진다. api · esc 는 마운트할 때 받는다(signal-rank.js 와 같은 방식).
 *  - 함수 이름은 `kr` 로 시작한다(scripts/view_scan.py 가 함수를 이름으로 이어 다른 화면과 엉키지 않게).
 *
 * 표시 규칙: 판단 문장을 짓지 않는다 — 숫자는 서버 응답의 값 · 받은 목록의 단순 개수다. 영문 상태 코드는 한국어 낱말 옆에 작게 둔다.
 * 시각은 KST(UTC+9)로 고쳐 보이고, 모르는 값은 줄표(0 으로 메우지 않는다).
 */
import { NOTICE_LINE } from "./learnnotice.js";

// ── 상수 ─────────────────────────────────────────────────────────────
const KR_OWNER = "me";                           // 내 주문만 — 바꾸지 않는다(시험이 지킨다)
export const KR_PAGE_SIZES = Object.freeze([20, 50, 100]);
export const KR_CSV_PAGE = 500;                  // 서버 limit 상한
export const KR_CSV_MAX = 2000;                  // 서버가 한 번에 훑는 상한 — 그 이상은 담지 못한다
const KR_NOTE_MAX = 80;                          // 표에 보이는 메모 길이(전체는 title)
export const KR_EMPTY_FILTERS = Object.freeze({ status: "", side: "", dateFrom: "", dateTo: "", q: "" });

// 상태 코드 → 묶음. 서버 ORDER_STATUSES 열 개가 한 번씩 들어 있어야 한다(시험이 서버 목록과 맞춘다).
export const KR_GROUPS = Object.freeze([
  Object.freeze({ key: "filled", label: "체결", codes: Object.freeze(["FILLED"]) }),
  Object.freeze({ key: "open", label: "접수 · 대기", codes: Object.freeze(["PENDING", "ACCEPTED", "PARTIALLY_FILLED", "CANCEL_REQUESTED"]) }),
  Object.freeze({ key: "failed", label: "거부 · 실패", codes: Object.freeze(["REJECTED", "ERROR"]) }),
  Object.freeze({ key: "cancelled", label: "취소", codes: Object.freeze(["CANCELLED"]) }),
  // UNKNOWN = 응답을 잃어 접수 여부를 모르는 주문 · LOST = 정해진 시간 안에 확인하지 못하고 끝낸 주문 — 체결됐을 수도 있어 「실패」 로 부르지 않는다
  Object.freeze({ key: "check", label: "확인 필요", codes: Object.freeze(["UNKNOWN", "LOST"]) }),
]);
const KR_GROUP_OF = Object.freeze(Object.fromEntries(KR_GROUPS.flatMap((g) => g.codes.map((c) => [c, g]))));
export const KR_STATUS_WORD = Object.freeze({
  FILLED: "체결", PARTIALLY_FILLED: "일부 체결", ACCEPTED: "접수", PENDING: "대기", CANCEL_REQUESTED: "취소 요청",
  CANCELLED: "취소", REJECTED: "거부", ERROR: "오류", UNKNOWN: "접수 여부 미확인", LOST: "확인 못 하고 종료",
});
const KR_KIND = Object.freeze({ filled: "ok", open: "wait", failed: "bad", cancelled: "idle", check: "warn", other: "idle" });

// ── 순수 함수: 글 · 숫자 · 시각 ─────────────────────────────────────────
export function krEsc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/** 천 단위 쉼표 · 정수는 그대로 · 소수는 둘째 자리까지 · 모르는 값은 줄표. */
export function krNum(v) {
  if (v == null || v === "") return "-";
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  const abs = Math.abs(n);
  const text = Number.isInteger(abs) ? String(abs) : String(Number(abs.toFixed(2)));
  const [int, frac] = text.split(".");
  return `${n < 0 ? "-" : ""}${int.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${frac ? `.${frac}` : ""}`;
}

function krParse(value) {
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value : null;
  if (value == null || value === "") return null;
  const raw = String(value).trim();
  // 서버 시각은 UTC — 오프셋 표시가 없으면 UTC 로 읽는다(common.js kstTime 과 같은 규칙)
  const noZone = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(raw) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const d = new Date(noZone ? `${raw.replace(" ", "T")}Z` : raw);
  return Number.isFinite(d.getTime()) ? d : null;
}

const krPad2 = (n) => String(n).padStart(2, "0");

/** UTC → KST(+9) 「YYYY-MM-DD HH:MM:SS」. Intl 을 쓰지 않고 +9시간 계산이라 어느 환경에서도 같은 글이 나온다. */
export function krKstText(value) {
  const d = krParse(value);
  if (!d) return "-";
  const k = new Date(d.getTime() + 9 * 3600 * 1000);
  return `${k.getUTCFullYear()}-${krPad2(k.getUTCMonth() + 1)}-${krPad2(k.getUTCDate())} ` +
    `${krPad2(k.getUTCHours())}:${krPad2(k.getUTCMinutes())}:${krPad2(k.getUTCSeconds())}`;
}

/** KST 날짜 「YYYY-MM-DD」 — CSV 파일 이름용. */
export function krKstDate(value) {
  const t = krKstText(value);
  return t === "-" ? "" : t.slice(0, 10);
}

/** 종목코드: 6자리(.KS · .KQ 꼬리 뗌)면 그 코드, 아니면 받은 글 그대로(대문자). */
export function krCode(symbol) {
  const raw = String(symbol ?? "").trim().toUpperCase();
  const m = raw.match(/^(?:KRX:)?(\d{6})(?:\.(?:KS|KQ))?$/);
  return m ? m[1] : raw;
}

// ── 순수 함수: 상태 · 방향 · 요약 ─────────────────────────────────────────
/** 상태 코드 → 한국어 낱말 + 원래 코드 + 묶음 + 색 종류. 모르는 코드는 코드 그대로(묶음 other). */
export function krStatusView(code) {
  const raw = String(code ?? "").trim().toUpperCase();
  const group = KR_GROUP_OF[raw];
  return {
    code: raw || "-",
    word: KR_STATUS_WORD[raw] || raw || "-",
    group: group ? group.key : "other",
    kind: KR_KIND[group ? group.key : "other"],
  };
}

export function krSideView(side) {
  const raw = String(side ?? "").trim().toUpperCase();
  if (raw === "BUY") return { word: "매수", kind: "buy", code: raw };
  if (raw === "SELL") return { word: "매도", kind: "sell", code: raw };
  return { word: raw || "-", kind: "none", code: raw };
}

/** 상태 필터 한 묶음 → 서버에 보낼 쉼표 목록(서버 status 인자). */
export function krGroupValue(key) {
  const g = KR_GROUPS.find((x) => x.key === key);
  return g ? g.codes.join(",") : "";
}

/** 서버 counts_by_status → 카드 숫자. 합은 전체와 같다(묶음에 없는 코드는 「기타」 로 따로 센다 · 판단 문장 없음). */
export function krStatusCounts(counts) {
  const src = counts && typeof counts === "object" ? counts : {};
  const per = Object.fromEntries(KR_GROUPS.map((g) => [g.key, 0]));
  let total = 0;
  let other = 0;
  for (const [code, n] of Object.entries(src)) {
    const v = Math.max(0, Math.trunc(Number(n) || 0));
    total += v;
    const g = KR_GROUP_OF[String(code).trim().toUpperCase()];
    if (g) per[g.key] += v; else other += v;
  }
  return { total, other, groups: KR_GROUPS.map((g) => ({ key: g.key, label: g.label, codes: g.codes, count: per[g.key] })) };
}

/** 쪽 계산 — total · offset · limit 으로 지금 쪽 · 전체 쪽 · 보이는 범위 · 이전/다음 가능 여부. */
export function krPageInfo({ total, offset, limit } = {}) {
  const t = Math.max(0, Math.trunc(Number(total) || 0));
  const lim = Math.max(1, Math.trunc(Number(limit) || KR_PAGE_SIZES[0]));
  const off = Math.max(0, Math.trunc(Number(offset) || 0));
  const pages = Math.max(1, Math.ceil(t / lim));
  const page = Math.min(pages, Math.floor(off / lim) + 1);
  return {
    total: t, limit: lim, offset: off, pages, page,
    from: t ? Math.min(t, off + 1) : 0,
    to: Math.min(t, off + lim),
    hasPrev: off > 0,
    hasNext: off + lim < t,
    prevOffset: Math.max(0, off - lim),
    nextOffset: off + lim,
    lastOffset: (pages - 1) * lim,
  };
}

// ── 순수 함수: 필터 · 주소 ──────────────────────────────────────────────
export function krFiltersActive(f) {
  const x = f || {};
  return Boolean(x.status || x.side || x.dateFrom || x.dateTo || String(x.q || "").trim());
}

/** 요청 전에 잡을 수 있는 입력 문제(없으면 빈 글). 서버도 같은 검사를 하지만 왕복 없이 알려 준다. */
export function krFilterProblem(f) {
  const x = f || {};
  if (x.dateFrom && x.dateTo && x.dateFrom > x.dateTo) return "시작일은 종료일보다 앞서야 합니다.";
  return "";
}

/** 조회 주소의 질의 글. owner 는 항상 me. withStatus=false 면 상태 조건을 뺀다(요약 카드용). */
export function krQuery(filters, { offset = 0, limit = KR_PAGE_SIZES[0], withStatus = true } = {}) {
  const f = filters || {};
  const p = new URLSearchParams();
  p.set("owner", KR_OWNER);
  if (withStatus && f.status) p.set("status", f.status);
  if (f.side) p.set("side", f.side);
  const q = String(f.q || "").trim().slice(0, 80);
  if (q) p.set("q", q);
  if (f.dateFrom) p.set("date_from", f.dateFrom);
  if (f.dateTo) p.set("date_to", f.dateTo);
  p.set("limit", String(Math.min(KR_CSV_PAGE, Math.max(1, Math.trunc(Number(limit) || KR_PAGE_SIZES[0])))));
  p.set("offset", String(Math.max(0, Math.trunc(Number(offset) || 0))));
  return p.toString();
}

// ── 순수 함수: CSV ────────────────────────────────────────────────────
/**
 * CSV 셀 하나 — 늘 큰따옴표로 감싸고 안의 큰따옴표는 두 번 쓴다. 글자 셀이 `= + - @` (또는 탭 · 줄바꿈 복귀)로 시작하면
 * 앞에 작은따옴표를 붙여 스프레드시트가 수식으로 읽지 못하게 한다. 숫자 셀은 그대로 둔다.
 */
export function krCsvCell(v) {
  if (v == null) return '""';
  let s = String(v);
  if (typeof v !== "number" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return `"${s.replace(/"/g, '""')}"`;
}

export const KR_CSV_COLUMNS = Object.freeze([
  ["시각(KST)", (r) => { const t = krKstText(r.created_at); return t === "-" ? "" : t; }],   // 모르는 시각은 빈 셀(줄표는 수식 막음 때문에 따옴표가 붙는다)
  ["종목코드", (r) => krCode(r.symbol)],
  ["종목명", (r) => r.name ?? ""],
  ["방향", (r) => krSideView(r.side).word],
  ["주문유형", (r) => r.order_type ?? ""],
  ["주문수량", (r) => (r.quantity == null ? "" : Number(r.quantity))],
  ["주문가격", (r) => (r.price == null ? "" : Number(r.price))],
  ["체결수량", (r) => (r.filled_quantity == null ? "" : Number(r.filled_quantity))],
  ["체결평균가", (r) => (r.avg_filled_price == null ? "" : Number(r.avg_filled_price))],
  ["상태", (r) => krStatusView(r.status).word],
  ["상태코드", (r) => String(r.status ?? "")],
  ["주문번호", (r) => r.order_no ?? ""],
  ["계좌구분", (r) => r.environment ?? ""],
  ["메모", (r) => r.message ?? ""],
]);

/** 행 목록 → CSV 글. 맨 앞 BOM(엑셀에서 한글이 깨지지 않게) · 줄바꿈은 CRLF. 개인정보 칸(IP · 브라우저 · 계정)은 없다. */
export function krCsvText(rows) {
  const head = KR_CSV_COLUMNS.map(([name]) => krCsvCell(name)).join(",");
  const body = (rows || []).map((r) => KR_CSV_COLUMNS.map(([, get]) => krCsvCell(get(r || {}))).join(","));
  return `﻿${[head, ...body].join("\r\n")}`;
}

export function krCsvFileName(now) {
  return `kis-my-orders-${krKstDate(now) || "export"}.csv`;
}

// ── 순수 함수: 표 · 카드 · 쪽 글 (esc 를 받는다) ──────────────────────────────
const KR_COLUMNS = Object.freeze([
  { head: "시각 (KST)" }, { head: "종목" }, { head: "방향" },
  { head: "수량", num: true }, { head: "가격 (원)", num: true }, { head: "체결", num: true },
  { head: "상태" }, { head: "주문번호" },
]);

function krEnvNote(env) {
  const e = String(env ?? "").trim();
  return !e || e.toLowerCase() === "paper" ? "" : `계좌 구분: ${e}`;   // 모의(paper)가 아니면 숨기지 않고 보인다
}

/** 표 한 줄에 쓸 글 모음. */
export function krRowView(r) {
  const row = r || {};
  const code = krCode(row.symbol);
  const name = String(row.name ?? "").trim();
  const price = Number(row.price);
  const filledQty = Number(row.filled_quantity);
  const note = String(row.message ?? "").trim();
  return {
    time: krKstText(row.created_at),
    code,
    name: name || code || "-",
    showCode: Boolean(name && code),
    side: krSideView(row.side),
    qty: krNum(row.quantity),
    price: price > 0 ? krNum(price) : String(row.order_type ?? "").toUpperCase() === "MARKET" ? "시장가" : "-",
    filled: filledQty > 0 ? `${krNum(filledQty)}주 @ ${krNum(row.avg_filled_price)}` : "-",
    status: krStatusView(row.status),
    orderNo: String(row.order_no ?? "").trim() || "-",
    note,
    noteShort: note.length > KR_NOTE_MAX ? `${note.slice(0, KR_NOTE_MAX)}…` : note,
    env: krEnvNote(row.environment),
  };
}

function krRowHtml(v, esc) {
  const code = v.showCode ? ` <small class="kr-code">${esc(v.code)}</small>` : "";
  const noteLine = v.note ? `<div class="kr-note" title="${esc(v.note)}">${esc(v.noteShort)}</div>` : "";
  const env = v.env ? ` <span class="kr-badge" data-kind="warn">${esc(v.env)}</span>` : "";
  return `<tr>`
    + `<td data-label="시각 (KST)" class="kr-time">${esc(v.time)}</td>`
    + `<td data-label="종목"><span class="kr-name">${esc(v.name)}</span>${code}</td>`
    + `<td data-label="방향"><span class="kr-side" data-kind="${esc(v.side.kind)}">${esc(v.side.word)}</span></td>`
    + `<td data-label="수량" class="kr-num">${esc(v.qty)}</td>`
    + `<td data-label="가격 (원)" class="kr-num">${esc(v.price)}</td>`
    + `<td data-label="체결" class="kr-num">${esc(v.filled)}</td>`
    + `<td data-label="상태"><span class="kr-badge" data-kind="${esc(v.status.kind)}">${esc(v.status.word)}</span>`
    + ` <small class="kr-code">${esc(v.status.code)}</small>${env}${noteLine}</td>`
    + `<td data-label="주문번호" class="kr-orderno">${esc(v.orderNo)}</td>`
    + `</tr>`;
}

/** 주문 표. 좁은 화면에서는 표 칸만 좌우로 민다(쪽 전체는 넘치지 않는다). */
export function krTableHtml(rows, esc = krEsc) {
  const head = KR_COLUMNS.map((c) => `<th scope="col"${c.num ? ' class="kr-num"' : ""}>${esc(c.head)}</th>`).join("");
  const body = (rows || []).map((r) => krRowHtml(krRowView(r), esc)).join("");
  return `<div class="kr-table-wrap" role="region" tabindex="0" aria-label="내 주문 표 — 좁은 화면에서는 좌우로 밀어 봅니다">`
    + `<table class="kr-table"><caption class="kr-sr">내 KIS 모의투자 주문 (최신순)</caption>`
    + `<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/** 상태 요약 카드 — 숫자는 서버 counts_by_status 의 단순 합. 「기타」 는 있을 때만. */
export function krCardsHtml(counts, esc = krEsc) {
  const c = krStatusCounts(counts);
  const card = (key, label, n, codes) =>
    `<li class="kr-stat" data-kr-stat="${esc(key)}"><span class="kr-stat-k">${esc(label)}</span>`
    + `<b class="kr-stat-n">${esc(krNum(n))}</b><small class="kr-stat-c">${esc(codes)}</small></li>`;
  const items = [card("all", "전체", c.total, "모든 상태")];
  for (const g of c.groups) items.push(card(g.key, g.label, g.count, g.codes.join(" · ")));
  if (c.other > 0) items.push(card("other", "기타", c.other, "위에 없는 상태 코드"));
  return `<ul class="kr-cards" aria-label="상태별 건수">${items.join("")}</ul>`;
}

/** 카드 아래 한 줄 — 무엇을 센 숫자인지(기준)만 적는다. */
export function krCardsNote({ truncated = false, statusFiltered = false } = {}) {
  const parts = ["방향 · 기간 · 검색어 조건에 맞는 내 주문의 건수입니다"];
  if (statusFiltered) parts.push("상태 조건은 뺀 숫자입니다");
  if (truncated) parts.push(`최근 ${krNum(KR_CSV_MAX)}건까지만 조회됩니다`);
  return parts.join(" · ");
}

/** 쪽 이동 줄 — 이전 · 다음 · 쪽/전체 쪽 · 보이는 범위 · 쪽당 건수. */
export function krPagerHtml(info, esc = krEsc) {
  const size = KR_PAGE_SIZES.map((n) => `<option value="${n}"${n === info.limit ? " selected" : ""}>${n}건</option>`).join("");
  return `<nav class="kr-pager" aria-label="페이지 이동">`
    + `<button type="button" class="btn-secondary" data-kr-prev${info.hasPrev ? "" : " disabled"}>이전</button>`
    + `<span class="kr-pager-text">${esc(info.page)} / ${esc(info.pages)} 쪽 · ${esc(krNum(info.from))}–${esc(krNum(info.to))}번째 · 총 ${esc(krNum(info.total))}건</span>`
    + `<button type="button" class="btn-secondary" data-kr-next${info.hasNext ? "" : " disabled"}>다음</button>`
    + `<label class="kr-size"><span>쪽당</span><select class="input" data-kr-size>${size}</select></label>`
    + `</nav>`;
}

/** 빈 상태 — none: 필터 없이 0건(까닭과 다음 행동) · filtered: 조건에 맞는 주문이 없음. */
export function krEmptyHtml(kind, esc = krEsc) {
  if (kind === "filtered") {
    return `<div class="kr-empty" role="note"><b>조건에 맞는 주문이 없습니다.</b>`
      + `<p>조건을 바꾸거나 <button type="button" class="kr-linkbtn" data-kr-reset>조건 모두 지우기</button> 를 눌러 보세요.</p></div>`;
  }
  return `<div class="kr-empty" role="note"><b>아직 내 KIS 모의투자 주문이 없습니다.</b>`
    + `<p>내 계정으로 모의투자 주문이 나가면 여기에 쌓입니다. 자동매매를 켜고 상태를 확인하거나, 증권사 연동이 되어 있는지 확인해 보세요.</p>`
    + `<p><a class="kr-link" href="#quant-auto">자동매매 현황으로 가기</a> · <a class="kr-link" href="#mypage">마이페이지에서 증권사 연동 확인</a></p></div>`;
}

export function krErrorHtml(message, esc = krEsc) {
  return `<div class="kr-empty" role="alert"><b>주문 기록을 불러오지 못했습니다.</b><p>${esc(message || "잠시 뒤 새로고침을 눌러 다시 시도해 주세요.")}</p></div>`;
}

/** 화면 뼈대(한 번만 그린다) — 기준 안내 · 요약 카드 칸 · 필터 · 결과 줄 · 표 칸 · 쪽 칸 · 고지 한 줄. */
export function krShellHtml(esc = krEsc) {
  const statusOptions = [`<option value="">전체</option>`]
    .concat(KR_GROUPS.map((g) => `<option value="${esc(g.codes.join(","))}">${esc(g.label)}</option>`)).join("");
  return `<p class="kr-basis"><i class="fa-solid fa-circle-info" aria-hidden="true"></i> `
    + `<b>모의투자 계좌 기준</b> — 한국투자증권 모의투자 계좌로 낸 <b>내 주문</b>의 앱 저장 기록입니다. 실거래 주문이 아니며, 증권사 전체 체결 내역과 다를 수 있습니다.</p>`
    + `<div data-kr-cards></div><p class="kr-cards-note" data-kr-cards-note></p>`
    + `<form class="kr-filter" data-kr-form novalidate>`
    + `<label class="kr-field"><span>상태</span><select name="status" class="input">${statusOptions}</select></label>`
    + `<label class="kr-field"><span>방향</span><select name="side" class="input"><option value="">전체</option><option value="BUY">매수</option><option value="SELL">매도</option></select></label>`
    + `<label class="kr-field"><span>시작일 (KST)</span><input type="date" name="dateFrom" class="input"></label>`
    + `<label class="kr-field"><span>종료일 (KST)</span><input type="date" name="dateTo" class="input"></label>`
    + `<label class="kr-field kr-grow"><span>검색어</span><input type="search" name="q" class="input" maxlength="80" autocomplete="off" placeholder="종목코드 · 종목명 · 주문번호"></label>`
    + `<div class="kr-actions">`
    + `<button type="submit" class="btn-primary">검색</button>`
    + `<button type="button" class="btn-secondary" data-kr-reset>조건 지우기</button>`
    + `<button type="button" class="btn-secondary" data-kr-refresh>새로고침</button>`
    + `<button type="button" class="btn-secondary" data-kr-csv title="지금 조건에 맞는 주문 전체를 CSV 로 내려받습니다(최근 ${esc(krNum(KR_CSV_MAX))}건까지)">CSV 내려받기</button>`
    + `</div></form>`
    + `<p class="kr-result" role="status" aria-live="polite" data-kr-result>불러오는 중…</p>`
    + `<div data-kr-list></div><div data-kr-pager></div>`
    + `<p class="kr-foot"><i class="fa-solid fa-circle-info" aria-hidden="true"></i> ${esc(NOTICE_LINE)}</p>`;
}

// ── 화면 동작 (브라우저에서만 돈다) ───────────────────────────────────────
function krReadFilters(form) {
  const el = form.elements;
  return {
    status: String(el.status.value || ""),
    side: String(el.side.value || ""),
    dateFrom: String(el.dateFrom.value || ""),
    dateTo: String(el.dateTo.value || ""),
    q: String(el.q.value || "").trim().slice(0, 80),
  };
}

function krSameFilters(a, b) {
  return a.status === b.status && a.side === b.side && a.dateFrom === b.dateFrom && a.dateTo === b.dateTo && a.q === b.q;
}

/** 지금 조건에 맞는 주문 전체(최대 KR_CSV_MAX)를 쪽으로 나눠 받는다. */
async function krFetchAllRows(api, filters) {
  const byKey = new Map();
  let total = Infinity;
  let offset = 0;
  while (offset < total && offset < KR_CSV_MAX) {
    const res = await api(`/api/quant/kis/orders?${krQuery(filters, { offset, limit: KR_CSV_PAGE })}`);
    const got = Array.isArray(res && res.rows) ? res.rows : [];
    total = Number(res && res.total) || 0;
    got.forEach((r, i) => byKey.set(r.id || `${offset}-${i}`, r));
    if (!got.length) break;
    offset += got.length;
  }
  return [...byKey.values()];
}

function krSaveCsv(text, fileName) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * 화면 칸(host)에 그리고 이벤트를 한 번 묶는다. api 는 common.js 의 api(경로) — 주소는 이 파일이 읽기(GET)로만 부른다.
 * 돌려주는 값: { krReload } — 화면에 들어올 때마다 부른다.
 */
export function mountKisResults(host, { api, esc = krEsc, now = () => new Date() } = {}) {
  const st = { filters: { ...KR_EMPTY_FILTERS }, offset: 0, size: KR_PAGE_SIZES[0], seq: 0, busy: false };
  host.innerHTML = krShellHtml(esc);
  const krPick = (sel) => host.querySelector(sel);
  const form = krPick("[data-kr-form]");

  const krSay = (text) => { krPick("[data-kr-result]").textContent = text; };

  async function krReload(again = false) {
    const seq = ++st.seq;
    const problem = krFilterProblem(st.filters);
    if (problem) { host.removeAttribute("aria-busy"); krSay(problem); return; }   // 앞 요청의 finally 는 seq 가 바뀌어 정리하지 않으므로 여기서 푼다
    host.setAttribute("aria-busy", "true");
    krSay("불러오는 중…");
    try {
      const statusFiltered = Boolean(st.filters.status);
      const [page, wide] = await Promise.all([
        api(`/api/quant/kis/orders?${krQuery(st.filters, { offset: st.offset, limit: st.size })}`),
        // 카드는 상태 조건을 뺀 건수 — 상태로 거르면 다른 카드가 0 이 되어 맥락이 사라지므로 한 번 더 묻는다(1건만)
        statusFiltered ? api(`/api/quant/kis/orders?${krQuery(st.filters, { limit: 1, withStatus: false })}`) : Promise.resolve(null),
      ]);
      if (seq !== st.seq) return;   // 더 새 요청이 나갔다 — 낡은 응답은 버린다
      const total = Number(page.total) || 0;
      const rows = Array.isArray(page.rows) ? page.rows : [];
      if (!rows.length && total > 0 && st.offset > 0 && !again) {   // 지운 주문 때문에 쪽이 비었다 — 마지막 쪽으로
        st.offset = krPageInfo({ total, offset: st.offset, limit: st.size }).lastOffset;
        return krReload(true);
      }
      const base = wide || page;
      krPick("[data-kr-cards]").innerHTML = krCardsHtml(base.counts_by_status, esc);
      krPick("[data-kr-cards-note]").textContent = krCardsNote({ truncated: Boolean(base.truncated), statusFiltered });
      const info = krPageInfo({ total, offset: st.offset, limit: st.size });
      if (!total) {
        krPick("[data-kr-list]").innerHTML = krEmptyHtml(krFiltersActive(st.filters) ? "filtered" : "none", esc);
        krPick("[data-kr-pager]").innerHTML = "";
      } else {
        krPick("[data-kr-list]").innerHTML = krTableHtml(rows, esc);
        krPick("[data-kr-pager]").innerHTML = krPagerHtml(info, esc);
      }
      krSay(`검색 결과 ${krNum(total)}건${page.truncated ? ` · 최근 ${krNum(KR_CSV_MAX)}건까지만 조회됩니다` : ""} · 갱신 ${krKstText(now())} (KST)`);
    } catch (err) {
      if (seq !== st.seq) return;
      krPick("[data-kr-list]").innerHTML = krErrorHtml(err && err.message, esc);
      krPick("[data-kr-pager]").innerHTML = "";
      krSay("");
    } finally {
      if (seq === st.seq) host.removeAttribute("aria-busy");
    }
  }

  /** 폼 값을 조건으로 받아들인다 — 바뀌었으면 첫 쪽부터 다시 읽는다. 바뀐 게 없으면 false. */
  function krApply() {
    const next = krReadFilters(form);
    if (krSameFilters(next, st.filters)) return false;
    st.filters = next;
    st.offset = 0;
    return true;
  }

  function krReset() {
    form.reset();
    st.filters = { ...KR_EMPTY_FILTERS };
    st.offset = 0;
  }

  async function krDownload(button) {
    if (st.busy) return;
    st.busy = true;
    const label = button.textContent;
    button.disabled = true;
    button.textContent = "내려받는 중…";
    try {
      if (krApply()) await krReload();   // 폼에 적은 조건이 아직 안 걸렸으면 먼저 걸고 그 조건으로 받는다
      if (krFilterProblem(st.filters)) return;
      const rows = await krFetchAllRows(api, st.filters);
      if (!rows.length) { krSay("내려받을 주문이 없습니다."); return; }
      krSaveCsv(krCsvText(rows), krCsvFileName(now()));
      krSay(`CSV ${krNum(rows.length)}건을 내려받았습니다.`);
    } catch (err) {
      krSay(`CSV 를 만들지 못했습니다: ${err && err.message ? err.message : "잠시 뒤 다시 시도해 주세요."}`);
    } finally {
      st.busy = false;
      button.disabled = false;
      button.textContent = label;
    }
  }

  form.addEventListener("submit", (ev) => { ev.preventDefault(); krApply(); krReload(); });
  form.addEventListener("change", (ev) => {
    if (ev.target && ev.target.name && ev.target.name !== "q") { krApply(); krReload(); }   // 선택 · 날짜는 바로 적용, 검색어는 검색 단추 · Enter
  });
  host.addEventListener("click", (ev) => {
    const t = ev.target && ev.target.closest ? ev.target.closest("button") : null;
    if (!t || !host.contains(t) || t.disabled) return;
    if (t.hasAttribute("data-kr-reset")) { krReset(); krReload(); return; }
    if (t.hasAttribute("data-kr-refresh")) { krApply(); krReload(); return; }
    if (t.hasAttribute("data-kr-csv")) { krDownload(t); return; }
    if (t.hasAttribute("data-kr-prev")) { st.offset = Math.max(0, st.offset - st.size); krReload(); return; }
    if (t.hasAttribute("data-kr-next")) { st.offset += st.size; krReload(); }
  });
  host.addEventListener("change", (ev) => {
    const sel = ev.target && ev.target.closest ? ev.target.closest("[data-kr-size]") : null;
    if (!sel) return;
    st.size = Number(sel.value) || KR_PAGE_SIZES[0];
    st.offset = 0;
    krReload();
  });

  return { krReload: () => krReload(), state: st };
}

let krControl = null;

/** 화면에 들어올 때(main.js) — 처음엔 그리고, 그 뒤로는 같은 조건으로 다시 읽는다. api 는 main.js 가 넘긴다. */
export function onKisResultsViewActivated({ api } = {}) {
  const host = document.getElementById("kr-root");
  if (!host || typeof api !== "function") return null;
  if (!krControl) krControl = mountKisResults(host, { api, esc: krEsc });
  return krControl.krReload();
}
