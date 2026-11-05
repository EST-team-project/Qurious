"""TC-LBR — 리밸런싱 이력 · TradingView 수신 신호 · 데이터 관제 표의 필터 칩 + 새로고침 (public/js/rebalance.js · tradingview.js · datahub.js · screenlists.js · 2026-11-05 화면 전수 점검 뒤)

각 화면 파일의 실제 패널 설정 · 표 함수를 잘라 node 에서 가짜 DOM · 가짜 api 로 돌린다(서버 · app.html 은 건드리지 않았다).
1. 리밸런싱 실행 이력 — 상태(응답에 있는 값만 · 장이 안 열려 취소된 예약은 화면 배지처럼 「미체결」) · 트리거(한 회차에 둘이면 어느 쪽 칩으로도 보임) 칩,
   풀면 복귀, 새로고침이 서버를 다시 부르고 필터를 유지, 주문 상세는 걸러 남긴 회차만 그린다, 이스케이프. (TC-LBR-01, 02)
2. 입출금 이력 — 구분 칩(입금 · 출금 · 배당 + 응답에 있는 그 밖) · 이스케이프 · 빈 응답. (TC-LBR-03)
3. TradingView 수신 신호 — 방향(매수/매도/알림) · 처리 칩, 새로고침이 신호 + 교차 검증 이력을 함께 다시 읽고 필터를 유지, 빈 응답 · 이스케이프. (TC-LBR-04, 05)
4. 데이터 관제 — 판정 칩은 서버의 verdict_label 그대로 · 30초 자동 새로고침(화면 통째로 다시 그림)이 걸어 둔 칩을 지우지 않는다 ·
   「수집 자료 없음」 안내는 거르기 전 전체로 판단 · 이스케이프. (TC-LBR-06, 07)
5. 구조 — 화면의 배지 · 라벨 낱말이 칩과 어긋나면 여기서 먼저 깨진다 · 쓰기 단추를 이 파일들이 새로 부르지 않는다. (TC-LBR-08)
node 가 없으면 1~4 는 건너뛴다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js"
LISTBAR = (JS / "listbar.js").read_text(encoding="utf-8")
LISTS = (JS / "paperlists.js").read_text(encoding="utf-8")
SCREENLISTS = (JS / "screenlists.js").read_text(encoding="utf-8")
REBAL = (JS / "rebalance.js").read_text(encoding="utf-8")
TV = (JS / "tradingview.js").read_text(encoding="utf-8")
HUB = (JS / "datahub.js").read_text(encoding="utf-8")
HTML = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _fn(src: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {name}\(", src, re.M)
    assert m, name
    return src[m.start():src.index("\n}\n", m.start()) + 3]


def _const(src: str, name: str) -> str:
    """한 줄 `const x = …;` 또는 여러 줄 `const x = {` … `};`."""
    m = re.search(rf"^const {name} = ", src, re.M)
    assert m, name
    line_end = src.index("\n", m.start())
    if src[m.start():line_end].rstrip().endswith(";"):
        return src[m.start():line_end + 1]
    return src[m.start():src.index("\n};\n", m.start()) + 4]


def _line(src: str, startswith: str) -> str:
    m = re.search(rf"^{re.escape(startswith)}.*$", src, re.M)
    assert m, startswith
    return m.group(0)


def _panel(src: str, name: str) -> str:
    start = src.index(f"const {name} = createScreenPanel(")
    line_end = src.index("\n", src.index("}, { esc: escHtml, byId", start)) + 1
    return src[start:line_end]


def _modules() -> str:
    out = []
    for p in (LISTBAR, LISTS, SCREENLISTS):
        p = re.sub(r"^import [^\n]*\n", "", p, flags=re.M)
        out.append(re.sub(r"^export ", "", p, flags=re.M))
    return "\n".join(out)


PRELUDE = textwrap.dedent("""
    const escHtml = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    const fmt = (n, d = 0) => n == null ? "-" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });
    function makeEl() {
      return { innerHTML: "", textContent: "", disabled: false, dataset: {}, listeners: [], attrs: {},
        addEventListener(t, f) { this.listeners.push([t, f]); }, contains() { return true; },
        querySelector() { return null; }, querySelectorAll() { return []; }, setAttribute(k, v) { this.attrs[k] = v; }, focus() {} };
    }
    const els = {};
    const byIdFake = id => (els[id] ||= makeEl());
    const $ = byIdFake;
    const calls = [];
    let routes = {};
    async function api(path, opts) {
      calls.push({ path, method: (opts && opts.method) || "GET" });
      const r = routes[path.split("?")[0]];
      if (typeof r === "function") return r();
      if (r instanceof Error) throw r;
      if (r === undefined) throw new Error("가짜 경로 없음 " + path);
      return JSON.parse(JSON.stringify(r));
    }
    const pressed = html => [...html.matchAll(/data-lb-filter="([^"]+)" data-value="([^"]+)" aria-pressed="true"/g)].map(m => m[1] + "=" + m[2]);
    const chips = (html, key) => [...html.matchAll(new RegExp('data-lb-filter="' + key + '" data-value="([^"]*)"[^>]*>([^<]*)<', "g"))].map(m => m[1] + ":" + m[2]);
    const note = html => (html.match(/data-lb-note[^>]*>([^<]*)</) || [])[1];
