"""TC-SDR — 종목 허브 서랍 화면 시험 (할 일 ②-10 · ②-20 · 2026-10-31 S182)

결정: Figma 「Qurious · 종목 허브」 03 설계 B 서랍(2026-10-17 결정 알림 #259) — 종목 이름 옆 단추를 누르면 보던 화면을 떠나지 않고
오른쪽에 서랍이 열려, 우리 앱의 화면마다 이미 아는 값을 기준일 · 출처와 함께 칸별로 모은다. 서버(GET /api/stock-hub)는 이미 있고
이번에 화면(public/js/stockdrawer.js)을 만들었다.

여기서 지키는 것 —
1. 그리기(DOM 없음 — Node 로 돌림): 칸마다 서버 값 · 기준일 · 출처 · 서버 글을 그대로 옮긴다. 새로 계산하지 않고 한 줄 결론도 만들지 않는다. (TC-SDR-01)
2. 칸이 없거나 「준비 중」 · 오류 · 자료 없음이면 값을 지어내지 않고 서버 까닭을 보인다 — 나머지 칸은 그대로 그린다. (TC-SDR-02)
3. 글자 막기: 이름 · 제목에 든 태그는 글자로 나오고 http(s) 가 아닌 주소는 링크로 만들지 않는다. (TC-SDR-03)
4. 계약: 서랍의 칸 차례 = 서버 stock_hub.SECTIONS 에서 머리(identity)를 뺀 일곱, 「그 화면으로」 단추 이름은 서버 links 글. (TC-SDR-04)
5. 연결: app.html 이 CSS 를 부르고, main.js 가 서랍을 붙이며, 입구 단추(AI 투자 상담 카드 · 투자 정보 리서치 종목 칩)가 있다. (TC-SDR-05)
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
DRAWER = JS / "stockdrawer.js"

#: 2026-10-31 이 PC 앱의 실제 응답(GET /api/stock-hub?symbol=005930)에서 줄여 옮김 — 칸마다 항목 하나
HUB = {
    "version": 3, "symbol": "005930", "name": "삼성전자", "market": "KOSPI", "generated_at": "2026-10-31T18:47:26+09:00",
    "order": list(stock_hub.SECTIONS),
    "links": [{"view": "trading-chart", "label": "주가 차트"}, {"view": "robo-patterns", "label": "차트 패턴 · 다중 주기"},
              {"view": "agent-cb", "label": "재무 · 신용 위험"}, {"view": "agent-news", "label": "공시 · 기사 시간표"},
              {"view": "market-calendar", "label": "일정"}],
    "notice": "정보를 모아 보여 드릴 뿐 투자 권유가 아닙니다. 칸마다 기준일 · 출처가 서로 다를 수 있습니다.",
    "note": "새로 계산하지 않고 앱의 다른 화면이 쓰는 값 · 글을 그대로 모았습니다 — 칸을 합친 한 줄 결론은 만들지 않습니다.",
    "sections": {
        "identity": {"key": "identity", "label": "종목", "status": "ok", "as_of": None, "view": "", "source": "수집 시세의 마지막 줄", "reason": "",
                     "data": {"name": "삼성전자", "market": "KOSPI", "kind": "stock", "signal_universe": True}},
        "price": {"key": "price", "label": "마지막 종가", "status": "ok", "as_of": "2026-10-29", "view": "trading-chart",
                  "source": "수집 시세 — 일봉 종가(수정주가)", "reason": "",
                  "data": {"close": 232000.0, "trade_date": "2026-10-29", "prev_close": 242000.0, "prev_date": "2026-10-28",
                           "change_pct": -4.13, "basis": "adj_base", "market": "KOSPI"}},
        "signal": {"key": "signal", "label": "다중 주기 신호", "status": "ok", "as_of": "2026-10-29", "view": "robo-patterns",
                   "source": "다중 주기 신호 — 60분 · 일 · 주봉 지표 규칙 점수의 합", "reason": "",
                   "data": {"signal": "매도", "strength": "보통", "confidence": 0.55, "confidence_text": "주기 셋 중 둘이 매도 쪽 · 기운 정도 보통",
                            "summary": "주봉 기준으로 5주선이 20주선 아래고 MACD 가 신호선 아래라 매도 쪽입니다.",
                            "reasons": [{"key": "ma_down", "timeframe": "1d", "label": "일봉", "text": "5일선이 20일선 아래", "points": -1}],
                            "counter_reasons": [{"key": "macd_up", "timeframe": "1d", "label": "일봉", "text": "MACD 가 신호선 위", "points": 1}]}},
        "financials": {"key": "financials", "label": "재무 건전성", "status": "ok", "as_of": "2026-08-18", "view": "agent-cb",
                       "source": "전자공시(DART) 다중회사 주요계정", "reason": "",
                       "data": {"kind": "general", "kind_note": "", "latest": {"period_end": "2026-06-30", "report": "반기보고서", "restated": False,
                                                                                "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814003699"},
                                "summary": {"pass": 5, "fail": 0, "unknown": 2, "total": 7},
                                "metrics": [{"key": "current_ratio", "label": "유동비율", "value": 283.0, "unit": "%",
                                             "sentence": "유동비율은 283% — 1년 안에 돈이 되는 자산이 1년 안에 갚을 빚의 2.8배입니다."}],
                                "zscore": {"value": 7.97, "zone_label": "높은 구간(2.60 초과)", "reason": ""}}},
        "disclosures": {"key": "disclosures", "label": "최근 공시", "status": "ok", "as_of": "2026-10-30", "view": "agent-news",
                        "source": "전자공시(DART) 공시 목록", "reason": "",
                        "data": {"items": [{"title": "특수관계인으로부터주식의취득", "published": "2026-10-30", "source_label": "공시",
                                            "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261030000586", "attribution": ""}], "total": 4756}},
        "news": {"key": "news", "label": "최근 기사", "status": "ok", "as_of": "2026-10-31", "view": "agent-news",
                 "source": "정책브리핑 정책뉴스 · 언론사 기사 제목(GDELT)", "reason": "",
                 "data": {"items": [{"title": "삼성전자 팔고 나면 후회할까", "published": "2026-10-31T08:15:00+09:00", "source_label": "언론사 기사",
                                     "url": "https://www.fnnews.com/news/202610310030550039", "attribution": "GDELT Project 메타데이터 · 원문은 언론사"}], "total": 704}},
        "schedule": {"key": "schedule", "label": "앞으로의 일정", "status": "ok", "as_of": "2026-10-31", "view": "market-calendar",
                     "source": "금융 일정 — 공시 · 거래소 규칙에서 모은 배당 · 실적 · 주주총회 일정", "reason": "",
                     "data": {"events": [{"date": "2026-11-27", "weekday": "금", "kind": "dividend_pay", "kind_label": "배당금 지급",
                                          "title": "삼성전자 배당금 지급(분기배당)", "confidence_label": "예정"}], "days": 60}},
        "sector": {"key": "sector", "label": "업종", "status": "ok", "as_of": "2026-10-30", "view": "",
                   "source": "전자공시(DART) 기업개황 업종코드 · 한국표준산업분류(KSIC) 제11차", "reason": "",
                   "data": {"induty_code": "264", "division_code": "26", "division_name": "전자 부품, 컴퓨터, 영상, 음향 및 통신장비 제조업",
                            "section_code": "C", "section_name": "제조업(10~34)", "peer_count": 31}},
    },
}


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    return node


def _run(tmp_path: Path, hub: dict, body: str):
    """stockdrawer.js 를 Node 로 불러 body(그 안에서 out 을 채움)를 돌린다 — 화면 파일을 바꾸지 않는다."""
    script = tmp_path / "drawer.mjs"
    script.write_text(f'import * as sd from "{DRAWER.resolve().as_uri()}";\nconst HUB = {json.dumps(hub, ensure_ascii=False)};\nconst out = {{}};\n'
                      f"{body}\nprocess.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run([_node(), str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def test_drawer_copies_server_values_dates_and_sources(tmp_path):
    """TC-SDR-01 · 서랍은 칸마다 서버 값 · 기준일 · 출처 · 서버 글을 옮긴다 — 머리(이름 · 코드 · 시장 · 종가 · 등락) · 일곱 칸 차례 · 고지."""
    out = _run(tmp_path, HUB, "out.html = sd.stockDrawerHtml(HUB);")
    html, t = out["html"], _text(out["html"])
    for want in ("삼성전자", "005930", "코스피", "232,000원", "−4.13%", "10월 29일 종가", "전일 242,000원", "수정주가 기준",
                 "매도 쪽 · 보통", "주기 셋 중 둘이 매도 쪽", "주봉 기준으로 5주선이 20주선 아래고", "일봉 · 5일선이 20일선 아래", "일봉 · MACD 가 신호선 위",
                 "그렇다 5 · 모름 2", "유동비율은 283%", "부실 위험 점수(Z″) 7.97","높은 구간(2.60 초과)", "반기보고서(2026-06-30)",
                 "10-30", "특수관계인으로부터주식의취득", "전체 4,756건 가운데 최근 1건",
                 "삼성전자 팔고 나면 후회할까", "GDELT Project 메타데이터", "11월 27일(금)", "삼성전자 배당금 지급(분기배당)", "예정",
                 "제조업(10~34) › 전자 부품, 컴퓨터, 영상, 음향 및 통신장비 제조업", "수집 상장사 31곳", "같은 업종(KSIC 264)",
                 "10월 29일 기준", "10월 31일 기준", "수집 시세 — 일봉 종가(수정주가)", HUB["notice"], HUB["note"]):
        assert want in t, want
    # 칸 차례 = 서버가 주는 차례에서 머리를 뺀 일곱 — 여섯째 칸 앞에 다섯째가 온다
    keys = re.findall(r'data-hub-sec="([a-z]+)"', html)
    assert keys == ["price", "signal", "financials", "disclosures", "news", "schedule", "sector"]
    assert 'href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261030000586"' in html
    assert 'rel="noopener noreferrer"' in html
    # 그 화면으로 단추 — 서버 links 글 그대로 · links 에 없는 화면(업종 칸 view 없음)은 단추가 없다
    assert '>주가 차트 →</button>' in html and 'data-hub-go="robo-patterns"' in html and '>일정 →</button>' in html
    assert html.count("data-hub-go=") == 8      # 여섯 근거 화면 + 리밸런싱 + PAPER 모의주문
    assert "결론" not in re.sub(HUB["note"], "", t)        # 한 줄 결론을 만들지 않는다(서버 note 만 말한다)


def test_missing_pending_and_error_sections_show_server_reason(tmp_path):
    """TC-SDR-02 · 칸이 없거나 준비 중 · 오류 · 자료 없음이면 값을 지어내지 않고 서버 까닭 — 나머지 칸은 그대로 그린다."""
    hub = json.loads(json.dumps(HUB))
    hub["sections"]["sector"].update(status="pending", reason="섹터 분류 기준을 확인하는 중입니다.")
    hub["sections"]["news"].update(status="error", reason="기사 색인을 읽지 못했습니다.", data={})
    hub["sections"]["schedule"].update(status="empty", reason="앞으로 60일 안의 일정이 없습니다.", data={})
    del hub["sections"]["financials"]
    out = _run(tmp_path, hub, "out.html = sd.stockDrawerHtml(HUB);")
    t = _text(out["html"])
    for want in ("준비 중", "섹터 분류 기준을 확인하는 중입니다.", "불러오지 못함", "기사 색인을 읽지 못했습니다.", "자료 없음",
                 "앞으로 60일 안의 일정이 없습니다.", "서버가 이 칸을 주지 않았습니다.",
                 "232,000원", "특수관계인으로부터주식의취득"):       # 다른 칸은 그대로
        assert want in t, want
    assert "31곳" not in t and "삼성전자 팔고" not in t       # 막힌 칸의 값은 그리지 않는다
    assert out["html"].count('class="sd-sec sd-sec--empty"') == 4      # 업종 · 기사 · 일정 · (없는) 재무


def test_text_is_escaped_and_unsafe_urls_are_not_links(tmp_path):
    """TC-SDR-03 · 이름 · 제목의 태그는 글자로 나오고 javascript: 같은 주소는 링크가 되지 않는다."""
    hub = json.loads(json.dumps(HUB))
    hub["name"] = '<img src=x onerror="alert(1)">'
    hub["sections"]["disclosures"]["data"]["items"][0].update(title="<b>굵게</b>", url="javascript:alert(1)")
    out = _run(tmp_path, hub, "out.html = sd.stockDrawerHtml(HUB); out.fail = sd.sdFailText(new Error('401'));")
    html = out["html"]
    assert "<img" not in html and "&lt;img" in html
    assert "<b>굵게</b>" not in html and "&lt;b&gt;굵게&lt;/b&gt;" in html
    assert "javascript:" not in html
    assert "로그인이 풀렸습니다" in out["fail"]


def test_drawer_sections_match_server_and_link_labels_come_from_server(tmp_path):
    """TC-SDR-04 · 서랍 칸 차례 = 서버 SECTIONS 에서 identity 를 뺀 일곱 · 서버 칸 이름이 서랍에서 모두 그려진다."""
    out = _run(tmp_path, HUB, "out.sections = sd.DRAWER_SECTIONS; out.path = sd.hubDrawerPath('005930'); out.md = sd.sdMonthDay('2026-10-05');")
    assert out["sections"] == [s for s in stock_hub.SECTIONS if s != "identity"]
    assert out["path"] == "/api/stock-hub?symbol=005930"
    assert out["md"] == "10월 5일"


def test_drawer_links_to_npay_securities_only_for_valid_codes(tmp_path):
    """TC-SDR-06 · 머리에 「Npay 증권에서 보기」 링크 — 6자리 영숫자 코드(ETF 포함)일 때만 · 새 창 · 주소는 코드만 끼운다."""
    out = _run(tmp_path, HUB, "out.html = sd.stockDrawerHtml(HUB); out.etf = sd.hubNaverUrl('0000D0'); out.bad = ['', '5930', '005930.KS', '../x', null].map(sd.hubNaverUrl);")
    assert 'href="https://stock.naver.com/domestic/stock/005930/price"' in out["html"]
    assert "Npay 증권에서 보기" in _text(out["html"])
    assert 'target="_blank" rel="noopener noreferrer">Npay' in out["html"]
    assert out["etf"] == "https://stock.naver.com/domestic/stock/0000D0/price"
    assert out["bad"] == [""] * 5                                       # 코드가 아니면 링크를 만들지 않는다
    hub = json.loads(json.dumps(HUB))
    hub["symbol"] = "<x>"
    assert "stock.naver.com" not in _run(tmp_path, hub, "out.html = sd.stockDrawerHtml(HUB);")["html"]


def test_drawer_is_wired_into_the_app():
    """TC-SDR-05 · CSS 를 부르고 · main.js 가 붙이고 · 입구 단추가 두 화면에 있다."""
    app = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    main = (JS / "main.js").read_text(encoding="utf-8")
    card = (JS / "stockcard.js").read_text(encoding="utf-8")
    research = (JS / "research.js").read_text(encoding="utf-8")
    assert '/css/stockdrawer.css' in app
    assert 'from "/js/stockdrawer.js"' in main and "mountStockDrawer(document," in main
    assert 'data-hub-open="${esc(hub.symbol)}"' in card                      # AI 투자 상담 카드
    assert 'data-hub-open="${escHtml(S.symbol)}"' in research                # 투자 정보 리서치 종목 칩
    assert (ROOT / "public" / "css" / "stockdrawer.css").is_file()


def test_drawer_has_daily_chart_box_and_expand_modal_html(tmp_path):
    """TC-SDR-07 · 서랍에 일봉 차트 칸(기간 단추 셋 · 크게 보기) — 국내 6자리 코드일 때만 · 크게 보기 모달은 큰 차트 + 신호 칸 + 닫기(크게 보기 단추는 없음)."""
    out = _run(tmp_path, HUB, """
