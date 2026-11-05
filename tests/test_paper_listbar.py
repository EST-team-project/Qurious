"""TC-PLB — 모의투자 4개 화면의 표 위 줄(필터 칩 + 새로고침) (public/js/paperlists.js · paper.js · app.html · 2026-11-05 화면 전수 점검 뒤)

퀀트 대시보드 관찰 목록 표(quant.js qdWatch*)와 같은 모양 · 같은 동작을 공용 도우미(listbar.js)로 모의투자 화면에 붙였다.
paper.js 의 실제 표 함수 · 패널 설정을 잘라 node 에서 가짜 DOM · 가짜 api 로 돌린다(브라우저 경로 import 는 쓰지 않는다).
1. paper-stock — 주문 내역에 매매 · 출처(응답에 있는 값만) 칩 · 눌러 둔 값이 새 응답에 사라져도 칩이 남아 풀 수 있다 · 새로고침이 서버를 다시 부르고 필터를 유지 ·
   실패하면 「다시 읽었습니다」 시각을 찍지 않는다 · 이스케이프. (TC-PLB-01)
   보유(+현금) · 스탑은 새로고침만이고 빈 목록에서도 단추가 보인다 (TC-PLB-01b) · 고를 값이 「전체」 하나뿐인 칩 묶음은 줄에서 빠진다 (TC-PLB-01c)
2. paper-crypto — 순위 상승/하락 칩(칩 줄은 스크롤 상자 밖 · # 는 거르기 전 순위) · 내역 매매 칩(소문자 buy/sell 도) · 보유 새로고침(현금 갱신). (TC-PLB-02)
3. paper-alternative — 구분 칩은 응답의 category 그대로(파생상품) · 카드/보유/내역 · 주문 칸 목록은 거르지 않고 새로고침 뒤에도 고른 상품이 유지된다. (TC-PLB-03)
4. paper-dashboard — 최근 체결 구분/매매/출처 칩(거른 뒤에 15줄로 자른다) · 새로고침 묶음이 KPI · 자산 구성 · QFRS/추이까지 읽고 백테스트 길은 안 부른다. (TC-PLB-04, 05)
5. 구조 — 칩 CSS 는 항상 로드 · 새 칸 · 가져오기. (TC-PLB-06)
node 가 없으면 1~5 는 건너뛴다.
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
PAPER = (PUB / "js" / "paper.js").read_text(encoding="utf-8")
LISTS = (PUB / "js" / "paperlists.js").read_text(encoding="utf-8")
LISTBAR = (PUB / "js" / "listbar.js").read_text(encoding="utf-8")
HTML = (PUB / "app.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _plain(src: str) -> str:
    """ES 모듈 글을 node 한 덩어리로 돌리도록 import 줄 · export 만 뗀다."""
    src = re.sub(r"^import .*$", "", src, flags=re.M)
    return re.sub(r"^export ", "", src, flags=re.M)


def _fn(name: str) -> str:
    m = re.search(rf"^(?:async )?function {name}\(", PAPER, re.M)
    assert m, name
    return PAPER[m.start():PAPER.index("\n}\n", m.start()) + 3]


def _const(name: str) -> str:
    m = re.search(rf"^const {name} = ", PAPER, re.M)
    assert m, name
    end = "\n});\n" if PAPER.startswith("listPanel({", m.end()) or PAPER.startswith("createRefreshGroup", m.end()) else ";\n"
    return PAPER[m.start():PAPER.index(end, m.start()) + len(end)]


def _top_consts() -> str:
    """paper.js 맨 위 도우미(won · signCls · ts · sideBadge · kpi · emptyRow · listPanel)."""
    a = PAPER.index("const won = ")
    b = PAPER.index("const listPanel = ")
    return PAPER[a:PAPER.index(";\n", b) + 2]


PRELUDE = textwrap.dedent("""
    const escHtml = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    const fmt = (n, d = 0) => n == null ? "-" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });
    const fmtPct = n => n == null ? "-" : `${Number(n) >= 0 ? "+" : ""}${Number(n).toFixed(2)}%`;
    const toasts = [];
    const setToast = (m, k) => toasts.push([m, k]);
    function makeEl() {
      return { innerHTML: "", textContent: "", value: "", disabled: false, dataset: {}, listeners: [],
        addEventListener(t, f) { this.listeners.push(f); }, contains() { return true; },
        querySelector() { return null; }, querySelectorAll() { return []; }, setAttribute() {}, focus() {} };
    }
    const els = {};
    const byId = id => (els[id] ||= makeEl());
    const $ = byId;
    const calls = [];
    let routes = {};
    async function api(path) {
      calls.push(path);
      const r = routes[path];
      if (r instanceof Error) throw r;
      if (r === undefined) throw new Error("가짜 경로 없음 " + path);
      return JSON.parse(JSON.stringify(r));
    }
    function stockOrder() {} function cryptoOrder() {} function altOrder() {} function altChartLoad() { calls.push("chart"); }
    function cryptoTicker() { calls.push("ticker"); } function cancelStopOrder() {}
    const click = (rootId, key, value) => byId(rootId).listeners.forEach(f => f({ target: { closest: s => (s === "button[data-lb-filter]" ? { dataset: { lbFilter: key, value } } : null) } }));
    const clickRefresh = rootId => byId(rootId).listeners.forEach(f => f({ target: { closest: s => (s === "button[data-lb-refresh]" ? {} : null) } }));
    const count = (html, s) => html.split(s).length - 1;
    const chipPressed = (html, key, value) => html.includes(`data-lb-filter="${key}" data-value="${value}" aria-pressed="true"`);
    const hasChip = (html, key, value) => html.includes(`data-lb-filter="${key}" data-value="${value}"`);
