"""TC-LBT — 미국주식 · 직접매매 화면의 목록 위 줄(필터 칩 + 새로고침) (public/js/listbar-trade.js · us.js · trading.js · 2026-11-05 화면 전수 점검 뒤)

paperlists.js 의 제어기(createListPanel) 위에 얹은 설정을 node 에서 가짜 DOM · 가짜 api 로 돌린다(브라우저 경로 import 는 쓰지 않는다).
1. us-order 주문 내역 — 매수/매도 칩이 맞는 줄만 남기고 풀면 복귀 · 국내 종목은 미국 화면에서 빠진다 · 새로고침이 서버를 다시 부르고(예약 목록도 같이) 필터를 유지 ·
   실패하면 시각을 안 찍는다 · 글은 이스케이프 · 빈 응답. (TC-LBT-01)
2. us-dashboard 종목 카드 — 크게 오름 / 크게 내림 / 그대로 칩(문턱은 quoteview.js 그대로) · 등락 모름 칩은 그런 종목이 있을 때만 ·
   새로고침(자료가 다시 들어옴)에도 걸어 둔 칩이 남는다 · 칩 줄은 격자 밖. (TC-LBT-02)
3. trading-portfolio 보유 표 — 새로고침만(칩 없음) · 다시 읽으면 새 값 · 실패 · 빈 보유 · 이스케이프. (TC-LBT-03)
4. trading-order 최근 주문 — 매수/매도 칩(소문자 buy/sell) · 20건 상한은 거른 뒤에 · 새로고침이 필터 유지. (TC-LBT-04)
5. 구조 — 주문 · 취소를 부르는 길이 없다 · loadUsDashboard 의 새로고침 연결이 그대로 · 칩 줄 칸을 JS 가 만든다(app.html 무변경). (TC-LBT-05)
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
QUOTE = (JS / "quoteview.js").read_text(encoding="utf-8")
TRADE = (JS / "listbar-trade.js").read_text(encoding="utf-8")
US = (JS / "us.js").read_text(encoding="utf-8")
TRADING = (JS / "trading.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _plain(src: str) -> str:
    """ES 모듈 글을 node 한 덩어리로 돌리도록 import 줄 · export 만 뗀다."""
    src = re.sub(r"^import .*$", "", src, flags=re.M)
    return re.sub(r"^export ", "", src, flags=re.M)


PRELUDE = textwrap.dedent("""
    const escHtml = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    const fmt = (n, d = 0) => n == null ? "-" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });
    function makeEl() {
      return { innerHTML: "", textContent: "", value: "", disabled: false, dataset: {}, listeners: [],
        addEventListener(t, f) { this.listeners.push(f); }, contains() { return true; },
        querySelector() { return null; }, querySelectorAll() { return []; }, setAttribute() {}, focus() {} };
    }
    const els = {};
    const byId = id => (els[id] ||= makeEl());
    const calls = [];
    let routes = {};
    async function api(path) {
      calls.push(path);
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
    const DIR = { up: "G", down: "R", flat: "F", none: "N" };
    const tick = () => new Promise(r => setTimeout(r, 0));
""")


def _run(body: str, data: dict | None = None):
    js = "\n".join([PRELUDE, _plain(LISTBAR), _plain(LISTS), _plain(QUOTE), _plain(TRADE), f"const DATA = {json.dumps(data or {}, ensure_ascii=False)};",
                    "(async () => {", "const out = {};", textwrap.dedent(body), "console.log(JSON.stringify(out));", "})().catch(e => { console.error(e); process.exit(1); });"])
    done = subprocess.run([NODE, "-"], input=js, capture_output=True, text=True, timeout=90, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def _us(i: int, symbol: str, side: str, source: str = "SIM") -> dict:
    return {"order_id": f"o{i}", "ts": 1_730_000_000_000 + i, "type": side, "symbol": symbol, "quantity": i, "price": 1000 * i, "source": source}


US_URL = "/api/paper/stocks/orders/history?limit=200"


# ── 1. 미국주식 주문 내역 ────────────────────────────────────────────────────────────
@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_us_order_history_chips_refresh_and_failure():
    """TC-LBT-01 · 매수/매도 칩이 맞는 줄만 · 풀면 복귀 · 국내 종목은 빠진다 · 새로고침이 내역과 예약 목록을 다시 부르고 필터 유지 · 실패하면 시각을 안 찍는다 · 이스케이프."""
    rows = [_us(1, "AAPL", "BUY"), _us(2, "TSLA", "SELL"), _us(3, "005930.KS", "BUY"), _us(4, "NVDA", "BUY", "WEB")]
    more = rows + [_us(5, "MSFT", "SELL"), _us(6, "AMZN", "BUY")]
    evil = [_us(7, "<img src=x onerror=1>", "BUY")]
    got = _run("""
      const extra = [];
      const panel = usOrderPanel({ esc: escHtml, fmt, byId, api, isKrSymbol: s => /\\.(KS|KQ|KN)$/i.test(s), fmtTime: t => "T" + t,
        alsoRefresh: async () => { extra.push("reservations"); }, now: () => new Date("2026-11-05T03:00:00Z") });
      routes["%s"] = { history: DATA.rows };
      await panel.load();
      const host = () => byId("us-order-history").innerHTML;
      out.first = { rows: count(host(), "data-us-order-row"), hasKr: host().includes("005930"), chipBuy: hasChip(host(), "side", "BUY"), chipSell: hasChip(host(), "side", "SELL"),
                    refresh: hasRefresh(host()), oldNote: host().includes("옛 주문"), dollar: host().includes("$4,000"), limit: host().includes("서버에서 받은 4줄 중 미국 종목 3건") };
      click("us-order-history", "side", "BUY");
      out.buy = { rows: count(host(), "data-us-order-row"), pressed: chipPressed(host(), "side", "BUY"), sellRows: count(host(), "badge-sell"), summary: host().includes("조건 매수") };
      click("us-order-history", "side", "");
      out.all = count(host(), "data-us-order-row");
      click("us-order-history", "side", "SELL");
      click("us-order-history", "side", "<script>");                  // 허용 밖 낱말은 무시
      out.sell = { rows: count(host(), "data-us-order-row"), pressed: chipPressed(host(), "side", "SELL") };
      routes["%s"] = { history: DATA.more };
      const before = calls.length;
      clickRefresh("us-order-history");
      await tick(); await tick();
      out.refresh = { calls: calls.length - before, extra: extra.slice(), rows: count(host(), "data-us-order-row"), stillSell: chipPressed(host(), "side", "SELL"), stamp: host().includes("서버에서 다시 읽었습니다(12:00)"), meaning: host().includes("주문 · 취소는 하지 않습니다") };
      routes["%s"] = new Error("서버 오류");
      clickRefresh("us-order-history");
      await tick(); await tick();
      out.fail = { stamp: host().includes("다시 읽었습니다(") , warn: host().includes("다시 읽지 못했습니다(서버 오류)"), rows: count(host(), "data-us-order-row") };
      routes["%s"] = { history: DATA.evil };
      await panel.load();
      click("us-order-history", "side", "");
      out.evil = { raw: host().includes("<img src=x"), esc: host().includes("&lt;img src=x onerror=1&gt;") };
      routes["%s"] = { history: [] };
      await panel.load();
      out.empty = { text: host().includes("주문 내역 없음"), refresh: hasRefresh(host()) };
    """ % (US_URL, US_URL, US_URL, US_URL, US_URL), {"rows": rows, "more": more, "evil": evil})
    assert got["first"]["rows"] == 3 and not got["first"]["hasKr"]
    assert got["first"]["chipBuy"] and got["first"]["chipSell"] and got["first"]["refresh"]
    assert got["first"]["oldNote"] and got["first"]["dollar"] and got["first"]["limit"]
    assert got["buy"] == {"rows": 2, "pressed": True, "sellRows": 0, "summary": True}
    assert got["all"] == 3
    assert got["sell"] == {"rows": 1, "pressed": True}
    assert got["refresh"]["calls"] == 1 and got["refresh"]["extra"] == ["reservations"]
    assert got["refresh"]["rows"] == 2 and got["refresh"]["stillSell"] and got["refresh"]["stamp"] and got["refresh"]["meaning"]
    assert got["fail"] == {"stamp": False, "warn": True, "rows": 2}
    assert got["evil"] == {"raw": False, "esc": True}
    assert got["empty"] == {"text": True, "refresh": True}


# ── 2. 미국주식 대시보드 종목 카드 ───────────────────────────────────────────────────
def _card(sym: str, pct, price: float = 100.0, key: str = "change_pct") -> dict:
    d = {"symbol": sym, "name": f"{sym} 회사", "price": price}
    if pct is not None:
        d[key] = pct
    return d


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_us_cards_move_chips_keep_across_refresh():
    """TC-LBT-02 · 문턱은 quoteview.js 그대로(1.5 는 크게 오름) · 칩이 맞는 종목만 · 등락 모름 칩은 그런 종목이 있을 때만 · 자료가 다시 들어와도 칩이 남는다 · 이스케이프."""
    stocks = [_card("UP1", 2.0), _card("DN1", -3.2), _card("FL1", 0.3), _card("EDGE", 1.5), _card("PY", 1.6, key="change_p"), _card("NA", None)]
    stocks_after = [_card("UP1", 2.4), _card("DN1", -1.0), _card("FL1", 0.1), _card("NEW", 5.0)]
    got = _run("""
      let stash = { rows: DATA.stocks, meta: { noteHtml: "지연 시세 · 외부 시세를 다시 받았습니다(12:00)" } };
      const panel = usCardsPanel({ esc: escHtml, fmt, dirColor: DIR, byId, load: async () => stash });
      await panel.load();
      const cards = () => byId("us-signal-cards").innerHTML;
      const bar = () => byId("us-signal-bar").innerHTML;
      const syms = () => (cards().match(/data-us-card="([^"]*)"/g) || []).map(s => s.slice(14, -1));
      out.buckets = [usMoveBucket(1.49), usMoveBucket(1.5), usMoveBucket(-1.5), usMoveBucket(0), usMoveBucket(null), usMoveBucket(undefined), usMoveBucket("2")];
      out.first = { syms: syms(), chips: ["up","down","flat","unknown"].map(v => hasChip(bar(), "move", v)), refreshBtn: hasRefresh(bar()), barOutsideGrid: !cards().includes("data-lb-filter"),
                    note: cards().includes("외부 시세를 다시 받았습니다(12:00)"), rule: bar().includes("±1.5% 안"), limit: bar().includes("받은 종목 안에서 거릅니다") };
      click("us-signal-bar", "move", "up");
      out.up = { syms: syms(), pressed: chipPressed(bar(), "move", "up") };
      click("us-signal-bar", "move", "down");
      out.down = syms();
      click("us-signal-bar", "move", "flat");
      out.flat = syms();
      click("us-signal-bar", "move", "unknown");
      out.unknown = syms();
      click("us-signal-bar", "move", "up");
      stash = { rows: DATA.after, meta: { noteHtml: "" } };       // 새로고침 = loadUsDashboard 가 새로 받은 종목을 다시 넣는다
      await panel.load();
      out.afterRefresh = { syms: syms(), pressed: chipPressed(bar(), "move", "up"), unknownChip: hasChip(bar(), "move", "unknown") };
      click("us-signal-bar", "move", "");
      out.afterClear = syms().length;
      stash = { rows: [{ symbol: "<b>x</b>", name: "<img src=x onerror=1>", price: 1, change_pct: 2 }], meta: null };
      await panel.load();
      out.evil = { raw: cards().includes("<img src=x") || cards().includes("<b>x</b>"), esc: cards().includes("&lt;img src=x onerror=1&gt;") };
      stash = { rows: [], meta: null };
      await panel.load();
      out.empty = cards().includes("시세를 받지 못했습니다");
    """, {"stocks": stocks, "after": stocks_after})
    assert got["buckets"] == ["flat", "up", "down", "flat", "unknown", "unknown", "unknown"]
    assert got["first"]["syms"] == ["UP1", "DN1", "FL1", "EDGE", "PY", "NA"]
    assert got["first"]["chips"] == [True, True, True, True]
    assert not got["first"]["refreshBtn"] and got["first"]["barOutsideGrid"] and got["first"]["note"] and got["first"]["rule"] and got["first"]["limit"]
    assert got["up"] == {"syms": ["UP1", "EDGE", "PY"], "pressed": True}
    assert got["down"] == ["DN1"] and got["flat"] == ["FL1"] and got["unknown"] == ["NA"]
    assert got["afterRefresh"] == {"syms": ["UP1", "NEW"], "pressed": True, "unknownChip": False}
    assert got["afterClear"] == 4
    assert got["evil"] == {"raw": False, "esc": True}
    assert got["empty"] is True


# ── 3. 직접매매 보유 표 ──────────────────────────────────────────────────────────────
def _hold(sym: str, name: str, cur=70000) -> dict:
    return {"symbol": sym, "name": name, "quantity": 3, "avg_price": 60000, "current_price": cur, "eval_amount": None if cur is None else cur * 3}


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_trading_portfolio_refresh_only():
    """TC-LBT-03 · 칩 없이 새로고침만 · 다시 읽으면 새 값 · 실패하면 시각을 안 찍고 이전 표를 둔다 · 빈 보유 · 이스케이프."""
    got = _run("""
      const panel = portfolioPanel({ esc: escHtml, fmt, byId, api, now: () => new Date("2026-11-05T03:00:00Z") });
      const host = () => byId("portfolio-table").innerHTML;
      routes["/api/portfolio"] = { holdings: DATA.a };
      await panel.load();
      out.first = { rows: count(host(), "<tr class=\\"border-b border-white/5\\">"), chips: host().includes("data-lb-filter"), refresh: hasRefresh(host()), basis: host().includes("data-pf-basis"), dash: host().includes(">-</td>") };
      routes["/api/portfolio"] = { holdings: DATA.b };
      const before = calls.length;
      clickRefresh("portfolio-table");
      await tick(); await tick();
      out.refresh = { calls: calls.length - before, hasNew: host().includes("현대차"), hasOld: host().includes("삼성전자"), stamp: host().includes("서버에서 다시 읽었습니다(12:00)"), meaning: host().includes("주문 · 계산은 하지 않습니다") };
      routes["/api/portfolio"] = new Error("연결 실패");
      clickRefresh("portfolio-table");
      await tick(); await tick();
      out.fail = { warn: host().includes("다시 읽지 못했습니다(보유 종목을 불러오지 못했습니다 — 연결 실패)"), kept: host().includes("현대차"), stamp: host().includes("다시 읽었습니다(") };
      routes["/api/portfolio"] = { holdings: [] };
      await panel.load();
      out.empty = { text: host().includes("보유 종목이 없습니다."), refresh: hasRefresh(host()) };
      routes["/api/portfolio"] = { holdings: DATA.evil };
      await panel.load();
      out.evil = { raw: host().includes("<img src=x"), esc: host().includes("&lt;img src=x onerror=1&gt;") };
      const p2 = portfolioPanel({ esc: escHtml, fmt, byId: id => byId("x" + id), api });
      routes["/api/portfolio"] = new Error("처음부터 실패");
      await p2.load();
      out.firstFail = byId("xportfolio-table").innerHTML.includes("보유 종목을 불러오지 못했습니다 — 처음부터 실패");
    """, {"a": [_hold("005930", "삼성전자"), _hold("000660", "하이닉스", None)], "b": [_hold("005380", "현대차")],
          "evil": [_hold("<b>1</b>", "<img src=x onerror=1>")]})
    assert got["first"] == {"rows": 2, "chips": False, "refresh": True, "basis": True, "dash": True}
    assert got["refresh"] == {"calls": 1, "hasNew": True, "hasOld": False, "stamp": True, "meaning": True}
    assert got["fail"] == {"warn": True, "kept": True, "stamp": False}
    assert got["empty"] == {"text": True, "refresh": True}
    assert got["evil"] == {"raw": False, "esc": True}
    assert got["firstFail"] is True


# ── 4. 직접매매 최근 주문 ────────────────────────────────────────────────────────────
def _ord(i: int, side: str, name: str = "삼성전자") -> dict:
    return {"id": i, "order_type": side, "name": name, "symbol": "005930.KS", "quantity": 1, "price": 70000, "broker": "virtual", "created_at": f"2026-11-0{1 + i % 5}T09:00:00"}


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_trading_orders_chips_refresh_and_cap():
    """TC-LBT-04 · 매수/매도 칩(소문자 order_type) · 20건 상한은 거른 뒤에 · 새로고침이 서버를 다시 부르고 필터 유지 · 빠진 주문 안내가 남는다 · 이스케이프 · 빈 응답."""
    many = [_ord(i, "buy" if i % 2 == 0 else "sell") for i in range(1, 51)]            # 매수 25 · 매도 25
    after = many + [_ord(99, "sell", "<img src=x onerror=1>")]
    got = _run("""
      const panel = tradeOrderPanel({ esc: escHtml, fmt, byId, api, now: () => new Date("2026-11-05T03:00:00Z") });
      const host = () => byId("order-history").innerHTML;
      routes["/api/orders"] = { orders: DATA.many };
      await panel.load();
      out.first = { rows: count(host(), "data-trade-order-row"), chips: [hasChip(host(), "side", "BUY"), hasChip(host(), "side", "SELL")], refresh: hasRefresh(host()),
                    guide: host().includes("자동매매 현황"), limit: host().includes("서버가 준 50건 안에서 거릅니다 · 최근 20건만 보입니다") };
      click("order-history", "side", "BUY");
      out.buy = { rows: count(host(), "data-trade-order-row"), sell: count(host(), "badge-sell"), guide: host().includes("자동매매 현황") };
      click("order-history", "side", "SELL");
      routes["/api/orders"] = { orders: DATA.after };
      const before = calls.length;
      clickRefresh("order-history");
      await tick(); await tick();
      out.refresh = { calls: calls.length - before, pressed: chipPressed(host(), "side", "SELL"), rows: count(host(), "data-trade-order-row"), buy: count(host(), "badge-buy"),
                      stamp: host().includes("서버에서 다시 읽었습니다(12:00)"), raw: host().includes("<img src=x"), esc: host().includes("&lt;img src=x onerror=1&gt;") };
      routes["/api/orders"] = { orders: [] };
      await panel.load();
      out.empty = { text: host().includes("주문 내역 없음"), guide: host().includes("자동매매 현황"), refresh: hasRefresh(host()) };
    """, {"many": many, "after": after})
    assert got["first"] == {"rows": 20, "chips": [True, True], "refresh": True, "guide": True, "limit": True}
    assert got["buy"] == {"rows": 20, "sell": 0, "guide": True}
    assert got["refresh"]["calls"] == 1 and got["refresh"]["pressed"] and got["refresh"]["rows"] == 20 and got["refresh"]["buy"] == 0
    assert got["refresh"]["stamp"] and not got["refresh"]["raw"]
    assert got["empty"] == {"text": True, "guide": True, "refresh": True}


# ── 5. 구조 ──────────────────────────────────────────────────────────────────────────
def test_structure_no_order_paths_and_dashboard_refresh_kept():
    """TC-LBT-05 · 새 모듈은 주문 · 취소 길(POST · DELETE · 주문 경로)을 모른다 · loadUsDashboard 의 새로고침 연결과 serverRefreshNote 가 그대로 ·
    칩 줄 칸은 JS 가 만든다(app.html 에 us-signal-bar 가 없다) · 두 화면 파일이 새 모듈을 가져온다."""
    code = re.sub(r"//[^\n]*", "", TRADE)
    for banned in ("POST", "DELETE", "method", "reservations", "/run", "compute", "/preview"):
        assert banned not in code, banned
    calls = re.findall(r"\.api\(([^)]*)\)", code)                       # 서버를 부르는 곳은 전부 인자 하나(GET)뿐이다
    assert calls and all("," not in c for c in calls), calls
    assert '"?refresh=true"' in US and "loadUsDashboard({ refresh: true })" in US
    assert 'import { serverRefreshNote } from "/js/listbar.js";' in US and "serverRefreshNote(resp.refresh)" in US
    assert 'from "/js/listbar-trade.js"' in US and 'from "/js/listbar-trade.js"' in TRADING
    html = (PUB / "app.html").read_text(encoding="utf-8")
    assert "us-signal-bar" not in html


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_ensure_bar_host_creates_once_before_anchor():
    """TC-LBT-05b · 칩 줄 칸을 목록 칸 바로 앞에 한 번만 만든다 · 기준 칸이 없으면 만들지 않는다."""
    got = _run("""
      const log = [];
      const anchor = { parentNode: { insertBefore(el, ref) { log.push([el.id, ref === anchor]); doc.made[el.id] = el; } } };
      const doc = { made: {}, getElementById(id) { return id === "grid" ? anchor : this.made[id] || null; }, createElement() { return { id: "" }; } };
      const a = ensureBarHost(doc, "grid", "bar");
      const b = ensureBarHost(doc, "grid", "bar");
      out.same = a === b; out.log = log;
      out.missing = ensureBarHost(doc, "nope", "bar2");
      out.noDoc = ensureBarHost(null, "grid", "bar");
    """)
    assert got["same"] is True and got["log"] == [["bar", True]]
    assert got["missing"] is None and got["noDoc"] is None
