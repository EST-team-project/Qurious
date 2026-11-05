"""TC-LBS — 마이페이지의 「KIS 실주문 현황」 · 「최근 발송 이력」 표 위 줄(필터 칩 + 새로고침) (public/js/settings.js · screenlists.js · 2026-11-05 화면 전수 점검 뒤)

settings.js 의 실제 패널 설정을 잘라 node 에서 가짜 DOM · 가짜 api 로 돌린다(브라우저 경로 import 는 쓰지 않는다 · 서버는 건드리지 않는다).
1. 실주문 — 상태(미체결/체결/취소/그 밖 · 응답에 있는 갈래만) · 환경 · 매매 칩, 겹쳐 걸기, 풀면 전부 복귀, 새로고침이 서버를 다시 부르고 필터를 유지,
   받은 30건 안에서만 거른다는 안내, 읽지 못하면 시각을 찍지 않는다, 이스케이프, 빈 응답. (TC-LBS-01, 02)
2. 취소 · 재주문 단추는 그대로 그려지지만 이 줄 · 새로고침은 GET 만 부른다(쓰기 요청 0). (TC-LBS-03)
3. 발송 이력 — 새로고침 단추가 줄에 생긴다 · 「실패 · 결과 불명만」 칩은 화면이 빨강으로 보이는 두 낱말과 같다 · 전달 상태 칩은 서버 status_label 그대로 ·
   새로고침 뒤에도 칩 유지 · 이스케이프 · 빈 응답. (TC-LBS-04, 05)
4. 구조 — 칩 낱말이 서버 · 화면의 표와 어긋나면 여기서 먼저 깨진다. (TC-LBS-06)
node 가 없으면 1~3 · 5 는 건너뛴다.
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
SETTINGS = (JS / "settings.js").read_text(encoding="utf-8")
HTML = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _fn(src: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {name}\(", src, re.M)
    assert m, name
    return src[m.start():src.index("\n}\n", m.start()) + 3]


def _const(src: str, name: str) -> str:
    m = re.search(rf"^const {name} = ", src, re.M)
    assert m, name
    return src[m.start():src.index("\n};\n", m.start()) + 4]


def _panel(src: str, name: str) -> str:
    """`const xxxPanel = createScreenPanel({ … }, { esc: escHtml, byId … });` 한 문장."""
    start = src.index(f"const {name} = createScreenPanel(")
    line_end = src.index("\n", src.index("}, { esc: escHtml, byId", start)) + 1
    return src[start:line_end]


def _modules() -> str:
    parts = [LISTBAR, LISTS, SCREENLISTS]
    out = []
    for p in parts:
        p = re.sub(r"^import [^\n]*\n", "", p, flags=re.M)
        # 여러 줄 import 가 없다는 전제(screenlists · paperlists 는 한 줄) — 있으면 아래 단언이 깨진다
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
    const document = { getElementById: byIdFake };
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
    const names = html => [...html.matchAll(/<td>(N\\d+)<\\/td>/g)].map(m => m[1]);
    const pressed = html => [...html.matchAll(/data-lb-filter="([^"]+)" data-value="([^"]+)" aria-pressed="true"/g)].map(m => m[1] + "=" + m[2]);
    const chips = (html, key) => [...html.matchAll(new RegExp('data-lb-filter="' + key + '" data-value="([^"]*)"[^>]*>([^<]*)<', "g"))].map(m => m[1] + ":" + m[2]);
    const note = html => (html.match(/data-lb-note[^>]*>([^<]*)</) || [])[1];
""")


