/**
 * 신호 순위 화면(화면 키 `signal-rank` · 로보 어드바이저 메뉴 — 2026-11-02 사용자 결정: 새 화면 「안 A」).
 *
 * 순위 표 · 서랍의 판단과 그리기는 js/signal-rank.js(TC-RKS)가 맡는다. 이 파일은 화면 칸(#sr-root)에 그것을 한 번 붙이고,
 * 화면에 들어올 때마다 순위를 다시 읽는다. 새로 계산하지 않는다(GET /api/stock-hub/signal-rank — 기록을 읽을 뿐).
 */
import { api, escHtml } from "/js/common.js";
import { mountSignalRank } from "/js/signal-rank.js";

let srvControl = null;

export async function onSignalRankViewActivated() {
  const host = document.getElementById("sr-root");
  if (!host) return;
  if (!srvControl) srvControl = mountSignalRank(host, { api, esc: escHtml });
  await srvControl.loadRankRows();
}
