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
    assert d.count("aria-pressed=") == 3 and 'data-hub-period="3m" aria-pressed="true"' in d and 'data-hub-period="1m" aria-pressed="false"' in d, "기간 칩도 눌림 상태를 aria-pressed 로 알린다"
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
    assert "이 설명이 말하지 않는 것" in m and "맞을 확률이 아닙니다" in m and "그 규칙들이 과거에 맞았는지 재지 않았습니다" not in m and "동전 던지기와 비슷했고" in m and "앞날을 맞히는 예측이 아니라" in m
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


def test_empty_code_entrance_is_hidden_and_ignored():
    """TC-SDR-12 · 시세 조회 전의 모의주문 입구는 숨겨져 있고, 코드가 빈 입구를 눌러도 열지 않는다(빈 코드로 부르면 422 — 2026-11-02 클릭 점검에서 찾음)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "public" / "app.html").read_text(encoding="utf-8")
    tag = re.search(r'<button[^>]*id="ps-hub-open"[^>]*>', html).group(0)
    assert re.search(r"\shidden[\s>]", tag), "조회 전에는 숨겨 둔다"
    js = (root / "public" / "js" / "stockdrawer.js").read_text(encoding="utf-8")
    assert 'if (!String(btn.dataset.hubOpen || "").trim()) return;' in js


def test_signal_hit_note_is_one_sentence_used_in_modal_and_copy_template():
    """TC-SDR-13 · 「예측력을 아직 재지 않았다」 대신 신장환 님 적중 대조 결과(5거래일 · 매수 48.9 ~ 50.1% · 매도 45.5%)를 한 문장으로 두 곳이 같이 쓴다
    (사용자 결정 2026-11-02 · 0.7 의 4번) — 숫자는 stockplain.js 한 곳, 앞날을 맞히는 예측이 아니라고 읽히게."""
    plain = (JS / "stockplain.js").read_text(encoding="utf-8")
    drawer = DRAWER.read_text(encoding="utf-8")
    assert plain.count("export const SIGNAL_HIT_NOTE") == 1
    for needle in ("48.9 ~ 50.1%", "45.5%", "5거래일", "동전 던지기와 비슷했고", "신뢰도가 높아도 적중률은 그대로였습니다", "앞날을 맞히는 예측이 아니라"):
        assert needle in plain, needle
    # S208(2026-11-06 · 종목 근거 피드백 ③) — 기준선(무조건 오른다고 찍은 적중률 51.3%, 결과.md)과 표본 한계를 같은 문장에 둔다
    for needle in ("기준선", "51.3%", "매수 쪽 적중률은 기준선보다 낮았습니다", "표본이 겉보기보다 적습니다"):
        assert needle in plain, needle
    # S209(2026-11-06 · 유효 표본 측정) — 줄(53,044)이 아니라 날 138개 단위로 다시 잰 95% 구간(날짜 묶음 부트스트랩: 매수 49.1% → 45.9 ~ 52.2%)을 넣는다.
    # 근거: docs/_local/유효표본-측정-2026-11-06/결과.md(gitignore · 같은 스캔을 다시 돌려 11-02 값과 일치 확인). 옛 「우연인지는 가리기 어렵습니다」 는 측정으로 대체했다.
    for needle in ("날 138개 단위로 다시 재면", "49.1%", "95% 구간은 약 46 ~ 52%", "기준선 51.3% 를 포함해", "우연과 구분하기 어렵습니다"):
        assert needle in plain, needle
    assert "우연인지는 가리기 어렵습니다" not in plain
    assert "${SIGNAL_HIT_NOTE}" in plain and "${esc(SIGNAL_HIT_NOTE)}" in drawer          # 정리 틀(복사)과 모달 하단이 같은 문장
    for src in (plain, drawer):
        assert "과거에 맞았는지 재지 않았습니다" not in src
    assert not re.search(r"(BUY|SELL)", plain)                                       # 규칙 표시이지 매매 권유가 아니다


def _hub_with_signal(**data):
    import copy
    hub = copy.deepcopy(HUB)
    hub["sections"]["signal"]["data"].update(data)
    return hub


def test_modal_signal_shows_all_reasons_counts_and_signal_close_slot(tmp_path):
    """TC-SDR-14 · 신호 순위 줄이 같은 모달을 여므로(사용자 11-02 입구 통일) 모달 신호 칸이 순위 서랍이 보이던 것을 이어받는다 —
    ① 근거를 자르지 않고 전부(서버가 전부 준다) · ② 「근거 n개 (매수 쪽 · 중립 · 매도 쪽)」 한 줄(못 세면 0개가 아니라 서버 까닭) ·
    ③ 신호 기준 종가 자리(그 신호 기록의 기준일 · 마지막 종가로 대신하지 않는다). 서랍(작은 화면)은 그대로 3줄."""
    reasons = [{"key": f"r{i}", "timeframe": "1d", "label": "일봉", "text": f"근거 문장 {i}", "points": 1} for i in range(1, 6)]
    counters = [{"key": f"c{i}", "timeframe": "1w", "label": "주봉", "text": f"반대 문장 {i}", "points": -1} for i in range(1, 4)]
    hub = _hub_with_signal(reasons=reasons, counter_reasons=counters, counts={"buy": 3, "neutral": 1, "sell": 1})
    out = _run(tmp_path, hub, """
