/**
 * 신호 순위 화면(화면 키 `signal-rank` · 로보 어드바이저 메뉴 — 2026-11-02 사용자 결정: 새 화면 「안 A」).
 *
 * 순위 표 · 서랍의 판단과 그리기는 js/signal-rank.js(TC-RKS)가 맡는다. 이 파일은 화면 칸(#sr-root)에 그것을 한 번 붙이고,
 * 화면에 들어올 때마다 순위를 다시 읽는다. 새로 계산하지 않는다(GET /api/stock-hub/signal-rank — 기록을 읽을 뿐).
 *
 * 2026-11-03: 표 위에 종목 검색 줄을 붙였다(「모든 종목을 검색해서 신호와 근거를 확인하고 싶다」 피드백) — 이름이나 코드를 치면
 * 종목 코드로 그 종목의 기록 한 줄만 읽고, 이름이 여럿이면 종목 찾기 창에서 고른다. app.html 은 건드리지 않고 칸을 여기서 만든다.
 */
import { api, escHtml } from "/js/common.js";
import { mountSignalRank, findQuery, findBarHtml, findNoteHtml } from "/js/signal-rank.js";
import { resolveSymbolInput } from "/js/stockfind.js";
import { openStockSearch } from "/js/company.js";

let srvControl = null;
let srvBar = null;

function srvNote(html) {
  const el = srvBar && srvBar.querySelector("[data-sr-find-note]");
  if (el) el.innerHTML = html;
}

/** 검색 칸의 글(코드 또는 이름)을 종목으로 풀어 그 종목의 기록 한 줄을 읽는다. 이름이 여럿이면 창에서 고른 뒤 이어서 한다. */
async function srvSearchSymbol(symbol, name = "") {
  const q = findQuery(symbol);
  if (!q.ok) { srvNote(escHtml(q.message)); return; }
  srvNote(findNoteHtml(q.code, name, escHtml));
  await srvControl.loadRankRows(q.query);
}

async function srvSubmit(input) {
  if (!String(input.value || "").trim()) { srvNote(escHtml("종목 이름이나 코드를 입력해 주세요. 비워 두려면 「전체 순위」 를 누르세요.")); return; }
  const sym = await resolveSymbolInput(document, input, {
    search: async q => ((await api(`/api/stocks/search?q=${encodeURIComponent(q)}`)).results) || [],
    open: openStockSearch,
    onPicked: item => { srvSearchSymbol(item && item.symbol, item && item.name); },   // 창에서 고르면 이어서 읽는다
  });
  if (sym) await srvSearchSymbol(sym);
}

function srvMountFind(host) {
  if (srvBar || !host.parentNode) return;
  srvBar = document.createElement("div");
  srvBar.id = "sr-find";
  srvBar.innerHTML = findBarHtml(escHtml);
  host.parentNode.insertBefore(srvBar, host);
  const input = srvBar.querySelector("#sr-find-input");
  srvBar.querySelector("form").addEventListener("submit", ev => { ev.preventDefault(); srvSubmit(input); });
  srvBar.querySelector("[data-sr-find-reset]").addEventListener("click", async () => {
    input.value = "";
    srvNote(escHtml("전체 순위로 돌아왔습니다."));
    await srvControl.loadRankRows();
  });
}

export async function onSignalRankViewActivated() {
  const host = document.getElementById("sr-root");
  if (!host) return;
  if (!srvControl) srvControl = mountSignalRank(host, { api, esc: escHtml });
  srvMountFind(host);
  const again = document.getElementById("sr-find-input");
  if (again) again.value = "";   // 전체 순위를 다시 읽으니 지난 검색어 · 안내도 처음으로
  srvNote(escHtml("기록된 종목 중에서 찾습니다. 종목을 고르면 그 종목의 규칙 신호와 근거를 봅니다 — 과거 자료 기준 참고용이며 투자 권유가 아닙니다."));
  await srvControl.loadRankRows();
}