""")

def _scope(parts: list[str], exports: str) -> str:
    """세 화면 파일이 같은 이름(ts · STATUS_BADGE)을 따로 갖고 있어, 파일마다 함수 범위로 감싸 필요한 것만 꺼낸다."""
    return "(() => {\n" + "\n".join(parts) + "\nreturn { " + exports + " };\n})()"


REBAL_SRC = "const REB = " + _scope([
    _const(REBAL, "won"), _const(REBAL, "ts"), _const(REBAL, "TRIGGER_LABEL"), _const(REBAL, "STATUS_BADGE"), _const(REBAL, "KIND_LABEL"),
    "const rendered = []; const renderOrders = (orders, id) => rendered.push(id); const executeRebalance = () => {}; const cancelReservation = () => {};",
    _fn(REBAL, "cashflowTableHtml"), _panel(REBAL, "cashflowPanel"), _fn(REBAL, "runCardHtml"), _panel(REBAL, "runsPanel"),
], "runsPanel, cashflowPanel, rendered") + ";\nconst { runsPanel, cashflowPanel, rendered } = REB;"
TV_SRC = "const TVX = " + _scope([
    _const(TV, "ts"), _const(TV, "STATUS_BADGE"), _fn(TV, "signalsTableHtml"), _fn(TV, "loadComparisons"), _panel(TV, "signalsPanel"),
], "signalsPanel") + ";\nconst { signalsPanel } = TVX;"
HUB_SRC = "const HUB = " + _scope([
    _const(HUB, "VERDICT_CLASS"), _fn(HUB, "mmdd"), _fn(HUB, "pill"), _line(HUB, "let tableFilters"), _line(HUB, "let shownStatus"),
    _fn(HUB, "tableCard"), _fn(HUB, "setTableFilter"),
    # 화면 뿌리 — 표 칸(box)을 바꿔 쓰는 것만 흉내 낸다
    "const box = { html: '' }; Object.defineProperty(box, 'outerHTML', { set(v) { this.html = v; } });",
    "const hubRoot = { querySelector: sel => (sel === '[data-dh-tables]' ? box : null), querySelectorAll: () => [] }; const dataHubRoot = () => hubRoot;",
], "tableCard, setTableFilter, box, setStatus: v => { shownStatus = v; }, setFilters: v => { tableFilters = v; }") + ";\nconst { tableCard, setTableFilter, box } = HUB;"


def _run(body: str):
    js = "\n".join([_modules(), PRELUDE, REBAL_SRC, TV_SRC, HUB_SRC, textwrap.dedent(body)])
    out = subprocess.run([NODE, "--input-type=module", "-"], input=js, capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


RUNS = """
const run = (id, status, trigger, extra = {}) => ({ id, status, trigger, plan_kind: "full", decision_date: "2026-11-05", total_asset: 10000000, max_drift_pct: 1.2, orders: [],
  target_weights: { A: 50, CASH: 50 }, before_weights: { A: 40, CASH: 60 }, note: "", context: {}, created_at: "2026-11-05T01:00:00Z", ...extra });
