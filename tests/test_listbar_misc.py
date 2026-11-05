"""TC-LBM — 표 위 줄(필터 칩 + 새로고침) 4~7번 화면 (public/js/listbar-misc.js · paper.js · sysadmin.js · company.js · company-compare-table.js · calendar.js · 2026-11-05 화면 전수 점검 뒤)

퀀트 관찰 목록 표(quant.js qdWatch*) · 모의투자(paperlists.js)와 같은 모양 · 같은 동작을 공용 도우미(listbar.js)로 붙였다.
설정 · 걸러내기 · 줄 HTML 은 listbar-misc.js 의 순수 함수라 node 에서 가짜 DOM · 가짜 api 로 그대로 돌린다(브라우저 경로 import 는 쓰지 않는다).
1. quant-lean — LEAN 실행 이력에 전략 · 티커 칩(응답 값만) · 새로고침이 이력 읽기만 다시 부른다(실행 길은 안 부른다). (TC-LBM-01)
2. sysadmin-logs — 이벤트 유형 칩(응답 event_type, 많이 나온 순) · 새로고침이 입력 칸 조건 그대로 다시 읽고 칩을 유지. (TC-LBM-02)
3. company-sector — 업종명 검색 + 정렬(PER · PBR 중앙값 없는 업종은 맨 뒤) · 새로고침이 검색 · 정렬을 유지. (TC-LBM-03)
4. company-compare — 지표 비교 표 새로고침 단추가 같은 질의로 서버를 다시 부르고 쪽 · 정렬 · 필터를 유지한다. (TC-LBM-04)
5. 구조 — 화면 연결 · 서버 코드 무변경 · 실행(POST) 길을 부르지 않는다 · market-calendar 새로고침 단추. (TC-LBM-05)
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
PUB = ROOT / "public"
JS = PUB / "js"
LISTBAR = (JS / "listbar.js").read_text(encoding="utf-8")
LISTS = (JS / "paperlists.js").read_text(encoding="utf-8")
MISC = (JS / "listbar-misc.js").read_text(encoding="utf-8")
PAPER = (JS / "paper.js").read_text(encoding="utf-8")
SYSADMIN = (JS / "sysadmin.js").read_text(encoding="utf-8")
COMPANY = (JS / "company.js").read_text(encoding="utf-8")
CTABLE = (JS / "company-compare-table.js").read_text(encoding="utf-8")
CALENDAR = (JS / "calendar.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _plain(src: str) -> str:
    """ES 모듈 글을 node 한 덩어리로 돌리도록 import 줄 · export 만 뗀다."""
    src = re.sub(r"^import .*$", "", src, flags=re.M)
    return re.sub(r"^export ", "", src, flags=re.M)


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
    async function api(path, opt) {
      calls.push(opt && opt.method ? opt.method + " " + path : path);
      const r = routes[path];
      if (r instanceof Error) throw r;
      if (r === undefined) throw new Error("가짜 경로 없음 " + path);
      return JSON.parse(JSON.stringify(r));
    }
    const click = (rootId, key, value) => byId(rootId).listeners.forEach(f => f({ target: { closest: s => (s === "button[data-lb-filter]" ? { dataset: { lbFilter: key, value } } : null) } }));
    const clickRefresh = rootId => byId(rootId).listeners.forEach(f => f({ target: { closest: s => (s === "button[data-lb-refresh]" ? {} : null) } }));
    const typeInto = (id, text) => { byId(id).value = text; byId(id).listeners.forEach(f => f({})); };
    const hasChip = (html, key, value) => html.includes(`data-lb-filter="${key}" data-value="${value}"`);
    const chipPressed = (html, key, value) => html.includes(`data-lb-filter="${key}" data-value="${value}" aria-pressed="true"`);
    const count = (html, s) => html.split(s).length - 1;
    const panel = (cfg) => createListPanel(cfg, { esc: escHtml, byId, now: () => new Date("2026-11-05T03:07:00Z") });
""")