out.modal = sd.sdModalHtml(HUB);
out.drawer = sd.stockDrawerHtml(HUB);
out.odd = sd.sdModalHtml({ ...HUB, sections: { ...HUB.sections, signal: { ...HUB.sections.signal,
  data: { ...HUB.sections.signal.data, counts: null, counts_note: '낯선 근거 문장' } } } });
out.close = [
  sd.sdSignalCloseView({ basis: 'raw', rows: [{ trade_date: '2026-10-29', close: 72300 }] }, '2026-10-29'),
  sd.sdSignalCloseView({ basis: 'raw', rows: [{ trade_date: '2026-10-28', close: 70000 }] }, '2026-10-29'),
  sd.sdSignalCloseView(null, '2026-10-29', '서버에 연결할 수 없습니다.'),
];
""")
    m = out["modal"]
    sig = m[m.index('data-hub-sec="signal"'):m.index('data-hub-sec="financials"')]
    assert all(f"근거 문장 {i}" in sig for i in range(1, 6)) and all(f"반대 문장 {i}" in sig for i in range(1, 4))     # ① 전부
    assert "근거 5개 (매수 쪽 3 · 중립 1 · 매도 쪽 1)" in sig                                                         # ② 순위 표와 같은 글
    assert 'data-hub-sigclose="2026-10-29"' in sig                                                                  # ③ 그 신호 기록의 기준일
    dr = out["drawer"]
    assert "근거 문장 3" in dr and "근거 문장 4" not in dr and "data-hub-sigclose" not in dr and "근거 5개" not in dr   # 서랍은 그대로
    assert "근거 개수를 셀 수 없습니다" in out["odd"] and "낯선 근거 문장" in out["odd"] and "근거 0개" not in out["odd"]
    ok, other_day, failed = out["close"]
    assert ok["ok"] is True and ok["text"] == "신호 기준 종가(10-29) 72,300원"
    assert other_day["ok"] is False and other_day["text"] == "신호 기준 종가(10-29) 확인 불가"                          # 다른 날 종가로 대신하지 않는다
    assert failed["ok"] is False and "서버에 연결할 수 없습니다." in failed["note"]


def test_modal_signal_groups_by_timeframe_and_shows_observed_and_contribution(tmp_path):
    """TC-SDR-16 · 모달 신호 칸 글 다듬기(사용자 11-02 「따닥따닥 · XAI 답지 않다」) — ① 근거를 주기(일봉 · 주봉)별 묶음으로 ② 줄마다 서버가 준
    「본 값」 · 「종합 점수 몫」 을 보이고 ③ 옛 응답(두 칸 없음)이면 그 줄도 설명 줄도 만들지 않고 ④ 서랍(작은 화면)은 그대로다."""
    reasons = [
        {"key": "ma_up", "timeframe": "1d", "label": "일봉", "text": "5일선이 20일선 위", "points": 1, "observed": "5일선 15,700 · 20일선 15,416", "contribution": 0.5},
        {"key": "macd_up", "timeframe": "1d", "label": "일봉", "text": "MACD 가 신호선 위", "points": 1, "observed": None, "contribution": 0.5},
        {"key": "ma_up", "timeframe": "1w", "label": "주봉", "text": "5주선이 20주선 위", "points": 1, "observed": "5주선 15,386 · 20주선 15,292", "contribution": 0.3},
    ]
    counters = [{"key": "rsi_high", "timeframe": "1d", "label": "일봉", "text": "RSI 가 높음", "points": -1, "observed": "RSI 71.0", "contribution": -0.25}]
    old = [{"key": "ma_up", "timeframe": "1d", "label": "일봉", "text": "옛 줄", "points": 1}]
    hub = _hub_with_signal(reasons=reasons, counter_reasons=counters, counts={"buy": 3, "neutral": 0, "sell": 1})
    out = _run(tmp_path, hub, """