def _run(body: str, extra: str = ""):
    js = "\n".join([_modules(), PRELUDE, LIVE_SRC, NOTI_SRC, extra, textwrap.dedent(body)])
    out = subprocess.run([NODE, "--input-type=module", "-"], input=js, capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


LIVE_SRC = "\n".join([_const(SETTINGS, "LIVE_STATUS_BADGE"), _fn(SETTINGS, "liveOrdersTableHtml"), _panel(SETTINGS, "liveOrdersPanel")])
NOTI_SRC = "\n".join([_fn(SETTINGS, "notiPayloadDetails"), _fn(SETTINGS, "notiEventHtml"), _panel(SETTINGS, "notiHistoryPanel")])

# 서버(/api/quant/live-orders)가 주는 줄 모양 — 상태 · 환경 · 매매가 여럿 섞인 한 묶음
LIVE_ROWS = """
const mk = (name, status, env, side, extra = {}) => ({ id: "id-" + name, owner: "me", broker: "kis-direct", environment: env, order_type: "LIMIT", name, symbol: "005930",
  side, quantity: 10, price: 71000, filled_quantity: 0, avg_filled_price: 0, status, created_at: "2026-11-05T10:00:00", order_no: "0001", message: "", ...extra });
const ROWS = [
  mk("N1", "ACCEPTED", "paper", "BUY"),
  mk("N2", "PARTIALLY_FILLED", "paper", "SELL", { filled_quantity: 4, avg_filled_price: 71000 }),
  mk("N3", "FILLED", "real", "BUY", { filled_quantity: 10, avg_filled_price: 71000 }),
  mk("N4", "CANCELLED", "paper", "SELL"),
  mk("N5", "REJECTED", "real", "SELL", { message: "증거금 부족" }),
  mk("N6", "CANCEL_REQUESTED", "paper", "BUY"),
];
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_live_orders_chips_filter_release_and_refresh_keep_filter():
    """TC-LBS-01 · 상태 칩은 응답에 있는 갈래만 · 걸면 맞는 줄만 · 겹쳐 걸면 모두 맞는 줄 · 풀면 전부 · 새로고침은 서버를 다시 부르고 필터를 유지 · 받은 30건 안에서 거른다는 안내."""
    got = _run(LIVE_ROWS + """
      routes = { "/api/quant/live-orders": { orders: ROWS } };
      await liveOrdersPanel.load();
      const html0 = () => els["quant-live-orders"].innerHTML;
      const out = { names0: names(html0()), statusChips: chips(html0(), "status"), envChips: chips(html0(), "env"), sideChips: chips(html0(), "side"), note0: note(html0()) };
      const each = {};
      for (const v of ["open", "filled", "cancelled", "other"]) { liveOrdersPanel.setFilter("status", v); each[v] = names(html0()); }
      liveOrdersPanel.setFilter("status", "");
      liveOrdersPanel.setFilter("env", "real"); each.real = names(html0());
      liveOrdersPanel.setFilter("side", "SELL"); each.realSell = names(html0()); out.pressedBoth = pressed(html0()); out.noteBoth = note(html0());
      liveOrdersPanel.setFilter("env", ""); liveOrdersPanel.setFilter("side", ""); out.released = names(html0());
      // 새로고침 — 서버가 줄을 하나 더 주고, 걸어 둔 상태 칩(미체결)이 유지된다
      liveOrdersPanel.setFilter("status", "open");
      routes = { "/api/quant/live-orders": { orders: [...ROWS, mk("N7", "PENDING", "paper", "BUY")] } };
      const before = calls.length;
      const ok = await liveOrdersPanel.refresh();
      out.refreshOk = ok; out.newCalls = calls.slice(before).map(c => c.path); out.afterRefresh = names(html0()); out.pressedAfter = pressed(html0()); out.noteAfter = note(html0());
      out.each = each;
      console.log(JSON.stringify(out));
    """)
    assert got["names0"] == ["N1", "N2", "N3", "N4", "N5", "N6"]
    assert got["statusChips"] == [":전체", "open:미체결", "filled:체결", "cancelled:취소", "other:그 밖"], got["statusChips"]
    assert got["envChips"] == [":전체", "real:실전", "paper:모의"]
    assert got["sideChips"] == [":전체", "BUY:매수", "SELL:매도"]
    assert got["each"]["open"] == ["N1", "N2"], "접수 · 일부 체결(잔량이 남음)이 미체결"
    assert got["each"]["filled"] == ["N3"] and got["each"]["cancelled"] == ["N4", "N6"] and got["each"]["other"] == ["N5"]
    assert got["each"]["real"] == ["N3", "N5"] and got["each"]["realSell"] == ["N5"]
    assert got["pressedBoth"] == ["env=real", "side=SELL"]
    assert "받은 6건 중 1건" in got["noteBoth"] and "서버가 최근 30건까지" in got["noteBoth"]
    assert "서버가 2분마다 증권사 체결을 확인해 저장한 값" in got["note0"], "새로고침이 증권사에 묻는 것이 아니라는 안내"
    assert got["released"] == got["names0"], "조건을 풀면 전부 돌아온다"
    assert got["refreshOk"] is True and got["newCalls"] == ["/api/quant/live-orders?limit=30"], "새로고침 = 서버 다시 읽기(GET 한 번)"
    assert got["afterRefresh"] == ["N1", "N2", "N7"], "걸어 둔 미체결 칩이 새로고침 뒤에도 유지된다"
    assert got["pressedAfter"] == ["status=open"]
    assert "서버에서 다시 읽었습니다" in got["noteAfter"] and "증권사에 새로 묻거나 주문 · 취소를 하지 않습니다" in got["noteAfter"]
    assert "미체결 = 접수 · 대기 · 일부 체결" in got["noteAfter"], "상태 칩을 걸면 갈래 풀이가 붙는다"


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_live_orders_escape_empty_and_failed_refresh():
    """TC-LBS-02 · 응답 글은 이스케이프 · 빈 응답에서도 칩 줄이 나오고 안 깨진다 · 읽지 못하면 「다시 읽었습니다」 시각을 찍지 않고 이전 값을 보인다."""
    got = _run(LIVE_ROWS + """
      const html = () => els["quant-live-orders"].innerHTML;
      routes = { "/api/quant/live-orders": { orders: [mk("N1", "ACCEPTED", "paper", "BUY", { message: "<img src=x onerror=alert(1)>", order_no: "<b>9</b>" }), mk("N2", "WEIRD<b>", "real", "BUY")] } };
      await liveOrdersPanel.load();
      const out = { html: html(), statusChips: chips(html(), "status") };
      // 읽기 실패 — 이전 값을 보이고 시각을 찍지 않는다
      routes = { "/api/quant/live-orders": new Error("서버 오류") };
      const ok = await liveOrdersPanel.refresh();
      out.failOk = ok; out.failNote = note(html()); out.failNames = names(html());
      // 빈 응답
      routes = { "/api/quant/live-orders": { orders: [] } };
      await liveOrdersPanel.load();
      out.emptyHtml = html(); out.emptyChips = chips(html(), "side");
      console.log(JSON.stringify(out));
    """)
    assert "<img" not in got["html"] and "&lt;img src=x onerror=alert(1)&gt;" in got["html"] and "&lt;b&gt;9&lt;/b&gt;" in got["html"]
    assert all("<" not in c for c in got["statusChips"])
    assert got["statusChips"] == [":전체", "open:미체결", "other:그 밖"], "모르는 상태 낱말은 「그 밖」 한 갈래로 묶인다(낱말을 칩 이름으로 쓰지 않는다)"
    assert got["failOk"] is False and "다시 읽지 못했습니다" in got["failNote"] and "이전에 받은 값을 보입니다" in got["failNote"]
    assert "다시 읽었습니다" not in got["failNote"]
    assert got["failNames"] == ["N1", "N2"]
    assert "추적 중인 증권사 주문이 없습니다" in got["emptyHtml"] and "data-lb-note" in got["emptyHtml"]
    assert len(got["emptyChips"]) == 3, "빈 응답에서도 매매 칩이 보인다"


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_live_orders_panel_only_reads_and_keeps_action_buttons():
    """TC-LBS-03 · 취소 · 재주문 단추는 표에 그대로 있지만(ACCEPTED 지정가 모의 → 취소) 이 줄 · 새로고침이 부르는 것은 GET 뿐이다(쓰기 요청 0)."""
    got = _run(LIVE_ROWS + """
      routes = { "/api/quant/live-orders": { orders: ROWS } };
      await liveOrdersPanel.load();
      liveOrdersPanel.setFilter("status", "open");
      await liveOrdersPanel.refresh();
      liveOrdersPanel.setFilter("status", "cancelled");
      console.log(JSON.stringify({ methods: [...new Set(calls.map(c => c.method))], paths: [...new Set(calls.map(c => c.path))],
        hasCancel: els["quant-live-orders"].innerHTML.includes('data-kis-action="'), html: els["quant-live-orders"].innerHTML }));
    """)
    assert got["methods"] == ["GET"] and got["paths"] == ["/api/quant/live-orders?limit=30"]
    assert 'data-kis-action="retry"' not in got["html"] or "취소 잔량 재주문" in got["html"]
    # 취소 요청 처리기는 칸(host) 위임이라 칩 · 새로고침이 다시 그려도 살아 있다 — 소스에서 굳힌다
    assert 'document.getElementById("quant-live-orders")?.addEventListener("click"' in SETTINGS
    assert 'event.target.closest("button[data-kis-action]")' in SETTINGS
    assert "bindRefreshButton(document.getElementById(\"live-orders-refresh\"), liveOrdersPanel)" in SETTINGS


NOTI_EVENTS = """
const ev = (n, state, label, extra = {}) => ({ created_at: "2026-11-05 10:0" + n, subject: "알림 " + n, delivery_status: state, status_label: label, channels: [{ channel: "discord", ok: state === "delivered" }], payload: null, ...extra });
const EVENTS = [
  ev(1, "delivered", "전달됨"), ev(2, "failed", "전달 실패"), ev(3, "sending", "결과 불명 · 자동 재발송 안 함"),
  ev(4, "partial", "일부만 전달"), ev(5, "delivered", "전달됨"),
];
const subjects = html => [...html.matchAll(/알림 (\\d)/g)].map(m => m[1]);
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_notification_history_refresh_button_and_bad_chip():
    """TC-LBS-04 · 새로고침 단추가 줄에 생긴다 · 「실패 · 결과 불명만」 = failed + sending(화면이 빨강으로 보이는 두 낱말) · 전달 상태 칩은 서버 글 그대로 · 새로고침 뒤에도 칩 유지 · 받은 30건 안."""
    got = _run(NOTI_EVENTS + """
      routes = { "/api/notification/history": { events: EVENTS, count: 5 } };
      await notiHistoryPanel.load();
      const html = () => els["noti-history"].innerHTML;
      const out = { hasRefresh: html().includes("data-lb-refresh"), badChips: chips(html(), "bad"), stateChips: chips(html(), "state"), all: subjects(html()) };
      notiHistoryPanel.setFilter("bad", "bad"); out.bad = subjects(html()); out.badNote = note(html());
      notiHistoryPanel.setFilter("bad", ""); notiHistoryPanel.setFilter("state", "partial"); out.partial = subjects(html());
      notiHistoryPanel.setFilter("state", ""); notiHistoryPanel.setFilter("bad", "bad");
      routes = { "/api/notification/history": { events: [...EVENTS, ev(6, "failed", "전달 실패")], count: 6 } };
      const before = calls.length;
      await notiHistoryPanel.refresh();
      out.newCalls = calls.slice(before).map(c => c.path); out.afterRefresh = subjects(html()); out.pressed = pressed(html()); out.noteAfter = note(html());
      notiHistoryPanel.setFilter("bad", ""); out.released = subjects(html());
      console.log(JSON.stringify(out));
    """)
    assert got["hasRefresh"] is True
    assert got["badChips"] == [":전체", "bad:실패 · 결과 불명만"]
    assert got["stateChips"] == [":전체", "failed:전달 실패", "sending:결과 불명 · 자동 재발송 안 함", "partial:일부만 전달", "delivered:전달됨"]
    assert got["all"] == ["1", "2", "3", "4", "5"] and got["bad"] == ["2", "3"] and got["partial"] == ["4"]
    assert "받은 5건 중 2건" in got["badNote"] and "서버가 최근 30건까지" in got["badNote"]
    assert got["newCalls"] == ["/api/notification/history?limit=30"] and got["afterRefresh"] == ["2", "3", "6"], "새로고침 = 서버 다시 읽기 · 걸어 둔 칩 유지"
    assert got["pressed"] == ["bad=bad"]
    assert "저장된 발송 이력을 다시 읽은 것이고 알림을 새로 보내지 않습니다" in got["noteAfter"]
    assert got["released"] == ["1", "2", "3", "4", "5", "6"]


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_notification_history_escape_empty_and_no_send():
    """TC-LBS-05 · 서버 글(status_label · 제목)은 이스케이프 · 빈 응답에서도 칩 줄과 새로고침 단추가 나온다 · 이력 줄은 GET 만 부른다(발송 0)."""
    got = _run(NOTI_EVENTS + """
      routes = { "/api/notification/history": { events: [ev(1, "failed", "<b>실패</b>", { subject: "알림 1 <script>x</script>" }), ev(2, "delivered", "전달됨")], count: 2 } };
      await notiHistoryPanel.load();
      const html = () => els["noti-history"].innerHTML;
      const out = { html: html(), stateChips: chips(html(), "state") };
      routes = { "/api/notification/history": { events: [], count: 0 } };
      await notiHistoryPanel.refresh();
      out.empty = html(); out.methods = [...new Set(calls.map(c => c.method))];
      routes = { "/api/notification/history": new Error("권한 없음") };
      await notiHistoryPanel.load();
      out.errHtml = html();
      console.log(JSON.stringify(out));
    """)
    assert "<script>" not in got["html"] and "&lt;script&gt;" in got["html"] and "&lt;b&gt;실패&lt;/b&gt;" in got["html"]
    assert all("<" not in c for c in got["stateChips"])
    assert "발송 이력이 없습니다." in got["empty"] and "data-lb-refresh" in got["empty"] and 'data-lb-filter="bad"' in got["empty"]
    assert got["methods"] == ["GET"]
    assert "권한 없음" in got["errHtml"]


def test_settings_structure_and_vocabulary_match_server_and_screen():
    """TC-LBS-06 · 화면 연결(settings.js)은 서버 인자를 더하지 않고 칩 낱말이 서버 · 표와 어긋나지 않는다."""
    # 순수 모듈은 DOM · 네트워크를 만지지 않는다
    assert "document." not in SCREENLISTS and "fetch(" not in SCREENLISTS and "api(" not in SCREENLISTS and "POST" not in SCREENLISTS
    # 칸이 app.html 에 그대로 있다 — 이 파일은 app.html 을 고치지 않는다
    for hid in ('id="quant-live-orders"', 'id="live-orders-refresh"', 'id="noti-history"'):
        assert hid in HTML, hid
    # 요청 개수 = 안내 글의 개수
    assert "limit=${LIVE_ORDERS_LIMIT}" in SETTINGS and "limit=${NOTI_HISTORY_LIMIT}" in SETTINGS
    assert re.search(r"LIVE_ORDERS_LIMIT = 30;", SCREENLISTS) and re.search(r"NOTI_HISTORY_LIMIT = 30;", SCREENLISTS)
    # 기존 시험(TC-NH-03)이 읽는 글이 그대로 있다
    assert "ev.status_label" in SETTINGS and '["failed", "sending"].includes(ev.delivery_status)' in SETTINGS and "var(--red)" in SETTINGS
    assert 'NOTI_BAD_STATUSES = ["failed", "sending"]' in SCREENLISTS, "칩의 「실패 · 결과 불명」 이 화면이 빨강으로 보이는 두 낱말과 같다"
    # 실주문 상태: 서버의 모든 상태가 한 갈래에 들어간다(모르는 상태는 「그 밖」)
    server = (ROOT / "app" / "routes" / "kis_monitor.py").read_text(encoding="utf-8")
    statuses = re.search(r"ORDER_STATUSES = \(([^)]*)\)", server).group(1)
    codes = re.findall(r'"([A-Z_]+)"', statuses)
    bucket_codes = {c for m in re.finditer(r'codes: \[([^\]]*)\]', SCREENLISTS) for c in re.findall(r'"([A-Z_]+)"', m.group(1))}
    assert {"PENDING", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "CANCEL_REQUESTED", "CANCELLED"} <= bucket_codes <= set(codes), (bucket_codes, codes)
    for code in re.findall(r"([A-Z_]+): \"badge-", _const(SETTINGS, "LIVE_STATUS_BADGE")):
        assert code in codes, f"표가 아는 상태 {code} 를 서버가 모른다"