out.drawer = sd.stockDrawerWithChartHtml(HUB);
out.foreign = sd.stockDrawerWithChartHtml({ ...HUB, symbol: 'AAPL' });
out.box = sd.sdChartBoxHtml('005930.KS', { expand: false, height: 340 });
out.none = ['AAPL', '', '5930', null].map(s => sd.sdChartBoxHtml(s));
out.modal = sd.sdModalHtml(HUB);
out.modalForeign = sd.sdModalHtml({ ...HUB, symbol: 'AAPL' });
out.sections = sd.DRAWER_SECTIONS;
""")
    d = out["drawer"]
    assert 'data-hub-chartbox' in d and 'data-hub-chart-note' in d and "data-hub-expand" in d and "크게 보기" in d
    assert d.count("data-hub-period=") == 3 and 'data-hub-period="3m"' in d and 'class="sd-period on" data-hub-period="3m"' in d
    assert d.index("data-hub-chartbox") < d.index('data-hub-sec="price"')            # 차트가 칸들 위
    assert "data-hub-chartbox" not in out["foreign"]                                 # 해외 종목은 수집 일봉이 없다
    assert out["none"] == [""] * 4
    assert 'style="height:340px"' in out["box"] and "data-hub-expand" not in out["box"]
    m = out["modal"]
    sd_sections = out["sections"]
    assert "data-hub-modal-close" in m and "data-hub-expand" not in m and 'style="height:340px"' in m
    assert all(f'data-hub-sec="{k}"' in m for k in sd_sections)                      # 모달은 일곱 칸을 모두 담고 안에서 내리며 읽는다(사용자 11-02)
    assert "주봉 기준으로 5주선이 20주선 아래" in m                                   # 신호 근거는 서버 글 그대로
    assert "수집 일봉이 없어" in out["modalForeign"] and "data-hub-chartbox" not in out["modalForeign"]


def test_drawer_wires_expand_to_a_modal_sharing_the_chart_part():
    """TC-SDR-08 · 서랍 → 크게 보기 → 모달은 같은 차트 부품(stockchart.js) · Esc · 바깥 · 닫기 · 모달 CSS."""
    js = DRAWER.read_text(encoding="utf-8")
    css = (ROOT / "public" / "css" / "stockdrawer.css").read_text(encoding="utf-8")
    assert 'from "./stockchart.js"' in js and "mountDailyChart" in js
    assert "[data-hub-expand]" in js and "openModal(hub)" in js and "hubLast" in js and 'hubMode !== "drawer"' in js and "openModalFor" in js        # 서랍이 받은 응답을 다시 묻지 않고 쓴다 · 입구는 기본이 모달 직행
    assert "closeModal" in js and 'ev.key !== "Escape"' in js
    assert ".sd-modal" in css and ".sd-chartbox" in css and ".sd-period.on" in css


def test_every_stock_entry_opens_the_modal_directly():
    """TC-SDR-09 · 「종목 근거」 입구는 모두 서랍을 거치지 않고 바로 큰 모달(사용자 11-02) — 서랍이 필요한 입구만 `data-hub-mode="drawer"` · 팀 파일의 단추 줄은 그대로 · 모달에 서랍의 두 이동 단추가 옮겨 옴."""
    js = DRAWER.read_text(encoding="utf-8")
    quant = (ROOT / "public" / "js" / "quant.js").read_text(encoding="utf-8")
    assert 'btn.dataset.hubMode !== "drawer"' in js and "openModalFor(btn.dataset.hubOpen" in js
    assert 'data-hub-open="${escHtml(code)}"' in quant and "data-hub-mode" not in quant         # 카드 단추 줄은 건드리지 않는다
    for f in ("app.html", "js/signal-rank.js", "js/trade-status.js", "js/quant.js"):             # 어느 입구도 서랍을 명시하지 않는다
        assert 'data-hub-mode="drawer"' not in (ROOT / "public" / f).read_text(encoding="utf-8")


def test_modal_has_easy_reading_helpers(tmp_path):
    """TC-SDR-10 · 모달은 칸마다 「이 칸 읽는 법」 · 신호 근거마다 「쉬운 뜻 · 조심할 점 · 규칙 점수」 · 이동 단추 둘 · 정리 틀 — 서랍은 그대로(읽는 법 없음)."""
    out = _run(tmp_path, HUB, """
