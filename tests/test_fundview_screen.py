"""TC-FV — 재무제표 분석 화면(public/js/fundview.js · ml.js · app.html) · 2026-10-29 · 할 일 ①-10

옛 화면은 `/api/macro/fundamental` 이 지어낸 값(DCF = 가격 × 1.15 · FCF 수익률 = 100 ÷ 가격 × 1000)을 「목업」 이라는 말만 붙여 보였다.
지금 약속:
1. 화면 모듈은 DART 주요계정 · 건전성 지표 · 종가를 **응답 값 그대로** 그린다 — 숫자마다 기준 기간 · 공시 접수일 · 쓸 수 있는 날 · 출처 한 줄 ·
   단위 글(조 · 억)만 바꾸고 셈하지 않는다 · 같은 계정이 두 번 와도(당기순이익) 한 번만. (TC-FV-01)
2. DCF 내재가치 · FCF 수익률은 숫자를 보이지 않고 「계산하지 않음 — 까닭」 과 개념 설명만 보인다. (TC-FV-02)
3. 종가는 「종가」 라 부르고 「현재 주가」 라 하지 않는다 · 자료가 없거나 요청이 실패하면 줄표와 까닭, 나머지는 그대로 그린다. (TC-FV-03)
4. 서버 `/api/macro/fundamental` 은 지어낸 값을 내지 않는다(null + 까닭). (TC-FV-04)
5. ml.js 는 이 길을 더 부르지 않고 fundview.js 를 부른다 · 화면에 「(목업)」 글이 없다. (TC-FV-05)
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FV = ROOT / "public" / "js" / "fundview.js"

ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')

ROW = {
    "period_end": "2026-06-30", "report": "반기보고서", "known_at": "2026-08-14", "available_from": "2026-08-18",
    "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814003699",
    "accounts": [
        {"statement": "BS", "name": "자산총계", "amount": 759480516000000, "cumulative": None, "previous": 566942110000000},
        {"statement": "BS", "name": "부채총계", "amount": 180170840000000, "cumulative": None, "previous": 130621773000000},
        {"statement": "BS", "name": "자본총계", "amount": 579309676000000, "cumulative": None, "previous": 436320337000000},
        {"statement": "IS", "name": "매출액", "amount": 171499470000000, "cumulative": 305372914000000, "previous": 74566317000000},
        {"statement": "IS", "name": "영업이익", "amount": 89492412000000, "cumulative": 146725209000000, "previous": 4676057000000},
        {"statement": "IS", "name": "당기순이익(손실)", "amount": 71624461000000, "cumulative": 118849733000000, "previous": 5116435000000},
        {"statement": "IS", "name": "당기순이익(손실)", "amount": 71624461000000, "cumulative": 118849733000000, "previous": 5116435000000},
    ],
}
FIN = {"source": "전자공시(DART) 다중회사 주요계정(fnlttMultiAcnt)", "note": "손익계산서 amount 는 분기 · 반기 보고서면 그 3개월 값이다.", "periods": [ROW]}
HEALTH = {"fs_note": "연결재무제표 기준", "notice": "투자 권유가 아닙니다.",
          "metrics": [{"key": "debt_ratio", "label": "부채비율", "value": 31.1, "unit": "%", "sentence": "부채총계 ÷ 자본총계 입니다.",
                       "formula": "부채총계 ÷ 자본총계 × 100", "basis": "2026-06-30 반기"}]}
HUB = {"sections": {"price": {"status": "ok", "data": {"close": 72300, "trade_date": "2026-10-28"}}}}


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as fv from "{FV.resolve().as_uri()}";\n{ESC}\n'
                      f"const FIN = {json.dumps(FIN, ensure_ascii=False)}, HEALTH = {json.dumps(HEALTH, ensure_ascii=False)}, "
                      f"HUB = {json.dumps(HUB, ensure_ascii=False)};\nconst out = {{}};\n{body}\n"
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_numbers_come_from_response_with_provenance(tmp_path):
    """TC-FV-01 — 응답 값 그대로 · 숫자마다 출처 한 줄 · 단위 글만 · 중복 계정은 한 번."""
    out = _run(tmp_path, """
      out.html = fv.renderFundamental({fin: FIN, health: HEALTH, hub: HUB}, esc);
      out.won = [fv.wonText(171499470000000), fv.wonText(520309210901), fv.wonText(-89000000), fv.wonText(null), fv.wonText(12345)];
      out.code = [fv.shortCode("005930.KS"), fv.shortCode("000660"), fv.shortCode("AAPL"), fv.shortCode(""), fv.shortCode("../x")];
      out.prov = fv.provenanceLine(FIN.periods[0], FIN);
    """)
    html = out["html"]
    assert "171.50조 원" in html and "89.49조 원" in html and "71.62조 원" in html          # 매출 · 영업이익 · 순이익
    assert "759.48조 원" in html and "180.17조 원" in html and "579.31조 원" in html          # 자산 · 부채 · 자본
    assert html.count("71.62조 원") == 1                                                      # 같은 계정 두 줄 → 한 번
    assert "누적 305.37조 원" in html                                                         # 손익은 누적도
    assert "2026-06-30 기준 반기보고서" in html and "공시 접수 2026-08-14" in html and "쓸 수 있는 날 2026-08-18" in html
    assert "전자공시(DART)" in html
    assert "부채비율" in html and "31.1%" in html and "부채총계 ÷ 자본총계 입니다." in html and "식: 부채총계 ÷ 자본총계 × 100" in html
    assert 'href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814003699"' in html and 'rel="noopener noreferrer"' in html
    assert out["won"] == ["171.50조 원", "5,203억 원", "−89,000,000원", "—", "12,345원"]       # 1억 미만은 원 단위 그대로
    assert out["code"] == ["005930", "000660", "", "", ""]
    assert out["prov"].startswith("2026-06-30 기준 반기보고서 · 공시 접수 2026-08-14")


def test_dcf_and_fcf_are_not_computed(tmp_path):
    """TC-FV-02 — DCF · FCF 수익률은 숫자 없이 까닭 + 개념 설명만."""
    out = _run(tmp_path, """
      out.html = fv.renderFundamental({fin: FIN, health: HEALTH, hub: HUB}, esc);
      out.reason = fv.NOT_COMPUTED_REASON;
    """)
    html = out["html"]
    assert "DCF 내재가치 · FCF 수익률" in html and out["reason"] in html
    assert "영업현금흐름" in out["reason"] and "설비투자" in out["reason"]
    assert "미래 현금흐름을 현재가치로 할인" in html and "잉여현금흐름 = 영업현금흐름 − 설비투자" in html
    # 계산 결과처럼 보이는 글자가 없다 — 옛 화면의 「(목업)」 과 가격 곱셈 결과(72300 × 1.15 = 83,145)
    assert "목업" not in html and "83,145" not in html and "%" not in html.split("DCF 내재가치 · FCF 수익률")[1].split("</div></div>")[0].replace("31.1%", "")


def test_close_label_and_partial_failure(tmp_path):
    """TC-FV-03 — 종가는 종가 · 현재 주가라 하지 않는다 · 일부가 없거나 실패해도 나머지를 그린다."""
    out = _run(tmp_path, """
      out.ok = fv.renderFundamental({fin: FIN, health: HEALTH, hub: HUB}, esc);
      out.noFin = fv.renderFundamental({finErr: {message: "재무제표 자료가 없습니다(수집 전)."}, health: HEALTH, hub: HUB}, esc);
      out.noHub = fv.renderFundamental({fin: FIN, health: null, healthErr: {message: "건전성 지표를 받지 못했습니다."},
                                        hub: {sections: {price: {status: "empty", reason: "최근 일봉이 없습니다."}}}}, esc);
      out.nothing = fv.renderFundamental({}, esc);
      out.noRow = fv.renderFundamental({fin: {periods: []}, hub: HUB}, esc);
    """)
    assert "72,300원" in out["ok"] and "2026-10-28 마지막 종가 · 지금 가격이 아닙니다" in out["ok"]
    assert "현재 주가" not in out["ok"]
    assert "재무제표 자료가 없습니다(수집 전)." in out["noFin"] and "72,300원" in out["noFin"] and "부채비율" in out["noFin"]
    assert "최근 일봉이 없습니다." in out["noHub"] and "건전성 지표를 받지 못했습니다." in out["noHub"] and "171.50조 원" in out["noHub"]
    assert "DCF 내재가치 · FCF 수익률" in out["nothing"]                                      # 아무것도 못 받아도 깨지지 않는다
    assert "이 종목의 재무제표 자료가 없습니다." in out["noRow"]


def test_macro_fundamental_route_does_not_invent_numbers(monkeypatch):
    """TC-FV-04 — 서버 /api/macro/fundamental 은 DCF · FCF 수익률 자리에 null + 까닭."""
    from app.routes import macro

    async def fake_chart(symbol, interval, rng):
        return {"meta": {"regularMarketPrice": 72300}}

    monkeypatch.setattr(macro, "_yahoo_chart", fake_chart)
    res = asyncio.run(macro.macro_fundamental(symbol="005930.KS", _user=None))
    v = res["valuation"]
    assert v["DCF_intrinsic_value"] is None and v["FCF_yield_pct"] is None
    assert "계산하지 않습니다" in v["reason"] and set(v["concept"]) == {"DCF", "EVA", "FCF"}
    assert res["price"] == 72300                       # 시세 값은 야후가 준 것 그대로
    assert 72300 * 1.15 != res["valuation"].get("DCF_intrinsic_value")


def test_ml_js_uses_fundview_not_the_old_route():
    """TC-FV-05 — ml.js 는 옛 길을 안 부르고 fundview.js 를 부른다 · 「(목업)」 글이 화면 코드에 없다."""
    ml = (ROOT / "public" / "js" / "ml.js").read_text(encoding="utf-8")
    assert "/api/macro/fundamental" not in ml and "DCF_intrinsic_value" not in ml and "FCF_yield_pct" not in ml
    assert 'from "/js/fundview.js"' in ml and "loadFundamental(api, symbol)" in ml and "renderFundamental(parts, escHtml)" in ml
    assert "(목업)" not in ml and "(목업)" not in FV.read_text(encoding="utf-8")
