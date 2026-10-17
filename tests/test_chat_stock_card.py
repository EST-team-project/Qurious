"""AI 투자 상담 — 답 위 앱 판단 카드 화면 시험 (TC-SCC) · 2026-10-17 · 모의투자 점검 L2.

결정: Figma 「AI 투자 상담 — 근거 답과 출처」 03-2 [결정] 설계 A — 질문에 종목 이름이 그대로 있으면 AI 답보다 먼저, 우리 앱이 그 종목에
대해 이미 아는 것(종목 허브 묶음의 지금가 · 다중 주기 신호 · 재무 건전성 · 최근 공시)을 카드 한 장으로 보인다. 머리 글 「질문의 ○○ 을
종목으로 읽었습니다」 로 무엇을 읽었는지 밝힌다(잘못 읽어도 사용자가 알게). 카드 값은 서버 묶음 그대로라 AI 가 숫자를 바꿀 수 없다.

여기서 지키는 것 —
1. 그리기(js/stockcard.js · DOM 없음 — Node 로 돌림): 칸마다 서버 값 · 기준일 · 그 화면 · 서버 글(까닭 · 고지)만 옮긴다 · 칸을 합친 결론을
   만들지 않는다 · 글자를 막는다 · 칸이 없거나 「준비 중」 이면 서버 까닭을 보인다 · 둘째 종목은 접어 둔다.
2. 계약: 카드가 부르는 칸 · 다른 화면 단추가 서버 허브의 칸 · 단추 이름과 같다(화면 → API).
3. 연결(js/kbchat.js): 질문 말풍선 바로 뒤에 자리를 먼저 잡고 근거 답과 함께 불러온다(답을 기다리게 하지 않음) · 다른 엔진 답은 그 답 위에.
네트워크 · 실제 DB 없이 돈다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import stock_hub

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js"
CARD = JS / "stockcard.js"

#: 2026-10-17 14:35 이 PC 앱의 실제 응답(GET /api/stock-hub?symbol=055550&sections=price,signal,financials,disclosures)에서 옮김 — 칸 이름 짐작 금지(S120)
HUB = {
    "version": 1, "symbol": "055550", "name": "신한지주", "market": "KOSPI",
    "order": ["identity", "price", "signal", "financials", "disclosures"],
    "sections": {
        "identity": {"key": "identity", "label": "종목", "status": "ok", "as_of": None, "source": "수집 시세의 마지막 줄(종목 이름 · 시장)",
                     "view": "", "data": {"name": "신한지주", "market": "KOSPI", "kind": "stock", "signal_universe": True}, "reason": ""},
        "price": {"key": "price", "label": "마지막 종가", "status": "ok", "as_of": "2026-10-15", "view": "trading-chart",
                  "source": "수집 시세 — 일봉 종가(수정주가) · 매 거래일 12:30 에 전 거래일분을 받음",
                  "data": {"close": 94200.0, "trade_date": "2026-10-15", "prev_close": 95000.0, "prev_date": "2026-10-14",
                           "change_pct": -0.84, "basis": "adj_base", "market": "KOSPI"}, "reason": "",
                  "note": "실시간이나 지연 시세가 아니라 마지막 거래일의 장 마감 종가입니다."},
        "signal": {"key": "signal", "label": "다중 주기 신호", "status": "ok", "as_of": "2026-10-15", "view": "robo-patterns",
                   "source": "다중 주기 신호 — 60분 · 일 · 주봉 지표 규칙 점수의 합(매 거래일 12:30 기록)",
                   "data": {"signal": "매도", "strength": "보통", "confidence": 0.7,
                            "summary": "주봉 기준으로 5주선이 20주선 아래고 MACD 가 신호선 아래라 매도 쪽입니다. 다만 일봉은 RSI 가 30 아래인 28.8까지 떨어진 상태입니다.",
                            "confidence_text": "주기 셋 모두 매도 쪽 · 기운 정도 보통", "definition": "tv-2026", "reasons": [], "counter_reasons": []},
                   "reason": "", "notice": "지표 규칙의 점수를 합친 결과입니다. 신뢰도는 주기들이 얼마나 같은 방향인지를 나타낼 뿐 확률이 아니며, 투자 권유가 아닙니다."},
        "financials": {"key": "financials", "label": "재무 건전성", "status": "ok", "as_of": "2026-10-08", "view": "agent-cb",
                       "source": "전자공시(DART) 다중회사 주요계정 — 접수일 다음 거래일부터 쓴 판",
                       "data": {"kind": "financial",
                                "kind_note": "금융회사는 예금 · 보험 같은 부채가 장사 밑천이고 유동 · 비유동 구분이 없어 이 비율로 견줄 수 없습니다",
                                "fs": "CFS", "latest": {"period_end": "2026-06-30", "report": "반기보고서", "bsns_year": "2026",
                                                        "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261007000223", "restated": True,
                                                        "available_from": "2026-10-08"},
                                "summary": {"pass": 2, "fail": 0, "unknown": 5, "total": 7},
                                "metrics": [{"key": "current_ratio", "label": "유동비율", "value": None, "unit": "%", "sentence": "…"},
                                            {"key": "debt_ratio", "label": "부채비율", "value": None, "unit": "%", "sentence": "…"},
                                            {"key": "equity_ratio", "label": "자기자본비율", "value": 7.4, "unit": "%", "sentence": "…"},
                                            {"key": "impairment", "label": "자본잠식률", "value": 0.0, "unit": "%", "sentence": "…"}]},
                       "reason": "", "notice": "투자 권유가 아닙니다."},
        "disclosures": {"key": "disclosures", "label": "최근 공시", "status": "ok", "as_of": "2026-10-13", "view": "agent-news",
                        "source": "전자공시(DART) 공시 목록 — 수집기 검색 색인",
                        "data": {"items": [{"title": "타법인주식및출자증권취득결정(자율공시)", "published": "2026-10-13",
                                            "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261013800171", "source": "dart",
                                            "source_label": "공시", "attribution": "", "topics": ["투자·출자"]}],
                                 "total": 1073, "index_built_at": "2026-10-17T14:05:27+09:00"}, "reason": ""},
    },
    "links": [{"view": "trading-chart", "label": "주가 차트"}, {"view": "robo-patterns", "label": "차트 패턴 · 다중 주기"},
              {"view": "robo-screening", "label": "종목 스크리닝"}, {"view": "agent-cb", "label": "재무 · 신용 위험"},
              {"view": "invest-fundamental", "label": "재무제표 분석"}, {"view": "agent-news", "label": "공시 · 기사 시간표"},
              {"view": "market-calendar", "label": "일정"}, {"view": "paper-stock", "label": "모의 주문(연습)"}],
    "notice": "정보를 모아 보여 드릴 뿐 투자 권유가 아닙니다. 칸마다 그 화면의 값을 옮겨 기준일 · 출처가 서로 다를 수 있고, 지난 값은 앞날을 보장하지 않습니다.",
}
MENTION = {"symbol": "055550", "name": "신한지주", "market": "KOSPI", "matched": "신한지주", "at": 0}


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    return node


def _run(tmp_path: Path, body: str):
    """stockcard.js 를 Node 로 불러 body(그 안에서 out 을 채움)를 돌린다 — 화면 파일을 바꾸지 않는다."""
    script = tmp_path / "card.mjs"
    script.write_text(f'import * as sc from "{CARD.resolve().as_uri()}";\nconst HUB = {json.dumps(HUB, ensure_ascii=False)};\n'
                      f"const MENTION = {json.dumps(MENTION, ensure_ascii=False)};\nconst out = {{}};\n{body}\n"
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run([_node(), str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def test_card_copies_server_values_and_says_what_it_read(tmp_path):
    """TC-SCC-01 · 카드는 서버 값 · 기준일 · 서버 글만 옮긴다 — 머리(이름 · 코드 · 시장 · 마지막 종가 · 등락 · 그날) · 읽은 이름 ·
    신호(쪽 · 기운 · 기록한 날 · 서버 요약) · 재무(그렇다 · 아니다 · 모름 · 보고서 · 지표 값 · 셀 수 없음 · 서버 까닭) · 최근 공시 · 고지."""
    out = _run(tmp_path, 'out.html = sc.stockCardHtml(HUB, MENTION);\n'
                         'out.spaced = sc.stockCardHtml(HUB, { ...MENTION, matched: "신한 지주" });')
    # 머리 글은 질문에서 읽은 글자 그대로 — 회사 이름으로 바꿔 쓰지 않는다(무엇을 읽었는지 밝히는 것이 목적)
    assert "질문의 「신한 지주」 를 종목으로 읽었습니다" in _text(out["spaced"])
    t = _text(out["html"])
    for want in ("신한지주", "055550", "코스피", "94,200원", "−0.84%", "10-15 종가",
                 "질문의 「신한지주」 를 종목으로 읽었습니다", "하나로 합친 결론이 아닙니다",
                 "다중 주기 신호", "매도 쪽 · 보통", "10월 15일 기록", "주봉 기준으로 5주선이 20주선 아래고",
                 "재무 건전성", "그렇다 2 · 모름 5", "반기보고서(2026-06-30)", "자기자본비율 7.4%", "유동비율 셀 수 없음",
                 "자본잠식률 0%", "금융회사는 예금 · 보험 같은 부채가 장사 밑천",
                 "최근 공시", "10-13", "전자공시 1,073건 가운데", "타법인주식및출자증권취득결정(자율공시)", HUB["notice"]):
        assert want in t, want
    assert "아니다" not in t.split("재무 건전성")[1].split("최근 공시")[0]       # 아니다 0 은 칩에 쓰지 않는다
    assert 'href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261013800171"' in out["html"]
    assert "data-view=" not in out["html"]                                        # 앱의 화면 이름 속성과 겹치지 않게(data-sc-view)


def test_links_are_the_decided_five_with_server_labels(tmp_path):
    """TC-SCC-02 · 다른 화면 단추 = 결정 A 의 다섯(차트 패턴 · 스크리닝 · 재무 · 신용 위험 · 공시 · 기사 시간표 · 모의 주문) · 차례 그대로 ·
    이름은 서버 links 글 · 서버에 없는 화면은 그리지 않는다."""
    out = _run(tmp_path, r"""