out.modal = sd.sdModalHtml(HUB, { marketLine: '시장 맥락 — 코스피 5,937.66(−1.24%)' });
out.drawer = sd.stockDrawerHtml(HUB);
out.foreign = sd.sdModalHtml({ ...HUB, symbol: 'AAPL' });
out.unknown = sd.sdSectionHtml('signal', { status: 'ok', label: 's', data: { signal: '매도', reasons: [{ key: 'new_rule', label: '일봉', text: '새 근거', points: -1 }], counter_reasons: [] } }, new Map(), { plain: true });
""")
    m = out["modal"]
    assert m.count('class="sd-howto"') == 7 and "이 칸 읽는 법" in m                                # 일곱 칸마다
    assert "쉬운 뜻" in m and "조심할 점" in m and "규칙 점수 −1" in m and "규칙 점수 +1" in m           # 근거(5일선 · MACD)마다
    assert "짧은 기간의 평균 가격이 더 긴 기간의 평균 가격보다 아래에" in m and "MACD 는 12일 평균과 26일 평균의 차이" in m   # key 로 찾은 쉬운 풀이
    assert "매도 쪽 근거로 셉니다" in m and "매수 쪽 근거로 셉니다" in m                              # 평가어(약해진 · 강한 · 반등할 수)가 아니라 규칙이 어느 쪽으로 세는지
    assert "약해진 모습" not in m and "반등할 수" not in m and "우호적" not in m
    assert m.count('class="sd-more"') == 2 and m.count('class="sd-more" open') == 2                   # 펼치기 층 — 「까닭」 · 「반대 까닭」 각 목록의 첫 줄만 열려 있다(같은 무게 · 이 시료는 각 한 줄)
    assert "이 설명이 말하지 않는 것" in m and "맞을 확률이 아닙니다" in m and "그 규칙들이 과거에 맞았는지 재지 않았습니다" in m
    assert "쉬워졌다고 더 확실해진 것은 아닙니다" in m and "그 신호가 앞으로 맞을지는 이 화면에서 알 수 없습니다" in m
    assert 'data-hub-go="paper-stock"' in m and 'data-hub-go="robo-rebalance"' in m                  # 서랍에 있던 두 단추가 모달로
    assert "시장 맥락 — 코스피 5,937.66(−1.24%)" in m and "data-hub-market" in m
    assert "data-hub-tpl" in m and "data-hub-copy" in m and "내가 정할 것" in m and "투자 권유가 아닙니다" in m
    assert "sd-howto" not in out["drawer"]                                                           # 서랍은 바꾸지 않는다
    assert 'data-hub-go="paper-stock"' not in out["foreign"]                                         # 해외 종목은 6자리 코드가 아니라 이동 단추 없음
    assert "쉬운 뜻" not in out["unknown"] and "새 근거" in out["unknown"]                              # 모르는 규칙 key 는 서버 글만


def test_plain_rules_match_server_rules_and_note_text(tmp_path):
    """TC-SDR-11 · 쉬운 풀이의 규칙 key 는 서버 규칙표와 같고(열한 가지) · 금지 낱말이 없고 · 시장 맥락 · 정리 틀 글은 이미 보인 값만 쓴다."""
    from app.services import signal_explain
    out = _run(tmp_path, HUB, """
