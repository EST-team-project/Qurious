"""TC-ATL — 자동매매 현황(quant-auto) · 모의 투자 의사결정(robo-decision) 필터 칩 (public/js/autotrade-filter.js · 2026-11-05 화면 전수 점검 뒤)

서버 응답 · 판정은 그대로 두고, 브라우저가 이미 받은 줄 안에서만 거른다. 순수 함수는 node 로 실제로 돌린다(listbar.js 와 함께).
1. 신호 갈래(매수/매도/관망/판단 불가)가 서버가 BUY/SELL/HOLD 를 정하는 규칙과 같다. (TC-ATL-01)
2. 자동매매 현황 — 「체결·주문 있는 회차만」은 위험관리 주문 생략을 주문으로 세지 않는다 · 신호는 「그 갈래가 하나라도 있는 회차」 ·
   조건을 풀면 복귀 · 빈 응답에도 칩 줄이 나오고 안 깨진다 · 글은 이스케이프. (TC-ATL-02)
3. 의사결정 로그 — 종류는 응답에 나온 것만 · 걸린 칩은 응답에서 사라져도 남아 풀 수 있다 · 수준 칩 · 이스케이프 · 「최근 90줄」 안내. (TC-ATL-03)
4. 근거 카드 — 다시 그리지 않고 keep 배열로 숨긴다 · 「최근 40개 신호 중 가장 최근 회차」 안내. (TC-ATL-04)
5. 서버 글머리 · 자르는 크기가 바뀌면 여기서 먼저 깨진다(서버는 건드리지 않았다). (TC-ATL-05)
6. 화면 연결(quant.js · robo.js)은 서버 인자를 더하지 않고 순수 함수 모듈은 DOM 을 만지지 않는다. (TC-ATL-06)
node 가 없으면 1~4 는 건너뛴다(5 · 6 은 항상 돈다).
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
FILTER = (JS / "autotrade-filter.js").read_text(encoding="utf-8")
STOCKS = (ROOT / "app" / "routes" / "stocks.py").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _strip(src: str) -> str:
    """node 에서 바로 돌리도록 import 줄과 export 만 뗀다(브라우저 경로 /js/... 는 node 가 못 푼다)."""
    return re.sub(r"^export ", "", re.sub(r"^import .*$", "", src, flags=re.M), flags=re.M)


MODULE = _strip(LISTBAR) + "\n" + _strip(FILTER)


def _run(body: str):
    js = MODULE + textwrap.dedent("""
        const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
        const cycleHtml = c => `<div data-c="${esc(c.time)}"></div>`;
        const timesOf = html => [...html.matchAll(/data-c="([^"]*)"/g)].map(m => m[1]);
        const pressed = html => [...html.matchAll(/data-lb-filter="([^"]+)" data-value="([^"]*)" aria-pressed="true"/g)].map(m => m[1] + "=" + m[2]);
        const chips = (html, key) => [...html.matchAll(new RegExp('data-lb-filter="' + key + '" data-value="([^"]*)"', "g"))].map(m => m[1]);
        const note = html => (html.match(/data-lb-note>([^<]*)</) || [])[1];
    """) + textwrap.dedent(body)
    out = subprocess.run([NODE, "-"], input=js, capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# 서버(auto_trade.get_status)가 주는 회차 모양 — 주문(가상 체결) · 위험관리 생략(type "risk" · 수량 0) · 주문 생략(type 아님 · status skipped)
CYCLES = """
const ORDER = { type: "auto", action: "buy", quantity: 3, execution: { status: "virtual_filled", label: "가상 체결", level: "info" } };
const RISKSKIP = { type: "risk", action: "buy", quantity: 0, status: "skipped", execution: { status: "skipped", label: "주문 생략", level: "warning" } };
const SKIPPED = { type: "auto", action: "sell", execution: { status: "skipped", label: "주문 생략", level: "warning" } };
const CYCLES = [
  { time: "c1", signals: [{ name: "삼성전자", action: "매수" }, { name: "A", action: "관망" }], trades: [ORDER] },
  { time: "c2", signals: [{ name: "B", action: "강력 매도" }], trades: [RISKSKIP] },
  { time: "c3", signals: [{ symbol: "C", error: "지표 계산 실패" }], trades: [] },
  { time: "c4", signals: [{ name: "D", action: "데이터 대기" }], trades: [SKIPPED] },
  { time: "c5", signals: [{ name: "E", action: "강력 매수" }, { name: "F", action: "매도" }], trades: [ORDER, RISKSKIP] },
];
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_signal_bucket_follows_the_server_rule():
    """TC-ATL-01 · 계산 실패 → 판단 불가 · 매수/매도가 들어간 action → 매수/매도 · 그 밖(관망 · 데이터 대기 · action 없음) → 관망 · 서버가 준 signal 이 있으면 그것을 먼저."""
    got = _run("""
      const b = s => signalBucket(s);
      console.log(JSON.stringify([
        b({ error: "x", action: "매수" }), b({ signal: "UNAVAILABLE", action: "관망" }), b({ signal: "BUY" }), b({ signal: "SELL", action: "관망" }), b({ signal: "HOLD", action: "매수" }),
        b({ action: "매수" }), b({ action: "강력 매수" }), b({ action: "강력 매도" }), b({ action: "강력매도" }), b({ action: "매도" }),
        b({ action: "관망" }), b({ action: "데이터 대기" }), b({}), b(null), b(undefined),
      ]));
    """)
    assert got == ["판단 불가", "판단 불가", "매수", "매도", "관망",
                   "매수", "매수", "매도", "매도", "매도",
                   "관망", "관망", "관망", "판단 불가", "판단 불가"], got


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_auto_trade_chips_filter_cycles_and_release_restores():
    """TC-ATL-02 · 주문 칩은 위험관리 생략(type risk)·주문 생략만 있는 회차를 뺀다 · 신호 칩은 「그 갈래가 하나라도 있는 회차」 · 겹쳐 걸면 둘 다 맞는 회차 · 풀면 전부 · 최신 회차가 위."""
    got = _run(CYCLES + """
      const view = f => autoTradeView(CYCLES, f, { esc, cycleHtml });
      const all = view({ order: "", signal: "" });
      const order = view({ order: "yes", signal: "" });
      const buy = view({ order: "", signal: "매수" });
      const sell = view({ order: "", signal: "매도" });
      const hold = view({ order: "", signal: "관망" });
      const unavail = view({ order: "", signal: "판단 불가" });
      const both = view({ order: "yes", signal: "매도" });
      const released = view({ order: "", signal: "" });
      console.log(JSON.stringify({
        hasOrder: CYCLES.map(cycleHasOrder), buckets: CYCLES.map(c => cycleBuckets(c)),
        all: timesOf(all.listHtml), order: timesOf(order.listHtml), buy: timesOf(buy.listHtml), sell: timesOf(sell.listHtml),
        hold: timesOf(hold.listHtml), unavail: timesOf(unavail.listHtml), both: timesOf(both.listHtml), released: timesOf(released.listHtml),
        counts: [order.total, order.shown, both.shown], orderNote: note(order.barHtml), bothNote: note(both.barHtml), allNote: note(all.barHtml),
        pressedBoth: pressed(both.barHtml),
      }));
    """)
    assert got["hasOrder"] == [True, False, False, False, True], "위험관리 생략 · 주문 생략만 있는 회차는 주문 회차가 아니다"
    assert got["buckets"] == [["매수", "관망"], ["매도"], ["판단 불가"], ["관망"], ["매수", "매도"]]
    assert got["all"] == ["c5", "c4", "c3", "c2", "c1"], "기존처럼 최신 회차가 위"
    assert got["order"] == ["c5", "c1"]
    assert got["buy"] == ["c5", "c1"] and got["sell"] == ["c5", "c2"] and got["hold"] == ["c4", "c1"] and got["unavail"] == ["c3"]
    assert got["both"] == ["c5"]
    assert got["released"] == got["all"], "조건을 풀면 전부 돌아온다"
    assert got["counts"] == [5, 2, 1]
    assert got["allNote"].startswith("받은 5회차") and "서버가 보낸 최근 회차 안에서 거릅니다" in got["allNote"]
    assert got["orderNote"].startswith("조건 체결·주문이 있는 회차만 — 받은 5회차 중 2회차") and "주문 생략" in got["orderNote"]
    assert got["bothNote"].startswith("조건 체결·주문이 있는 회차만 · 매도 — 받은 5회차 중 1회차")
    assert got["pressedBoth"] == ["order=yes", "signal=매도"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_auto_trade_chip_rows_empty_response_and_escaping():
    """TC-ATL-02b · 판단 불가 칩은 응답에 있을 때만(걸려 있으면 남김) · 새로고침 단추를 또 만들지 않는다 · 빈 응답(undefined · null · 배열 아님)에도 칩 줄 · 맞는 회차 없음 안내 · 안내 글 이스케이프."""
    got = _run(CYCLES + """
      const noErr = CYCLES.filter(c => c.time !== "c3");
      const a = autoTradeView(noErr, {}, { esc, cycleHtml });
      const b = autoTradeView(noErr, { signal: "판단 불가" }, { esc, cycleHtml });
      const withErr = autoTradeView(CYCLES, {}, { esc, cycleHtml });
      const empties = [undefined, null, {}, "x", []].map(l => { const v = autoTradeView(l, { order: "yes" }, { esc, cycleHtml }); return [v.total, v.shown, v.listHtml.includes("자동매매 로그가 없습니다"), v.barHtml.includes("data-lb-filter"), note(v.barHtml)]; });
      const none = autoTradeView([CYCLES[2]], { order: "yes" }, { esc, cycleHtml });
      const evil = autoTradeView(CYCLES, {}, { esc, cycleHtml, note: '<img src=x onerror=1>' });
      console.log(JSON.stringify({
        a: chips(a.barHtml, "signal"), b: chips(b.barHtml, "signal"), withErr: chips(withErr.barHtml, "signal"), order: chips(a.barHtml, "order"),
        noRefresh: !withErr.barHtml.includes("data-lb-refresh"), label: withErr.barHtml.includes('aria-label="자동매매 회차 필터"'),
        empties, none: none.listHtml, evilOk: evil.barHtml.includes("&lt;img") && !evil.barHtml.includes("<img"),
      }));
    """)
    assert got["a"] == ["", "매수", "매도", "관망"], "응답에 없는 판단 불가 칩은 만들지 않는다"
    assert got["b"] == ["", "매수", "매도", "관망", "판단 불가"], "걸려 있는 칩은 응답에서 사라져도 남겨 풀 수 있게 한다"
    assert got["withErr"] == ["", "매수", "매도", "관망", "판단 불가"]
    assert got["order"] == ["", "yes"]
    assert got["noRefresh"] and got["label"], "새로고침 단추는 기존 것을 쓴다(refresh: false)"
    for total, shown, msg, bar, text in got["empties"]:
        assert (total, shown, msg, bar) == (0, 0, True, True), "빈 응답에도 칩 줄이 나오고 안 깨진다"
        assert text == "받은 회차가 없습니다"
    assert "이 조건에 맞는 회차가 없습니다" in got["none"] and "필터를 풀어" in got["none"]
    assert got["evilOk"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_robo_log_kinds_come_from_the_response_and_filter():
    """TC-ATL-03 · 종류는 execution(주문·체결) 또는 서버 글머리([배치] 뒤 포함)로 갈린다 · 칩은 응답에 나온 종류·수준만 · 걸린 칩은 남는다 · 겹쳐 걸기 · 풀기 · 최근 90줄 안내."""
    got = _run("""
      const time = t => "T" + t;
      const L = [
        { time: "1", message: "[가상 체결] 삼성전자 매수 가상 기록 3주 — a", level: "info", execution: { label: "가상 체결", level: "info" } },
        { time: "2", message: "[배치] [증권사 주문 실패] 현대차 매도 주문 요청 1주 — b", level: "error", execution: { label: "증권사 주문 실패", level: "error" } },
        { time: "3", message: "[위험관리 생략] 삼성전자 BUY — 한도" },
        { time: "4", message: "[배치] [위험관리 생략] SK하이닉스 SELL — 쿨다운" },
        { time: "5", message: "[공격 모드] 이번 회차 매수 1건" },
        { time: "6", message: "퀀트 가상 장부 평가(KIS 계좌 아님) 10,000,000원 / 손익 +0.10%" },
        { time: "7", message: "[배치] KIS 계좌 평가(주문 전 조회) 9,000,000원 / 손익 계산 불가" },
        { time: "8", message: "[정합성] qty_mismatch 005930 — qty=1" },
        { time: "9", message: "아무 글머리도 없는 줄" },
        { time: "10", message: "경고 줄", level: "warning", execution: { label: "증권사 접수·체결 미확인" } },
      ];
      const v = f => roboLogView(L, f, { esc, time });
      const times = html => [...html.matchAll(/T(\\d+)/g)].map(m => m[1]);
      const all = v({}), kindOrder = v({ kind: "order" }), kindRisk = v({ kind: "risk" }), err = v({ level: "error" }), both = v({ kind: "order", level: "warning" });
      console.log(JSON.stringify({
        kinds: L.map(roboLogKind), all: times(all.listHtml), order: times(kindOrder.listHtml), risk: times(kindRisk.listHtml), err: times(err.listHtml), both: times(both.listHtml),
        kindChips: chips(all.barHtml, "kind"), levelChips: chips(all.barHtml, "level"), allNote: note(all.barHtml), riskNote: note(kindRisk.barHtml),
        pressed: pressed(v({ kind: "risk", level: "error" }).barHtml), released: times(v({ kind: "", level: "" }).listHtml),
      }));
    """)
    assert got["kinds"] == ["order", "order", "risk", "risk", "aggressive", "account", "account", "reconcile", "other", "order"]
    assert got["all"] == [str(i) for i in range(1, 11)], "서버가 준 순서 그대로"
    assert got["order"] == ["1", "2", "10"] and got["risk"] == ["3", "4"] and got["err"] == ["2"] and got["both"] == ["10"]
    assert got["released"] == got["all"]
    assert got["kindChips"] == ["", "order", "risk", "aggressive", "reconcile", "account", "other"]
    assert got["levelChips"] == ["", "error", "warning", "info"], "success 는 응답에 없으니 칩도 없다"
    assert "최근 90줄 안에서 거릅니다" in got["allNote"] and "받은 10줄" in got["allNote"]
    assert got["riskNote"].startswith("조건 위험관리 생략 — 받은 10줄 중 2줄") and "최근 90줄 안에서만 거른 결과" in got["riskNote"]
    assert got["pressed"] == ["kind=risk", "level=error"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_robo_log_view_survives_missing_data_and_escapes():
    """TC-ATL-03b · 응답에 없는 종류는 칩이 없다(없는 종류를 지어내지 않는다) · 걸린 종류가 사라져도 칩이 남는다 · 빈 응답 · 일치 없음 · 메시지 · 수준 글 이스케이프."""
    got = _run("""
      const time = t => "T" + t;
      const only = [{ time: "1", message: "[정합성] x" }];
      const a = roboLogView(only, {}, { esc, time });
      const stuck = roboLogView(only, { kind: "risk", level: "error" }, { esc, time });
      const empties = [undefined, null, [], "x"].map(l => { const v = roboLogView(l, { kind: "order" }, { esc, time }); return [v.total, v.shown, v.listHtml.includes("의사결정 로그가 없습니다"), v.barHtml.includes("data-lb-filter"), note(v.barHtml)]; });
      const evil = [{ time: "<b>1</b>", message: "<script>alert(1)</script>", level: '"><img src=x>', execution: { label: "<i>" } }];
      const e = roboLogView(evil, {}, { esc, time: t => String(t), note: "<u>다시</u>" });
      const e2 = roboLogView(evil, { level: '"><img src=x>' }, { esc, time: t => String(t) });
      console.log(JSON.stringify({
        aKinds: chips(a.barHtml, "kind"), aLevel: chips(a.barHtml, "level"), stuckKinds: chips(stuck.barHtml, "kind"), stuckLevel: chips(stuck.barHtml, "level"), stuckList: stuck.listHtml,
        empties, bad: [e.listHtml, e.barHtml, e2.listHtml.includes("data-rb-kind")],
      }));
    """)
    assert got["aKinds"] == ["", "reconcile"] and got["aLevel"] == [], "level 이 하나도 없으면 수준 줄 자체를 만들지 않는다"
    assert got["stuckKinds"] == ["", "risk", "reconcile"] and got["stuckLevel"] == ["", "error"]
    assert "이 조건에 맞는 로그가 없습니다" in got["stuckList"]
    for total, shown, msg, bar, text in got["empties"]:
        assert (total, shown, msg, bar) == (0, 0, True, True)
        assert text == "받은 로그가 없습니다"
    line, bar, kept = got["bad"]
    assert "<script>" not in line and "&lt;script&gt;" in line and "&lt;b&gt;1" in line and "<img" not in line
    assert "<img" not in bar and "&lt;img" in bar and "<u>" not in bar and "&lt;u&gt;" in bar, "알 수 없는 level 글도 칩 이름으로 쓸 때 이스케이프"
    assert kept is True


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_robo_cards_keep_array_and_note():
    """TC-ATL-04 · 카드는 다시 그리지 않고 keep 배열(카드 순서)로 숨긴다 · 칩 · 최근 40개 신호 중 가장 최근 회차 안내 · 빈 카드 · 판단 불가는 있을 때만."""
    got = _run("""
      const S = [{ name: "A", signal: "BUY", action: "매수" }, { name: "B", signal: "HOLD", action: "관망" }, { name: "C", signal: "UNAVAILABLE", error: "x" }];
      const v = f => roboCardView(S, f, { esc });
      const none = v({}), buy = v({ signal: "매수" }), un = v({ signal: "판단 불가" }), miss = v({ signal: "매도" });
      const noUn = roboCardView(S.slice(0, 2), {}, { esc });
      const empty = roboCardView([], { signal: "매수" }, { esc });
      const nul = roboCardView(null, {}, { esc, note: "<b>x</b>" });
      console.log(JSON.stringify({
        keep: [none.keep, buy.keep, un.keep, miss.keep], shown: [none.shown, buy.shown, un.shown, miss.shown, none.total],
        chips: chips(none.barHtml, "signal"), noUn: chips(noUn.barHtml, "signal"), emptyChips: chips(empty.barHtml, "signal"),
        noteNone: note(none.barHtml), noteBuy: note(buy.barHtml), noteEmpty: note(empty.barHtml), nulOk: [nul.total, nul.keep, nul.barHtml.includes("&lt;b&gt;x")],
        pressed: pressed(buy.barHtml), label: buy.barHtml.includes('aria-label="판단 근거 카드 필터"'), noRefresh: !buy.barHtml.includes("data-lb-refresh"),
      }));
    """)
    assert got["keep"] == [[True, True, True], [True, False, False], [False, False, True], [False, False, False]]
    assert got["shown"] == [3, 1, 1, 0, 3]
    assert got["chips"] == ["", "매수", "매도", "관망", "판단 불가"] and got["noUn"] == ["", "매수", "매도", "관망"]
    assert got["emptyChips"] == ["", "매수", "매도", "관망"], "카드가 없어도 칩 줄은 그린다"
    assert got["noteNone"] == "최근 40개 신호 중 가장 최근 회차 카드 3장 안에서 거릅니다"
    assert got["noteBuy"].startswith("조건 매수 — 받은 3장 중 1장") and "최근 40개 신호 중 가장 최근 회차 카드 안에서만 거른 결과" in got["noteBuy"]
    assert got["noteEmpty"] == "받은 신호가 없습니다"
    assert got["nulOk"] == [0, [], True]
    assert got["pressed"] == ["signal=매수"] and got["label"] and got["noRefresh"]


def test_server_prefixes_and_caps_are_what_the_filter_assumes():
    """TC-ATL-05 · 서버는 안 고쳤다 — 그래서 서버의 글머리 · 자르는 크기 · BUY/SELL/HOLD 규칙이 바뀌면 여기서 먼저 깨진다."""
    for literal in ('"logs": logs[-90:], "signals": signals[-40:]',
                    '"UNAVAILABLE" if sig.get("error") else "BUY" if "매수" in action else "SELL" if "매도" in action else "HOLD"',
                    'f"{prefix}[공격 모드] {note}"', 'f"{prefix}[위험관리 생략] {skip.get(', "f\"[정합성] {i['type']}",
                    '"KIS 계좌 평가(주문 전 조회)"', '"퀀트 가상 장부 평가(KIS 계좌 아님)"',
                    'sources.append(("[배치] "', '"execution": execution'):
        assert literal in STOCKS, f"stocks.py 에 {literal} 이 없다 — 필터의 갈래 규칙을 다시 맞춘다"
    assert "ROBO_LOG_CAP = 90" in FILTER and "ROBO_SIGNAL_CAP = 40" in FILTER
    auto = (ROOT / "app" / "services" / "auto_trade.py").read_text(encoding="utf-8")
    assert '"status": "skipped", "type": "risk"' in auto, "위험관리 생략 주문은 type risk · status skipped 로 기록된다"
    assert '"log":          cycles[-50:]' in auto, "자동매매 현황은 서버가 최근 50회차까지만 보낸다(안내 글은 숫자를 못 박지 않고 받은 수를 센다)"


def test_screens_wire_the_helpers_without_server_params_or_dom_in_the_module():
    """TC-ATL-06 · 화면 연결 — 같은 서버 주소(인자 없음) · 칩 줄은 목록 칸 앞 형제 · 낯선 낱말은 isAllowed 로 막는다 · 카드 필터는 다시 그리지 않는다 · 순수 모듈은 DOM 을 안 만진다."""
    assert not re.search(r"\b(document|window|localStorage|fetch)\b", re.sub(r"//.*", "", FILTER)), "순수 모듈은 DOM · 네트워크를 만지지 않는다"
    assert FILTER.count("refresh: false") == 3, "새로고침 단추는 두 화면에 이미 있다 — 칩 줄은 단추를 더하지 않는다"
    quant = (JS / "quant.js").read_text(encoding="utf-8")
    zone = quant[quant.index("// ── 자동매매 ──"):quant.index("// ── 백테스트 ──")]
    assert 'import { autoTradeView } from "/js/autotrade-filter.js"' in zone and 'from "/js/listbar.js"' in zone
    assert 'api("/api/auto-trade/status")' in zone and "/api/auto-trade/status?" not in quant, "서버 인자를 더하지 않는다"
    assert "insertBefore(host, log)" in zone and "bindListBar(host, { onFilter: autoSetFilter })" in zone
    assert re.search(r"function autoSetFilter\(key, value\) \{\s*if \(!isAllowed\(autoGroups, key, value\)\) return;", zone)
    assert 'getElementById("auto-refresh").addEventListener("click", autoRefreshClick)' in zone and "auto-start" in zone
    # 칩을 눌러도 서버를 다시 부르지 않는다 — autoRepaint 는 받아 둔 응답만 쓴다
    repaint = zone[zone.index("function autoRepaint()"):zone.index("function autoSetFilter")]
    assert "api(" not in repaint and "loadAutoTradeStatus" not in repaint
    robo = (JS / "robo.js").read_text(encoding="utf-8")
    rzone = robo[robo.index("// ── 로보 어드바이저: 모의 투자 의사결정"):robo.index("// 데모 데이터 단추")]
    assert 'api("/api/quant/auto/status")' in rzone and "/api/quant/auto/status?" not in robo
    assert "list.parentNode.insertBefore(host, list)" in rzone
    assert re.search(r"function roboSetLogFilter\(key, value\) \{\s*if \(!isAllowed\(roboLogGroups, key, value\)\) return;", rzone)
    assert re.search(r"function roboSetCardFilter\(key, value\) \{\s*if \(!isAllowed\(roboCardGroups, key, value\)\) return;", rzone)
    paint = rzone[rzone.index("function roboPaintCardBar()"):rzone.index("async function loadRoboDecision")]
    assert "_loadRationaleExplain" not in paint and "innerHTML = " not in paint.replace("host.innerHTML = view.barHtml", ""), "카드 필터는 카드를 다시 그리지 않는다(다중 주기 설명 요청이 또 나간다)"
    assert "card.hidden = view.keep[i] === false" in paint
    assert 'getElementById("robo-decision-refresh").addEventListener("click", roboRefreshClick)' in rzone
