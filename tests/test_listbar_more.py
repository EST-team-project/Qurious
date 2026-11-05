"""TC-LBF — 자유 산식 계산 결과 목록 · 투자 정보 리서치 · 상품 안내의 필터 칩 / 새로고침 (public/js/listbar-more.js · formula.js · research.js · products.js · 2026-11-05 화면 전수 점검 뒤)

paperlists.js 의 제어기(createListPanel) 위에 얹은 설정과, 두 화면(리서치 · 상품 안내)의 새로고침 함수를 node 에서 가짜 DOM · 가짜 api 로 돌린다.
1. indicator-formula 결과 목록 — 종목 · 버전 칩(응답 값만) · 칩이 맞는 줄만 · 풀면 복귀 · 새로고침이 결과 목록(GET)만 다시 부르고 계산(compute · POST)은 부르지 않는다 ·
   필터 유지 · 실패하면 시각을 안 찍는다 · 「보기」 는 누를 때만 · 지표를 바꾸면 칩을 푼다 · 이스케이프 · 빈 응답. (TC-LBF-01)
2. agent-news — 새로고침이 지금 조건 그대로 다시 받고(조건을 바꾸지 않는다) 실패하면 시각을 안 찍는다 · 받는 중 다시 누르면 무시. (TC-LBF-02)
3. agent-products — 새로고침이 한눈에 · 비중만 다시 읽고(예금 · 적금 호출 없음) 실패하면 보이던 목록을 그대로 둔다 · 받는 중 다시 누르면 무시. (TC-LBF-03)
4. 구조 — 새 모듈은 계산 · 저장 길을 모른다 · 화면 파일이 새 모듈을 가져온다. (TC-LBF-04)
node 가 없으면 1~3 은 건너뛴다.
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
MORE = (JS / "listbar-more.js").read_text(encoding="utf-8")
FORMULA = (JS / "formula.js").read_text(encoding="utf-8")
RESEARCH = (JS / "research.js").read_text(encoding="utf-8")
PRODUCTS = (JS / "products.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _plain(src: str) -> str:
    src = re.sub(r"^import .*$", "", src, flags=re.M)
    return re.sub(r"^export ", "", src, flags=re.M)


def _fn(src: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {name}\(", src, re.M)
    assert m, name
    return src[m.start():src.index("\n}\n", m.start()) + 3]


PRELUDE = textwrap.dedent("""
    const escHtml = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    function makeEl() {
      return { innerHTML: "", textContent: "", value: "", disabled: false, dataset: {}, listeners: [],
        addEventListener(t, f) { this.listeners.push(f); }, contains() { return true; },
        querySelector() { return null; }, querySelectorAll() { return []; }, setAttribute() {}, focus() {} };
    }
    const els = {};
    const byId = id => (els[id] ||= makeEl());
    const calls = [];
    let routes = {};
    async function api(path, opts) {
      calls.push((opts && opts.method || "GET") + " " + path);
      const r = routes[path];
      if (r instanceof Error) throw r;
      if (r === undefined) throw new Error("가짜 경로 없음 " + path);
      return JSON.parse(JSON.stringify(r));
    }
    const click = (rootId, key, value) => byId(rootId).listeners.forEach(f => f({ target: { closest: s => (s === "button[data-lb-filter]" ? { dataset: { lbFilter: key, value } } : null) } }));
    const clickRefresh = rootId => byId(rootId).listeners.forEach(f => f({ target: { closest: s => (s === "button[data-lb-refresh]" ? {} : null) } }));
    const count = (html, s) => html.split(s).length - 1;
    const chipPressed = (html, key, value) => html.includes(`data-lb-filter="${key}" data-value="${value}" aria-pressed="true"`);
    const hasChip = (html, key, value) => html.includes(`data-lb-filter="${key}" data-value="${value}"`);
    const hasRefresh = html => html.includes("data-lb-refresh");
    const tick = () => new Promise(r => setTimeout(r, 0));