import * as pl from "%s";
out.keys = Object.keys(pl.RULE_PLAIN);
out.howto = Object.keys(pl.SECTION_HOWTO);
out.texts = [...Object.values(pl.RULE_PLAIN).flatMap(p => [p.mean, p.care]), ...Object.values(pl.SECTION_HOWTO)];
out.move = pl.planIndexMove('코스피', [{ trade_date: '2026-10-28', close: 6012.44 }, { trade_date: '2026-10-29', close: 5937.66 }]);
out.none = [pl.planIndexMove('코스닥', [{ trade_date: '2026-10-29', close: 1 }]), pl.planIndexMove('코스닥', null)];
out.line = pl.planMarketLine([out.move], false);
out.fail = pl.planMarketLine([], true);
out.empty = pl.planMarketLine([], false);
out.note = pl.planNoteText(HUB, out.line);
""" % (JS / "stockplain.js").resolve().as_uri())
    assert sorted(out["keys"]) == sorted(r.key for r in signal_explain.RULES)                       # 규칙표와 같은 열한 가지
    assert out["howto"] == list(stock_hub.SECTIONS[1:]) or sorted(out["howto"]) == sorted(["price", "signal", "financials", "disclosures", "news", "schedule", "sector"])
    texts = [t.replace("횡보장", "") for t in out["texts"]]                                          # 「횡보장」 안의 「보장」 은 낱말이 다르다
    assert not [w for w in signal_explain.FORBIDDEN if any(w in t for t in texts)]               # 설명 기준 5.4.1 의 쓰지 않는 말(확률 · 추천 · 강력 …)
    assert abs(out["move"]["pct"] - (5937.66 / 6012.44 - 1) * 100) < 1e-9 and out["move"]["day"] == "2026-10-29"
    assert out["none"] == [None, None]
    assert out["line"] == "시장 맥락 — 코스피 5,937.66(−1.24%) · 10월 29일 종가 기준"
    assert out["fail"] == "시장 지표를 불러오지 못했습니다." and out["empty"] == "시장 지표 자료가 없습니다."
    n = out["note"]
    assert n.startswith("삼성전자(005930) · 기준일 10-29 종가 232,000원(−4.13%)") and "· 시장 맥락 — 코스피" in n
    assert "규칙 신호: 매도 쪽 · 보통 · 근거 1개(일봉 5일선이 20일선 아래) · 반대 근거 1개(일봉 MACD 가 신호선 위)" in n
    assert "재무: 그렇다 5 · 아니다 0 · 모름 2" in n and "최근 공시: 10-30 특수관계인으로부터주식의취득" in n and "확인할 일정: 11-27 삼성전자 배당금 지급(분기배당)" in n
    assert "목표가 1차 ______" in n and "손절가 ______" in n and "투자 권유가 아닙니다" in n        # 정하는 칸은 비워 둔다
    assert "틀렸다고 볼 조건 ________" in n and "적은 날 ______" in n and "본 것(사실) ________ / 왜 그게 이유인가 ________" in n   # 두 조사가 같은 방향인 칸
    assert "수급(외국인 · 기관): 앱이 모으지 않는 자료입니다" in n                                    # 수급은 지어내지 않고 직접 적게(D6 ⑥ 결정)
    assert "목표가 232" not in n and "손절가 2" not in n                                             # 앱이 목표가 · 손절가 값을 만들지 않는다
    out2 = _run(tmp_path, HUB, "import * as pl from \"%s\"; out.n = pl.planNoteText({ ...HUB, sections: { price: { status: 'error' } } }, '');" % (JS / "stockplain.js").resolve().as_uri())
    assert "기준일" not in out2["n"] and "내가 정할 것" in out2["n"]                                 # 칸이 없으면 값을 지어내지 않는다