const RUNS = [
  run("R1", "proposed", "TIME"),
  run("R2", "scheduled", "DRIFT", { context: { price_basis: "previous_close", valuation_date: "2026-11-04" } }),
  run("R3", "executed", "DRIFT", { triggers: ["DRIFT", "CASHFLOW"] }),
  run("R4", "cancelled", "MANUAL", { context: { cancel_reason: "open_not_tradable" } }),
  run("R5", "failed", "TIME"),
];
const ids = html => [...html.matchAll(/id="rb-run-([^"]+)"/g)].map(m => m[1]);
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_rebalance_run_chips_status_and_multi_trigger():
    """TC-LBR-01 · 상태 칩은 응답에 있는 값만(취소 + open_not_tradable 은 배지처럼 「미체결」) · 트리거는 한 회차에 둘이면 어느 쪽으로도 보임 · 겹쳐 걸기 · 풀면 복귀 · 주문 상세는 걸러 남긴 회차만."""
    got = _run(RUNS + """
      routes = { "/api/rebalance/runs": { runs: RUNS } };
      await runsPanel.load();
      const html = () => els["rb-runs"].innerHTML;
      const out = { all: ids(html()), statusChips: chips(html(), "status"), triggerChips: chips(html(), "trigger"), hasRefresh: html().includes("data-lb-refresh"), note0: note(html()) };
      const each = {};
      // 칩을 걸고 → [그려진 회차, 주문 상세를 그린 회차]
      const apply = (k, v) => { rendered.length = 0; runsPanel.setFilter(k, v); return [ids(html()), rendered.map(x => x.replace("rb-run-", ""))]; };
      each.scheduled = apply("status", "scheduled");
      each.openNot = apply("status", "open_not_tradable");
      apply("status", "");
      each.cashflow = apply("trigger", "CASHFLOW");
      each.drift = apply("trigger", "DRIFT");
      each.time = apply("trigger", "TIME");                                  // 앞 칩에서 바꾸면 새 칩 기준으로 다시 거른다
      each.timeFailed = apply("status", "failed"); out.pressed = pressed(html()); out.noteBoth = note(html());
      runsPanel.setFilter("trigger", ""); runsPanel.setFilter("status", ""); out.released = ids(html());
      out.each = each;
      console.log(JSON.stringify(out));
    """)
    assert got["all"] == ["R1", "R2", "R3", "R4", "R5"] and got["hasRefresh"] is True
    assert got["statusChips"] == [":전체", "proposed:제안", "scheduled:시가 체결 대기", "executed:체결", "open_not_tradable:미체결", "failed:실패"], got["statusChips"]
    assert got["triggerChips"] == [":전체", "TIME:시간", "DRIFT:이탈률", "CASHFLOW:현금흐름", "MANUAL:수동"]
    e = got["each"]
    assert e["scheduled"] == [["R2"], ["R2"]] and e["openNot"] == [["R4"], ["R4"]], "주문 상세는 보이는 회차만 그린다"
    assert e["cashflow"] == [["R3"], ["R3"]]
    assert e["drift"] == [["R2", "R3"], ["R2", "R3"]], "트리거가 둘인 회차(R3)는 이탈률 칩으로도 보인다"
    assert e["time"] == [["R1", "R5"], ["R1", "R5"]]
    assert e["timeFailed"] == [["R5"], ["R5"]] and got["pressed"] == ["status=failed", "trigger=TIME"]
    assert "받은 5건 중 1건" in got["noteBoth"] and "서버가 최근 20건까지" in got["noteBoth"]
    assert got["released"] == got["all"], "조건을 풀면 전부 돌아온다"
    assert "한 회차에 트리거가 둘이면" in got["note0"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_rebalance_run_refresh_keeps_filter_escape_and_only_reads():
    """TC-LBR-02 · 새로고침 = 서버 다시 읽기(GET) + 시각 + 「계산 · 실행하지 않습니다」 · 걸어 둔 칩 유지 · 눌러 둔 값이 응답에서 사라져도 칩이 남음 · 이스케이프 · 빈 응답 · 승인/예약 취소 단추는 그려질 뿐 누르지 않는다."""
    got = _run(RUNS + """
      routes = { "/api/rebalance/runs": { runs: RUNS } };
      await runsPanel.load();
      runsPanel.setFilter("status", "scheduled");
      const html = () => els["rb-runs"].innerHTML;
      const out = { hasCancelBtn: html().includes("rb-cancel"), hasApproveHidden: !html().includes("rb-approve") };
      routes = { "/api/rebalance/runs": { runs: [run("R9", "scheduled", "TIME", { note: "<script>alert(1)</script>" }), run("R8", "executed", "CASHFLOW")] } };
      const before = calls.length;
      await runsPanel.refresh();
      out.newCalls = calls.slice(before).map(c => c.path); out.afterRefresh = ids(html()); out.pressed = pressed(html()); out.noteAfter = note(html()); out.html = html();
      // 눌러 둔 값(scheduled)이 새 응답에서 사라져도 칩은 남아 풀 수 있다
      routes = { "/api/rebalance/runs": { runs: [run("R7", "executed", "TIME")] } };
      await runsPanel.refresh();
      out.goneChips = chips(html(), "status"); out.goneBody = html().includes("이 조건에 맞는 건이 없습니다");
      runsPanel.setFilter("status", "");
      routes = { "/api/rebalance/runs": { runs: [] } };
      await runsPanel.refresh();
      out.empty = html(); out.methods = [...new Set(calls.map(c => c.method))];
      console.log(JSON.stringify(out));
    """)
    assert got["hasCancelBtn"] is True, "예약 취소 단추는 그대로 그려진다(이 시험은 누르지 않는다)"
    assert got["newCalls"] == ["/api/rebalance/runs?limit=20"] and got["afterRefresh"] == ["R9"] and got["pressed"] == ["status=scheduled"]
    assert "서버에서 다시 읽었습니다" in got["noteAfter"] and "리밸런싱을 새로 계산 · 실행하지 않습니다" in got["noteAfter"]
    assert "<script>" not in got["html"] and "&lt;script&gt;alert(1)&lt;/script&gt;" in got["html"]
    assert "scheduled:시가 체결 대기" in got["goneChips"] and got["goneBody"] is True
    assert "아직 리밸런싱 이력이 없습니다." in got["empty"] and "data-lb-refresh" in got["empty"]
    assert got["methods"] == ["GET"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_rebalance_cashflow_kind_chips():
    """TC-LBR-03 · 입금 · 출금 · 배당 칩은 늘 있고 응답에 있는 그 밖의 구분은 낱말 그대로 덧붙는다 · 걸면 맞는 줄만 · 이스케이프 · 새로고침이 서버를 다시 부르고 필터 유지 · 빈 응답."""
    got = _run("""
      const ev = (m, kind, extra = {}) => ({ created_at: "2026-11-05T01:00:00Z", kind, amount: 100000, symbol: "", memo: m, cash_after: 5000000, rebalance_run_id: null, ...extra });
      const EVENTS = [ev("M1", "DEPOSIT"), ev("M2", "WITHDRAW"), ev("M3", "DIVIDEND", { symbol: "005930" }), ev("M4", "ODD<b>"), ev("<i>M5</i>", "DEPOSIT")];
      const memos = html => [...html.matchAll(/<td class="text-xs">(M\\d|&lt;i&gt;M5&lt;\\/i&gt;)<\\/td>/g)].map(m => m[1]);
      routes = { "/api/rebalance/cashflows": { events: EVENTS } };
      await cashflowPanel.load();
      const html = () => els["rb-cashflows"].innerHTML;
      const out = { all: memos(html()), kindChips: chips(html(), "kind"), html: html() };
      cashflowPanel.setFilter("kind", "DEPOSIT"); out.deposit = memos(html()); out.note = note(html());
      routes = { "/api/rebalance/cashflows": { events: [...EVENTS, ev("M6", "DEPOSIT")] } };
      const before = calls.length;
      await cashflowPanel.refresh();
      out.newCalls = calls.slice(before).map(c => c.path); out.afterRefresh = memos(html()); out.pressed = pressed(html());
      cashflowPanel.setFilter("kind", "");
      routes = { "/api/rebalance/cashflows": { events: [] } };
      await cashflowPanel.refresh();
      out.empty = html(); out.methods = [...new Set(calls.map(c => c.method))];
      console.log(JSON.stringify(out));
    """)
    assert got["kindChips"] == [":전체", "DEPOSIT:입금", "WITHDRAW:출금", "DIVIDEND:배당", "ODD<b>:ODD&lt;b&gt;"] or \
        [c.split(":", 1)[0] for c in got["kindChips"]][:4] == ["", "DEPOSIT", "WITHDRAW", "DIVIDEND"], got["kindChips"]
    assert not any("<b>" in c for c in got["kindChips"]) and "ODD<b>" not in got["html"], "서버 낱말은 이스케이프"
    assert got["all"][:3] == ["M1", "M2", "M3"] and got["deposit"] == ["M1", "&lt;i&gt;M5&lt;/i&gt;"]
    assert "받은 5건 중 2건" in got["note"] and "서버가 최근 20건까지" in got["note"]
    assert got["newCalls"] == ["/api/rebalance/cashflows?limit=20"] and got["afterRefresh"] == ["M1", "&lt;i&gt;M5&lt;/i&gt;", "M6"] and got["pressed"] == ["kind=DEPOSIT"]
    assert "아직 입출금·배당 이벤트가 없습니다." in got["empty"] and got["methods"] == ["GET"]


TV_SIGNALS = """
const sg = (sym, side, status, extra = {}) => ({ created_at: "2026-11-05T01:00:00Z", strategy: "S", symbol: sym, side, quantity: 1, signal_price: 71000, fill_price: 0, status, message: "", ...extra });
const SIGNALS = [sg("S1", "BUY", "filled"), sg("S2", "SELL", "rejected"), sg("S3", "", "alert"), sg("S4", "BUY", "duplicate"), sg("S5", "weird", "error")];
const syms = html => [...html.matchAll(/<td class="font-mono text-xs">([^<]*)<\\/td>/g)].map(m => m[1]);
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_tradingview_signal_chips_and_refresh_rereads_comparisons_too():
    """TC-LBR-04 · 방향(매수/매도/알림 — 표가 보이는 규칙 그대로) · 처리 칩(응답에 있는 값만) · 새로고침 단추가 신호 + 교차 검증 이력을 함께 다시 읽는다 · 걸어 둔 칩 유지 · 쓰기 요청 0."""
    got = _run(TV_SIGNALS + """
      routes = { "/api/tradingview/signals": { signals: SIGNALS }, "/api/tradingview/comparisons": { comparisons: [] } };
      await signalsPanel.load();
      const html = () => els["tv-signals"].innerHTML;
      const out = { all: syms(html()), dirChips: chips(html(), "dir"), statusChips: chips(html(), "status"), loadCalls: calls.map(c => c.path) };
      const each = {};
      signalsPanel.setFilter("dir", "BUY"); each.buy = syms(html());
      signalsPanel.setFilter("dir", "SELL"); each.sell = syms(html());
      signalsPanel.setFilter("dir", "ALERT"); each.alert = syms(html());
      signalsPanel.setFilter("dir", ""); signalsPanel.setFilter("status", "duplicate"); each.dup = syms(html());
      signalsPanel.setFilter("dir", "BUY"); each.buyDup = syms(html()); out.pressed = pressed(html()); out.note = note(html());
      signalsPanel.setFilter("dir", ""); signalsPanel.setFilter("status", ""); out.released = syms(html());
      // 머리줄의 새로고침 단추 — 눌러도 신호 칩이 유지되고 교차 검증 이력(tvc-history)도 다시 읽는다
      signalsPanel.setFilter("dir", "BUY");
      routes = { "/api/tradingview/signals": { signals: [...SIGNALS, sg("S6", "BUY", "filled")] },
                 "/api/tradingview/comparisons": { comparisons: [{ created_at: "2026-11-05T01:00:00Z", ticker: "005930", strategy: "ma_cross", start_date: "2025-11-05", end_date: "2026-11-05",
                   verdict: "<b>v</b>", tv_metrics: {}, lean_metrics: {} }] } };
      const btn = makeEl();
      bindRefreshButton(btn, signalsPanel); bindRefreshButton(btn, signalsPanel);      // 두 번 불러도 한 번만 잇는다
      out.listeners = btn.listeners.length;
      const before = calls.length;
      await btn.listeners[0][1]();
      out.newCalls = calls.slice(before).map(c => c.path).sort(); out.afterRefresh = syms(html()); out.pressedAfter = pressed(html());
      out.noteAfter = note(html()); out.btnDisabled = btn.disabled; out.history = els["tvc-history"].innerHTML; out.methods = [...new Set(calls.map(c => c.method))];
      out.each = each;
      console.log(JSON.stringify(out));
    """)
    assert got["all"] == ["S1", "S2", "S3", "S4", "S5"]
    assert got["dirChips"] == [":전체", "BUY:매수", "SELL:매도", "ALERT:알림"]
    assert got["statusChips"] == [":전체", "filled:체결", "alert:알림", "duplicate:중복", "rejected:거절", "error:오류"], got["statusChips"]
    assert got["loadCalls"] == ["/api/tradingview/signals?limit=30"], "처음 읽기는 신호만(교차 검증 이력은 화면이 따로 읽는다)"
    e = got["each"]
    assert e["buy"] == ["S1", "S4"] and e["sell"] == ["S2"] and e["alert"] == ["S3", "S5"], "BUY · SELL 이 아닌 방향은 표처럼 알림"
    assert e["dup"] == ["S4"] and e["buyDup"] == ["S4"] and got["pressed"] == ["dir=BUY", "status=duplicate"]
    assert "받은 5건 중 1건" in got["note"] and "서버가 최근 30건까지" in got["note"]
    assert got["released"] == got["all"]
    assert got["listeners"] == 1 and got["newCalls"] == ["/api/tradingview/comparisons?limit=15", "/api/tradingview/signals?limit=30"], "새로고침 = 신호 + 교차 검증 이력"
    assert got["afterRefresh"] == ["S1", "S4", "S6"] and got["pressedAfter"] == ["dir=BUY"], "걸어 둔 칩 유지"
    assert "저장된 값에서 다시 읽은 것이고 신호를 보내거나 LEAN 비교를 다시 돌리지 않습니다" in got["noteAfter"]
    assert got["btnDisabled"] is False and got["methods"] == ["GET"]
    assert "&lt;b&gt;v&lt;/b&gt;" in got["history"] and "<b>v</b>" not in got["history"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_tradingview_signals_escape_empty_and_failed_refresh():
    """TC-LBR-05 · 이스케이프 · 빈 응답에도 칩 줄 · 신호를 읽지 못하면 시각을 찍지 않는다."""
    got = _run(TV_SIGNALS + """
      routes = { "/api/tradingview/signals": { signals: [sg("<img src=x>", "BUY", "late<b>", { message: "<script>1</script>" })] }, "/api/tradingview/comparisons": { comparisons: [] } };
      await signalsPanel.load();
      const html = () => els["tv-signals"].innerHTML;
      const out = { html: html(), statusChips: chips(html(), "status") };
      routes = { "/api/tradingview/signals": new Error("서버 오류"), "/api/tradingview/comparisons": { comparisons: [] } };
      const ok = await signalsPanel.refresh();
      out.failOk = ok; out.failNote = note(html());
      routes = { "/api/tradingview/signals": { signals: [] }, "/api/tradingview/comparisons": { comparisons: [] } };
      await signalsPanel.refresh();
      out.empty = html();
      console.log(JSON.stringify(out));
    """)
    assert "<img" not in got["html"] and "&lt;img src=x&gt;" in got["html"] and "&lt;script&gt;1&lt;/script&gt;" in got["html"]
    assert not any("<" in c for c in got["statusChips"])
    assert got["failOk"] is False and "다시 읽지 못했습니다" in got["failNote"] and "다시 읽었습니다" not in got["failNote"]
    assert "아직 수신된 TradingView 신호가 없습니다" in got["empty"] and 'data-lb-filter="dir"' in got["empty"]


HUB_STATUS = """
const tb = (label, verdict, verdict_label, extra = {}) => ({ label, source: "krx", last_date: "2026-11-04", verdict, verdict_label, rows: 10, detail: "", ...extra });
const ST = { checked_at: "2026-11-05T10:00:00", calendar: { previous_trading_day: "2026-11-04" }, tables: [
  tb("T1", "fresh", "최신"), tb("T2", "late", "늦음"), tb("T3", "stale", "멈춤"), tb("T4", "info", "참고"), tb("T5", "late", "늦음 · 다시 받기"), tb("T6", "ok", "정상 · 공개 전"),
] };
const labels = html => [...html.matchAll(/class="dh-name">([^<]*)</g)].map(m => m[1]);
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_datahub_verdict_chips_survive_auto_refresh():
    """TC-LBR-06 · 판정 칩은 서버 verdict_label 그대로 · 걸면 맞는 줄만 · 30초 자동 새로고침(화면 통째로 다시 그림)이 걸어 둔 칩을 지우지 않는다 · 사라진 판정의 칩도 남아 풀 수 있다 · 허용 밖 낱말은 무시."""
    got = _run(HUB_STATUS + """
      HUB.setStatus(ST);
      const out = { html0: tableCard(ST) };
      out.all = labels(out.html0); out.chips = chips(out.html0, "verdict");
      setTableFilter("verdict", "late"); const late = box.html;
      out.late = labels(late); out.pressed = pressed(late); out.note = note(late);
      setTableFilter("verdict", "<script>"); out.ignored = labels(box.html);
      // 30초 뒤 자동 새로고침 — 응답이 바뀌었다(늦음 → 모두 최신). 화면은 tableCard 를 다시 부르지만 필터는 모듈 변수에 남아 있다
      const ST2 = { ...ST, tables: ST.tables.map(t => (t.verdict === "late" ? { ...t, verdict: "fresh", verdict_label: "최신" } : t)) };
      HUB.setStatus(ST2);
      const auto = tableCard(ST2);
      out.auto = labels(auto); out.autoPressed = pressed(auto); out.autoChips = chips(auto, "verdict"); out.autoEmptyMsg = auto.includes("이 조건에 맞는 자료가 없습니다");
      setTableFilter("verdict", ""); out.released = labels(box.html);
      console.log(JSON.stringify(out));
    """)
    assert got["all"] == ["T1", "T2", "T3", "T4", "T5", "T6"]
    assert got["chips"] == [":전체", "fresh:최신", "ok:정상", "late:늦음", "stale:멈춤", "info:참고"], "같은 판정이라도 줄마다 글이 달라질 수 있어(정상 · 공개 전) 칩은 판정의 기본 글"
    assert got["late"] == ["T2", "T5"] and got["pressed"] == ["verdict=late"]
    assert "조건 늦음" in got["note"] and "받은 6개 중 2개" in got["note"]
    assert got["ignored"] == ["T2", "T5"], "허용 밖 낱말은 무시(필터 그대로)"
    assert got["auto"] == [] and got["autoEmptyMsg"] is True, "응답에서 사라진 판정이라도 걸린 조건은 유지된다"
    assert got["autoPressed"] == ["verdict=late"] and "late:늦음" in got["autoChips"], "사라진 판정의 칩이 남아 풀 수 있다"
    assert got["released"] == got["all"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_datahub_no_data_notice_uses_unfiltered_tables_escape_and_empty():
    """TC-LBR-07 · 「수집 자료 없음」 안내는 거르기 전 전체로 판단 · 서버 글 이스케이프 · 표가 비어도 안 깨진다."""
    got = _run(HUB_STATUS + """
      const allMissing = { ...ST, tables: [tb("M1", "missing", "없음"), tb("M2", "missing", "없음")] };
      HUB.setStatus(allMissing);
      const out = {};
      const none0 = tableCard(allMissing);
      out.noticeAll = none0.includes("이 PC 에는 수집 자료가 없습니다"); out.chips = chips(none0, "verdict");
      setTableFilter("verdict", "missing"); out.noticeFiltered = box.html.includes("이 PC 에는 수집 자료가 없습니다"); out.filtered = labels(box.html);
      // 일부만 없음 — 거른 결과가 전부 「없음」 이어도 전체가 다 없음은 아니므로 안내가 뜨지 않는다
      const mixed = { ...ST, tables: [tb("A", "fresh", "최신"), tb("B", "missing", "없음")] };
      HUB.setStatus(mixed);
      out.noticeMixed = tableCard(mixed).includes("이 PC 에는 수집 자료가 없습니다");
      // 이스케이프
      const evil = { ...ST, tables: [tb("<b>X</b>", "late", "<img src=x>")] };
      HUB.setStatus(evil);
      HUB.setFilters({});
      const e = tableCard(evil);
      out.evil = e; out.evilChips = chips(e, "verdict");
      // 빈 표
      HUB.setStatus({ ...ST, tables: [] });
      HUB.setFilters({});
      out.emptyOk = tableCard({ ...ST, tables: [] }).includes("data-dh-tables");
      out.noTables = tableCard({ ...ST }).length > 0;
      console.log(JSON.stringify(out));
    """)
    assert got["noticeAll"] is True and got["noticeFiltered"] is True and got["noticeMixed"] is False
    assert got["filtered"] == ["M1", "M2"]
    assert "<b>X</b>" not in got["evil"] and "&lt;b&gt;X&lt;/b&gt;" in got["evil"] and "<img" not in got["evil"]
    assert not any("<" in c for c in got["evilChips"])
    assert got["emptyOk"] is True and got["noTables"] is True


def test_screens_structure_and_vocabulary_match():
    """TC-LBR-08 · 화면 연결은 서버 인자를 더하지 않고 · 칩 낱말이 화면의 배지 · 라벨과 어긋나지 않으며 · 새로 쓰기 요청을 부르지 않는다."""
    # 순수 모듈 — DOM · 네트워크 · 쓰기 없음
    assert "document." not in SCREENLISTS and "fetch(" not in SCREENLISTS and "api(" not in SCREENLISTS and "POST" not in SCREENLISTS
    # 화면 칸은 app.html 에 그대로 있다(이 작업은 app.html 을 고치지 않는다)
    for hid in ('id="rb-runs"', 'id="rb-cashflows"', 'id="rb-refresh"', 'id="tv-signals"', 'id="tv-refresh"', 'id="tvc-history"', '<div class="dh-root">'):
        assert hid in HTML, hid
    # 요청 개수 = 안내 글의 개수
    assert "limit=${REBAL_RUNS_LIMIT}" in REBAL and "limit=${REBAL_CASHFLOWS_LIMIT}" in REBAL
    assert "limit=${TV_SIGNALS_LIMIT}" in TV and "limit=${TV_COMPARISONS_LIMIT}" in TV
    for name, n in (("REBAL_RUNS_LIMIT", 20), ("REBAL_CASHFLOWS_LIMIT", 20), ("TV_SIGNALS_LIMIT", 30), ("TV_COMPARISONS_LIMIT", 15)):
        assert f"{name} = {n};" in SCREENLISTS, name
    # 상태 라벨 — 화면의 배지 글과 칩 글이 같다
    badge = lambda src: dict(re.findall(r"(\w+): `<span class=\"badge-\w+\">([^<]+)</span>`", _const(src, "STATUS_BADGE")))
    tv_labels = dict(re.findall(r"(\w+): \"([^\"]+)\"", re.search(r"TV_STATUS_LABEL = \{([^}]*)\}", SCREENLISTS).group(1)))
    assert tv_labels == badge(TV), (tv_labels, badge(TV))
    rb_labels = dict(re.findall(r"(\w+): \"([^\"]+)\"", re.search(r"REBAL_STATUS_LABEL = \{([^}]*)\}", SCREENLISTS, re.S).group(1)))
    rb_badge = badge(REBAL)
    assert {k: v for k, v in rb_labels.items() if k != "open_not_tradable"} == rb_badge, (rb_labels, rb_badge)
    assert rb_labels["open_not_tradable"] == "미체결" and "'<span class=\"badge-hold\">미체결</span>'" in REBAL, "취소 + open_not_tradable 은 배지가 「미체결」"
    trig_screen = dict(re.findall(r"(\w+): \"([^\"]+)\"", re.search(r"TRIGGER_LABEL = \{([^}]*)\}", REBAL).group(1)))
    trig_chip = dict(re.findall(r"(\w+): \"([^\"]+)\"", re.search(r"REBAL_TRIGGER_LABEL = \{([^}]*)\}", SCREENLISTS).group(1)))
    assert trig_chip == trig_screen
    kind_screen = dict(re.findall(r"(\w+): `<span class=\"badge-\w+\">([^<]+)</span>`", _fn(REBAL, "cashflowTableHtml")))
    kind_chip = dict(re.findall(r"(\w+): \"([^\"]+)\"", re.search(r"REBAL_KIND_LABEL = \{([^}]*)\}", SCREENLISTS).group(1)))
    assert kind_chip == kind_screen
    # 데이터 관제 판정 기본 글 = 서버가 판정마다 쓰는 글(같은 판정이라도 줄마다 verdict_label 이 달라질 수 있다)
    server = (ROOT / "app" / "services" / "data_status.py").read_text(encoding="utf-8")
    server_labels = dict(re.findall(r'"(\w+)": "([^"]+)"', re.search(r"VERDICT_LABEL = \{([^}]*)\}", server).group(1)))
    chip_labels = dict(re.findall(r"(\w+): \"([^\"]+)\"", re.search(r"DATA_VERDICT_LABEL = \{([^}]*)\}", SCREENLISTS).group(1)))
    assert chip_labels == server_labels, (chip_labels, server_labels)
    # 새로고침 연결 — 클릭 이벤트가 첫 인자로 새지 않게 화살표로 감싼다 · 신호 새로고침은 교차 검증 이력도 부른다
    assert 'on("rb-refresh", "click", () => loadStatus({ stamp: true }))' in REBAL
    assert 'bindRefreshButton($("tv-refresh"), signalsPanel)' in TV and "alsoOnRefresh: () => loadComparisons()" in TV
    # 데이터 관제: 진입 훅 글자 그대로(화면 스캐너가 읽는다) · 칩 처리기는 root 에 한 번 · 표 거르기는 서버를 다시 부르지 않는다
    assert 'if (view !== "data-status") return;' in HUB and "bindListBar(root, { onFilter: setTableFilter })" in HUB
    set_filter = _fn(HUB, "setTableFilter")
    assert "fetchStatus" not in set_filter and "api(" not in set_filter
    # 쓰기 단추 처리(주문 · 취소 · 발송 · 저장 · 실행)는 새 모듈이 알지 못한다
    for word in ("executeRebalance", "cancelReservation", "sendTestSignal", "runCompare", "noti-test", "kis/orders"):
        assert word not in SCREENLISTS, word
