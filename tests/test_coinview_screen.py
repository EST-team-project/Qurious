"""TC-CRY — 코인 모의매매 화면의 정직한 글 · 가격 차트 판단(public/js/coinview.js · paper.js · app.html) · 2026-10-30 · 할 일 ①-20

옛 화면은 시세에 출처 · 받은 시각이 없었고, 주문이 수수료 · 슬리피지 없이 현재가로 즉시 체결되며 이 앱의 모의 장부에만 기록된다는 말이 없었다.
설계 결정(2026-10-30 · 질문 · 바로 · 안 A + 차트) — 글을 시세 밑 · 주문 칸 위에 한 줄씩, 업비트 일봉 차트를 시세 아래에.
1. 글 — 출처 · 저장 시간 · 시각 미표시 · 못 받으면 마지막 값 / 모의 장부에만 기록 · 업비트로 나가지 않음 · 수수료 · 슬리피지 없음. (TC-CRY-01)
2. 서버가 실제로 그렇게 한다(글이 지어낸 말이 아니다) — 체결 코드에 수수료 · 슬리피지가 없고 시세 저장이 5초다. (TC-CRY-02)
3. 차트 점 — 일봉 종가만 · 날짜는 앞 10자 · 없는 줄은 뺀다 · 아래 글에 최고 · 최저 · 마지막 일봉과 「저장하지 않음 · 진행 중 · 실시간 아님」. (TC-CRY-03)
4. 화면 — 글 · 차트 칸이 app.html 에 있고 paper.js 가 시세를 그릴 때 채운다 · 야후가 없다. (TC-CRY-04)

실시간(2026-10-30 사용자 결정 「실제 서비스에서 하듯이 그대로 … 지연되면 큰일나」 · 일봉 + 지연 해석은 버림)
5. 판단 함수 — 구독 메시지 · 수신 풀기 · 체결 값 · 체결 시각(한국) · 일봉 날짜(09:00 경계) · 배지 · 가격 어긋남 · 재연결. (TC-CRY-05)
6. 화면 연결 — 업비트 공개 주소 한 곳 · 끊기면 늘려 가며 재연결 · 화면을 떠나거나 탭이 숨겨지면 닫음 · 저장 · 외부 전송 없음. (TC-CRY-06)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CV = ROOT / "public" / "js" / "coinview.js"
APP = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
PAPER = (ROOT / "public" / "js" / "paper.js").read_text(encoding="utf-8")
SERVICE = (ROOT / "app" / "services" / "paper_trading.py").read_text(encoding="utf-8")


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as cv from "{CV.resolve().as_uri()}";\nconst out = {{}};\n{body}\nprocess.stdout.write(JSON.stringify(out));\n', encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_notes_say_source_limits_and_how_orders_fill(tmp_path):
    """TC-CRY-01 — 시세 글(출처 · 약 5초 · 시각 미표시 · 마지막 값) · 주문 글(모의 장부 · 업비트로 안 나감 · 수수료 · 슬리피지 없음)."""
    out = _run(tmp_path, "out.s = cv.COIN_SOURCE_NOTE; out.o = cv.COIN_ORDER_NOTE;")
    s, o = out["s"], " ".join(out["o"])
    assert "업비트 공개 시세" in s and "약 5초" in s and "받은 시각은 표시되지 않음" in s and "마지막으로 받은 값이 나올 수 있습니다" in s
    assert "모의 장부에만 기록" in o and "업비트로 주문이 나가지 않습니다" in o and "수수료 · 슬리피지 없이 즉시 체결" in o
    assert "서버" not in s + o and "DB" not in s + o                      # 화면 글에 개발 티가 나는 말을 쓰지 않는다(규칙 L317)


def test_notes_match_what_the_server_really_does():
    """TC-CRY-02 — 글이 지어낸 말이 아니다: 코인 체결 코드에 수수료 · 슬리피지가 없고, 시세 저장은 5초이며, 실패하면 마지막 값을 돌려준다."""
    buy = SERVICE[SERVICE.index("async def crypto_buy("):SERVICE.index("async def crypto_sell(")]
    sell = SERVICE[SERVICE.index("async def crypto_sell("):SERVICE.index("async def crypto_history(")]
    for body in (buy, sell):
        assert "fee" not in body.lower() and "slippage" not in body.lower() and "수수료" not in body
        assert "upbit_trade_price" in body                                   # 위 현재가 그대로
    assert "account.cash = float(account.cash - buy_krw)" in buy and "proceeds = round(price * sell_count)" in sell
    assert "_UPBIT_TICKER_TTL = 5" in SERVICE
    tick = SERVICE[SERVICE.index("async def upbit_tickers("):SERVICE.index("async def upbit_trade_price(")]
    assert "except Exception:\n            pass" in tick and "return [_UPBIT_TICKER_CACHE[c][\"data\"]" in tick   # 실패하면 저장 값을 그대로(서버 고침은 장부 담당 몫)


def test_chart_points_and_summary(tmp_path):
    """TC-CRY-03 — 점은 종가 · 날짜 앞 10자 · 빠진 줄은 뺀다 · 글에 최고 · 최저 · 마지막 일봉 · 저장하지 않음 · 진행 중 · 실시간이 아님."""
    out = _run(tmp_path, """
      const c = [{time: "2026-10-28T09:00:00", close: 100000000}, {time: "2026-10-29T09:00:00", close: 104000000}, {time: "2026-10-30T09:00:00", close: 102500000},
                 {time: "bad", close: 1}, {time: "2026-10-31T09:00:00", close: null}];
      out.p = cv.coinPoints(c); out.s = cv.coinChartSummary(out.p); out.e = [cv.coinChartSummary([]), cv.coinPoints(null)];
    """)
    assert [p["time"] for p in out["p"]] == ["2026-10-28", "2026-10-29", "2026-10-30"] and len(out["p"]) == 3
    s = out["s"]
    assert "최근 3일 최고 104,000,000원 · 최저 100,000,000원 · 마지막 일봉 102,500,000원(2026-10-30)" in s
    assert "저장하지 않으며" in s and "오늘 봉은 진행 중" in s
    assert "지금은 실시간으로 연결되어 있지 않아 초 단위로 움직이지 않습니다" in s           # 연결 전에는 실시간이라고 쓰지 않는다(S172)
    assert out["e"] == ["일봉 자료를 받지 못했습니다.", []]
    live = _run(tmp_path, 'out.s = cv.coinChartSummary(cv.coinPoints([{time: "2026-10-30T09:00:00", close: 100}]), true);')["s"]
    assert "연결된 동안 오늘 봉이 체결마다 움직입니다" in live and "실시간으로 연결되어 있지 않아" not in live


def test_screen_wires_notes_and_chart_without_yahoo():
    """TC-CRY-04 — app.html 에 글 · 차트 칸이 있고 paper.js 가 시세를 그릴 때 채운다 · 일봉은 기존 캔들 길 · 야후 없음."""
    view = re.search(r'data-view="paper-crypto">(.*?)data-view="paper-alternative"', APP, flags=re.S).group(1)
    for ident in ("pc-source-note", "pc-chart", "pc-chart-note", "pc-order-note", "pc-live-badge", "pc-gap-warn", "pc-order-price", "pc-order-price-line", "pc-order-price-note"):
        assert f'id="{ident}"' in view, ident
    order = ("pc-live-badge", "pc-ticker", "pc-source-note", "pc-chart", "pc-gap-warn", "pc-order-price", "pc-order-note", "pc-buy-krw")
    pos = [view.index(f'id="{i}"') for i in order]
    assert pos == sorted(pos)                                              # 배지 → 현재가 → 출처 글 → 차트 → 경고 → 주문 가격 → 체결 글 → 입력
    body = PAPER[PAPER.index("async function cryptoTicker()"):PAPER.index("async function cryptoTicker()") + 3200]
    assert "COIN_LIVE_NOTE" in body and "COIN_ORDER_NOTE" in body and "pcDrawChart(code)" in body and "pcStartLive(code)" in body
    assert 'id="pc-live-price"' in body and 'id="pc-live-rate"' in body    # 체결이 올 때 다시 그릴 칸
    assert "COIN_SOURCE_NOTE" in PAPER[PAPER.index("function pcRenderGap()"):PAPER.index("function pcRenderLive()")]   # 주문 가격의 출처 · 한계 글은 주문 가격 옆
    assert "/api/paper/crypto/${encodeURIComponent(code)}/candles?unit=days&count=120" in PAPER
    code = CV.read_text(encoding="utf-8").split("*/", 1)[1]
    assert "yahoo" not in code.lower() and "/api/stocks/" not in code


def test_live_functions(tmp_path):
    """TC-CRY-05 — 실시간 판단(2026-10-30 사용자 결정 「지연되면 큰일나」) — 구독 메시지 · 수신 풀기 · 체결 값 · 시각 · 일봉 날짜 · 배지 · 가격 어긋남 · 재연결."""
    out = _run(tmp_path, """
      const tick = {type: "ticker", code: "KRW-BTC", trade_price: 98120000, trade_timestamp: Date.UTC(2026, 9, 30, 5, 2, 31), timestamp: 1, signed_change_rate: 0.0123, stream_type: "REALTIME"};
      out.sub = JSON.parse(cv.coinSubscribeMessage("KRW-BTC", "t1"));
      const bytes = new TextEncoder().encode(JSON.stringify(tick));
      out.dec = [cv.decodeWsData(JSON.stringify(tick)).code, cv.decodeWsData(bytes).code, cv.decodeWsData(bytes.buffer).code, cv.decodeWsData("not json"), cv.decodeWsData(tick).code];
      const t = cv.parseUpbitTicker(tick, "KRW-BTC");
      out.t = {price: t.price, tradeTs: t.tradeTs, cr: Math.round(t.changeRate * 100) / 100};
      out.bad = [cv.parseUpbitTicker(tick, "KRW-ETH"), cv.parseUpbitTicker({...tick, type: "trade"}, "KRW-BTC"), cv.parseUpbitTicker({...tick, trade_price: 0}, "KRW-BTC"), cv.parseUpbitTicker(null, "KRW-BTC"), cv.parseUpbitTicker({status: "UP"}, "KRW-BTC")];
      const noTs = {...tick}; delete noTs.trade_timestamp; noTs.timestamp = 1234;
      out.fallback = cv.parseUpbitTicker(noTs, "KRW-BTC").tradeTs;
      out.clock = cv.kstClock(Date.UTC(2026, 9, 30, 5, 2, 31));
      out.day = [cv.coinCandleDate(Date.UTC(2026, 9, 29, 23, 59, 59)), cv.coinCandleDate(Date.UTC(2026, 9, 30, 0, 0, 0))];   // 한국 시각 08:59:59 · 09:00:00
      out.badge = [cv.liveBadge("live", Date.UTC(2026, 9, 30, 5, 2, 31)), cv.liveBadge("live"), cv.liveBadge("reconnecting", Date.UTC(2026, 9, 30, 5, 2, 31)), cv.liveBadge("reconnecting"), cv.liveBadge("unsupported"), cv.liveBadge("connecting")];
      const now = Date.UTC(2026, 9, 30, 5, 3, 0);
      out.gap = [cv.priceGap({live: 98120000, order: 97350000, checkedAt: now - 89000, now}), cv.priceGap({live: 98120000, order: 98115000, checkedAt: now - 1000, now}),
                 cv.priceGap({live: 98120000, order: 98115000, checkedAt: now - 40000, now}), cv.priceGap({live: null, order: 98115000, checkedAt: now, now}), cv.priceGap({live: 98120000, order: 0, checkedAt: now, now})];
      out.line = [cv.orderPriceLine(98115000, Date.UTC(2026, 9, 30, 5, 2, 30)), cv.orderPriceLine(null, 1), cv.orderPriceLine(98115000)];
      out.delay = [0, 1, 2, 5, 10, -3].map(cv.reconnectDelay);
      out.consts = [cv.UPBIT_WS_URL, cv.PING_MS, cv.GAP_PCT_LIMIT, cv.ORDER_AGE_LIMIT_SEC];
    """)
    assert out["sub"] == [{"ticket": "t1"}, {"type": "ticker", "codes": ["KRW-BTC"]}, {"format": "DEFAULT"}]
    assert out["dec"] == ["KRW-BTC", "KRW-BTC", "KRW-BTC", None, "KRW-BTC"]       # 문자열 · 바이트 · ArrayBuffer · 이미 푼 객체 · 깨진 글
    ts = int(datetime(2026, 10, 30, 5, 2, 31, tzinfo=timezone.utc).timestamp() * 1000)         # 한국 시각 14:02:31
    assert out["t"] == {"price": 98120000, "tradeTs": ts, "cr": 1.23}
    assert out["bad"] == [None] * 5                                              # 다른 종목 · 다른 종류 · 값 없음 · PING 응답은 섞이지 않는다
    assert out["fallback"] == 1234
    assert out["clock"] == "14:02:31"                                            # 한국 시각
    assert out["day"] == ["2026-10-29", "2026-10-30"]                            # 일봉은 한국 시각 09:00 에 바뀐다
    texts = [b["text"] for b in out["badge"]]
    assert texts == ["● 실시간 · 14:02:31 체결", "● 연결됨 · 체결을 기다리는 중", "● 다시 연결하는 중 · 마지막 체결 14:02:31", "● 다시 연결하는 중",
                     "실시간이 아닙니다 · 이 브라우저는 실시간 연결을 지원하지 않습니다", "실시간 연결하는 중…"]
    assert [b["tone"] for b in out["badge"]] == ["ok", "ok", "warn", "warn", "mute", "mute"]
    assert not any("실시간" in t for t in texts[2:4])                            # 끊겼을 때는 「실시간」 이라고 쓰지 않는다(「연결하는 중」 · 「마지막 체결」 만)
    g = out["gap"]
    assert g[0]["warn"] and "0.8% 다릅니다" in g[0]["text"] and "89초 전" in g[0]["text"] and g[0]["text"].endswith("주문은 아래 가격으로 체결됩니다.")
    assert not g[1]["warn"] and g[1]["text"] == ""                               # 0.004% · 1초 — 조용히
    assert g[2]["warn"] and "40초 전" in g[2]["text"] and "다릅니다" not in g[2]["text"]   # 가격은 같아도 확인이 오래되면 알린다
    assert not g[3]["warn"] and not g[4]["warn"] and g[3]["pct"] is None          # 비교할 수 없으면 경고하지 않는다(없는 값을 지어내지 않음)
    assert out["line"] == ["98,115,000원 · 14:02:30 확인", "주문 가격을 확인하지 못했습니다", "98,115,000원"]
    assert out["delay"] == [1000, 2000, 4000, 30000, 30000, 1000]
    assert out["consts"] == ["wss://api.upbit.com/websocket/v1", 60000, 0.5, 30]


def test_screen_wires_live_connection_safely():
    """TC-CRY-06 — paper.js 의 실시간 연결: 업비트 공개 주소 하나 · 바이너리 수신 · 끊기면 늘려 가며 재연결 · 화면을 떠나거나 탭이 숨겨지면 닫는다 · 주문 가격은 앱 길 · 야후 · 저장 없음."""
    assert 'wss://api.upbit.com/websocket/v1' in CV.read_text(encoding="utf-8")
    assert "new WebSocket(UPBIT_WS_URL)" in PAPER and PAPER.count("new WebSocket(") == 1      # 연결 주소는 이 한 곳 — 다른 곳으로 시세를 보내지 않는다
    assert 'ws.binaryType = "arraybuffer"' in PAPER and "decodeWsData(ev.data)" in PAPER
    assert "reconnectDelay(pcWsAttempt++)" in PAPER and "clearInterval(pcWsPing)" in PAPER
    stop = PAPER[PAPER.index("function pcStopLive()"):PAPER.index("async function pcPollOrderQuote()")]
    assert "pcWs.close()" in stop and "clearTimeout(pcWsRetry)" in stop and "clearInterval(pcOrderPoll)" in stop
    assert "if (!el || !el.offsetParent) { pcStopLive(); return; }" in PAPER                 # 이 화면을 떠나면 닫는다
    assert 'document.addEventListener("visibilitychange"' in PAPER and "document.hidden" in PAPER   # 탭이 숨겨지면 닫고 돌아오면 다시
    assert "/api/paper/crypto/ticker?markets=" in PAPER[PAPER.index("async function pcPollOrderQuote()"):]  # 주문 가격은 앱이 확인한 길
    live = PAPER[PAPER.index("// ── 코인 실시간"):PAPER.index("async function cryptoTicker()")]
    assert "yahoo" not in live.lower() and "localStorage" not in live and "sessionStorage" not in live and 'method: "POST"' not in live   # 저장 · 외부 전송 없음
    assert "pcSeries.update({ time: day, value: t.price })" in live and "coinCandleDate(t.tradeTs)" in live      # 오늘 봉을 체결마다 · 날짜가 앞서면 새 봉
    # 차트 라이브러리는 update · setData 에 넘긴 객체의 time 을 제자리에서 바꾼다(2026-10-30 실제 앱에서 두 번째 체결부터 멈춤) — 들고 있는 값은 복사본으로
    assert "pcSeries.update(pcLastPoint)" not in PAPER and "series.setData(pts)" not in PAPER[PAPER.index("async function pcDrawChart"):PAPER.index("// ── 코인 실시간")]
    comp = (ROOT / "public" / "js" / "company.js").read_text(encoding="utf-8")
    assert "series.setData(pts)" not in comp and comp.index("coLastTime = pts[pts.length - 1].time;") < comp.index("series.setData(pts.map(")