def _run(body: str, data: dict | None = None, extra: str = ""):
    js = "\n".join([PRELUDE, _plain(LISTBAR), _plain(LISTS), _plain(MISC), extra, f"const DATA = {json.dumps(data or {}, ensure_ascii=False)};",
                    "(async () => {", "const out = {};", textwrap.dedent(body), "console.log(JSON.stringify(out));", "})().catch(e => { console.error(e); process.exit(1); });"])
    done = subprocess.run([NODE, "-"], input=js, capture_output=True, text=True, timeout=90, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# ── 가짜 응답 ─────────────────────────────────────────────────────────────

def _run_row(i: int, ticker: str, strategy: str, label: str, lean_ok: bool = True) -> dict:
    return {"id": f"r{i}", "ticker": ticker, "strategy": strategy, "strategy_label": label, "engine": "lean", "start_date": "2023-01-01", "end_date": "2023-12-31",
            "strategy_return_pct": 5.5 - i, "max_drawdown_pct": -3.2, "sharpe_ratio": 0.8, "lean_ok": lean_ok, "created_at": f"2026-11-0{i}T01:00:00+00:00"}


LEAN_URL = "/api/backtests/lean/history?limit=15"
LEAN_PRELUDE = """
const h = { esc: escHtml, fmtPct: n => `${Number(n) >= 0 ? "+" : ""}${Number(n).toFixed(2)}%`, signCls: n => (parseFloat(n) >= 0 ? "up" : "down"),
  emptyRow: (cols, text) => `<tr><td colspan="${cols}">${escHtml(text)}</td></tr>`, fmtTime: v => String(v).slice(0, 10), load: () => api("/api/backtests/lean/history?limit=15") };
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_lean_history_chips_refresh_and_safety():
    """TC-LBM-01 · 전략 · 티커 칩은 응답 값만 · 걸면 맞는 줄만 · 풀면 복귀 · 새로고침이 이력 읽기만 다시 부르고 필터를 유지 · 사라진 전략 칩도 남는다 · 실패 · 빈 응답 · 이스케이프."""
    rows = [_run_row(1, "SPY", "ma_cross", "이동평균 교차"), _run_row(2, "QQQ", "ma_cross", "이동평균 교차"), _run_row(3, "SPY", "dca", "적립식 매수", False)]
    after = rows + [_run_row(4, "AAPL", "momentum", "돌파 모멘텀")]
    evil = [_run_row(5, "<img src=x onerror=1>", "ma_cross", "<b>교차</b>")]
    got = _run(f"""
      routes["{LEAN_URL}"] = {{ runs: DATA.rows }};
      const p = panel(leanHistoryCfg(h));
      await p.load();
      const first = byId("ql-history").innerHTML, bar0 = byId("ql-history-bar").innerHTML;
      out.initial = {{ rows: count(first, "<tr><td"), stratChips: ["ma_cross", "dca", "momentum"].map(v => hasChip(bar0, "strategy", v)), tickerChips: ["SPY", "QQQ", "AAPL"].map(v => hasChip(bar0, "ticker", v)),
        labelShown: bar0.includes("적립식 매수"), refreshBtn: bar0.includes("data-lb-refresh"), limitNote: bar0.includes("최근 15건까지만 받습니다 — 받은 3건 안에서 거릅니다") }};
      click("ql-history-bar", "strategy", "ma_cross");
      out.strategy = {{ rows: count(byId("ql-history").innerHTML, "<tr><td"), pressed: chipPressed(byId("ql-history-bar").innerHTML, "strategy", "ma_cross"), summary: byId("ql-history-bar").innerHTML.includes("조건 이동평균 교차 — 받은 3건 중 2건") }};
      click("ql-history-bar", "ticker", "SPY");
      out.both = count(byId("ql-history").innerHTML, "<tr><td");
      click("ql-history-bar", "strategy", ""); click("ql-history-bar", "ticker", "");
      out.released = count(byId("ql-history").innerHTML, "<tr><td");
      click("ql-history-bar", "strategy", "dca");
      routes["{LEAN_URL}"] = {{ runs: DATA.after.filter(r => r.strategy !== "dca") }};      // 눌러 둔 전략이 새 응답에서 사라졌다
      calls.length = 0;
      clickRefresh("ql-history-bar");
      await new Promise(r => setTimeout(r, 30));
      const bar1 = byId("ql-history-bar").innerHTML;
      out.refresh = {{ calls: calls.slice(), stillPressed: chipPressed(bar1, "strategy", "dca"), emptyMsg: byId("ql-history").innerHTML.includes("이 조건에 맞는 건이 없습니다"),
        stamp: bar1.includes("서버에서 이력을 다시 읽었습니다(12:07)") && bar1.includes("LEAN 을 다시 돌리지 않습니다"), newTicker: hasChip(bar1, "ticker", "AAPL") }};
      click("ql-history-bar", "strategy", "");
      out.afterRelease = count(byId("ql-history").innerHTML, "<tr><td");
      routes["{LEAN_URL}"] = new Error("서버 오류");
      clickRefresh("ql-history-bar");
      await new Promise(r => setTimeout(r, 30));
      const bar2 = byId("ql-history-bar").innerHTML;
      out.failure = {{ noStamp: !bar2.includes("다시 읽었습니다("), notice: bar2.includes("다시 읽지 못했습니다(서버 오류)"), keepRows: count(byId("ql-history").innerHTML, "<tr><td") }};
      routes["{LEAN_URL}"] = {{ runs: [] }};
      const e = panel(leanHistoryCfg(h));
      await e.load();
      out.empty = {{ row: byId("ql-history").innerHTML.includes("실행 이력이 없습니다."), noChipGroups: !byId("ql-history-bar").innerHTML.includes("data-lb-filter"), refreshStill: byId("ql-history-bar").innerHTML.includes("data-lb-refresh") }};
      routes["{LEAN_URL}"] = {{ runs: DATA.evil }};
      const x = panel(leanHistoryCfg(h));
      await x.load();
      out.evil = {{ body: byId("ql-history").innerHTML, bar: byId("ql-history-bar").innerHTML }};
      out.run = calls.filter(c => c.includes("/run"));
    """, {"rows": rows, "after": after, "evil": evil}, LEAN_PRELUDE)
    assert got["initial"]["rows"] == 3
    # 처음 응답에는 momentum · AAPL 이 없다 — 응답에 없는 값은 칩이 되지 않는다
    assert got["initial"]["stratChips"] == [True, True, False]
    assert got["initial"]["tickerChips"] == [True, True, False]
    assert got["initial"]["labelShown"] and got["initial"]["refreshBtn"] and got["initial"]["limitNote"]
    assert got["strategy"] == {"rows": 2, "pressed": True, "summary": True}
    assert got["both"] == 1 and got["released"] == 3
    r = got["refresh"]
    assert r["calls"] == [LEAN_URL] and r["stillPressed"] and r["emptyMsg"] and r["stamp"] and r["newTicker"]
    assert got["afterRelease"] == 3
    assert got["failure"] == {"noStamp": True, "notice": True, "keepRows": 3}
    assert got["empty"] == {"row": True, "noChipGroups": True, "refreshStill": True}
    assert "<img" not in got["evil"]["body"] and "&lt;img" in got["evil"]["body"] and "<b>" not in got["evil"]["bar"] + got["evil"]["body"]
    assert got["run"] == []


# ── sysadmin-logs ────────────────────────────────────────────────────────

def _ev(i: int, etype: str, user: str = "u1", payload: dict | None = None) -> dict:
    return {"id": f"e{i}", "user_id": user, "client_id": "c", "event_type": etype, "payload": payload or {"n": i}, "created_at": f"2026-11-05T0{i}:00:00"}


AUDIT_PRELUDE = """
const params = { q: "" };
const load = () => api(`/api/admin/audit-log?event_type=${params.q}&user_id=&limit=100`);
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_audit_log_type_chips_refresh_and_safety():
    """TC-LBM-02 · 이벤트 유형 칩은 응답 event_type(많이 나온 순) · 걸면 맞는 줄만 · 새로고침이 입력 칸 조건 그대로 다시 읽고 칩을 유지 · 실패 · 빈 응답 · 이스케이프."""
    events = [_ev(1, "order.paper"), _ev(2, "auth.login"), _ev(3, "order.paper"), _ev(4, "broker.sync"), _ev(5, "order.paper")]
    evil = [_ev(6, "<script>x</script>", "<u>", {"k": "<i>"})]
    got = _run("""
      const URL = "/api/admin/audit-log?event_type=&user_id=&limit=100";
      routes[URL] = { events: DATA.events };
      const p = panel(auditCfg({ esc: escHtml, load }));
      await p.load();
      const bar0 = byId("audit-log-bar").innerHTML;
      const order = [...bar0.matchAll(/data-lb-filter="type" data-value="([^"]*)"/g)].map(m => m[1]);
      out.initial = { rows: count(byId("audit-log").innerHTML, "py-1 border-b"), order, limit: bar0.includes("최근 100건까지만 받습니다 — 받은 5건 안에서 거릅니다") };
      click("audit-log-bar", "type", "order.paper");
      out.filtered = { rows: count(byId("audit-log").innerHTML, "py-1 border-b"), pressed: chipPressed(byId("audit-log-bar").innerHTML, "type", "order.paper"), summary: byId("audit-log-bar").innerHTML.includes("조건 order.paper — 받은 5건 중 3건") };
      click("audit-log-bar", "type", "");
      out.released = count(byId("audit-log").innerHTML, "py-1 border-b");
      click("audit-log-bar", "type", "broker.sync");
      routes[URL] = { events: DATA.events.filter(e => e.event_type !== "broker.sync") };
      calls.length = 0;
      clickRefresh("audit-log-bar");
      await new Promise(r => setTimeout(r, 30));
      const bar1 = byId("audit-log-bar").innerHTML;
      out.refresh = { calls: calls.slice(), kept: chipPressed(bar1, "type", "broker.sync"), none: byId("audit-log").innerHTML.includes("이 조건에 맞는 건이 없습니다"), stamp: bar1.includes("서버에서 로그를 다시 읽었습니다(12:07)") && bar1.includes("위 입력 칸 조건 그대로 읽습니다") };
      routes[URL] = new Error("관리자만 볼 수 있습니다");
      clickRefresh("audit-log-bar");
      await new Promise(r => setTimeout(r, 30));
      out.failure = { noStamp: !byId("audit-log-bar").innerHTML.includes("다시 읽었습니다("), notice: byId("audit-log-bar").innerHTML.includes("다시 읽지 못했습니다(관리자만 볼 수 있습니다)") };
      routes[URL] = { events: [] };
      const e = panel(auditCfg({ esc: escHtml, load }));
      await e.load();
      out.empty = { msg: byId("audit-log").innerHTML.includes("표시할 감사 로그가 없습니다."), noChips: !byId("audit-log-bar").innerHTML.includes("data-lb-filter"), refresh: byId("audit-log-bar").innerHTML.includes("data-lb-refresh") };
      routes[URL] = { events: DATA.evil };
      const x = panel(auditCfg({ esc: escHtml, load }));
      await x.load();
      out.evil = byId("audit-log").innerHTML + byId("audit-log-bar").innerHTML;
      // 입력 칸 조건이 바뀌면 그 조건으로 읽는다(서버가 먼저 거른다)
      params.q = "order";
      routes["/api/admin/audit-log?event_type=order&user_id=&limit=100"] = { events: DATA.events.filter(e => e.event_type === "order.paper") };
      calls.length = 0;
      await panel(auditCfg({ esc: escHtml, load })).refresh();
      out.query = calls.slice();
    """, {"events": events, "evil": evil}, AUDIT_PRELUDE)
    assert got["initial"] == {"rows": 5, "order": ["", "order.paper", "auth.login", "broker.sync"], "limit": True}
    assert got["filtered"] == {"rows": 3, "pressed": True, "summary": True}
    assert got["released"] == 5
    assert got["refresh"] == {"calls": ["/api/admin/audit-log?event_type=&user_id=&limit=100"], "kept": True, "none": True, "stamp": True}
    assert got["failure"] == {"noStamp": True, "notice": True}
    assert got["empty"] == {"msg": True, "noChips": True, "refresh": True}
    assert "<script>" not in got["evil"] and "&lt;script&gt;" in got["evil"] and "<u>" not in got["evil"] and "<i>" not in got["evil"]
    assert got["query"] == ["/api/admin/audit-log?event_type=order&user_id=&limit=100"]


# ── company-sector ───────────────────────────────────────────────────────

def _grp(code: str, name: str, n: int, per: float | None, pbr: float | None) -> dict:
    return {"code": code, "name": name, "section": {"code": "C", "name": "제조업"}, "n": n, "thin": n < 3,
            "per": {"median": per, "n": n if per is not None else 0}, "pbr": {"median": pbr, "n": n if pbr is not None else 0}, "top": [{"code": "000000", "name": "대표"}]}


SECTOR = {"available": True, "as_of": "2026-11-04", "groups": [_grp("26", "전자 부품 제조업", 30, 12.5, 1.4), _grp("64", "금융업", 20, 8.1, 0.6),
                                                             _grp("21", "의약품 제조업", 15, None, 3.2), _grp("10", "식료품 제조업", 8, 20.0, None)], "notice": "n"}
SECTOR_PRELUDE = """
const cards = (data, esc) => data.groups.map(g => `<div data-cv-sector="${esc(g.code)}">${esc(g.name)}</div>`).join("");
const msg = (t, c) => `<div data-msg="${c || ""}">${escHtml(t)}</div>`;
const sector = () => createSectorPanel({ barHost: "co-sector-bar", cardsHost: "co-sector-cards", noteHost: "co-sector-note", searchId: "co-sector-q",
  load: () => api("/api/data/indicators/sectors"), renderCards: cards, renderNote: (d, esc) => `<p>${esc(d.notice)}</p>`, message: msg,
  loadingText: "계산하는 중…", meaning: "서버에서 다시 읽었습니다", tail: "서버가 5분 안에 만든 업종 묶음은 그대로 돌려줍니다" },
  { esc: escHtml, byId, now: () => new Date("2026-11-05T03:07:00Z") });
const order = () => [...byId("co-sector-cards").innerHTML.matchAll(/data-cv-sector="(\\d+)"/g)].map(m => m[1]);
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_sector_search_sort_refresh():
    """TC-LBM-03 · 업종명 검색 · 정렬(없는 중앙값은 맨 뒤) · 풀면 서버 순서 · 새로고침이 서버를 다시 부르고 검색 · 정렬을 유지 · 실패 · 이스케이프 · 빈 응답."""
    got = _run("""
      const URL = "/api/data/indicators/sectors";
      routes[URL] = DATA.sector;
      const p = sector();
      const loading = p.load();
      out.loadingText = byId("co-sector-cards").innerHTML.includes("계산하는 중…");
      await loading;
      out.server = order();
      out.noteHost = byId("co-sector-note").innerHTML;
      out.view = {
        perAsc: sectorView(DATA.sector.groups, { sort: "per_asc" }).map(g => g.code),
        perDesc: sectorView(DATA.sector.groups, { sort: "per_desc" }).map(g => g.code),
        pbrAsc: sectorView(DATA.sector.groups, { sort: "pbr_asc" }).map(g => g.code),
        name: sectorView(DATA.sector.groups, { sort: "name" }).map(g => g.name),
        q: sectorView(DATA.sector.groups, { q: " 제조 " }).map(g => g.code),
        qCase: sectorView([{ name: "ABC Bank" }], { q: "abc" }).length,
        none: sectorView(DATA.sector.groups, { q: "없는업종" }).length,
        nullSafe: sectorView(null, { q: "x", sort: "per_asc" }).length,
      };
      click("co-sector-bar", "sort", "per_asc");
      out.sorted = { codes: order(), pressed: chipPressed(byId("co-sector-bar").innerHTML, "sort", "per_asc"), chips: ["", "per_asc", "per_desc", "pbr_asc", "pbr_desc", "name"].every(v => hasChip(byId("co-sector-bar").innerHTML, "sort", v)) };
      typeInto("co-sector-q", "제조");
      out.searched = { codes: order(), summary: byId("co-sector-bar").innerHTML.includes("조건 업종명 「제조」 · PER 낮은 순 — 받은 4곳 중 3곳"), inputKept: byId("co-sector-q").value === "제조" };
      typeInto("co-sector-q", "없는업종");
      out.filteredEmpty = byId("co-sector-cards").innerHTML.includes("이 조건에 맞는 업종이 없습니다. 검색어를 지워 보세요.");
      typeInto("co-sector-q", "");
      click("co-sector-bar", "sort", "");
      out.released = order();
      typeInto("co-sector-q", "금융");
      click("co-sector-bar", "sort", "pbr_desc");
      const changed = JSON.parse(JSON.stringify(DATA.sector));
      changed.groups.push({ code: "99", name: "금융 서비스 <b>기타</b>", section: { code: "K", name: "금융" }, n: 5, thin: false, per: { median: 9, n: 5 }, pbr: { median: 0.9, n: 5 }, top: [] });
      routes[URL] = changed;
      calls.length = 0;
      clickRefresh("co-sector-bar");
      await new Promise(r => setTimeout(r, 30));
      const bar1 = byId("co-sector-bar").innerHTML;
      out.refresh = { calls: calls.slice(), codes: order(), q: byId("co-sector-q").value, sortPressed: chipPressed(bar1, "sort", "pbr_desc"), stamp: bar1.includes("서버에서 다시 읽었습니다(12:07)") && bar1.includes("5분 안에 만든 업종 묶음"), escaped: !byId("co-sector-cards").innerHTML.includes("<b>") };
      routes[URL] = new Error("업종별 자료를 아직 받지 못했습니다.");
      clickRefresh("co-sector-bar");
      await new Promise(r => setTimeout(r, 30));
      out.failure = { noStamp: !byId("co-sector-bar").innerHTML.includes("다시 읽었습니다("), notice: byId("co-sector-bar").innerHTML.includes("다시 읽지 못했습니다(업종별 자료를 아직 받지 못했습니다.) — 이전에 받은 값을 보입니다"), keep: order().length };
      out.method = calls.every(c => !c.startsWith("POST"));
      // 처음부터 실패하면 카드 칸에 빨간 안내 · 새로고침은 남는다
      for (const k of Object.keys(els)) delete els[k];
      routes[URL] = new Error("수집 DB 가 없다");
      const f = sector();
      await f.load();
      out.firstFail = { msg: byId("co-sector-cards").innerHTML.includes('data-msg="var(--red)"') && byId("co-sector-cards").innerHTML.includes("수집 DB 가 없다"), refresh: byId("co-sector-bar").innerHTML.includes("data-lb-refresh") };
      for (const k of Object.keys(els)) delete els[k];
      routes[URL] = { available: true, groups: [] };
      const e = sector();
      await e.load();
      out.empty = { cards: byId("co-sector-cards").innerHTML };
    """, {"sector": SECTOR}, SECTOR_PRELUDE)
    assert got["loadingText"] is True
    assert got["server"] == ["26", "64", "21", "10"]
    assert "<p>n</p>" in got["noteHost"]
    v = got["view"]
    assert v["perAsc"] == ["64", "26", "10", "21"]          # PER 없는 의약품은 맨 뒤
    assert v["perDesc"] == ["10", "26", "64", "21"]
    assert v["pbrAsc"] == ["64", "26", "21", "10"]          # PBR 없는 식료품은 맨 뒤
    assert v["name"] == ["금융업", "식료품 제조업", "의약품 제조업", "전자 부품 제조업"]
    assert v["q"] == ["26", "21", "10"] and v["qCase"] == 1 and v["none"] == 0 and v["nullSafe"] == 0
    assert got["sorted"] == {"codes": ["64", "26", "10", "21"], "pressed": True, "chips": True}
    assert got["searched"] == {"codes": ["26", "10", "21"], "summary": True, "inputKept": True}
    assert got["filteredEmpty"] is True
    assert got["released"] == ["26", "64", "21", "10"]
    r = got["refresh"]
    assert r["calls"] == ["/api/data/indicators/sectors"] and r["codes"] == ["99", "64"] and r["q"] == "금융" and r["sortPressed"] and r["stamp"] and r["escaped"]
    assert got["failure"] == {"noStamp": True, "notice": True, "keep": 2} and got["method"] is True
    assert got["firstFail"] == {"msg": True, "refresh": True}
    assert got["empty"]["cards"] == ""                      # 빈 응답은 「조건에 맞는 업종 없음」 이 아니라 카드 그리기(빈 안내)로 넘긴다


# ── company-compare 표 새로고침 ──────────────────────────────────────────

CT_PRELUDE = """
const doc = { els: {}, getElementById(id) { return this.els[id] || null; },
  createElement() { return { type: "", id: "", className: "", textContent: "", title: "", disabled: false, listeners: [], attrs: {},
    addEventListener(t, f) { this.listeners.push(f); }, setAttribute(k, v) { this.attrs[k] = v; }, click() { this.listeners.forEach(f => f({})); } }; } };
globalThis.document = doc;
const mk = (extra = {}) => Object.assign({ textContent: "", innerHTML: "", value: "", style: {}, options: [], dataset: {}, disabled: false, listeners: [],
  addEventListener(t, f) { this.listeners.push([t, f]); }, setAttribute() {}, removeAttribute() {}, querySelectorAll() { return []; } }, extra);
for (const id of ["ct-table", "ct-msg", "ct-q", "ct-market", "ct-sector", "ct-prev", "ct-next", "ct-page", "ct-range", "ct-picked", "ct-foot"]) doc.els[id] = mk();
const parent = { insertBefore(n, ref) { doc.els[n.id] = n; this.inserted = true; } };
doc.els["ct-goto"] = mk({ parentNode: parent });
const page = (n) => ({ page: n, pages: 3, total: 90, universe: 90, start: 1, end: 30, rows: [], columns: [], filters: { markets: [], sectors: [] }, as_of: "2026-11-04", source: "s", limits: [] });
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_compare_table_refresh_button():
    """TC-LBM-04 · 새로고침 단추를 JS 가 만든다(app.html 무변경) · 누르면 같은 질의로 서버를 다시 부르고 쪽 · 정렬을 유지 · 안내는 성공일 때만 · 읽는 중 다시 누르면 무시."""
    got = _run_ct("""
      const queries = [];
      let fail = false, hold = null;
      const m = ctMount({ fetchPage: async (qs) => { queries.push(qs); if (hold) await hold; if (fail) throw new Error("표를 받지 못했습니다"); return page(Number((qs.match(/page=([0-9]+)/) || [0, 1])[1])); },
        esc: escHtml, max: 8, isPicked: () => false, pickedCount: () => 0, onPick: () => "", refreshNote: () => "서버에서 다시 읽었습니다(12:07)" });
      const btn = doc.els["ct-refresh"];
      out.button = { made: !!btn, text: btn.textContent, inserted: parent.inserted === true };
      m.ensureLoaded();
      await new Promise(r => setTimeout(r, 10));
      out.first = { n: queries.length, msg: doc.els["ct-msg"].textContent };
      const next = doc.els["ct-next"].listeners.find(l => l[0] === "click")[1];
      next();
      await new Promise(r => setTimeout(r, 10));
      const before = queries.slice();
      btn.click();
      await new Promise(r => setTimeout(r, 10));
      out.refresh = { added: queries.length - before.length, sameQuery: queries[queries.length - 1] === before[before.length - 1], msg: doc.els["ct-msg"].textContent, enabled: btn.disabled === false };
      fail = true;
      btn.click();
      await new Promise(r => setTimeout(r, 10));
      out.failure = { msg: doc.els["ct-msg"].textContent, noStamp: !doc.els["ct-msg"].textContent.includes("다시 읽었습니다") };
      fail = false;
      let release; hold = new Promise(r => { release = r; });
      const n0 = queries.length;
      btn.click(); btn.click();
      out.busyDuring = { calls: queries.length - n0, disabled: btn.disabled };
      release(); await new Promise(r => setTimeout(r, 10));
      out.busyAfter = { calls: queries.length - n0, disabled: btn.disabled };
    """)
    assert got["button"] == {"made": True, "text": "새로고침", "inserted": True}
    assert got["first"] == {"n": 1, "msg": ""}
    assert got["refresh"] == {"added": 1, "sameQuery": True, "msg": "서버에서 다시 읽었습니다(12:07)", "enabled": True}
    assert got["failure"]["msg"] == "표를 받지 못했습니다" and got["failure"]["noStamp"]
    assert got["busyDuring"] == {"calls": 1, "disabled": True} and got["busyAfter"] == {"calls": 1, "disabled": False}


def _run_ct(body: str):
    js = "\n".join([PRELUDE, CT_PRELUDE, _plain(CTABLE), "(async () => {", "const out = {};", textwrap.dedent(body), "console.log(JSON.stringify(out));", "})().catch(e => { console.error(e); process.exit(1); });"])
    done = subprocess.run([NODE, "-"], input=js, capture_output=True, text=True, timeout=90, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# ── 구조 ────────────────────────────────────────────────────────────────

def test_wiring_and_no_run_paths():
    """TC-LBM-05 · 화면 연결 · 새로고침이 실행(POST) · 계산 길을 부르지 않는다 · 서버 코드 무변경 · 달력 새로고침 단추."""
    # paper.js — LEAN 이력만 (실행 길 runLeanBacktest 는 그대로, 이력 새로고침은 history 만 읽는다)
    assert 'from "/js/listbar-misc.js"' in PAPER and "leanHistoryCfg" in PAPER
    seg = PAPER[PAPER.index("const leanHistoryPanel"):PAPER.index("/* ────", PAPER.index("const leanHistoryPanel"))]
    assert 'api("/api/backtests/lean/history?limit=15")' in seg and "/lean/run" not in seg and "POST" not in seg
    # sysadmin.js — 입력 칸 2개 · 「조회」 단추 유지 + 새 칩
    assert 'document.getElementById("audit-refresh-btn")?.addEventListener("click", loadAuditLog)' in SYSADMIN
    assert "audit-event-filter" in SYSADMIN and "audit-user-filter" in SYSADMIN and "auditCfg" in SYSADMIN
    # company.js — 업종 검색 · 정렬, 서버 읽기 주소 그대로(화면 ↔ API 스캐너)
    assert 'api("/api/data/indicators/sectors")' in COMPANY and "createSectorPanel" in COMPANY and "refreshNote" in COMPANY
    # 지표 비교 표 — 새로고침은 같은 load() (질의 문자열을 바꾸지 않는다)
    assert "ensureRefreshButton" in CTABLE and "refreshBtn.addEventListener" in CTABLE
    # 달력 — 단추 · 읽기만
    assert "cal-refresh-btn" in CALENDAR and "async function refreshCalendar" in CALENDAR
    seg = CALENDAR[CALENDAR.index("async function refreshCalendar"):CALENDAR.index('document.addEventListener("keydown"')]
    assert "POST" not in seg and "method" not in seg
    # 새 모듈은 실행 · 계산 길을 알지 못한다
    assert not re.search(r"/lean/run|/compute|runLeanBacktest|method:\s*\"(POST|PUT|DELETE)\"", MISC)
    # 서버 코드는 이 작업에서 고치지 않았다(칩 CSS 도 기존 qd-fchip 그대로 — 새 클래스 없음)
    assert "qd-fchip" in LISTBAR and "qd-fchip" not in MISC
