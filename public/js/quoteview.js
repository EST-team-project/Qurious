/* 시세 표시 판단 — DOM 없이 글 · 표시만 정한다(node 로 시험 · TC-QVS · 2026-10-16).
 *
 * 왜 따로 두나 — 미국주식 화면(us.js)은 강사님 기초 코드라 부르는 몇 줄만 두고 규칙은 여기 한 곳에(S86 규칙).
 *
 * 무엇을 정하나(Figma 「모의투자 여정 고치기」 03-5 융합안 · 2026-10-16 결정)
 *   pctText(v)   전일 대비 등락률 글 — 모르면 「—」(0 으로 메우지 않는다 · 서버도 None 을 준다 · DF-123)
 *   moveTag(v)   ±MOVE_LIMIT % 를 넘을 때만 「▲ 크게 오름」 · 「▼ 크게 내림」 · 그 밖(보합권 · 모름)은 빈 글
 *                — 규칙 표시일 뿐 매매 신호가 아니라서 BUY · SELL 낱말을 쓰지 않는다(옛 화면은 이 규칙을 「AI 시그널」 이라 불렀다)
 *   asOfText(s)  서버 시세 시각 「YYYY-MM-DD HH:MM」(KST) → 「마지막 체결 MM-DD HH:MM(KST)」 · 모르면 빈 글
 */

/** 크게 움직였다고 표시하는 전일 대비 기준(%) — 옛 화면의 BUY · SELL 문턱과 같은 값(강사님 us.js 의 1.5). */
export const MOVE_LIMIT = 1.5;

const isNum = v => typeof v === "number" && Number.isFinite(v);

/** 등락률 글 — 숫자는 common.js `fmtPct` 와 같은 꼴(+0.27% · -1.29% · 0 은 +0.00%) · 모르면 「—」
 *  (fmtPct 는 모르면 「-」 라 빼기 부호와 헷갈린다 — 이 화면은 줄표로 가른다 · node 시험이 두 꼴을 맞댄다). */
export function pctText(v) {
  if (!isNum(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

/** 등락 방향 — 색을 고를 때만 쓴다. 모르면 "none". */
export function direction(v) {
  if (!isNum(v)) return "none";
  return v > 0 ? "up" : v < 0 ? "down" : "flat";
}

/** ±MOVE_LIMIT % 를 넘은 종목에만 붙이는 사실 표시 — { text, dir } · 그 밖은 { text: "", dir: "none" }. */
export function moveTag(v) {
  if (!isNum(v) || Math.abs(v) < MOVE_LIMIT) return { text: "", dir: "none" };
  return v > 0 ? { text: "▲ 크게 오름", dir: "up" } : { text: "▼ 크게 내림", dir: "down" };
}

/** 서버 시세 시각 → 「마지막 체결 10-16 05:00(KST)」 · 꼴이 다르거나 없으면 빈 글(지어내지 않는다). */
export function asOfText(s) {
  const m = /^\d{4}-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/.exec(String(s || ""));
  return m ? `마지막 체결 ${m[1]}-${m[2]} ${m[3]}:${m[4]}(KST)` : "";
}