out.views = [...sc.stockCardHtml(HUB, MENTION).matchAll(/data-sc-view="([^"]+)"[^>]*>([^<]+)</g)].map(m => [m[1], m[2].trim()]);
const fewer = { ...HUB, links: HUB.links.filter(l => l.view !== "robo-screening") };
out.fewer = [...sc.stockCardHtml(fewer, MENTION).matchAll(/data-sc-view="([^"]+)"/g)].map(m => m[1]);
out.decided = sc.STOCK_CARD_VIEWS;
""")
    assert out["decided"] == ["robo-patterns", "robo-screening", "agent-cb", "agent-news", "paper-stock"]
    assert out["views"] == [["robo-patterns", "차트 패턴 · 다중 주기 →"], ["robo-screening", "종목 스크리닝 →"],
                            ["agent-cb", "재무 · 신용 위험 →"], ["agent-news", "공시 · 기사 시간표 →"], ["paper-stock", "모의 주문(연습) →"]]
    assert "robo-screening" not in out["fewer"] and len(out["fewer"]) == 4


def test_missing_or_pending_sections_show_the_server_reason(tmp_path):
    """TC-SCC-03 · 칸이 비거나 「준비 중」 · 오류면 값을 지어내지 않고 서버 까닭을 보인다 · 가격이 없으면 머리에 가격을 쓰지 않는다 ·
    관망은 「쪽」 을 붙이지 않는다 · 아니다가 있으면 칩에 쓴다 · 글자를 막는다(공시 제목 · 이름)."""
    out = _run(tmp_path, r"""