""")


def _run(parts: list[str], body: str, data: dict | None = None):
    js = "\n".join([PRELUDE, _plain(LISTBAR), _plain(LISTS), _top_consts(), *parts, f"const DATA = {json.dumps(data or {}, ensure_ascii=False)};",
                    "(async () => {", "const out = {};", textwrap.dedent(body), "console.log(JSON.stringify(out));", "})().catch(e => { console.error(e); process.exit(1); });"])
    done = subprocess.run([NODE, "-"], input=js, capture_output=True, text=True, timeout=90, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# ── 가짜 응답 ─────────────────────────────────────────────────────────────

def _stock(i: int, name: str, side: str, source: str) -> dict:
    return {"order_id": f"o{i}", "status": "filled", "order_kind": "market", "ts": 1_730_000_000_000 + i, "type": side, "symbol": f"00000{i}.KS", "name": name,
            "quantity": 1, "price": 1000, "amount": 1000, "commission": 0, "fee_clearing": 0, "tax_transfer": 0, "tax_rural": 0, "net_amount": 1000, "source": source}


HIST_URL = "/api/paper/stocks/orders/history?limit=30"


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_stock_history_chips_refresh_and_failure():
    """TC-PLB-01 · 매매 · 출처 칩이 맞는 줄만 남기고 풀면 복귀 · 출처 칩은 응답에 있는 값만 · 새로고침이 서버를 다시 부르고 필터를 유지 ·
    눌러 둔 출처가 사라져도 칩이 남는다 · 실패하면 시각을 안 찍는다 · 글은 이스케이프된다."""
    rows = [_stock(1, "삼성전자", "BUY", "WEB"), _stock(2, "하이닉스", "SELL", "WEB"), _stock(3, "카카오", "BUY", "SIM"), _stock(4, "네이버", "SELL", "SIM")]
    rows_after = rows + [_stock(5, "현대차", "BUY", "SIM"), _stock(6, "기아", "SELL", "WEB")]
    evil = [_stock(7, "<img src=x onerror=1>", "BUY", "<b>x</b>")]
    got = _run([_fn("psHistoryBody"), _const("psHistoryPanel")], f"""
      const URL = "{HIST_URL}";
      routes[URL] = {{ history: DATA.rows }};
      const p = psHistoryPanel;
      await p.load();
      const root = "ps-history";
      const names = html => ["삼성전자", "하이닉스", "카카오", "네이버", "현대차", "기아"].filter(n => html.includes(n));
      let html = byId(root).innerHTML;
      out.start = {{ names: names(html), sources: ["WEB", "PAPER", "PINE", "SIM"].filter(s => hasChip(html, "source", s)), refresh: html.includes("data-lb-refresh"), sideAll: chipPressed(html, "side", "") }};
      click(root, "side", "BUY");
      out.buy = names(byId(root).innerHTML);
      click(root, "source", "SIM");
      html = byId(root).innerHTML;
      out.buySim = {{ names: names(html), pressed: chipPressed(html, "side", "BUY") && chipPressed(html, "source", "SIM"), note: html.match(/data-lb-note>([^<]*)</)[1] }};
      const before = calls.length;
      routes[URL] = {{ history: DATA.after }};
      clickRefresh(root);
      await new Promise(r => setTimeout(r, 20));
      html = byId(root).innerHTML;
      out.refresh = {{ fetched: calls.slice(before).filter(c => c === URL).length, names: names(html), pressed: chipPressed(html, "side", "BUY") && chipPressed(html, "source", "SIM"),
        stamped: /서버에서 다시 읽었|주문 내역을 다시 읽었습니다\\(\\d\\d:\\d\\d\\)/.test(html), noRecalc: html.includes("신호는 새로 계산하지 않습니다") }};
      // 눌러 둔 출처(SIM)가 새 응답에 하나도 없다 → 칩은 남고 · 본문은 안내 · 전체로 풀면 복귀
      routes[URL] = {{ history: DATA.rows.filter(r => r.source === "WEB") }};
      await p.refresh();
      html = byId(root).innerHTML;
      out.gone = {{ chip: hasChip(html, "source", "SIM"), pressed: chipPressed(html, "source", "SIM"), msg: html.includes("이 조건에 맞는 줄이 없습니다"), names: names(html) }};
      click(root, "source", "");
      click(root, "side", "");
      out.released = names(byId(root).innerHTML);
      // 허용 밖 낱말은 무시
      click(root, "side", "HOLD");
      out.ignored = chipPressed(byId(root).innerHTML, "side", "");
      // 실패 — 시각을 찍지 않고 이전 값을 보이며 실패를 알린다
      routes[URL] = new Error("서버 오류 503");
      const ok = await p.refresh();
      html = byId(root).innerHTML;
      out.fail = {{ ok, stamped: /다시 읽었습니다\\(\\d\\d:\\d\\d\\)/.test(html), failedNote: html.includes("다시 읽지 못했습니다(서버 오류 503)"), kept: names(html) }};
      // 이스케이프
      routes[URL] = {{ history: DATA.evil }};
      await p.refresh();
      html = byId(root).innerHTML;
      out.evil = {{ rawImg: html.includes("<img src=x"), escImg: html.includes("&lt;img src=x"), rawB: html.includes("<b>x</b>"), escChip: html.includes("&lt;b&gt;x&lt;/b&gt;"), valueEsc: html.includes('data-value="&lt;b&gt;x&lt;/b&gt;"') }};
    """, {"rows": rows, "after": rows_after, "evil": evil})
    assert got["start"] == {"names": ["삼성전자", "하이닉스", "카카오", "네이버"], "sources": ["WEB", "SIM"], "refresh": True, "sideAll": True}, got["start"]
    assert got["buy"] == ["삼성전자", "카카오"]
    assert got["buySim"]["names"] == ["카카오"] and got["buySim"]["pressed"] is True, got["buySim"]
    assert "조건 매수 · SIM — 받은 4줄 중 1줄" in got["buySim"]["note"] and "최근 30줄까지" in got["buySim"]["note"], got["buySim"]["note"]
    assert got["refresh"]["fetched"] == 1 and got["refresh"]["pressed"] is True and got["refresh"]["noRecalc"] is True, got["refresh"]
    assert got["refresh"]["names"] == ["카카오", "현대차"], "새로고침은 새 응답을 받아 같은 필터(매수 · SIM)로 다시 건다"
    assert got["gone"] == {"chip": True, "pressed": True, "msg": True, "names": []}, got["gone"]
    assert got["released"] == ["삼성전자", "하이닉스"] and got["ignored"] is True
    assert got["fail"]["ok"] is False and got["fail"]["stamped"] is False and got["fail"]["failedNote"] is True and got["fail"]["kept"] == ["삼성전자", "하이닉스"], got["fail"]
    assert got["evil"] == {"rawImg": False, "escImg": True, "rawB": False, "escChip": True, "valueEsc": True}, got["evil"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_stock_positions_and_stops_are_refresh_only_and_visible_when_empty():
    """TC-PLB-01b · 보유 · 스탑 표는 칩 없이 새로고침만 — 빈 목록에서도 단추가 보인다 · 보유 새로고침은 머리글 현금(account)도 같이 읽는다 · 실패해도 단추가 남는다."""
    got = _run([_fn("refreshStockCash"), _fn("psPositionsBody"), _const("psPositionsPanel"), _fn("psStopBody"), _const("psStopPanel")], """
      routes["/api/paper/stocks/positions"] = { positions: [] };
      routes["/api/paper/stocks/orders/stop"] = { orders: [] };
      routes["/api/paper/account"] = { cash: 98765000 };
      await psPositionsPanel.load(); await psStopPanel.load();
      let pos = byId("ps-positions").innerHTML, stop = byId("ps-stop-list").innerHTML;
      out.empty = { posRefresh: pos.includes("data-lb-refresh"), posChips: pos.includes("data-lb-filter"), posMsg: pos.includes("보유 종목이 없습니다"),
        stopRefresh: stop.includes("data-lb-refresh"), stopMsg: stop.includes("대기 중인 스탑 주문이 없습니다") };
      // 새로고침 — 보유 + 현금
      routes["/api/paper/stocks/positions"] = { positions: [{ name: "삼성전자", symbol: "005930.KS", quantity: 3, avgPrice: 70000, currentPrice: 71000, evalAmount: 213000, pnl: 3000, pnlRate: 1.4 }] };
      const before = calls.length;
      clickRefresh("ps-positions");
      await new Promise(r => setTimeout(r, 20));
      pos = byId("ps-positions").innerHTML;
      out.refresh = { calls: calls.slice(before).sort(), row: pos.includes("삼성전자"), cash: byId("ps-cash").textContent, note: /보유 종목을 다시 읽었습니다\\(\\d\\d:\\d\\d\\)/.test(pos),
        price: pos.includes("시세를 못 받은 종목은 평균단가로 보입니다") };
      // 읽기 실패 — 단추는 남는다
      routes["/api/paper/stocks/orders/stop"] = new Error("스탑 목록 오류");
      await psStopPanel.load();
      stop = byId("ps-stop-list").innerHTML;
      out.fail = { text: stop.includes("스탑 목록 오류"), refresh: stop.includes("data-lb-refresh") };
    """)
    assert got["empty"] == {"posRefresh": True, "posChips": False, "posMsg": True, "stopRefresh": True, "stopMsg": True}, got["empty"]
    assert got["refresh"]["calls"] == ["/api/paper/account", "/api/paper/stocks/positions"], got["refresh"]
    assert got["refresh"]["row"] and got["refresh"]["cash"] == "98,765,000원" and got["refresh"]["note"] and got["refresh"]["price"], got["refresh"]
    assert got["fail"] == {"text": True, "refresh": True}, got["fail"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_group_without_real_choices_is_dropped_from_the_bar():
    """TC-PLB-01c · 고를 값이 「전체」 하나뿐인 칩 묶음(내역이 비어 출처 값이 없다)은 줄에서 빠지고 · 매매 칩과 새로고침은 남는다 ·
    출처가 생기면 나타나고 · 눌러 둔 출처는 응답에서 사라져도 남는다(TC-PLB-01)."""
    got = _run([_fn("psHistoryBody"), _const("psHistoryPanel")], f"""
      const URL = "{HIST_URL}";
      routes[URL] = {{ history: [] }};
      await psHistoryPanel.load();
      let html = byId("ps-history").innerHTML;
      out.empty = {{ side: count(html, 'data-lb-filter="side"'), source: html.includes('data-lb-filter="source"'), refresh: html.includes("data-lb-refresh"), msg: html.includes("주문 내역이 없습니다") }};
      routes[URL] = {{ history: DATA.rows }};
      await psHistoryPanel.refresh();
      html = byId("ps-history").innerHTML;
      out.filled = count(html, 'data-lb-filter="source"');
    """, {"rows": [_stock(1, "삼성전자", "BUY", "SIM")]})
    assert got["empty"] == {"side": 3, "source": False, "refresh": True, "msg": True}, got["empty"]
    assert got["filled"] == 2, "전체 + SIM"


# ── 코인 ─────────────────────────────────────────────────────────────────

def _rank(code: str, name: str, rate: float) -> dict:
    return {"market": f"KRW-{code}", "symbol": code, "koreanName": name, "price": 1000, "changeRate": rate, "accTradePrice24h": 5e9}


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_crypto_rankings_history_and_holdings():
    """TC-PLB-02 · 순위 상승/하락 칩(등락 0 은 어느 쪽도 아님 · # 는 거르기 전 순위 · 칩 줄은 스크롤 상자 밖) · 내역 매매 칩(소문자 buy/sell 도) · 보유 새로고침이 현금도 갱신."""
    ranks = [_rank("AAA", "에이", 0.02), _rank("BBB", "비", -0.01), _rank("CCC", "씨", 0.0), _rank("DDD", "디", 0.005)]
    hist = [{"marketCode": "KRW-BTC", "koreanName": "비트코인", "type": "buy", "quantity": 0.1, "price": 100, "amount": 10, "source": "WEB", "ts": 3},
            {"marketCode": "KRW-ETH", "koreanName": "이더리움", "type": "sell", "quantity": 1, "price": 100, "amount": 100, "source": "WEB", "ts": 2},
            {"marketCode": "KRW-XRP", "koreanName": "리플", "type": "BUY", "quantity": 5, "price": 100, "amount": 500, "source": "WEB", "ts": 1}]
    got = _run([_fn("pcRankingsBody"), _const("pcRankingsPanel"), _fn("pcHistoryBody"), _const("pcHistoryPanel"), _fn("pcHoldHead"), _fn("pcHoldBody"), _const("pcHoldPanel")], """
      const RURL = "/api/paper/crypto/rankings?limit=15";
      routes[RURL] = { rankings: DATA.ranks };
      await pcRankingsPanel.load();
      const bar = () => byId("pc-rankings-bar").innerHTML, body = () => byId("pc-rankings").innerHTML;
      const names = html => ["에이", "비", "씨", "디"].filter(n => new RegExp(`>${n} <span`).test(html));
      out.start = { names: names(body()), barChips: count(bar(), "data-lb-filter"), barRefresh: bar().includes("data-lb-refresh"), bodyHasBar: body().includes("data-lb-") };
      click("pc-rankings-bar", "dir", "UP");
      out.up = { names: names(body()), ranks: [...body().matchAll(/<td>(\\d+)<\\/td><td>/g)].map(m => m[1]), note: bar().match(/data-lb-note>([^<]*)</)[1] };
      click("pc-rankings-bar", "dir", "DOWN");
      out.down = names(body());
      const before = calls.length;
      routes[RURL] = { rankings: [DATA.ranks[1], DATA.ranks[0]] };
      clickRefresh("pc-rankings-bar");
      await new Promise(r => setTimeout(r, 20));
      out.refresh = { fetched: calls.slice(before).filter(c => c === RURL).length, names: names(body()), pressed: chipPressed(bar(), "dir", "DOWN"), ticker: calls.includes("ticker") };
      click("pc-rankings-bar", "dir", "");
      out.released = names(body());
      // 내역 — 매매 칩
      routes["/api/paper/trade/order/history?limit=30"] = { history: DATA.hist };
      await pcHistoryPanel.load();
      const hh = () => byId("pc-history").innerHTML;
      out.hist0 = ["비트코인", "이더리움", "리플"].filter(n => hh().includes(n));
      click("pc-history", "side", "BUY");
      out.histBuy = ["비트코인", "이더리움", "리플"].filter(n => hh().includes(n));
      click("pc-history", "side", "SELL");
      out.histSell = ["비트코인", "이더리움", "리플"].filter(n => hh().includes(n));
      // 보유 — 새로고침이 현금(머리글)도 갱신
      routes["/api/paper/trade/hold"] = { memberAsset: 1000000, totalBuyKrw: 0, totalEvalKrw: 0, holdCryptoList: [] };
      await pcHoldPanel.load();
      routes["/api/paper/trade/hold"] = { memberAsset: 777000, totalBuyKrw: 10, totalEvalKrw: 20, holdCryptoList: [{ koreanName: "비트코인", marketCode: "KRW-BTC", holdCount: 0.1, buyAverage: 1, currentPrice: 2, evalKrw: 3, pnl: 1, pnlRate: 1 }] };
      clickRefresh("pc-hold");
      await new Promise(r => setTimeout(r, 20));
      out.hold = { cash: byId("pc-cash").textContent, row: byId("pc-hold").innerHTML.includes("비트코인"), head: byId("pc-hold").innerHTML.includes("매수 원금 10원") };
    """, {"ranks": ranks, "hist": hist})
    assert got["start"] == {"names": ["에이", "비", "씨", "디"], "barChips": 3, "barRefresh": True, "bodyHasBar": False}, got["start"]
    assert got["up"]["names"] == ["에이", "디"] and got["up"]["ranks"] == ["1", "4"], got["up"]
    assert "조건 상승 — 받은 4종목 중 2종목" in got["up"]["note"] and "등락 0 은 상승 · 하락 어느 쪽에도" in got["up"]["note"], got["up"]["note"]
    assert got["down"] == ["비"]
    assert got["refresh"] == {"fetched": 1, "names": ["비"], "pressed": True, "ticker": False}, got["refresh"]
    assert got["released"] == ["에이", "비"]
    assert got["hist0"] == ["비트코인", "이더리움", "리플"] and got["histBuy"] == ["비트코인", "리플"] and got["histSell"] == ["이더리움"], got
    assert got["hold"] == {"cash": "777,000원", "row": True, "head": True}, got["hold"]


# ── 대체자산 ─────────────────────────────────────────────────────────────

CATS = ["선물", "옵션", "파생상품", "금", "은", "부동산"]


def _mk(symbol: str, name: str, cat: str) -> dict:
    return {"symbol": symbol, "name": name, "category": cat, "price": 1000, "changeRate": 0.5, "unit": "1계약", "marginRate": 100, "tradeAmountPerUnit": 1000, "source": "교육용 기준 시세"}


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_alt_cards_positions_history_use_response_categories():
    """TC-PLB-03 · 구분 칩은 응답의 category 값 그대로(파생상품 — 지어낸 「파생」 이 아니다) · 카드/보유/내역 모두 거르고 · 주문 칸 목록은 안 거른다 ·
    새로고침 뒤에도 필터 · 고른 상품이 유지 · 총 평가금액은 전체 보유 기준이라고 밝힌다 · category 글은 이스케이프."""
    markets = [_mk("FUT-K200", "코스피선물", "선물"), _mk("OPT-K200-C", "콜옵션", "옵션"), _mk("DRV-LEV", "레버리지", "파생상품"),
               _mk("MET-GOLD", "금현물", "금"), _mk("MET-SILVER", "은현물", "은"), _mk("RE-SEOUL", "강남지분", "부동산")]
    pos = [{"symbol": "MET-GOLD", "name": "금현물", "category": "금", "quantity": 2, "unit": "1g", "avgPrice": 1, "currentPrice": 2, "evalAmount": 4, "pnl": 2, "volatility": 1.5},
           {"symbol": "FUT-K200", "name": "코스피선물", "category": "선물", "quantity": 1, "unit": "1계약", "avgPrice": 1, "currentPrice": 2, "evalAmount": 6, "pnl": 1, "volatility": None}]
    hist = [{"symbol": "MET-GOLD", "name": "금현물", "category": "금", "type": "BUY", "quantity": 2, "price": 1, "amount": 2, "source": "WEB", "ts": 2},
            {"symbol": "X", "name": "<i>악성</i>", "category": "<i>악성</i>", "type": "SELL", "quantity": 1, "price": 1, "amount": 1, "source": "WEB", "ts": 1}]
    got = _run(["let altCategoryOrder = [];", _fn("altCardHtml"), _const("altMarketsPanel"), _fn("altPositionsHead"), _fn("altPositionsBody"), _const("altPositionsPanel"), _fn("altHistoryBody"), _const("altHistoryPanel")], """
      const MU = "/api/paper/alternatives/markets";
      routes[MU] = { markets: DATA.markets, notice: "교육용 기준 시세" };
      await altMarketsPanel.load();
      const bar = () => byId("pa-markets-bar").innerHTML, cards = () => byId("pa-markets").innerHTML;
      const cats = html => [...html.matchAll(/data-lb-filter="category" data-value="([^"]*)"/g)].map(m => m[1]);
      const cardNames = () => DATA.markets.map(m => m.name).filter(n => cards().includes(n));
      out.start = { cats: cats(bar()), cards: cardNames().length, refresh: bar().includes("data-lb-refresh"), cardsHaveBar: cards().includes("data-lb-"), notice: byId("pa-notice").textContent,
        select: DATA.markets.every(m => byId("pa-symbol").innerHTML.includes(m.symbol)) };
      click("pa-markets-bar", "category", "금");
      out.gold = { cards: cardNames(), selectStillAll: DATA.markets.every(m => byId("pa-symbol").innerHTML.includes(m.symbol)), msg: bar().match(/data-lb-note>([^<]*)</)[1] };
      byId("pa-symbol").value = "OPT-K200-C";                          // 사용자가 고른 상품
      const before = calls.length;
      clickRefresh("pa-markets-bar");
      await new Promise(r => setTimeout(r, 20));
      out.refresh = { fetched: calls.slice(before).filter(c => c === MU).length, cards: cardNames(), pressed: chipPressed(bar(), "category", "금"), selected: byId("pa-symbol").value, chart: calls.includes("chart") };
      click("pa-markets-bar", "category", "");
      out.released = cardNames().length;
      // 보유 — 같은 구분 순서 · 총 평가금액은 전체 기준
      routes["/api/paper/alternatives/positions?volatility=1"] = { positions: DATA.pos, totalEvalAmount: 10 };
      await altPositionsPanel.load();
      const pp = () => byId("pa-positions").innerHTML;
      out.posCats = cats(pp());
      click("pa-positions", "category", "금");
      out.posGold = { rows: ["금현물", "코스피선물"].filter(n => pp().includes(n)), total: pp().includes("총 평가금액 10원 (거르기와 상관없이 전체 보유 기준)") };
      click("pa-positions", "category", "");
      out.posAll = { rows: ["금현물", "코스피선물"].filter(n => pp().includes(n)), plain: pp().includes("총 평가금액 10원<") };
      // 내역 + 이스케이프
      routes["/api/paper/alternatives/orders/history?limit=30"] = { history: DATA.hist };
      await altHistoryPanel.load();
      const hh = byId("pa-history").innerHTML;
      out.hist = { raw: hh.includes("<i>악성"), esc: hh.includes("&lt;i&gt;악성&lt;/i&gt;"), chip: hh.includes('data-value="&lt;i&gt;악성&lt;/i&gt;"') };
      // 상품 목록 실패 → 알림 + 칸 안 안내 + 단추 유지
      routes[MU] = new Error("상품 오류");
      await altMarketsPanel.load();
      out.fail = { toast: toasts.some(t => t[0] === "상품 오류"), refresh: bar().includes("data-lb-refresh"), text: cards().includes("상품 오류") || cards().includes("코스피선물") };
    """, {"markets": markets, "pos": pos, "hist": hist})
    assert got["start"]["cats"] == ["", *CATS] and got["start"]["cards"] == 6 and got["start"]["refresh"] and not got["start"]["cardsHaveBar"], got["start"]
    assert "파생상품" in got["start"]["cats"] and "파생" not in got["start"]["cats"], "응답 값 그대로"
    assert got["start"]["select"] is True and got["start"]["notice"] == "교육용 기준 시세"
    assert got["gold"]["cards"] == ["금현물"] and got["gold"]["selectStillAll"] is True and "조건 금 — 받은 6상품 중 1상품" in got["gold"]["msg"], got["gold"]
    assert got["refresh"] == {"fetched": 1, "cards": ["금현물"], "pressed": True, "selected": "OPT-K200-C", "chart": False}, got["refresh"]
    assert got["released"] == 6
    assert got["posCats"] == ["", "선물", "금"], "칩 순서는 상품 목록 응답의 순서(선물 · … · 금)"
    assert got["posGold"] == {"rows": ["금현물"], "total": True}, got["posGold"]
    assert got["posAll"] == {"rows": ["금현물", "코스피선물"], "plain": True}, got["posAll"]
    assert got["hist"] == {"raw": False, "esc": True, "chip": True}, got["hist"]
    assert got["fail"]["toast"] is True and got["fail"]["refresh"] is True, got["fail"]


# ── 계좌 현황 ────────────────────────────────────────────────────────────

def _rec(i: int, **kw) -> dict:
    base = {"ts": 1_730_000_000_000 + i, "type": "BUY", "source": "PAPER", "quantity": 1, "price": 1000, "amount": 1000}
    return {**base, **kw}


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_dashboard_recent_fills_filter_before_the_15_row_cap():
    """TC-PLB-04 · 최근 체결 구분(주식/코인/대체자산) · 매매 · 출처 칩 — 거르기 전에 15줄로 자르지 않는다(코인이 오래돼도 0줄이 되지 않는다) ·
    칩 줄에 새로고침 단추를 또 두지 않는다(머리글 것 하나) · SIM 안내는 보이는 줄 기준 · loadPaperDashboard 는 KPI 실패도 알린다."""
    stock = [{**_rec(100 + i, name=f"주식{i}", symbol=f"S{i}", source="SIM" if i == 0 else "PAPER", type="SELL" if i % 2 else "BUY")} for i in range(20)]
    crypto = [{**_rec(i, koreanName=f"코인{i}", marketCode=f"KRW-C{i}", type="buy" if i % 2 else "sell")} for i in range(3)]
    alt = [{**_rec(50, name="금현물", category="금", type="BUY")}]
    got = _run([_const("PD_RECENT_CAP"), _const("pdSourceLabel"), _fn("pdRecentBody"), _fn("pdRecentRows"), _const("pdRecentPanel"), _fn("loadPaperDashboard")], """
      routes["/api/paper/stocks/orders/history?limit=30"] = { history: DATA.stock };
      routes["/api/paper/trade/order/history?limit=10"] = { history: DATA.crypto };
      routes["/api/paper/alternatives/orders/history?limit=10"] = { history: DATA.alt };
      routes["/api/paper/account"] = new Error("계좌 오류");
      const okAll = await loadPaperDashboard();               // 계좌 실패 → false · 최근 체결은 그래도 읽는다
      const h = () => byId("pd-recent").innerHTML;
      out.start = { ok: okAll, toast: toasts.length, trs: count(h(), "<tr>") - 1, refreshBtn: h().includes("data-lb-refresh"), groups: ["STOCK", "CRYPTO", "ALT"].filter(v => hasChip(h(), "kind", v)),
        sources: ["PAPER", "SIM"].filter(v => hasChip(h(), "source", v)), note: h().match(/data-lb-note>([^<]*)</)[1], sim: h().includes("SIM(백테스트)</b> 주문 1건") };
      click("pd-recent", "kind", "CRYPTO");
      out.crypto = { trs: count(h(), "<tr>") - 1, names: ["코인0", "코인1", "코인2"].filter(n => h().includes(n)), note: h().match(/data-lb-note>([^<]*)</)[1], sim: h().includes("SIM(백테스트)") };
      click("pd-recent", "side", "BUY");
      out.cryptoBuy = ["코인0", "코인1", "코인2"].filter(n => h().includes(n));         // 소문자 buy 도 매수
      click("pd-recent", "kind", "ALT"); click("pd-recent", "side", "");
      out.alt = { names: h().includes("금현물"), kind: h().includes("<td>금</td>") };
      click("pd-recent", "kind", "STOCK"); click("pd-recent", "source", "SIM");
      out.stockSim = { trs: count(h(), "<tr>") - 1, sim: h().includes("SIM(백테스트)</b> 주문 1건") };
      click("pd-recent", "source", ""); click("pd-recent", "kind", "");
      out.released = count(h(), "<tr>") - 1;
    """, {"stock": stock, "crypto": crypto, "alt": alt})
    assert got["start"]["ok"] is False and got["start"]["toast"] == 1, "KPI 읽기 실패는 알리고 false"
    assert got["start"]["trs"] == 15 and got["start"]["refreshBtn"] is False and got["start"]["groups"] == ["STOCK", "CRYPTO", "ALT"] and got["start"]["sources"] == ["PAPER", "SIM"], got["start"]
    assert "최신 15줄까지" in got["start"]["note"] and "주식 30 · 코인 10 · 대체자산 10줄" in got["start"]["note"] and got["start"]["sim"] is False, "SIM 안내는 보이는 15줄 기준(SIM 주문이 15줄 밖)"
    assert got["crypto"]["trs"] == 3 and got["crypto"]["names"] == ["코인0", "코인1", "코인2"] and got["crypto"]["sim"] is False, got["crypto"]
    assert "조건 코인 — 받은 24줄 중 3줄" in got["crypto"]["note"], got["crypto"]["note"]
    assert got["cryptoBuy"] == ["코인1"], "buy 소문자만 매수 — 코인1(i 홀수)"
    assert got["alt"] == {"names": True, "kind": True}
    assert got["stockSim"] == {"trs": 1, "sim": True}, got["stockSim"]
    assert got["released"] == 15


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_dashboard_refresh_group_reads_everything_and_reports_honestly():
    """TC-PLB-05 · 새로고침 묶음 — 세 읽기를 모두 부르고 · 읽는 중 다시 누르면 무시 · 하나라도 실패하면 시각 대신 실패를 알린다 · 단추는 읽는 동안 잠긴다."""
    got = _run([], """
      const log = [], notes = [], busy = [];
      let fail = false;
      const mk = name => async () => { log.push(name); await new Promise(r => setTimeout(r, 10)); return name === "perf" && fail ? false : true; };
      const run = createRefreshGroup({ tasks: [mk("kpi"), mk("alloc"), mk("perf")], setNote: t => notes.push(t), setBusy: b => busy.push(b), tail: "저장된 값만 읽었습니다", now: () => new Date(Date.UTC(2026, 10, 5, 3, 7)) });
      const first = run(); const second = run();                    // 읽는 중 두 번째는 무시
      const r1 = await first; const r2 = await second;
      out.ok = { r1, r2, log: log.slice(), last: notes[notes.length - 1], first: notes[0], busy: busy.slice() };
      log.length = 0; notes.length = 0; fail = true;
      const r3 = await run();
      out.fail = { r3, log: log.slice(), last: notes[notes.length - 1] };
      const run2 = createRefreshGroup({ tasks: [async () => { throw new Error("x"); }], setNote: t => notes.push(t) });
      out.throws = { r: await run2(), last: notes[notes.length - 1] };
    """)
    assert got["ok"]["r1"] is True and got["ok"]["r2"] is False and sorted(got["ok"]["log"]) == ["alloc", "kpi", "perf"], got["ok"]
    assert got["ok"]["first"] == "서버에서 다시 읽는 중…" and got["ok"]["last"] == "서버에서 다시 읽었습니다(12:07) — 저장된 값만 읽었습니다" and got["ok"]["busy"] == [True, False], got["ok"]
    assert got["fail"]["r3"] is False and got["fail"]["last"] == "1곳은 다시 읽지 못했습니다 — 읽은 곳만 새 값입니다" and "다시 읽었습니다(" not in got["fail"]["last"], got["fail"]
    assert got["throws"]["r"] is False and got["throws"]["last"].startswith("1곳은 다시 읽지 못했습니다")


def test_dashboard_refresh_never_calls_the_backtest_path():
    """TC-PLB-05b · 계좌 현황 새로고침은 세 읽기(loadPaperDashboard · 자산 구성 · QFRS/추이)만 묶는다 — 100일 백테스트(생성 · 삭제 · 상태 · 있는지 확인)와 신호 계산은 부르지 않는다(판 1 지문)."""
    wiring = PAPER[PAPER.index('on("pd-refresh", "click", createRefreshGroup({'):]
    wiring = wiring[:wiring.index("}));") + 4]
    assert "tasks: [loadPaperDashboard, loadPaperAllocation, loadPaperPerformance]" in wiring
    for banned in ("acktest", "_start", "_delete", "generate", "signal", "POST"):
        assert banned not in wiring.replace("신호나 백테스트는 새로 계산하지 않습니다", ""), banned
    for name in ("loadPaperDashboard", "loadPaperAllocation", "loadPaperPerformance", "pdRecentRows"):
        body = _fn(name)
        assert "backtest" not in body.lower() and "_generate_signal" not in body and 'method: "POST"' not in body, name
    # 백테스트 길은 자기 단추에만 묶여 있다
    assert "pd-backtest-generate')?.addEventListener('click', _startBacktest)" in PAPER
    assert re.search(r'on\("pd-refresh", "click", loadPaperDashboard\)', PAPER) is None, "옛 반쪽 새로고침이 남아 있지 않다"
    assert 'id="pd-refresh-note"' in HTML


def test_structure_css_always_loaded_and_new_slots_exist():
    """TC-PLB-06 · 칩 CSS(qd-fchip · qd-frow · qd-filter)는 app.html 머리에서 항상 로드 · 새 칸이 표 앞에 있다 · 가져오기."""
    css = (PUB / "css" / "signalrankview.css").read_text(encoding="utf-8")
    for cls in (".qd-fchip", ".qd-filter .qd-frow", '.qd-fchip[aria-pressed="true"]'):
        assert cls in css, cls
    head = HTML.split("</head>", 1)[0]
    assert '<link rel="stylesheet" href="/css/signalrankview.css"' in head, "칩 CSS 는 머리에서 항상 로드된다"
    assert HTML.index('id="pc-rankings-bar"') < HTML.index('id="pc-rankings"') and HTML.index('id="pa-markets-bar"') < HTML.index('id="pa-markets"')
    for ident in ("pc-rankings-bar", "pa-markets-bar", "pd-refresh-note"):
        assert HTML.count(f'id="{ident}"') == 1, ident
    assert 'from "/js/paperlists.js"' in PAPER and 'from "/js/listbar.js"' in LISTS