out.modal = sd.sdModalHtml(HUB);
out.drawer = sd.stockDrawerHtml(HUB);
out.old = sd.sdModalHtml({ ...HUB, sections: { ...HUB.sections, signal: { ...HUB.sections.signal,
  data: { ...HUB.sections.signal.data, reasons: %s, counter_reasons: [] } } } });
""" % json.dumps(old, ensure_ascii=False))
    m = out["modal"]
    sig = m[m.index('data-hub-sec="signal"'):m.index('data-hub-sec="financials"')]
    assert sig.count('class="sd-tfgroup"') == 3                                                                      # 까닭 둘(일봉 · 주봉) + 반대 까닭 하나(일봉)
    assert '<p class="sd-tfhead">일봉 <small>2개</small></p>' in sig and '<p class="sd-tfhead">주봉 <small>1개</small></p>' in sig
    assert "<b>5일선이 20일선 위</b>" in sig and "<b>일봉 · 5일선이 20일선 위</b>" not in sig                       # 줄마다 「일봉 · 」 을 되풀이하지 않는다
    assert "본 값 5일선 15,700 · 20일선 15,416 · 종합 점수 몫 +0.50" in sig and "종합 점수 몫 −0.25" in sig         # 서버 값 그대로 · 소수 둘째 자리
    assert "본 값 RSI 71.0" in sig and sig.count('class="sd-obs"') == 4                                              # observed 없는 줄(MACD)은 몫만
    assert "더하면 종합 점수" in sig                                                                                 # 「몫」 이 무엇인지 한 줄
    assert "규칙 점수 +1" in sig and "쉬운 뜻" in sig                                                                  # TC-SDR-10 이 보는 것은 그대로
    o = out["old"]
    assert "sd-obs" not in o[o.index('data-hub-sec="signal"'):o.index('data-hub-sec="financials"')] and "더하면 종합 점수" not in o   # 옛 응답이면 줄도 설명도 없음
    assert "sd-tfgroup" not in out["drawer"] and "sd-obs" not in out["drawer"]                                      # 서랍은 바꾸지 않는다


def test_modal_fills_signal_close_from_the_signal_day():
    """TC-SDR-15 · 모달이 열린 뒤 신호 기준 종가 자리를 채우는 길 — 그 신호 기록의 기준일 일봉만 부른다(`basis=raw` · 마지막 종가를 쓰지 않는다 ·
    오준영 님 #373 3번) · 늦게 온 응답이 다른 종목 모달을 덮지 않게 순번(seq)으로 막는다."""
    js = DRAWER.read_text(encoding="utf-8")
    assert 'from "./signal-rank.js"' in js and "fillSignalClose" in js and "data-hub-sigclose" in js
    assert "/api/data/ohlcv?symbol=" in js and "&basis=raw" in js and "from=${" in js
    assert "seq !== modalSeq" in js



def test_modal_has_external_chart_link_for_domestic_digit_codes_only(tmp_path):
    """TC-SDR-17 · 종목 근거 모달의 「외부 차트에서 열기 ↗」(2026-11-03) — 숫자 6자리 국내 코드만 새 탭 링크(rel noopener noreferrer) ·
    해외 · ETF(영숫자) 코드는 링크를 만들지 않는다 · 상표 이름은 작은 출처 줄에만(링크 글자에는 쓰지 않는다 · NOTICE.md)."""
    out = _run(tmp_path, HUB, """
out.modal = sd.sdModalHtml(HUB);
out.etf = sd.sdModalHtml({ ...HUB, symbol: '0000D0' });
out.foreign = sd.sdModalHtml({ ...HUB, symbol: 'AAPL' });
out.urls = [sd.hubExtChartUrl('005930'), sd.hubExtChartUrl('005930.KS'), sd.hubExtChartUrl('035720.KQ'), sd.hubExtChartUrl('0000D0'), sd.hubExtChartUrl('AAPL'), sd.hubExtChartUrl('')];
""")
    m = out["modal"]
    assert 'href="https://www.tradingview.com/symbols/KRX-005930/"' in m and 'target="_blank" rel="noopener noreferrer"' in m and "외부 차트에서 열기 ↗" in m
    assert "외부 차트 링크는 TradingView 로 연결됩니다" in m and "그쪽 정책을 따릅니다" in m
    assert ">TradingView" not in m.replace("외부 차트 링크는 TradingView", "")                       # 링크 글자 · 단추 이름에는 상표를 쓰지 않는다
    assert "data-hub-extchart" not in out["etf"] and "data-hub-extchart" not in out["foreign"]
    assert out["urls"] == ["https://www.tradingview.com/symbols/KRX-005930/", "https://www.tradingview.com/symbols/KRX-005930/",
                           "https://www.tradingview.com/symbols/KRX-035720/", "", "", ""]


# ── 신호 칸 기록 시점 · 날짜 고르기(S195 · 2026-11-03 · 날짜별 근거 안 A) ─────────────────────────────

_REC = {"computed_at": "2026-11-03 12:59", "record_kind": "regular", "lag_days": 0, "expected_on": "2026-11-03", "record_label": "정기 기록",
        "record_tip": "", "record_note": "11-02 종가 기준입니다. 다음 거래일(11-03) 12:59 에 계산해 기록했습니다.",
        "requested_on": None, "picked": False, "max_on": "2026-11-03", "latest_as_of": "2026-10-29", "prev_day": "2026-10-28", "next_day": None,
        "fell_back": False}


def test_modal_signal_head_and_record_line_show_the_calculation_time(tmp_path):
    """TC-SDR-18 · 모달 신호 칸 머리 「10-29 기준 · 11-03 12:59 계산」 + 정기 기록 한 줄(서버 글 그대로) · 옛 응답(새 칸 없음)이면 머리 · 줄 · 고르기가 지금까지와 같다 ·
    서랍(작은 화면)은 바꾸지 않는다."""
    hub = _hub_with_signal(**_REC)
    out = _run(tmp_path, hub, """
out.modal = sd.sdModalHtml(HUB);
out.drawer = sd.stockDrawerHtml(HUB);
out.old = sd.sdModalHtml({ ...HUB, sections: { ...HUB.sections, signal: { ...HUB.sections.signal, data: { ...HUB.sections.signal.data,
  computed_at: undefined, record_kind: undefined, record_note: undefined, max_on: undefined } } } });
out.head = [sd.sdSignalHeadText(HUB.sections.signal), sd.sdSignalHeadText({ as_of: '2026-10-29', data: {} }), sd.sdSignalHeadText({ as_of: null, data: {} }), sd.sdSignalHeadText(null)];
out.stamp = [sd.sdStamp('2026-11-03 12:59'), sd.sdStamp('2026-11-03T12:59:00+09:00'), sd.sdStamp(''), sd.sdStamp(null)];
""")
    m = out["modal"]
    sig = m[m.index('data-hub-sec="signal"'):m.index('data-hub-sec="financials"')]
    assert '<span class="sd-asof">10-29 기준 · 11-03 12:59 계산</span>' in sig and "10월 29일 기준" not in sig
    assert 'data-hub-record="regular"' in sig and "다음 거래일(11-03) 12:59 에 계산해 기록했습니다." in _text(sig)
    assert "sd-chip--late" not in sig and "늦게 계산" not in sig                                      # 정기 기록에는 칩이 없다
    o = out["old"]
    old_sig = o[o.index('data-hub-sec="signal"'):o.index('data-hub-sec="financials"')]
    assert "10월 29일 기준" in old_sig and "data-hub-record" not in old_sig and "data-hub-sigpick" not in old_sig
    assert "10월 29일 기준" in out["drawer"] and "data-hub-record" not in out["drawer"] and "data-hub-sigpick" not in out["drawer"]
    assert out["head"] == ["10-29 기준 · 11-03 12:59 계산", "10-29 기준", "", ""]
    assert out["stamp"] == ["11-03 12:59", "", "", ""]


def test_modal_signal_late_chip_and_collapsible_explanation(tmp_path):
    """TC-SDR-19 · 늦게 계산된 기록 — 칩 「늦게 계산」 + 계산 시각 + 접이식 쉬운 말 설명(서버 글 그대로 · 「소급」 단정 없음) · 칩 툴팁 · 글은 이스케이프 ·
    계산 시각을 모르는 옛 줄은 지어내지 않고 서버 글만."""
    late = {**_REC, "computed_at": "2026-11-05 09:20", "record_kind": "late", "lag_days": 2, "record_label": "늦게 계산",
            "record_tip": "그날 낮에 기록된 값이 아니라 나중에 계산한 값입니다.",
            "record_note": "10-29 종가 기준이지만 11-05 09:20 에 늦게 계산한 값입니다. <script>x</script> 같은 날을 다시 계산한 기록일 수 있습니다."}
    unknown = {**_REC, "computed_at": None, "record_kind": "unknown", "lag_days": None, "record_label": "계산 시각 모름",
               "record_note": "10-29 종가 기준입니다. 이 줄은 계산한 시각이 남아 있지 않아 언제 계산했는지 알 수 없습니다."}
    out = _run(tmp_path, _hub_with_signal(**late), """
out.late = sd.sdModalHtml(HUB);
const mk = data => ({ ...HUB, sections: { ...HUB.sections, signal: { ...HUB.sections.signal, data: { ...HUB.sections.signal.data, ...data } } } });
out.unknown = sd.sdModalHtml(mk(%s));
out.mark = [sd.sdChartSignal(HUB), sd.sdChartSignal(mk(%s)), sd.sdChartSignal({ sections: { signal: { status: 'empty' } } })];
""" % (json.dumps(unknown, ensure_ascii=False), json.dumps({"computed_at": "2026-11-03 12:59", "record_kind": "regular"})))
    m = out["late"]
    sig = m[m.index('data-hub-sec="signal"'):m.index('data-hub-sec="financials"')]
    assert '<span class="sd-chip sd-chip--late" title="그날 낮에 기록된 값이 아니라 나중에 계산한 값입니다.">늦게 계산</span>' in sig
    assert "11-05 09:20 에 계산" in _text(sig) and '<details class="sd-more"><summary>늦게 계산이란?</summary>' in sig
    assert "<script>x</script>" not in sig and "&lt;script&gt;x&lt;/script&gt;" in sig                  # 서버 글도 이스케이프
    assert '<span class="sd-asof">10-29 기준 · 11-05 09:20 계산</span>' in sig
    u = out["unknown"]
    usig = u[u.index('data-hub-sec="signal"'):u.index('data-hub-sec="financials"')]
    assert 'data-hub-record="unknown"' in usig and "알 수 없습니다" in usig and "sd-chip--late" not in usig
    assert "10월 29일 기준" in usig                                                                  # 계산 시각이 없으면 머리는 기준일만
    late_mark, regular_mark, empty_mark = out["mark"]
    # symbol 은 어느 종목의 기록인지 — 공용 차트가 다른 종목 칸에 표식을 찍지 않게 쓴다
    assert late_mark == {"asOf": "2026-10-29", "side": "매도", "symbol": "005930", "computedAt": "2026-11-05 09:20", "late": True}
    assert regular_mark == {"asOf": "2026-10-29", "side": "매도", "symbol": "005930", "computedAt": "2026-11-03 12:59", "late": False} and empty_mark is None


def test_modal_signal_date_picker_uses_server_trading_days(tmp_path):
    """TC-SDR-20 · 날짜 고르기 — 날짜 입력(오늘까지) + 앞/다음 거래일 단추는 서버가 거래일만 건너뛰어 준 날을 그대로 쓰고(없으면 누를 수 없음) · 고른 뒤에만 「가장 최근」 ·
    고른 날 줄이 없으면 안내문 · 고른 날 이전에 기록이 없어 빈 칸이어도 고르기가 남는다 · 옛 응답이면 고르기 없음 · 주소는 signal_on 만 더한다."""
    picked = {**_REC, "requested_on": "2026-10-27", "picked": True, "fell_back": True, "prev_day": "2026-10-23", "next_day": "2026-10-29",
              "fell_back_note": "10-27 은 신호 기록이 없어 그 앞 가장 가까운 날(10-26)의 기록을 보여 드립니다."}
    empty_hub = {**HUB, "sections": {**HUB["sections"], "signal": {"key": "signal", "label": "다중 주기 신호", "status": "empty", "as_of": None, "source": "", "view": "robo-patterns",
        "reason": "고른 날(10-01) 이전에는 이 종목의 신호 기록이 없습니다 — 다른 날짜를 골라 보세요.", "data": {
            "requested_on": "2026-10-01", "picked": True, "max_on": "2026-11-03", "latest_as_of": "2026-10-29", "prev_day": None, "next_day": "2026-10-02"}}}}
    out = _run(tmp_path, _hub_with_signal(**_REC), """
const mk = data => ({ ...HUB, sections: { ...HUB.sections, signal: { ...HUB.sections.signal, data: { ...HUB.sections.signal.data, ...data } } } });
out.latest = sd.sdModalHtml(HUB);
out.picked = sd.sdModalHtml(mk(%s));
out.empty = sd.sdModalHtml(%s);
out.drawerEmpty = sd.stockDrawerHtml(%s);
out.paths = [sd.hubSignalPath('005930', '2026-10-27'), sd.hubSignalPath('005930.KS', ''), sd.hubSignalPath('005930', 'latest'), sd.hubSignalPath('005930', '2026-10-27; drop')];
out.fail = [sd.sdSignalFailText({ status: 422, message: '미래 날짜' }), sd.sdSignalFailText({ status: 401, message: 'x' }), sd.sdSignalFailText(new Error('연결 끊김')), sd.sdSignalFailText(null)];
""" % (json.dumps(picked, ensure_ascii=False), json.dumps(empty_hub, ensure_ascii=False), json.dumps(empty_hub, ensure_ascii=False)))
    def part(html):
        return html[html.index('data-hub-sec="signal"'):html.index('data-hub-sec="financials"')]
    latest = part(out["latest"])
    assert 'type="date"' in latest and 'value="2026-10-29"' in latest and 'max="2026-11-03"' in latest                       # 입력 칸 값 = 지금 보이는 기록의 기준일
    assert 'data-hub-sigstep="2026-10-28">◀ 앞 거래일</button>' in latest
    assert '<button type="button" class="sd-pick-b" disabled>다음 거래일 ▶</button>' in latest                               # 가장 최근이라 다음은 눌리지 않는다
    assert "가장 최근</button>" not in latest and "data-hub-fellback" not in latest
    pk = part(out["picked"])
    assert 'value="2026-10-27"' in pk and 'data-hub-sigstep="2026-10-23">◀' in pk and 'data-hub-sigstep="2026-10-29">다음 거래일 ▶' in pk
    assert 'data-hub-sigstep="latest">가장 최근</button>' in pk
    assert "10-27 은 신호 기록이 없어 그 앞 가장 가까운 날(10-26)의 기록을 보여 드립니다." in _text(pk) and "data-hub-fellback" in pk
    em = part(out["empty"])
    assert 'sd-sec--empty" data-hub-sec="signal"' in out["empty"] and "고른 날(10-01) 이전에는 이 종목의 신호 기록이 없습니다" in _text(em)
    assert 'value="2026-10-01"' in em and 'data-hub-sigstep="2026-10-02">다음 거래일 ▶' in em and "disabled>◀ 앞 거래일" in em     # 막다른 길이 아니다
    assert "data-hub-sigpick" not in out["drawerEmpty"]                                                                       # 서랍은 그대로
    assert out["paths"] == ["/api/stock-hub?symbol=005930&sections=signal&signal_on=2026-10-27", "/api/stock-hub?symbol=005930.KS&sections=signal",
                            "/api/stock-hub?symbol=005930&sections=signal", "/api/stock-hub?symbol=005930&sections=signal"]
    assert out["fail"][0] == "미래 날짜" and "로그인" in out["fail"][1] and "연결 끊김" in out["fail"][2] and "불러오지 못했습니다" in out["fail"][3]


def test_modal_wires_the_signal_day_picker_and_chart_marker():
    """TC-SDR-21 · 모달이 날짜 고르기를 잇는 길 — 입력 change · 단추 click 을 받아 허브를 신호 칸만 다시 읽고(새 계산 없음) 그 칸 · 차트 신호 표식 · 신호 기준 종가를
    같이 바꾼다. 읽지 못하면 칸을 그대로 두고 까닭만 · 늦게 온 응답은 순번으로 막고 · 서랍에는 걸지 않는다 · 금지어 없음."""
    from app.services import signal_explain
    js = DRAWER.read_text(encoding="utf-8")
    assert "[data-hub-sigdate]" in js and "[data-hub-sigstep]" in js and 'addEventListener("change"' in js and "pickSignal(modal," in js
    assert "hubSignalPath(symbol," in js and "modalChart?.setSignal?.(sdChartSignal(next))" in js and "fillSignalClose(m, { symbol }, modalAt)" in js
    assert "mine !== sigSeq || modalAt !== modalSeq" in js and "sdSignalFailText(err)" in js
    assert "host.addEventListener" in js and "pickSignal(host" not in js and "pickSignal(drawer" not in js
    added = js[js.index("export function sdStamp"):js.index("/** 모달 안 신호 칸 — 서버 한 줄 요약")] + js[js.index("async function pickSignal"):js.index("function openModal(hub)")]
    code = re.sub(r"/\*.*?\*/", "", added, flags=re.S)                     # 이번에 더한 화면 글만 본다(앞서 있던 글은 다른 시험이 본다)
    code = "\n".join(re.sub(r"\s//.*$", "", line) for line in code.splitlines())
    for word in signal_explain.FORBIDDEN:
        assert word not in code, f"화면 글에 금지어 「{word}」"
    css =(DRAWER.parent.parent / "css" / "stockdrawer.css").read_text(encoding="utf-8")
    for cls in ("sd-pick", "sd-pick-l", "sd-pick-in", "sd-pick-b", "sd-rec", "sd-chip--late"):
        assert f".{cls}" in css, cls


def test_modal_now_button_is_press_only_and_shows_gap_to_last_close(tmp_path):
    """TC-SDR-22 · 종목 근거 모달 「지금 값 보기」(S208 · 2026-11-06 · 사용자 「현재 주가와 괴리」 피드백) —
    국내 숫자 6자리 코드에만 단추 · 누를 때만 /api/quote/now 를 한 번 부른다(열 때 자동 호출 없음) ·
    지금 값에는 출처 딱지, 수정주가 종가와 다를 때만 차이 %, 종가를 그대로 돌려받으면 차이를 지어내지 않고, 실패하면 종가 그대로라고 말한다."""
    out = _run(tmp_path, HUB, """
out.modal = sd.sdModalHtml(HUB);
out.etf = sd.sdModalHtml({ ...HUB, symbol: '0000D0' });
out.foreign = sd.sdModalHtml({ ...HUB, symbol: 'AAPL' });
out.path = sd.sdNowPath('005930.KS');
out.syms = [sd.sdNowSymbol(HUB), sd.sdNowSymbol({ ...HUB, market: 'KOSDAQ' }), sd.sdNowSymbol({ ...HUB, symbol: '035720.KQ', market: 'KOSPI' }),
            sd.sdNowSymbol({ ...HUB, market: '' , sections: {} }), sd.sdNowSymbol({ ...HUB, symbol: '0000D0' }), sd.sdNowSymbol({ ...HUB, market: 'ETF' }), sd.sdNowSymbol(null)];
const ref = { price: 232000, asOf: '2026-10-29' };
out.live = sd.sdNowView({ price: 235000, source: 'kis_user', market_state: 'closed', as_of: '2026-10-30 15:40', label: '증권사 조회' }, ref);
out.delay = sd.sdNowView({ price: 229000, source: 'delayed', market_state: 'open', as_of: '2026-10-30 10:20' }, ref);
out.close = sd.sdNowView({ price: 232000, source: 'collector', as_of: '2026-10-29' }, ref);
out.noref = sd.sdNowView({ price: 235000, source: 'kis_user', market_state: 'closed' }, null);
out.fail = sd.sdNowView({ price: null, source: null, fallback: ['증권사 키 없음', '지연 시세 없음'], label: '지금 가격을 받지 못했습니다' }, ref);
out.none = sd.sdNowView(null, ref);
""")
    m = out["modal"]
    assert "data-hub-now" in m and "지금 값 보기" in m and "누를 때만 불러옵니다" in m and "지금 시세가 아닙니다" in m
    assert "data-hub-now" not in out["etf"] and "data-hub-now" not in out["foreign"]
    assert out["path"] == "/api/quote/now?symbol=005930.KS"
    # 서버는 6자리만 받으면 수집 DB 를 못 찾는다(실제 화면 확인) — 시장 꼬리를 붙이되 시장을 모르면 짐작하지 않고 비운다
    assert out["syms"] == ["005930.KS", "005930.KQ", "035720.KQ", "", "", "", ""]
    assert "증권사 조회 · 장 마감" in out["live"]["text"] and "232,000원보다 +1.29%" in out["live"]["text"] and "(10월 29일)" in out["live"]["text"]
    assert "수정주가" in out["live"]["note"]
    assert "지연 시세" in out["delay"]["text"] and "−1.29%" in out["delay"]["text"]
    assert "%" not in out["close"]["text"] and "같은 종류" in out["close"]["note"]                # 종가를 그대로 돌려받으면 차이를 지어내지 않는다
    assert "%" not in out["noref"]["text"] and "차이는 적지 않습니다" in out["noref"]["note"]
    for k in ("fail", "none"):
        assert out[k]["ok"] is False and "지금 값을 받지 못했습니다" in out[k]["text"] and "마지막 거래일 종가 그대로" in out[k]["note"]
    assert "증권사 키 없음 · 지연 시세 없음" in out["fail"]["note"]
    js = DRAWER.read_text(encoding="utf-8")
    assert "showNow(modal, nowBtn)" in js and "deps.api(sdNowPath(sym))" in js and "sdNowSymbol(hub)" in js and "seq !== modalSeq || m.hidden" in js
    open_fn = js[js.index("function openModal(hub)"):js.index("/** 서랍을 거치지 않고 바로 모달")]
    assert "quote/now" not in open_fn and "showNow" not in open_fn                              # 모달을 열 때 자동으로 부르지 않는다