const h = JSON.parse(JSON.stringify(HUB));
h.sections.price = { key: "price", label: "마지막 종가", status: "empty", as_of: null, data: {}, reason: "이 종목의 시세가 아직 없습니다." };
h.sections.signal = { key: "signal", label: "다중 주기 신호", status: "empty", as_of: null, data: {},
  reason: "이 종목은 다중 주기 신호를 계산하는 401종목에 들지 않습니다." };
h.sections.financials.data.summary = { pass: 1, fail: 2, unknown: 4, total: 7 };
h.sections.disclosures.data.items[0].title = "<img src=x onerror=alert(1)>";
h.name = "<b>신한</b>";
out.empty = sc.stockCardHtml(h, MENTION);
const w = JSON.parse(JSON.stringify(HUB));
w.sections.signal.data.signal = "관망"; w.sections.signal.data.strength = "약함";
out.hold = sc.stockCardHtml(w, MENTION);
const e = JSON.parse(JSON.stringify(HUB));
e.sections.financials = { key: "financials", label: "재무 건전성", status: "error", as_of: null, data: {}, reason: "재무 자료를 읽지 못했습니다." };
out.err = sc.stockCardHtml(e, MENTION);
const n = JSON.parse(JSON.stringify(HUB));          // 주소 없는 공시 — 링크 없이 제목만 그리는 갈래도 글자를 막는다
n.sections.disclosures.data.items[0] = { ...n.sections.disclosures.data.items[0], url: "javascript:alert(1)", title: "<script>x</script>공시" };
out.nourl = sc.stockCardHtml(n, MENTION);
""")
    assert "<script>" not in out["nourl"] and "&lt;script&gt;x&lt;/script&gt;공시" in out["nourl"]
    assert "javascript:" not in out["nourl"]                                        # http(s) 가 아닌 주소는 링크로 쓰지 않는다
    t = _text(out["empty"])
    assert "이 종목의 시세가 아직 없습니다." in t and "원" not in t.split("질문의")[0]          # 머리에 가격 없음
    assert "이 종목은 다중 주기 신호를 계산하는 401종목에 들지 않습니다." in t and "쪽 ·" not in t
    assert "그렇다 1 · 아니다 2 · 모름 4" in t
    assert "<img" not in out["empty"] and "&lt;img src=x onerror=alert(1)&gt;" in out["empty"] and "<b>신한</b>" not in out["empty"]
    assert "관망 · 약함" in _text(out["hold"]) and "관망 쪽" not in _text(out["hold"])
    assert "재무 자료를 읽지 못했습니다." in _text(out["err"])


def test_second_stock_is_folded_and_reads_are_named(tmp_path):
    """TC-SCC-04 · 질문에 종목이 둘이면(서버 최대 둘) 첫째는 펼치고 둘째는 접어 둔다 — 둘째도 「질문의 ○○ 도 종목으로 읽었습니다」 로 밝힌다."""
    out = _run(tmp_path, r"""
