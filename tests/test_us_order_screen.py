"""미국주식 › 주문/매매 화면 시험 (TC-USS · `P01-④-3` · 2026-10-17 · 모의투자 점검 L10 · #255 · #256 미국 쪽).

결정: Figma 「Qurious · 미국주식 주문 화면」 C — 종목을 넣으면 시세 카드(현지 통화 · 등락 · 원화 환산 · 장 상태 ·
마지막 체결 · 환율 글) · 수량을 넣으면 예상 금액(서버 미리 보기) · 매수는 앱 안 확인 상자 · 장이 닫히면 예약 주문.

여기서 지키는 것 —
1. 그리기(js/usorder.js · DOM 없음 — Node 로 돌림): 서버 글(장 상태 · 환율 · 예약 안내 · 까닭)을 그대로 · 모르는 값은 「—」 ·
   글자를 막는다(이스케이프) · 장 상태를 모르면(null) 「닫힘」 으로 짐작하지 않는다 · 권유 낱말이 없다.
2. 계약: 화면이 부르는 길이 서버 라우터에 있다(화면 → API) · 시세 출처 이름이 서버 상수와 같다(두 곳에 적힐 수밖에 없는 값).
3. 연결(js/us.js · app.html): 지정가 · 매도 거름 → 확인 상자 → 주문 · 예약 차례 · 예약 본문에 가격이 없다 ·
   확인 상자는 취소 단추에 초점(실수로 Enter 를 눌러도 주문이 나가지 않게) · 칸 셋이 주문 칸 안에 있다.
네트워크 · 실제 DB 없이 돈다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.routes import paper as paper_routes, stocks as stocks_routes, us_reserve as reserve_routes
from app.services import data_provenance

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js"
MOD = JS / "usorder.js"
US_JS = JS / "us.js"
APP_HTML = ROOT / "public" / "app.html"

#: 2026-10-17 17:35 이 PC 앱의 실제 응답에서 옮김(GET /api/stocks/quote?symbol=PLUG · GET /api/paper/stocks/quote?symbol=PLUG) — 칸 이름을 짐작하지 않는다
Q = {"symbol": "PLUG", "name": "Plug Power Inc.", "price": 1.38, "prev_close": 1.485, "change_pct": -7.07,
     "currency": "USD", "market": "NCM", "as_of": "2026-10-17 05:00"}
PQ = {"symbol": "PLUG", "code": "PLUG", "name": "Plug Power Inc.", "market": "NCM", "price": 1834.8479999999997,
      "price_local": 1.38, "currency": "USD", "fx_rate": 1329.6, "fx_source": "live", "fx_as_of": "2026-10-17T17:35:18+09:00",
      "fx_note": "받은 환율 1 USD = 1,329.60원 · 10-17 17:35 기준", "settlement_currency": "KRW"}
CLOSED = {"open": False, "next_open_kst": "10-19(월) 22:30", "close_kst": None, "source": "NYSE 휴장일 공지(2026 ~ 2028)",
          "label": "미국 정규장 닫힘 · 다음 정규장 10-19(월) 22:30(KST)"}
OPEN = {"open": True, "next_open_kst": None, "close_kst": "10-20(화) 05:00", "label": "미국 정규장 열림 · 10-20(화) 05:00(KST) 마감"}
UNKNOWN = {"open": None, "label": "휴장일 표에 없는 해라 미국 정규장 상태를 판정하지 않습니다"}
#: 서버 미리 보기(POST /api/paper/stocks/orders/preview) 칸 — app/services/paper_trading.py stock_preview 가 돌려주는 이름 그대로
#: 2026-10-17 18:04 손 시험 응답 꼴 — 체결 단가는 원 단위로 버린다(1,834.848 → 1,834 · paper_trading._price_unit)
P = {"executable": True, "estimatedPrice": 1834.0, "estimatedAmount": 1834.0, "totalCost": 0.0, "netAmount": 1834.0,
     "cashBefore": 100000000.0, "cashAfter": 99998166.0, "reason": None}
RES = {"market": CLOSED, "note": "다음 정규장 시작가(그날 첫 거래 값)로 체결됩니다",
       "fired": [{"order_id": "a1", "symbol": "PLUG", "status": "filled", "fill_price": 1994.0, "open_local": 1.5,
                  "currency": "USD", "fx_note": "받은 환율 1 USD = 1,329.60원", "filled_at_kst": "10-19(월) 22:30"}],
       "reservations": [
           {"order_id": "b2", "symbol": "PLUG", "name": "Plug Power Inc.", "quantity": 2, "status": "pending", "next_open_kst": "10-19(월) 22:30"},
           {"order_id": "a1", "symbol": "PLUG", "name": "Plug Power Inc.", "quantity": 1, "status": "filled",
            "filled_at_kst": "10-19(월) 22:30", "fill_price": 1994.0}]}


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    return node


def _run(tmp_path: Path, body: str) -> dict:
    """usorder.js 를 Node 로 불러 body(그 안에서 out 을 채움)를 돌린다 — 화면 파일을 바꾸지 않는다."""
    script = tmp_path / "uso.mjs"
    consts = "\n".join(f"const {k} = {json.dumps(v, ensure_ascii=False)};"
                       for k, v in {"Q": Q, "PQ": PQ, "CLOSED": CLOSED, "OPEN": OPEN, "UNKNOWN": UNKNOWN, "P": P, "RES": RES}.items())
    script.write_text(f'import * as m from "{MOD.resolve().as_uri()}";\n{consts}\nconst out = {{}};\n{body}\n'
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run([_node(), str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# ── 1. 그리기 ─────────────────────────────────────────────────────────────────
def test_buy_label_follows_the_server_market_state(tmp_path):
    out = _run(tmp_path, "out.c = m.usoBuyLabel(CLOSED); out.o = m.usoBuyLabel(OPEN); out.u = m.usoBuyLabel(UNKNOWN); out.n = m.usoBuyLabel(null);")
    assert out == {"c": "예약 매수 (다음 정규장)", "o": "매수 (Buy)", "u": "매수 (Buy)", "n": "매수 (Buy)"}


def test_quote_card_shows_server_values_and_texts(tmp_path):
    out = _run(tmp_path, "out.h = m.usoQuoteHtml(Q, PQ, CLOSED); out.o = m.usoQuoteHtml(Q, PQ, OPEN);"
                         "out.none = m.usoQuoteHtml(null, null, CLOSED);"
                         "out.unk = m.usoQuoteHtml({symbol:'X'}, {symbol:'X', currency:'USD'}, UNKNOWN);"
                         "out.xss = m.usoQuoteHtml({name:'<img src=x onerror=1>'}, {fx_note:'<b>x</b>'}, null);")
    h = out["h"]
    for want in ("$1.38", "-7.07%", "≈ 1,835원", "마지막 체결 10-17 05:00(KST)", PQ["fx_note"], CLOSED["label"], "장 닫힘", "야후 파이낸스 지연 시세"):
        assert want in h, want
    assert "장 열림" in out["o"] and out["none"] == ""
    assert "장 상태 모름" in out["unk"] and "마지막 체결 시각 모름" in out["unk"]
    assert "≈ —" in out["unk"] and "0원" not in out["unk"]              # 모르는 원화 값을 0 으로 메우지 않는다
    assert "<img" not in out["xss"] and "&lt;img" in out["xss"] and "<b>" not in out["xss"]


def test_estimate_uses_preview_fields_and_says_when_it_is_only_a_guess(tmp_path):
    out = _run(tmp_path, "out.c = m.usoEstimateHtml(P, CLOSED); out.o = m.usoEstimateHtml(P, OPEN);"
                         "out.short = m.usoEstimateHtml({...P, executable:false, reason:'보유 현금이 부족합니다'}, OPEN);"
                         "out.none = m.usoEstimateHtml(null, OPEN);")
    for want in ("예상 금액(원화 환산)</span><b>1,834원</b>", "수수료 · 세금</span><b>0원</b>", "순정산</span><b>1,834원</b>",
                 "100,000,000원 → 99,998,166원"):
        assert want in out["o"], want                                  # 줄마다 미리 보기의 그 칸(다른 칸 값으로 우연히 맞지 않게)
    assert "다음 정규장 시작가로 체결돼 금액이 달라집니다" in out["c"] and "다음 정규장" not in out["o"]
    assert "보유 현금이 부족합니다" in out["short"] and out["none"] == ""


def test_confirm_reserves_only_when_the_server_says_closed(tmp_path):
    out = _run(tmp_path, "const a = {symbol:'PLUG', qty:1, q:Q, pq:PQ, p:P};"
                         "out.c = m.usoConfirm({...a, market:CLOSED}); out.o = m.usoConfirm({...a, market:OPEN});"
                         "out.u = m.usoConfirm({...a, market:UNKNOWN});")
    c, o, u = out["c"], out["o"], out["u"]
    assert c["reserve"] is True and c["title"] == "매수 예약 확인 · 모의투자" and c["okLabel"] == "예약 걸기"
    assert "10-19(월) 22:30(KST) 정규장 시작가로 체결합니다" in c["html"] and "취소할 수 있습니다" in c["html"]
    assert o["reserve"] is False and o["okLabel"] == "매수 주문 내기" and "data-uso-warn" not in o["html"]
    assert u["reserve"] is False and UNKNOWN["label"] in u["html"]      # 모르면 닫힘으로 짐작하지 않고 그 사실을 말한다
    for h in (c["html"], o["html"]):
        # 원화 단가는 미리 보기의 체결 단가(1,834) — 카드의 반올림 값(≈ 1,835)이 아니다 · 순정산 줄과 같은 숫자
        assert "$1.38 → 1,834원" in h and "1,834원 · 100,000,000원" in h and PQ["fx_note"] in h and "실제 주문이 나가지 않습니다" in h
    nop = _run(tmp_path, "out.h = m.usoConfirm({symbol:'PLUG', qty:1, q:Q, pq:PQ, p:null, market:OPEN}).html;")["h"]
    assert "$1.38 → 1,835원" in nop                                    # 미리 보기를 못 받았으면 모의 시세 값(그때만)


def test_reservation_list_rows_cancel_buttons_and_fired_notes(tmp_path):
    out = _run(tmp_path, "out.h = m.usoReservationsHtml(RES); out.e = m.usoReservationsHtml({reservations:[], fired:[]});"
                         "out.w = m.usoReservationsHtml({reservations:[], fired:[{symbol:'PLUG', status:'waiting', reason:'시가를 아직 받지 못했습니다'}]});")
    h = out["h"]
    assert 'data-uso-cancel="b2"' in h and 'data-uso-cancel="a1"' not in h         # 대기 줄에만 취소
    assert "10-19(월) 22:30 체결 예정" in h and "10-19(월) 22:30 체결 · 1,994원" in h
    assert "예약 체결: PLUG · 10-19(월) 22:30 정규장 시작가 $1.50 → 1,994원" in h and RES["note"] in h
    assert out["e"] == "" and "기다림 — 시가를 아직 받지 못했습니다" in out["w"]


def test_module_has_no_advice_words():
    # 주석(머리말이 금지 낱말을 예로 든다)은 빼고 화면에 나갈 수 있는 코드만 본다 — 글자만 찾으면 주석에 속는다(S92)
    code = re.sub(r"/\*.*?\*/", "", MOD.read_text(encoding="utf-8"), flags=re.S)
    code = "\n".join(line.split("//")[0] if "//" in line and "://" not in line else line for line in code.splitlines())
    for bad in ("매수 추천", "강력 매수", "사세요", "매수 신호"):
        assert bad not in code, bad


# ── 2. 계약 ───────────────────────────────────────────────────────────────────
def _paths(router) -> set[tuple[str, str]]:
    return {(r.path, m) for r in router.routes for m in getattr(r, "methods", ())}


def test_screen_calls_only_routes_that_exist():
    us = US_JS.read_text(encoding="utf-8")
    have = _paths(reserve_routes.router) | _paths(paper_routes.router) | _paths(stocks_routes.router)
    want = [("/api/paper/stocks/us-market", "GET"), ("/api/paper/stocks/reservations", "GET"),
            ("/api/paper/stocks/reservations", "POST"), ("/api/paper/stocks/reservations/{order_id}", "DELETE"),
            ("/api/paper/stocks/orders/preview", "POST"), ("/api/paper/stocks/quote", "GET"),
            ("/api/stocks/quote", "GET"), ("/api/paper/stocks/orders", "POST")]
    for path, method in want:
        assert (path, method) in have, (path, method)
        literal = path.split("{")[0].rstrip("/")
        assert literal in us, f"화면이 {literal} 를 부르지 않는다"


def test_quote_source_label_matches_the_server_constant():
    out = re.search(r'export const USO_SOURCE = "([^"]+)"', MOD.read_text(encoding="utf-8"))
    assert out and out.group(1) == data_provenance.QUOTE_SOURCE_LABEL


# ── 3. 연결 ───────────────────────────────────────────────────────────────────
def _func(name: str) -> str:
    text = US_JS.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = text.index(f"function {name}(")
    end = text.index("\n}\n", start)
    return text[start:end]


def test_order_flow_is_filter_then_confirm_then_order_or_reserve():
    f = _func("placeUsOrder")
    lim, sell = f.index('type === "limit"'), f.index('side === "sell"')
    ask = f.index("askUsConfirm(")
    res, order = f.index('"/api/paper/stocks/reservations"'), f.index('"/api/paper/stocks/orders"')
    assert lim < ask and sell < ask and ask < res and ask < order
    assert "await loadUsMarket()" in f[:ask]                       # 열어 둔 화면의 옛 장 상태로 주문하지 않게
    body = re.search(r'"/api/paper/stocks/reservations", \{ method: "POST", body: \{([^}]*)\}', f)
    assert body and "price" not in body.group(1)


def test_dialog_focuses_cancel_and_guards_stale_quotes():
    d = _func("askUsConfirm")
    assert "showModal()" in d and 'querySelector(\'[data-us-dlg="no"]\').focus()' in d
    q = _func("refreshUsQuote")
    assert "++usOrd.seq" in q and "if (seq !== usOrd.seq) return;" in q


def test_containers_sit_inside_the_order_panel():
    html = APP_HTML.read_text(encoding="utf-8")
    view = re.search(r'data-view="us-order">(.*?)data-view=', html, flags=re.S).group(1)
    for cid in ("us-ord-quote", "us-ord-estimate", "us-reserve-list"):
        assert f'id="{cid}"' in view, cid
    assert view.index('id="us-ord-symbol"') < view.index('id="us-ord-quote"') < view.index('id="us-ord-qty"') < view.index('id="us-ord-estimate"')
    assert "정규장이 닫힌 때는 예약 주문으로 받아 다음 정규장 시작가로 체결합니다" in view   # 안내 글도 같은 규칙을 말한다
