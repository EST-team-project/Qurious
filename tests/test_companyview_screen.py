"""TC-CV — 지표 대시보드 화면 판단(public/js/companyview.js · company.js · app.html) · 2026-10-30 · 할 일 ①-16

옛 화면은 야후 재무 요약을 그대로 그려 삼성전자가 EPS · BPS · PBR · 영업이익 N/A 에 PER 3.11 · ROE 30.79 처럼 우리 전자공시 값과 다른 숫자를 냈고
숫자마다 기준 기간 · 기준일이 없었다. 지금 약속(설계 결정 ① 안 A — 숫자 바로 밑에 한 줄):
1. 값 글 — 응답 값 그대로 · 단위 글만 · 근사면 「(근사)」 · 없으면 줄표 + 서버 까닭. (TC-CV-01)
2. 숫자 밑에 식 · 기준 기간 · 공시 접수일 · 종가 날짜 한 줄 · 근사는 한계 문장 한 줄 더 · 글은 이스케이프. (TC-CV-02)
3. 개요 카드 — 현재가(지연 시세 라벨) · 시가총액(종가 기준 · 보통주만) · 종가(지금 가격이 아님) · EPS. 자료가 없으면 줄표 + 까닭. (TC-CV-03)
4. 분기 실적 · 재무상태 표 — 서버가 준 값 그대로 · 기간 이름(연간 · 반기 3개월) · 없으면 줄표. (TC-CV-04)
5. 차트 — 마지막 날 기준 기간 자르기 · 글 요약(최고 · 최저 · 마지막 종가)과 「초 단위 실시간이 아니다」 한계. (TC-CV-05)
6. 요청 다섯 — 6자리가 아니면 요청을 보내지 않는다 · 현재가는 화면 심볼 그대로. (TC-CV-06)
7. 야후 · 「현재 주가」 낱말이 없다. (TC-CV-07)
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CV = ROOT / "public" / "js" / "companyview.js"
ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')

PER = {"key": "per", "label": "PER", "value": 35.1, "unit": "배", "sentence": "종가 232,000원은 …", "formula": "종가 ÷ 보고된 기본주당이익",
       "basis": "종가 2026-10-29 · 2025 사업보고서(연결) · 공시 접수 2026-03-10"}
PBR = {"key": "pbr", "label": "PBR", "value": 3.2, "unit": "배", "approx": True, "sentence": "우선주가 상장된 회사라 낮게 나올 수 있습니다.",
       "formula": "시가총액 ÷ 지배지분 자본", "basis": "종가 2026-10-29 · 2025 사업보고서(연결)"}
EPS = {"key": "eps", "label": "주당이익(EPS)", "value": 6605, "unit": "원", "sentence": "s", "formula": "보고된 값(계산하지 않음)", "basis": "2025 사업보고서(연결)"}
NOPER = {"key": "per", "label": "PER", "value": None, "unit": "배", "sentence": "적자라 계산하지 않았습니다.", "formula": "f", "basis": "b", "reason": "적자라 계산하지 않음"}
IND = {"name": "삼성전자", "price": {"close": 232000, "trade_date": "2026-10-29", "market_cap": 1356336637056000, "note": "2026-10-29 마지막 종가 · 지금 가격이 아닙니다"},
       "metrics": [EPS, PER, PBR]}
FIN = {"source": "전자공시(DART) 다중회사 주요계정(fnlttMultiAcnt)", "periods": [
    {"period_end": "2026-06-30", "report": "반기보고서", "known_at": "2026-08-14", "accounts": [
        {"statement": "IS", "name": "매출액", "amount": 171499470000000}, {"statement": "IS", "name": "영업이익", "amount": 89492412000000},
        {"statement": "IS", "name": "당기순이익(손실)", "amount": 71624461000000}, {"statement": "BS", "name": "자산총계", "amount": 759480516000000},
        {"statement": "BS", "name": "부채총계", "amount": 180170840000000}, {"statement": "BS", "name": "자본총계", "amount": 579309676000000}]},
    {"period_end": "2025-12-31", "report": "사업보고서", "known_at": "2026-03-10", "accounts": [
        {"statement": "IS", "name": "매출액", "amount": 333605938000000}]},
]}


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as cv from "{CV.resolve().as_uri()}";\n{ESC}\n'
                      f"const IND = {json.dumps(IND, ensure_ascii=False)}, FIN = {json.dumps(FIN, ensure_ascii=False)}, "
                      f"PER = {json.dumps(PER, ensure_ascii=False)}, PBR = {json.dumps(PBR, ensure_ascii=False)}, "
                      f"NOPER = {json.dumps(NOPER, ensure_ascii=False)};\nconst out = {{}};\n{body}\n"
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_value_text_and_basis_lines(tmp_path):
    """TC-CV-01 — 단위 글만 · 근사 · 줄표 · 까닭 · 식 · 기준 한 줄 · 근사는 한계 문장."""
    out = _run(tmp_path, """
      out.v = [cv.cvValueText(PER), cv.cvValueText(PBR), cv.cvValueText({value: 6605, unit: "원"}), cv.cvValueText({value: 10.4, unit: "%"}), cv.cvValueText(NOPER), cv.cvValueText(null)];
      out.l = [cv.cvBasisLines(PER), cv.cvBasisLines(PBR), cv.cvBasisLines(NOPER)];
      out.obj = cv.cvBasisLines({value: 31.1, unit: "%", formula: "부채총계 ÷ 자본총계 × 100", basis: {period_end: "2026-06-30", report: "반기보고서"}});
    """)
    assert out["obj"] == ["부채총계 ÷ 자본총계 × 100 · 2026-06-30 기준 반기보고서"]        # 건전성 지표의 기준은 {기간 · 보고서} 묶음으로 온다
    assert out["v"] == ["35.1배", "3.2배 (근사)", "6,605원", "10.4%", "—", "—"]
    assert out["l"][0] == ["종가 ÷ 보고된 기본주당이익 · 종가 2026-10-29 · 2025 사업보고서(연결) · 공시 접수 2026-03-10"]
    assert len(out["l"][1]) == 2 and "낮게 나올 수 있습니다" in out["l"][1][1]
    assert out["l"][2] == ["적자라 계산하지 않음"]


def test_metric_row_puts_basis_under_value_and_escapes(tmp_path):
    """TC-CV-02 — 줄 하나에 이름 · 값 · 그 밑 근거 · 서버 글은 이스케이프."""
    out = _run(tmp_path, """
      out.row = cv.cvMetricRow(PER, esc);
      out.evil = cv.cvMetricRow({key: "x", label: "<b>이름</b>", value: 1, unit: "배", formula: "<script>", basis: "b"}, esc);
    """)
    assert out["row"].index("35.1배") < out["row"].index("종가 ÷ 보고된 기본주당이익") and "공시 접수 2026-03-10" in out["row"]
    assert "<script>" not in out["evil"] and "&lt;script&gt;" in out["evil"] and "&lt;b&gt;" in out["evil"]


def test_overview_cards(tmp_path):
    """TC-CV-03 — 현재가(지연 시세 라벨) · 시가총액 · 종가 · EPS · 자료가 없으면 줄표 + 까닭."""
    out = _run(tmp_path, """
      out.full = cv.cvOverviewCards(IND, {price: 225000, change_pct: -3.02, label: "장 마감 · 지연 시세(약 20분) · 15:30 체결"}, esc);
      out.noquote = cv.cvOverviewCards(IND, null, esc);
      out.noprice = cv.cvOverviewCards({metrics: []}, null, esc);
    """)
    full = out["full"]
    assert "225,000원" in full and "-3.02%" in full and "지연 시세(약 20분)" in full
    assert "1356.34조 원" in full and "2026-10-29 종가 기준 · 보통주만(우선주 제외)" in full
    assert "232,000원" in full and "지금 가격이 아닙니다" in full and "6,605원" in full
    assert "지금 가격을 받지 못했습니다" in out["noquote"] and "232,000원" in out["noquote"]
    assert out["noprice"].count("—") >= 3 and "종가 자료가 없습니다" in out["noprice"]


def test_quarter_and_balance_tables(tmp_path):
    """TC-CV-04 — 기간 머리 이름(반기 3개월 · 연간) · 오래된 쪽이 왼쪽 · 값은 서버 값 그대로 · 없는 계정은 줄표."""
    out = _run(tmp_path, """
      out.q = cv.cvQuarterTable(FIN, esc); out.b = cv.cvBalanceTable(FIN, esc);
      out.empty = [cv.cvQuarterTable({periods: []}, esc), cv.cvBalanceTable(null, esc)];
    """)
    q = out["q"]
    assert q.index("2025-12-31") < q.index("2026-06-30") and "연간" in q and "반기(3개월)" in q
    assert "171.50조 원" in q and "333.61조 원" in q and "—" in q               # 사업보고서에 영업이익 없음 → 줄표
    assert "759.48조 원" in out["b"] and "180.17조 원" in out["b"] and "공시 접수 2026-08-14" in out["b"]
    assert all("재무제표 자료가 없습니다" in e for e in out["empty"])


def test_chart_slice_and_summary(tmp_path):
    """TC-CV-05 — 마지막 날 기준 기간 자르기 · 최고 · 최저 · 마지막 종가 글 · 실시간이 아니라는 한계."""
    out = _run(tmp_path, """
      const rows = [{trade_date: "2025-09-01", close: 100}, {trade_date: "2026-08-01", close: 300}, {trade_date: "2026-10-01", close: 200},
                    {trade_date: "2026-10-29", close: 232000 / 1000}, {trade_date: "2026-10-30", close: null}];
      out.m1 = cv.cvSlice(rows, "1m").length; out.m6 = cv.cvSlice(rows, "6m").length; out.y1 = cv.cvSlice(rows, "1y").length; out.none = cv.cvSlice([], "6m").length;
      out.sum = cv.cvChartSummary(cv.cvSlice(rows, "6m")); out.nosum = cv.cvChartSummary([]);
    """)
    assert (out["m1"], out["m6"], out["y1"], out["none"]) == (2, 3, 3, 0)         # 종가 null 줄은 뺀다 · 1년 = 2025-10-29 이후
    assert "최고 300원" in out["sum"] and "최저 200원" in out["sum"] and "마지막 종가 232원(2026-10-29)" in out["sum"]
    assert "초 단위 실시간 차트가 아니며" in out["sum"] and "지연 시세 약 20분" in out["sum"]
    assert out["nosum"] == "일봉 자료가 없습니다."


def test_load_sends_five_requests_only_for_six_digit_codes(tmp_path):
    """TC-CV-06 — 6자리 코드면 요청 다섯(현재가는 화면 심볼 그대로) · 아니면 보내지 않는다 · 하나가 실패해도 나머지는 온다."""
    out = _run(tmp_path, """
      const calls = [];
      const api = async url => { calls.push(url); if (url.includes("/risk/")) throw new Error("건전성 실패"); return {u: url}; };
      out.ok = await cv.cvLoad(api, "005930.KS"); out.calls = calls.slice();
      const calls2 = []; out.bad = await cv.cvLoad(async u => { calls2.push(u); return {}; }, "AAPL"); out.calls2 = calls2;
    """)
    assert out["calls"] == ["/api/data/indicators?symbol=005930", "/api/data/financials?symbol=005930", "/api/risk/company?symbol=005930",
                            "/api/quote/now?symbol=005930.KS", "/api/data/ohlcv?symbol=005930"]
    assert out["ok"]["code"] == "005930" and out["ok"]["ind"] and out["ok"]["health"] is None
    assert out["bad"]["unsupported"] is True and out["calls2"] == []


COLS = [
    {"code": "005930", "err": None, "ind": {"name": "삼성전자", "report": {"bsns_year": "2025", "report": "사업보고서", "fs": "CFS", "known_at": "2026-03-10"},
                                           "price": {"trade_date": "2026-10-29"}, "metrics": [PER, PBR, {"key": "roe", "value": 10.4, "unit": "%", "formula": "f", "basis": "b", "sentence": "s"}]}},
    {"code": "006400", "err": None, "ind": {"name": "삼성SDI", "report": {"bsns_year": "2025", "report": "사업보고서", "fs": "CFS", "known_at": "2026-03-10"},
                                           "price": {"trade_date": "2026-10-29"}, "metrics": [NOPER]}},
    {"code": "999999", "ind": None, "err": {"message": "999999 의 종가 · 재무 자료가 없습니다."}},
]


def test_compare_table_values_notes_and_failures(tmp_path):
    """TC-CV-08 — 종목마다 열 · 값은 서버 값 그대로 · 칸 title 에 식 · 기준 · 줄표는 아래에 까닭 · 근사는 한계 문장 · 한 종목 실패는 그 열만 줄표."""
    out = _run(tmp_path, f"""
      const COLS = {json.dumps(COLS, ensure_ascii=False)};
      out.html = cv.cvCompareTable(COLS, esc); out.empty = cv.cvCompareTable([], esc);
    """)
    html = out["html"]
    assert "삼성전자" in html and "삼성SDI" in html and "999999" in html
    assert "35.1배" in html and "3.2배 (근사)" in html and "10.4%" in html
    assert 'title="종가 ÷ 보고된 기본주당이익 · 종가 2026-10-29' in html
    assert "삼성SDI PER — 적자라 계산하지 않음" in html                                       # 줄표의 까닭
    assert "삼성전자 PBR — 근사: 우선주가 상장된 회사라 낮게 나올 수 있습니다." in html
    assert "삼성전자 — 2025 사업보고서(연결) · 공시 접수 2026-03-10 · 종가 2026-10-29" in html
    assert "999999 — 999999 의 종가 · 재무 자료가 없습니다." in html                          # 한 종목 실패 — 그 열만
    assert "투자 권유가 아닙니다" in html and "업종마다 보통 수준이 다르므로" in html
    assert "비교할 종목을 추가하세요" in out["empty"]


def test_compare_find_company_and_load(tmp_path):
    """TC-CV-09 — 종목 찾기(코드 · 이름 · 앞부분 · 포함 · 없음) · 종목마다 따로 요청하고 실패한 것만 오류로 담는다."""
    out = _run(tmp_path, """
      const L = [{code: "005930", name: "삼성전자"}, {code: "006400", name: "삼성SDI"}, {code: "000660", name: "SK하이닉스"}];
      out.f = ["005930", "삼성SDI", "삼성", "하이닉스", "없는회사", "", null].map(q => { const h = cv.cvFindCompany(L, q); return h ? h.code : null; });
      const calls = [];
      out.cols = await cv.cvCompareLoad(async u => { calls.push(u); if (u.endsWith("999999")) throw new Error("없음"); return {name: "x"}; }, ["005930", "999999"]);
      out.calls = calls; out.errMsg = out.cols[1].err.message;                                  // Error 는 JSON 으로 message 가 안 나간다
    """)
    assert out["f"] == ["005930", "006400", "005930", "000660", None, None, None]               # 「삼성」 은 앞부분이 맞는 첫 종목
    assert out["calls"] == ["/api/data/indicators?symbol=005930", "/api/data/indicators?symbol=999999"]
    assert out["cols"][0]["ind"] == {"name": "x"} and out["cols"][0]["err"] is None
    assert out["cols"][1]["ind"] is None and out["errMsg"] == "없음"


SECTORS = {"as_of": "2026-10-29", "universe": 351, "notice": "수집 대상 351곳만의 업종별 중앙값입니다 — 업종 전체 지수가 아닙니다.",
           "formula": {"per": "종목별 종가 ÷ 보고된 기본주당이익의 중앙값(흑자 종목만)", "pbr": "종목별 시가총액 ÷ 지배지분 자본의 중앙값(자본이 있는 종목만)"},
           "groups": [{"code": "20", "name": "화학 물질 및 화학제품 제조업; 의약품 제외", "section": {"code": "C", "name": "제조업"}, "n": 42, "thin": False,
                       "per": {"median": 21.6, "n": 30}, "pbr": {"median": 0.9, "n": 41}, "top": [{"code": "051910", "name": "LG화학"}]},
                      {"code": "99", "name": "작은 업종", "section": {"code": "", "name": ""}, "n": 2, "thin": True,
                       "per": {"median": None, "n": 0}, "pbr": {"median": 1.2, "n": 2}, "top": []}]}


def test_sector_cards_and_note(tmp_path):
    """TC-CV-10 — 업종 카드(중앙값 · 몇 곳 · 대표) · 종목이 적은 업종 표시 · 값이 없으면 줄표 · 아래 글(기준일 · 식 · 한계)."""
    out = _run(tmp_path, f"""
      const S = {json.dumps(SECTORS, ensure_ascii=False)};
      out.cards = cv.cvSectorCards(S, esc); out.note = cv.cvSectorNote(S, esc);
      out.none = [cv.cvSectorCards(null, esc), cv.cvSectorCards({{groups: []}}, esc), cv.cvSectorNote({{}}, esc)];
    """)
    c = out["cards"]
    assert "21.6배 (30곳)" in c and "0.9배 (41곳)" in c and "제조업 · 종목 42곳 · 대표 LG화학" in c
    assert c.count("적은 종목") == 1 and "—" in c and "1.2배 (2곳)" in c                      # 둘째 업종은 PER 값 없음 → 줄표
    assert "기준 2026-10-29 종가" in out["note"] and "흑자 종목만" in out["note"] and "업종 전체 지수가 아닙니다" in out["note"]
    assert "업종별 자료를 아직 받지 못했습니다" in out["none"][0] and out["none"][2] == ""


def test_no_yahoo_and_no_current_price_wording():
    """TC-CV-07 — 모듈에 야후 · 「현재 주가」 낱말이 없고 화면은 종가를 종가라 부른다."""
    src = CV.read_text(encoding="utf-8")
    assert "yahoo" not in src.lower() and "/api/stocks/" not in src
    code = src.split("*/", 1)[1]                                   # 머리 주석의 설명 문장은 화면에 나가지 않는다
    assert "현재 주가" not in code and "현재가" in code and "종가" in code