const kia = { ...JSON.parse(JSON.stringify(HUB)), symbol: "000270", name: "기아" };
out.two = sc.stockCardsHtml([{ hub: HUB, mention: MENTION }, { hub: kia, mention: { ...MENTION, symbol: "000270", name: "기아", matched: "기아" } }]);
out.none = sc.stockCardsHtml([]);
""")
    assert out["two"].count('<section class="kb-sc"') == 2
    assert re.search(r"<details[^>]*>\s*<summary[^>]*>질문의 「기아」 도 종목으로 읽었습니다", out["two"])
    head, folded = out["two"].split("<details", 1)
    assert head.count('<section class="kb-sc"') == 1 and "신한지주" in head      # 첫 카드는 접지 않는다
    assert '<section class="kb-sc"' in folded and "000270" in folded
    assert out["none"] == ""


def test_card_contract_matches_the_hub_server():
    """TC-SCC-05 · 화면 → API — 카드가 부르는 칸(sections)이 서버 허브 칸에 있고, 다섯 단추 화면이 서버 links 에 있다(이름은 서버 글)."""
    src = CARD.read_text(encoding="utf-8")
    sections = re.search(r"export const STOCK_CARD_SECTIONS = \[([^\]]*)\]", src).group(1)
    names = re.findall(r'"([a-z]+)"', sections)
    assert names == ["price", "signal", "financials", "disclosures"]
    assert set(names) <= set(stock_hub.SECTIONS)
    views = {v for v, _ in stock_hub.LINKS}
    for v in re.findall(r'"([a-z-]+)"', re.search(r"export const STOCK_CARD_VIEWS = \[([^\]]*)\]", src).group(1)):
        assert v in views, v
    assert re.search(r'^import \{ esc \} from "\./howtoview\.js";', src, re.M), "DOM 없는 글자 막기는 howtoview.js 한 곳(common.js 와 시험으로 맞댐)"


def test_chat_reserves_the_card_before_the_answer():
    """TC-SCC-06 · 연결 — 자동 · 근거 답 칸은 질문 말풍선 바로 뒤에 카드 자리를 먼저 잡고 근거 답과 함께 불러온다(기다리지 않음) ·
    다른 엔진 답은 그 답 줄 위에 끼운다 · 질문 속 종목 → 허브 두 주소 · 다른 화면 단추는 그 화면 칸에 종목을 넣어 연다."""
    src = (JS / "kbchat.js").read_text(encoding="utf-8")
    code = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    send = code[code.index("export async function sendKbChat"):code.index("export function afterChatAnswer")]
    i_user, i_slot, i_ask = send.index("ctx.appendUserMsg(q);"), send.index("reserveStockCard(box)"), send.index('api("/api/kb/ask"')
    assert i_user < i_slot < i_ask, "말풍선 → 카드 자리 → 근거 답 차례"
    assert re.search(r"^\s+fillStockCards\(slot, q\);", send, re.M), "카드는 기다리지 않는다(await 없음)"
    fill = code[code.index("async function fillStockCards"):code.index("\n}\n", code.index("async function fillStockCards"))]
    assert "/api/stock-hub/mentions?q=" in fill and "stockHubPath(" in fill and "stockCardsHtml(" in fill
    after = code[code.index("export function afterChatAnswer"):]
    assert "box.insertBefore(slot, row)" in after and "fillStockCards(slot, q)" in after
    opens = code[code.index("const STOCK_CARD_OPEN = {"):code.index("};", code.index("const STOCK_CARD_OPEN = {"))]
    for view, field in (("robo-patterns", "pt-symbol"), ("agent-cb", "rc-q"), ("paper-stock", "ps-symbol")):
        assert f'"{view}"' in opens and field in opens, view
    assert "openResearchSymbol" in opens and '"robo-screening"' in opens
