"""TC-CWS — 지표 대시보드 작업 공간(public/js/company-workspace.js · css/company-workspace.css · app.html) · 2026-11-04 · D10

강사님 lumina-invest 의 「지표 대시보드 작업 공간」(구역 이동 단추 · 따라오는 기업 스냅샷 · 차트 4장)을 우리 수집 값으로 옮겼다.
강사님 것은 Yahoo 모양 데이터(d.quarters / d.revenue …)를 그렸지만 우리는 서버가 준 응답을 재배열만 해서 그린다.

약속
1. 분기 막대는 1분기 · 반기 · 3분기 보고서의 3개월 값만 — 사업보고서(12개월 값)는 같은 축에 두지 않고, 4분기 단독 값을 만들어 끼우지 않는다. (TC-CWS-01)
2. 차트 series 의 숫자는 서버가 준 숫자 그대로다(합 · 차 · 비율 · 환산 없음) — 입력 값의 부분집합임을 시험한다. 없는 값은 null 이고 0 이 아니다. (TC-CWS-02)
3. 도넛은 서버의 부채총계 · 자본총계, 가운데는 서버의 자산총계(더하지 않는다). 자본이 0 이하이거나 없으면 그리지 않고 까닭을 말한다. (TC-CWS-03)
4. 수익성 막대는 서버가 계산한 ROE · 영업이익률만(ROA · 순이익률은 서버가 주지 않아 만들지 않는다). (TC-CWS-04)
5. 차트 옵션 — 조각 비율 글자 없음 · 값 글은 formatter 에서만 조 · 억으로 바꾼다. (TC-CWS-05)
6. 기업 스냅샷 — 줄마다 값 + 기준일 · 출처, 없으면 줄표 + 까닭, 서버 글은 이스케이프, 판단 낱말 없음. (TC-CWS-06)
7. 출처 · 기준일 줄과 빈 칸 까닭. (TC-CWS-07)
8. companyview.js 의 cvSubscribe — cvLoad 의 시작 · 끝(지원하지 않는 종목 포함)을 알리고 구독자 오류가 본 화면을 막지 않는다. (TC-CWS-08)
9. app.html — 구역 이동 단추가 가리키는 칸이 있고, 기존 칸 id 는 그대로, 새 파일이 연결돼 있다. (TC-CWS-09)
10. 낱말 · 원천 — 투자 권유 낱말 · 야후 · 새 API 호출이 없고, company.js 가 채우는 co-* 칸에 쓰지 않는다. (TC-CWS-10)
11. CSS — 좁은 화면 규칙 · 스냅샷이 따라오는 sticky · 가로 넘침 방지. (TC-CWS-11)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js" / "company-workspace.js"
CV = ROOT / "public" / "js" / "companyview.js"
CSS = ROOT / "public" / "css" / "company-workspace.css"
APP = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
BANNED = ("추천", "최적", "유망", "베스트", "안전한", "매수", "매도", "사세요", "파세요", "유리합니다", "확실", "보장",
          "우수", "적기", "저평가", "고평가", "양호", "위험 신호", "사야", "팔아야")
ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')


def _period(end, report, known, key, accounts=None):
    return {"period_end": end, "report": report, "known_at": known, "key": key, "accounts": accounts or []}


def _key(rev, op, net, assets, liab, eq):
    return {"revenue": rev, "operating_income": op, "net_income": net, "assets": assets, "liabilities": liab, "equity": eq}


# 실제 응답 모양(삼성전자 005930 · 2026-11-04 read_financials 결과를 줄인 것) — 새 것부터. 반기보고서 amount 는 그 3개월 값이다.
SAMSUNG = {"source": "전자공시(DART) 다중회사 주요계정(fnlttMultiAcnt)", "periods": [
    _period("2026-06-30", "반기보고서", "2026-08-14", _key(171499470000000, 89492412000000, 71624461000000, 759480516000000, 180170840000000, 579309676000000)),
    _period("2026-03-31", "1분기보고서", "2026-05-15", _key(133873444000000, 57232797000000, 47225272000000, 633339604000000, 146703628000000, 486635976000000)),
    _period("2025-12-31", "사업보고서", "2026-03-10", _key(333605938000000, 43601051000000, 45206805000000, 566942110000000, 130621773000000, 436320337000000)),
    _period("2025-09-30", "3분기보고서", "2025-11-14", _key(86061747000000, 12166062000000, 12225747000000, 523659586000000, 110158092000000, 413501494000000)),
    _period("2025-06-30", "반기보고서", "2025-08-14", _key(74566317000000, 4676057000000, 5116435000000, 504875185000000, 105313218000000, 399561967000000)),
    _period("2025-03-31", "1분기보고서", "2025-05-15", _key(79140503000000, 6685272000000, 8222878000000, 516376748000000, 109762479000000, 406614269000000)),
    _period("2024-12-31", "사업보고서", "2025-03-11", _key(300870903000000, 32725961000000, 34451351000000, 514531948000000, 112339878000000, 402192070000000)),
    _period("2024-09-30", "3분기보고서", "2024-11-14", _key(79098731000000, 9183371000000, 10100904000000, 491307317000000, 105025954000000, 386281363000000)),
]}
# 은행(KB금융 105560) — 매출액 항목이 없어 key.revenue 가 null 이다
KB = {"source": "전자공시(DART) 다중회사 주요계정(fnlttMultiAcnt)", "periods": [
    _period("2026-06-30", "반기보고서", "2026-08-14", _key(None, 2712548000000, 2010508000000, 866889205000000, 804187383000000, 62701822000000)),
    _period("2026-03-31", "1분기보고서", "2026-05-15", _key(None, 2727566000000, 1916469000000, 829740827000000, 768600691000000, 61140136000000)),
    _period("2025-12-31", "사업보고서", "2026-06-19", _key(None, 8517711000000, 5840715000000, 797923033000000, 737093044000000, 60829989000000)),
]}
ROE = {"key": "roe", "label": "ROE", "value": 10.4, "unit": "%", "formula": "지배주주 순이익 ÷ 지배지분 자본 × 100", "basis": "2025 사업보고서(연결) · 공시 접수 2026-03-10", "sentence": "s"}
OPM = {"key": "operating_margin", "label": "영업이익률", "value": 13.1, "unit": "%", "approx": True, "sentence": "한계 문장", "formula": "영업이익 ÷ 매출액 × 100", "basis": "2025 사업보고서(연결)"}
OPM_NONE = {"key": "operating_margin", "label": "영업이익률", "value": None, "unit": "%", "formula": "f", "basis": "b", "reason": "매출액 항목이 없어 계산하지 않음", "sentence": "s"}
PER = {"key": "per", "label": "PER", "value": 35.1, "unit": "배", "formula": "종가 ÷ 보고된 기본주당이익", "basis": "종가 2026-10-29 · 2025 사업보고서(연결) · 공시 접수 2026-03-10", "sentence": "s"}
PBR = {"key": "pbr", "label": "PBR", "value": 3.2, "unit": "배", "approx": True, "formula": "시가총액 ÷ 지배지분 자본", "basis": "종가 2026-10-29 · 2025 사업보고서(연결)", "sentence": "우선주 때문에 낮게 나올 수 있습니다."}
IND = {"name": "삼성전자", "price": {"close": 232000, "trade_date": "2026-10-29", "market_cap": 1356336637056000, "note": "2026-10-29 마지막 종가 · 지금 가격이 아닙니다"},
       "metrics": [PER, PBR, ROE, OPM, {"key": "dividend_yield", "label": "배당수익률", "value": 1.2, "unit": "%", "formula": "f", "basis": "최근 12개월"}]}
HEALTH = {"metrics": [{"key": "debt_ratio", "label": "부채비율", "value": 31.1, "unit": "%", "formula": "부채총계 ÷ 자본총계 × 100", "basis": {"period_end": "2026-06-30", "report": "반기보고서"}}]}
PARTS = {"code": "005930", "ind": IND, "fin": SAMSUNG, "health": HEALTH, "quote": None, "ohlcv": None}


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(
        f'import * as cw from "{JS.resolve().as_uri()}";\nimport * as cv from "{CV.resolve().as_uri()}";\n{ESC}\n'
        f"const SAMSUNG = {json.dumps(SAMSUNG, ensure_ascii=False)}, KB = {json.dumps(KB, ensure_ascii=False)}, IND = {json.dumps(IND, ensure_ascii=False)}, "
        f"HEALTH = {json.dumps(HEALTH, ensure_ascii=False)}, PARTS = {json.dumps(PARTS, ensure_ascii=False)}, OPM_NONE = {json.dumps(OPM_NONE, ensure_ascii=False)};\n"
        f"const out = {{}};\n{body}\nprocess.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _server_numbers(fin: dict) -> set:
    return {v for p in fin["periods"] for v in p["key"].values() if v is not None}


def test_quarter_series_uses_only_three_month_reports(tmp_path):
    """TC-CWS-01 — 1분기 · 반기 · 3분기 보고서만 · 오래된 쪽이 왼쪽 · 사업보고서(12개월 값)는 빼고 4분기 값을 만들어 끼우지 않는다 · 입력 순서와 상관없다."""
    out = _run(tmp_path, """
      const s = cw.cwQuarterSeries(SAMSUNG);
      const shuffled = { periods: SAMSUNG.periods.slice().reverse() };
      out.s = s; out.same = JSON.stringify(cw.cwQuarterSeries(shuffled)) === JSON.stringify(s);
      out.none = cw.cwQuarterSeries(null); out.annualOnly = cw.cwQuarterSeries({ periods: [SAMSUNG.periods[2]] });
    """)
    s = out["s"]
    assert [m["period_end"] for m in s["meta"]] == ["2024-09-30", "2025-03-31", "2025-06-30", "2025-09-30", "2026-03-31", "2026-06-30"]   # 4분기 자리(2024-12 · 2025-12)가 비어 있다
    assert s["categories"][0] == "2024-09-30 3분기(3개월)" and s["categories"][-1] == "2026-06-30 반기(3개월)"
    assert s["skippedAnnual"] == 2 and s["total"] == 8
    assert 333605938000000 not in s["revenue"] and 300870903000000 not in s["revenue"]                       # 연간 값이 3개월 막대에 섞이지 않는다
    assert out["same"] is True
    assert out["none"]["categories"] == [] and out["annualOnly"]["categories"] == [] and out["annualOnly"]["skippedAnnual"] == 1


def test_series_values_are_server_numbers_never_computed(tmp_path):
    """TC-CWS-02 — 막대 series 의 숫자는 모두 서버가 준 숫자 그대로(합 · 차 · 비율이면 입력에 없다) · 없는 값은 null(0 아님) · 계정 목록 대체 경로도 같다."""
    out = _run(tmp_path, """
      out.sam = cw.cwQuarterSeries(SAMSUNG); out.kb = cw.cwQuarterSeries(KB);
      out.hasKbRev = cw.cwHasValues(out.kb.revenue); out.hasKbOp = cw.cwHasValues(out.kb.operating);
      const noKey = { periods: [{ period_end: "2026-06-30", report: "반기보고서", known_at: "2026-08-14",
        accounts: [{ statement: "IS", name: "영업수익", amount: 111 }, { statement: "IS", name: "영업이익(손실)", amount: -22 }, { statement: "IS", name: "당기순이익", amount: null },
                   { statement: "BS", name: "자본총계", amount: 333 }] }] };
      out.fallback = cw.cwQuarterSeries(noKey);
      out.val = [cw.cwPeriodValue(noKey.periods[0], "equity"), cw.cwPeriodValue(noKey.periods[0], "assets"), cw.cwPeriodValue(null, "equity"), cw.cwPeriodValue({ key: { revenue: null }, accounts: [{ statement: "IS", name: "매출액", amount: 5 }] }, "revenue")];
    """)
    allowed = _server_numbers(SAMSUNG)
    for field in ("revenue", "operating", "net"):
        assert all(v in allowed for v in out["sam"][field]), field                                          # 입력에 없는 숫자(셈한 값)가 하나도 없다
    assert out["sam"]["revenue"][-1] == 171499470000000 and out["sam"]["net"][0] == 10100904000000
    assert out["kb"]["revenue"] == [None, None] and out["hasKbRev"] is False and out["hasKbOp"] is True      # 은행은 매출액 항목이 없다 — 0 이 아니라 null
    assert out["fallback"]["revenue"] == [111] and out["fallback"]["operating"] == [-22] and out["fallback"]["net"] == [None]   # 서버 key 가 없을 때만 같은 이름을 찾는다
    assert out["val"] == [333, None, None, None]                                                            # key 칸이 null 이라 한 것은 계정 목록으로 바꿔치지 않는다


def test_structure_donut_input(tmp_path):
    """TC-CWS-03 — 가장 최근 기간의 서버 부채총계 · 자본총계 · 자산총계 그대로(더하지 않는다) · 자본잠식 · 값 없음 · 자료 없음은 그리지 않고 까닭."""
    out = _run(tmp_path, """
      out.ok = cw.cwStructure(SAMSUNG);
      const odd = { periods: [{ period_end: "2026-06-30", report: "반기보고서", known_at: "2026-08-14", key: { assets: 999, liabilities: 100, equity: 200 }, accounts: [] }] };
      out.odd = cw.cwStructure(odd);
      out.neg = cw.cwStructure({ periods: [{ period_end: "2026-06-30", report: "반기보고서", key: { assets: 10, liabilities: 30, equity: -20 }, accounts: [] }] });
      out.miss = cw.cwStructure({ periods: [{ period_end: "2026-06-30", report: "반기보고서", key: { assets: 10, liabilities: null, equity: 5 }, accounts: [] }] });
      out.empty = [cw.cwStructure(null), cw.cwStructure({ periods: [] })];
      out.opt = cw.cwStructureOptions(out.odd); out.lab = cw.cwStructureOptions(out.ok);
      out.totalText = out.opt.plotOptions.pie.donut.labels.total.formatter();
    """)
    ok = out["ok"]
    assert ok["ok"] is True and ok["period_end"] == "2026-06-30" and (ok["liabilities"], ok["equity"], ok["assets"]) == (180170840000000, 579309676000000, 759480516000000)
    assert out["odd"]["ok"] is True and out["opt"]["series"] == [100, 200]                                  # 서버 값 그대로
    assert "999원" in out["totalText"]                                                                    # 가운데는 서버 자산총계 — 부채 + 자본(300)이 아니다
    assert out["neg"]["ok"] is False and "자본잠식" in out["neg"]["reason"] and "−20원" in out["neg"]["reason"]
    assert out["miss"]["ok"] is False and "부채총계" in out["miss"]["reason"]
    assert all(e["ok"] is False and "재무제표 자료가 없습니다" in e["reason"] for e in out["empty"])


def test_profit_bars_use_only_server_ratios(tmp_path):
    """TC-CWS-04 — 서버가 계산한 ROE · 영업이익률만 막대로(ROA · 순이익률 · PER 등은 넣지 않는다) · 값이 없는 지표는 까닭 · 근사 표시."""
    out = _run(tmp_path, """
      out.pb = cw.cwProfitBars(IND);
      out.bank = cw.cwProfitBars({ metrics: IND.metrics.filter(m => m.key === "roe").concat([OPM_NONE]) });
      out.none = [cw.cwProfitBars(null), cw.cwProfitBars({ metrics: [] })];
      out.sum = cw.cwProfitSummary(out.bank); out.sumFull = cw.cwProfitSummary(out.pb);
      out.opt = cw.cwProfitOptions(out.pb.bars);
      out.emptyMsg = [cw.cwProfitEmpty({ ind: IND }, out.pb), cw.cwProfitEmpty({ ind: IND }, { bars: [], missing: [] }), cw.cwProfitEmpty({ indErr: { message: "지표 오류" } }, out.pb), cw.cwProfitEmpty({ unsupported: true }, out.pb)];
    """)
    assert [b["key"] for b in out["pb"]["bars"]] == ["roe", "operating_margin"] and out["pb"]["missing"] == []
    assert out["pb"]["bars"][1]["approx"] is True and out["pb"]["bars"][0]["value"] == 10.4
    assert [b["key"] for b in out["bank"]["bars"]] == ["roe"] and out["bank"]["missing"][0]["reason"] == "매출액 항목이 없어 계산하지 않음"
    assert "영업이익률 — 매출액 항목이 없어 계산하지 않음" in out["sum"] and "ROE 10.4% — 지배주주 순이익" in out["sum"]
    assert "영업이익률 13.1% (근사)" in out["sumFull"] and "한계 문장" in out["sumFull"]
    assert out["opt"]["series"][0]["data"] == [10.4, 13.1] and out["opt"]["xaxis"]["categories"] == ["ROE", "영업이익률"]
    assert all(k not in json.dumps(out["pb"], ensure_ascii=False) for k in ("ROA", "순이익률", "PER"))
    assert out["none"][0] == {"bars": [], "missing": []} and out["none"][1] == {"bars": [], "missing": []}
    assert out["emptyMsg"][0] == "" and "계산하지 못해" in out["emptyMsg"][1] and out["emptyMsg"][2] == "지표 오류" and "지원하지 않습니다" in out["emptyMsg"][3]


def test_chart_options_series_axis_and_no_percent_labels(tmp_path):
    """TC-CWS-05 — 막대 옵션의 series 는 서버 값 그대로 · 조 · 억 글은 formatter 에서만 · 도넛 조각에 비율(%) 글자가 없다 · 막대 이름에 3개월이 적힌다."""
    out = _run(tmp_path, """
      const s = cw.cwQuarterSeries(SAMSUNG);
      const rev = cw.cwRevenueOptions(s), inc = cw.cwIncomeOptions(s), dn = cw.cwStructureOptions(cw.cwStructure(SAMSUNG)), pf = cw.cwProfitOptions(cw.cwProfitBars(IND).bars);
      out.rev = rev.series; out.inc = inc.series; out.cat = rev.xaxis.categories;
      out.axis = [rev.yaxis.labels.formatter(171499470000000), rev.yaxis.labels.formatter(338900000000), rev.yaxis.labels.formatter(-4.2e12), rev.yaxis.labels.formatter(null), rev.xaxis.labels.formatter("2026-06-30 반기(3개월)")];
      out.axis2 = [cw.cwAxisText(1.8e14), cw.cwAxisText(1.625e14), cw.cwAxisText(0)];
      out.tip = [rev.tooltip.y.formatter(171499470000000), rev.tooltip.y.formatter(null)];
      out.dn = { labels: dn.labels, series: dn.series, dl: dn.dataLabels, total: dn.plotOptions.pie.donut.labels.total, legend: dn.legend.formatter("자본총계", { seriesIndex: 1 }) };
      out.pf = { dl: pf.dataLabels.enabled, fmt: pf.dataLabels.formatter(10.4), horizontal: pf.plotOptions.bar.horizontal };
      out.noAssets = cw.cwStructureOptions({ ok: true, liabilities: 1, equity: 2, assets: null }).plotOptions.pie.donut.labels.total.show;
      out.types = [rev.chart.type, inc.chart.type, dn.chart.type, pf.chart.type]; out.anim = rev.chart.animations.enabled;
    """)
    assert out["rev"] == [{"name": "매출액(3개월)", "data": [79098731000000, 79140503000000, 74566317000000, 86061747000000, 133873444000000, 171499470000000]}]
    assert [s["name"] for s in out["inc"]] == ["영업이익(3개월)", "당기순이익(3개월)"] and out["inc"][0]["data"][-1] == 89492412000000
    assert out["cat"][2] == "2025-06-30 반기(3개월)"
    assert out["axis"] == ["171.5조", "3,389억", "−4.2조", "—", "26.06"] and out["axis2"] == ["180조", "162.5조", "0"]   # 눈금 뒤의 0 은 뗀다
    assert out["tip"] == ["171.50조 원", "—"]
    dn = out["dn"]
    assert dn["labels"] == ["부채총계", "자본총계"] and dn["series"] == [180170840000000, 579309676000000]
    assert dn["dl"]["enabled"] is False                                                                  # 조각 비율(%) 글자 없음
    assert dn["total"]["label"] == "자산총계" and dn["total"]["show"] is True and dn["legend"] == "자본총계 579.31조 원"
    assert out["pf"] == {"dl": True, "fmt": "10.4%", "horizontal": True} and out["noAssets"] is False
    assert out["types"] == ["bar", "bar", "donut", "bar"] and out["anim"] is False


def test_snapshot_rows_have_basis_and_dashes(tmp_path):
    """TC-CWS-06 — 스냅샷 줄마다 값 + 기준일 · 출처 · 없으면 줄표와 까닭 · 서버 글 이스케이프 · 판단 낱말 없음 · 지원하지 않는 종목 · 지표 오류."""
    out = _run(tmp_path, """
      out.rows = cw.cwSnapshotRows(PARTS); out.html = cw.cwSnapshotHtml(PARTS, esc);
      const bank = { ...PARTS, ind: { ...IND, metrics: [OPM_NONE], price: null }, health: null };
      out.bank = cw.cwSnapshotRows(bank); out.bankHtml = cw.cwSnapshotHtml(bank, esc);
      const evil = { ...PARTS, ind: { ...IND, name: "<b>이름</b>", metrics: [{ key: "per", label: "PER", value: 1, unit: "배", basis: "<script>x</script>", formula: "f" }] } };
      out.evil = cw.cwSnapshotHtml(evil, esc);
      out.unsupported = cw.cwSnapshotHtml({ code: "", unsupported: true }, esc);
      out.indErr = cw.cwSnapshotHtml({ code: "005930", indErr: { message: "<i>지표 오류</i>" }, fin: null }, esc);
      out.nothing = cw.cwSnapshotHtml(null, esc);
    """)
    rows = {r["key"]: r for r in out["rows"]}
    assert [r["key"] for r in out["rows"]] == ["close", "market_cap", "per", "pbr", "roe", "operating_margin", "dividend_yield", "debt_ratio", "fin_basis"]
    assert rows["close"]["value"] == "232,000원" and "2026-10-29" in rows["close"]["sub"] and "지금 가격이 아닙니다" in rows["close"]["sub"]
    assert rows["market_cap"]["value"] == "1356.34조 원" and "2026-10-29 종가 기준" in rows["market_cap"]["sub"]
    assert rows["per"]["value"] == "35.1배" and "공시 접수 2026-03-10" in rows["per"]["sub"]
    assert rows["pbr"]["value"] == "3.2배 (근사)" and rows["pbr"]["sub"].endswith("근사")
    assert rows["debt_ratio"]["value"] == "31.1%" and rows["debt_ratio"]["sub"] == "2026-06-30 기준 반기보고서"           # 건전성 지표의 기준은 기간 묶음으로 온다
    assert rows["fin_basis"]["value"] == "2026-06-30" and "공시 접수 2026-08-14" in rows["fin_basis"]["sub"]
    bank = {r["key"]: r for r in out["bank"]}
    assert bank["close"]["value"] == "—" and bank["close"]["sub"] == "종가 자료가 없습니다."
    assert bank["operating_margin"]["value"] == "—" and bank["operating_margin"]["sub"] == "매출액 항목이 없어 계산하지 않음"
    assert bank["per"]["value"] == "—" and "주지 않았습니다" in bank["per"]["sub"] and "debt_ratio" not in bank
    html = out["html"]
    assert 'data-cw-snap="per"' in html and "삼성전자" in html and "005930" in html and "투자 권유가 아닙니다" in html and "다시 계산하지 않습니다" in html
    assert "<script>" not in out["evil"] and "&lt;script&gt;" in out["evil"] and "&lt;b&gt;" in out["evil"]
    assert "지원하지 않습니다" in out["unsupported"] and "&lt;i&gt;지표 오류" in out["indErr"] and out["nothing"] == ""
    text = html + out["bankHtml"]
    assert not [w for w in BANNED if w in text]


def test_source_lines_and_empty_reasons(tmp_path):
    """TC-CWS-07 — 출처 · 기준 기간 · 공시 접수일 줄 · 3개월 값이라는 설명 · 0 으로 채우지 않음 · 빈 칸마다 알맞은 까닭."""
    out = _run(tmp_path, """
      const s = cw.cwQuarterSeries(SAMSUNG), kb = cw.cwQuarterSeries(KB);
      out.src = cw.cwSourceLines(PARTS); out.srcNone = [cw.cwSourceLines({ unsupported: true }), cw.cwSourceLines(null)];
      out.sum = [cw.cwQuarterSummary(s, "revenue", "매출액"), cw.cwQuarterSummary(kb, "revenue", "매출액")];
      out.empty = [
        cw.cwQuarterEmpty({ unsupported: true }, s, "revenue", "매출액"), cw.cwQuarterEmpty({ finErr: { message: "재무 오류" } }, s, "revenue", "매출액"),
        cw.cwQuarterEmpty({ fin: null }, cw.cwQuarterSeries(null), "revenue", "매출액"), cw.cwQuarterEmpty({ fin: { periods: [SAMSUNG.periods[2]] } }, cw.cwQuarterSeries({ periods: [SAMSUNG.periods[2]] }), "revenue", "매출액"),
        cw.cwQuarterEmpty({ fin: KB }, kb, "revenue", "매출액"), cw.cwQuarterEmpty({ fin: KB }, kb, "operating", "영업이익"), cw.cwQuarterEmpty({ fin: SAMSUNG }, s, "revenue", "매출액")];
      out.structSum = cw.cwStructureSummary(cw.cwStructure(SAMSUNG), HEALTH);
    """)
    src = "\n".join(out["src"])
    assert "전자공시(DART) 다중회사 주요계정" in src and "받은 보고서 8개(기준 2024-09-30 ~ 2026-06-30)" in src and "공시 접수 2026-08-14 까지" in src
    assert "3개월 값" in src and "빼서 만들지 않았고" in src and "0으로 채우지 않고" in src and "ROA · 순이익률은 서버가 주지 않아" in src and "투자 권유가 아닙니다" in src
    assert out["srcNone"][0] == [] and out["srcNone"][1] == []
    assert out["sum"][0].startswith("매출액 가장 최근 2026-06-30 반기(3개월) 171.50조 원 · 공시 접수 2026-08-14") and out["sum"][1] == ""
    e = out["empty"]
    assert "지원하지 않습니다" in e[0] and e[1] == "재무 오류" and "자료가 없습니다" in e[2]
    assert "사업보고서(12개월 값)뿐" in e[3] and "금융회사 등" in e[4] and e[5] == "" and e[6] == ""
    assert "2026-06-30 기준 반기보고서" in out["structSum"] and "자산총계 759.48조 원" in out["structSum"] and "서버가 준 부채비율 31.1%" in out["structSum"]


def test_cv_subscribe_emits_start_and_done_for_every_exit(tmp_path):
    """TC-CWS-08 — cvLoad 가 시작과 끝을 알린다(지원하지 않는 종목도) · 구독자 오류가 본 화면을 막지 않는다 · 구독 해제 · 요청 주소는 그대로."""
    out = _run(tmp_path, """
      const seen = [];
      const off = cv.cvSubscribe(e => seen.push({ phase: e.phase, symbol: e.symbol, code: e.code, hasParts: !!e.parts, unsupported: !!(e.parts && e.parts.unsupported) }));
      cv.cvSubscribe(() => { throw new Error("구독자 오류"); });
      const calls = [];
      const api = async u => { calls.push(u); if (u.includes("/risk/")) throw new Error("건전성 실패"); return { u }; };
      out.ok = await cv.cvLoad(api, "005930.KS"); out.bad = await cv.cvLoad(async () => ({}), "AAPL");
      off(); await cv.cvLoad(api, "000660.KS");
      out.seen = seen; out.calls = calls; out.after = seen.length;
    """)
    phases = [(x["phase"], x["symbol"]) for x in out["seen"]]
    assert phases == [("start", "005930.KS"), ("done", "005930.KS"), ("start", "AAPL"), ("done", "AAPL")]
    assert out["seen"][3]["unsupported"] is True and out["seen"][1]["hasParts"] is True and out["seen"][0]["hasParts"] is False
    assert out["ok"]["code"] == "005930" and out["ok"]["health"] is None and out["bad"]["unsupported"] is True      # 본 화면이 받는 값은 그대로
    assert out["after"] == 4 and out["calls"][0] == "/api/data/indicators?symbol=005930" and len(out["calls"]) == 10   # 구독 해제 뒤 알림 없음 · 요청 다섯 × 두 번


def test_app_html_markup_nav_targets_and_kept_ids():
    """TC-CWS-09 — 구역 이동 단추가 가리키는 칸이 있고 · 기존 칸 id 가 그대로이고 · 새 CSS · JS 가 연결되고 · 새 칸 id 가 모두 있다."""
    m = re.search(r'data-view="company-dashboard">(.*?)data-view=', APP, flags=re.S)
    assert m, "app.html 에서 지표 대시보드 화면을 찾지 못했다"
    view = m.group(1)
    targets = re.findall(r'data-cw-target="([^"]+)"', view)
    assert targets == ["cw-sec-price", "cw-sec-charts", "cw-sec-value", "cw-sec-detail"]
    for t in targets:
        assert f'id="{t}"' in view, t
    for old in ("company-tabs", "company-search-btn", "co-chart-card", "co-chart-title", "co-chart-periods", "co-chart", "co-chart-note",
                "co-overview", "co-valuation", "co-profitability", "co-quarterly", "co-balance"):
        assert view.count(f'id="{old}"') == 1, old                                                         # 한 번씩만(company.js · 시험이 찾는 칸)
    for new in ("cw-root", "cw-snapshot", "cw-side", "cw-chart-source", "cw-chart-revenue", "cw-chart-income", "cw-chart-structure", "cw-chart-profit",
                "cw-sum-revenue", "cw-sum-income", "cw-sum-structure", "cw-sum-profit"):
        assert view.count(f'id="{new}"') == 1, new
    assert view.count("<section") == view.count("</section>") == 4 and view.count("<aside") == view.count("</aside>") == 1
    assert view.count("<figure") == view.count("</figure>") == 4 and view.count("<nav") == view.count("</nav>") == 1
    assert view.count("<div") == view.count("</div>")                                                       # 여닫는 짝이 맞다
    assert '<link rel="stylesheet" href="/css/company-workspace.css" />' in APP and '<script type="module" src="/js/company-workspace.js"></script>' in APP
    assert APP.index("/js/company-workspace.js") < APP.index('src="/js/main.js"')
    assert JS.is_file() and CSS.is_file()


def test_no_advice_words_no_yahoo_no_new_api_and_own_cells_only():
    """TC-CWS-10 — 화면 글에 투자 권유 · 판단 낱말이 없고 · 야후 · 새 API 호출이 없고 · company.js 가 채우는 co-* 칸에 쓰지 않는다 · 화면이 값을 셈하지 않는다."""
    js = JS.read_text(encoding="utf-8")
    code = js.split("*/", 1)[1]                                                                             # 머리 주석의 설명 문장은 화면에 나가지 않는다
    assert not [w for w in BANNED if w in code], [w for w in BANNED if w in code]
    view = re.search(r'data-view="company-dashboard">(.*?)data-view=', APP, flags=re.S).group(1)
    fresh = view[view.index('<nav class="cw-nav"'):]
    text = re.sub(r"<[^>]+>", " ", fresh)
    assert not [w for w in BANNED if w in text]
    assert "yahoo" not in js.lower() and "/api/stocks/" not in js and "fetch(" not in code and "api(" not in code and "XMLHttpRequest" not in code
    assert not re.search(r'getElementById\(\s*[`"\']co-', code) and not re.search(r'byId\(\s*[`"\']co-', code) and not re.search(r'setText\(\s*[`"\']co-', code)
    assert "localStorage" not in code and "sessionStorage" not in code
    assert "cdn." not in code and 'createElement("script")' not in code and "import(" not in code                  # 새 라이브러리를 읽어 오지 않는다(app.html 이 이미 올린 window.ApexCharts 만 쓴다)
    assert code.count("window.ApexCharts") >= 2


def test_css_sticky_snapshot_and_mobile_rules():
    """TC-CWS-11 — 스냅샷이 따라오는 sticky · 좁은 화면에서 한 줄로 · 가로 넘침 방지(min-width:0 · overflow-wrap) · 규칙이 .cw-* 안에만."""
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.cw-side\s*\{[^}]*position:\s*sticky", css) and re.search(r"\.cw-nav\s*\{[^}]*position:\s*sticky", css)
    assert "@media (max-width: 1100px)" in css and "@media (max-width: 820px)" in css and "@media (max-width: 640px)" in css
    narrow = css[css.index("@media (max-width: 1100px)"):]
    assert re.search(r"\.cw-side\s*\{[^}]*position:\s*static", narrow) and "order: -1" in narrow
    assert "minmax(0, 1fr)" in css and "overflow-wrap: anywhere" in css and ".cw-main { min-width: 0; }" in css
    assert "var(--text-mute)" in css
    plain = re.sub(r"@media[^{]*\{", "", re.sub(r"/\*.*?\*/", "", css, flags=re.S))                      # 주석 · @media 머리를 걷고 선택자만 본다
    for sel in re.findall(r"([^{}]+)\{", plain):
        for part in sel.split(","):
            part = part.strip()
            if part and not re.match(r"^(from|to|\d+%)$", part):
                assert ".cw-" in part, f"다른 화면에 번질 수 있는 선택자: {part}"
    assert "nowrap" not in css                                                                              # 좁은 화면에서 가로 넘침의 흔한 원인