""")


def _run(parts: list[str], body: str, data: dict | None = None):
    js = "\n".join([PRELUDE, _plain(LISTBAR), _plain(LISTS), _plain(MORE), *parts, f"const DATA = {json.dumps(data or {}, ensure_ascii=False)};",
                    "(async () => {", "const out = {};", textwrap.dedent(body), "console.log(JSON.stringify(out));", "})().catch(e => { console.error(e); process.exit(1); });"])
    done = subprocess.run([NODE, "-"], input=js, capture_output=True, text=True, timeout=90, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def _res(i: int, symbol: str, version: int, signal: str = "BUY") -> dict:
    return {"id": f"r{i}", "created_at": "2026-11-05T01:00:00+00:00", "version": version, "symbol": symbol, "period": "1y", "as_of": "2026-11-04",
            "latest_value": 1.2345, "latest_signal": signal, "metrics": {"total_return_pct": 3.5, "sharpe_ratio": 0.8, "mdd_pct": -4.2},
            "costs": {"commission_bps": 1, "slippage_bps": 2}}


# ── 1. 계산 결과 목록 ────────────────────────────────────────────────────────────────
@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_formula_results_chips_refresh_without_compute():
    """TC-LBF-01 · 종목 · 버전 칩은 응답 값만 · 맞는 줄만 · 풀면 복귀 · 새로고침은 결과 목록 GET 만 다시 부른다(compute · POST 없음) · 필터 유지 · 실패 · 보기는 누를 때만 · 이스케이프."""
    rows = [_res(1, "AAPL", 1), _res(2, "005930.KS", 1, "SELL"), _res(3, "AAPL", 2, "HOLD"), _res(4, "TSLA", 2)]
    more = rows + [_res(5, "AAPL", 3)]
    evil = [_res(6, "<img src=x onerror=1>", 1)]
    url = "/api/formula-indicators/ind-1/results?limit=30"
    got = _run([], f"""
      let current = {{ id: "ind-1" }};
      const viewed = [];
      const btns = {{}};
      const panel = formulaResultsPanel({{ esc: escHtml, ts: iso => "T" + iso.slice(0, 4), byId, api, getCurrent: () => current, onView: r => viewed.push(r.id), now: () => new Date("2026-11-05T03:00:00Z") }});
      // 「보기」 단추 연결을 보려고 칸 하나만 가짜 단추를 돌려준다
      byId("fx-results").querySelectorAll = sel => sel === ".fx-view" ? (byId("fx-results").innerHTML.match(/data-id="(r\\d+)"/g) || []).map(m => {{ const id = m.slice(9, -1); return btns[id] ||= {{ dataset: {{ id }}, addEventListener(t, f) {{ this.f = f; }} }}; }}) : [];
      routes["{url}"] = {{ results: DATA.rows }};
      await panel.load();
      const host = () => byId("fx-results").innerHTML;
      out.first = {{ rows: count(host(), "data-fx-result-row"), symChips: ["AAPL", "005930.KS", "TSLA"].map(v => hasChip(host(), "symbol", v)), verChips: ["1", "2", "3"].map(v => hasChip(host(), "version", v)),
                    verLabel: host().includes(">v2<"), refresh: hasRefresh(host()), limit: host().includes("서버가 준 최근 4건(최대 30건) 안에서 거릅니다"), autoView: viewed.length }};
      click("fx-results", "symbol", "AAPL");
      out.aapl = {{ rows: count(host(), "data-fx-result-row"), pressed: chipPressed(host(), "symbol", "AAPL") }};
      click("fx-results", "version", "2");
      out.aapl2 = count(host(), "data-fx-result-row");
      click("fx-results", "symbol", "");
      out.v2 = count(host(), "data-fx-result-row");
      click("fx-results", "version", "");
      out.all = count(host(), "data-fx-result-row");
      click("fx-results", "symbol", "TSLA"); click("fx-results", "version", "1");
      out.none = {{ rows: count(host(), "data-fx-result-row"), msg: host().includes("이 조건에 맞는 건이 없습니다") }};
      click("fx-results", "version", "");
      routes["{url}"] = {{ results: DATA.more }};
      const before = calls.length;
      clickRefresh("fx-results");
      await tick(); await tick();
      out.refresh = {{ calls: calls.slice(before), stillTsla: chipPressed(host(), "symbol", "TSLA"), rows: count(host(), "data-fx-result-row"), v3chip: hasChip(host(), "version", "3"),
                      stamp: host().includes("서버에서 다시 읽었습니다(12:00)"), meaning: host().includes("계산은 하지 않습니다"), autoView: viewed.length }};
      click("fx-results", "symbol", "");
      btns["r1"] && btns["r1"].f();
      out.view = viewed.slice();
      routes["{url}"] = new Error("서버 오류");
      clickRefresh("fx-results");
      await tick(); await tick();
      out.fail = {{ stamp: host().includes("다시 읽었습니다("), warn: host().includes("다시 읽지 못했습니다(서버 오류)"), kept: count(host(), "data-fx-result-row") }};
      routes["{url}"] = {{ results: DATA.evil }};
      await panel.load();
      out.evil = {{ raw: host().includes("<img src=x"), esc: host().includes("&lt;img src=x onerror=1&gt;") }};
      routes["{url}"] = {{ results: [] }};
      await panel.load();
      out.empty = {{ text: host().includes("아직 저장된 계산 결과가 없습니다"), refresh: hasRefresh(host()) }};
      current = null;
      const n = calls.length;
      await panel.load();
      out.noCurrent = {{ apiCalls: calls.length - n, text: host().includes("아직 저장된 계산 결과가 없습니다") }};
    """, {"rows": rows, "more": more, "evil": evil})
    assert got["first"]["rows"] == 4 and got["first"]["symChips"] == [True, True, True] and got["first"]["verChips"] == [True, True, False]
    assert got["first"]["verLabel"] and got["first"]["refresh"] and got["first"]["limit"] and got["first"]["autoView"] == 0
    assert got["aapl"] == {"rows": 2, "pressed": True} and got["aapl2"] == 1 and got["v2"] == 2 and got["all"] == 4
    assert got["none"] == {"rows": 0, "msg": True}
    assert got["refresh"]["calls"] == [f"GET {url}"], "새로고침은 저장된 결과 목록을 읽는 GET 하나뿐이다(계산 · 저장 없음)"
    assert got["refresh"]["stillTsla"] and got["refresh"]["rows"] == 1 and got["refresh"]["v3chip"] and got["refresh"]["stamp"] and got["refresh"]["meaning"]
    assert got["refresh"]["autoView"] == 0, "새로고침이 「보기」(캐시 재사용 계산 호출)를 부르면 안 된다"
    assert got["view"] == ["r1"]
    assert got["fail"] == {"stamp": False, "warn": True, "kept": 5}
    assert got["evil"] == {"raw": False, "esc": True}
    assert got["empty"] == {"text": True, "refresh": True}
    assert got["noCurrent"] == {"apiCalls": 0, "text": True}


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_formula_load_results_resets_chips_on_other_indicator():
    """TC-LBF-01b · formula.js loadResults — 다른 지표를 열면 걸어 둔 종목 · 버전 칩을 푼다(다른 지표에 없는 값일 수 있다) · 같은 지표면 그대로."""
    a = [_res(1, "AAPL", 1), _res(2, "TSLA", 1)]
    b = [_res(3, "005930.KS", 1), _res(4, "AAPL", 1)]
    fn = _fn(FORMULA, "loadResults")
    got = _run([], f"""
      let current = {{ id: "A" }};
      let resultsFor = null;
      const resultsView = formulaResultsPanel({{ esc: escHtml, ts: () => "-", byId, api, getCurrent: () => current }});
      {fn}
      routes["/api/formula-indicators/A/results?limit=30"] = {{ results: DATA.a }};
      routes["/api/formula-indicators/B/results?limit=30"] = {{ results: DATA.b }};
      await loadResults();
      click("fx-results", "symbol", "TSLA");
      const host = () => byId("fx-results").innerHTML;
      out.a = {{ rows: count(host(), "data-fx-result-row"), pressed: chipPressed(host(), "symbol", "TSLA") }};
      await loadResults();                                    // 같은 지표 — 그대로
      out.same = {{ rows: count(host(), "data-fx-result-row"), pressed: chipPressed(host(), "symbol", "TSLA") }};
      current = {{ id: "B" }};
      await loadResults();                                    // 다른 지표 — 칩이 풀리고 전부 보인다
      out.b = {{ rows: count(host(), "data-fx-result-row"), tslaChip: hasChip(host(), "symbol", "TSLA") }};
      current = null;
      const n = calls.length;
      await loadResults();
      out.none = calls.length - n;
    """, {"a": a, "b": b})
    assert got["a"] == {"rows": 1, "pressed": True} and got["same"] == {"rows": 1, "pressed": True}
    assert got["b"] == {"rows": 2, "tslaChip": False} and got["none"] == 0


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_refresh_outcome_text():
    """TC-LBF-01c · 새로고침 안내 글 — 성공이면 시각 + 뜻 · 실패면 시각 없이 실패."""
    got = _run([], """
      const now = new Date("2026-11-05T03:07:00Z");
      out.ok = refreshOutcomeText(true, { tail: "뜻", now });
      out.okPlain = refreshOutcomeText(true, { now });
      out.fail = refreshOutcomeText(false, { error: "서버 오류", now });
      out.failPlain = refreshOutcomeText(false, { now });
    """)
    assert got["ok"] == "서버에서 다시 읽었습니다(12:07) — 뜻" and got["okPlain"] == "서버에서 다시 읽었습니다(12:07)"
    assert got["fail"] == "다시 읽지 못했습니다(서버 오류) — 이전에 받은 값을 보입니다" and "(" not in got["failPlain"].replace("다시 읽지 못했습니다", "", 1).split("—")[0]


# ── 2. 투자 정보 리서치 ──────────────────────────────────────────────────────────────
@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_research_refresh_keeps_conditions_and_reports_failure():
    """TC-LBF-02 · research.js refreshResearch — 지금 조건 그대로 reload · 성공하면 시각 · 실패하면 시각 대신 실패 · 받는 중 다시 누르면 무시 · 끝나면 단추가 풀린다."""
    fn = _fn(RESEARCH, "refreshResearch")
    got = _run([], f"""
      const S = {{ error: "", q: "배당", view: "list" }};
      let refreshBusy = false;
      let reloads = 0, fail = false, hold = null;
      const reload = () => new Promise(res => {{ reloads++; hold = () => {{ S.error = fail ? "검색 서버 오류" : ""; res(); }}; }});
      {fn}
      const btn = {{ disabled: false }}, note = {{ textContent: "" }};
      const r = {{ querySelector: sel => sel === "[data-rs-refresh]" ? btn : sel === ".rs-refresh-note" ? note : null }};
      const p1 = refreshResearch(r);
      const p2 = refreshResearch(r);                          // 받는 중 다시 누름
      out.during = {{ reloads, disabled: btn.disabled, note: note.textContent }};
      hold(); await p1; await p2;
      out.ok = {{ reloads, disabled: btn.disabled, note: /^서버에서 다시 읽었습니다\\(\\d\\d:\\d\\d\\) — 지금 조건 그대로/.test(note.textContent), q: S.q, view: S.view }};
      fail = true;
      const p3 = refreshResearch(r); hold(); await p3;
      out.fail = {{ reloads, note: note.textContent, stamp: note.textContent.includes("다시 읽었습니다("), disabled: btn.disabled }};
    """)
    assert got["during"] == {"reloads": 1, "disabled": True, "note": "서버에서 다시 읽는 중…"}
    assert got["ok"] == {"reloads": 1, "disabled": False, "note": True, "q": "배당", "view": "list"}
    assert got["fail"]["reloads"] == 2 and got["fail"]["note"].startswith("다시 읽지 못했습니다(검색 서버 오류)") and got["fail"]["stamp"] is False and got["fail"]["disabled"] is False


# ── 3. 상품 안내 ─────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_products_refresh_reads_overview_and_weights_only():
    """TC-LBF-03 · products.js refreshProducts — 한눈에 · 비중만 다시 읽는다(예금 · 적금 호출 없음) · 실패하면 보이던 목록을 두고 시각을 안 찍는다 · 받는 중 다시 누르면 무시."""
    fn = _fn(PRODUCTS, "refreshProducts")
    got = _run([], f"""
      let ov = {{ status: "ok", total: 10 }}, refreshNote = "", refreshBusy = false;
      let overviewCalls = 0, weightCalls = 0, savingsCalls = 0, draws = [], failNext = false, hold = null;
      const draw = () => draws.push(refreshNote);
      const loadSavings = () => {{ savingsCalls++; }};
      const loadOverview = () => new Promise(res => {{ overviewCalls++; hold = () => {{ ov = failNext ? {{ status: "error", notes: [] }} : {{ status: "ok", total: 11 }}; res(); }}; }});
      const loadWeights = async () => {{ weightCalls++; }};
      {fn}
      const p1 = refreshProducts();
      const p2 = refreshProducts();                           // 받는 중 다시 누름
      out.during = {{ overviewCalls, weightCalls, note: refreshNote, busy: refreshBusy }};
      hold(); await p1; await p2;
      out.ok = {{ overviewCalls, weightCalls, savingsCalls, total: ov.total, stamp: /^서버에서 다시 읽었습니다\\(\\d\\d:\\d\\d\\)/.test(refreshNote), busy: refreshBusy, savingsNote: refreshNote.includes("자산 배분 비중을 다시 읽었습니다") }};
      failNext = true;
      const p3 = refreshProducts(); hold(); await p3;
      out.fail = {{ status: ov.status, total: ov.total, note: refreshNote, stamp: refreshNote.includes("다시 읽었습니다("), busy: refreshBusy }};
    """)
    assert got["during"] == {"overviewCalls": 1, "weightCalls": 1, "note": "서버에서 다시 읽는 중…", "busy": True}
    assert got["ok"] == {"overviewCalls": 1, "weightCalls": 1, "savingsCalls": 0, "total": 11, "stamp": True, "busy": False, "savingsNote": True}
    assert got["fail"]["status"] == "ok" and got["fail"]["total"] == 11 and got["fail"]["stamp"] is False and got["fail"]["busy"] is False
    assert got["fail"]["note"].startswith("다시 읽지 못했습니다(상품 목록을 읽지 못했습니다)")


# ── 4. 구조 ──────────────────────────────────────────────────────────────────────────
def test_structure_no_compute_paths_and_screens_import_module():
    """TC-LBF-04 · 새 모듈은 계산 · 저장 길(compute · POST · PUT · DELETE)을 모른다 · 세 화면 파일이 새 모듈을 가져온다 · 새로고침 단추 연결."""
    code = re.sub(r"//[^\n]*", "", MORE)
    for banned in ("compute", "POST", "PUT", "DELETE", "method", "/versions", "/export"):
        assert banned not in code, banned
    calls = re.findall(r"\.api\(([^)]*)\)", code)
    assert calls and all("," not in c for c in calls), calls
    for name, src in (("formula.js", FORMULA), ("research.js", RESEARCH), ("products.js", PRODUCTS)):
        assert 'from "/js/listbar-more.js"' in src, name
    assert "data-rs-refresh" in RESEARCH and 'd.act === "refresh"' in PRODUCTS and 'data-act="refresh"' in PRODUCTS
    # 상품 새로고침은 예금 · 적금(하루 호출 한도)을 부르지 않는다
    assert "loadSavings" not in _fn(PRODUCTS, "refreshProducts")
    # 산식 결과 새로고침이 부르는 loadResults 는 목록 읽기뿐 — compute 를 직접 부르지 않는다
    assert "compute" not in _fn(FORMULA, "loadResults")
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    assert "fx-results-bar" not in html
