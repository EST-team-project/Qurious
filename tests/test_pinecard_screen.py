"""TC-PCD — 전략 카드 → Pine 내려받기 화면(public/js/pinecard.js · tradingview.js · app.html) · 2026-10-29 · 화면 벤치마킹 S3

서버 값(코드 · 지문 · 설정 · 경고)을 그대로 보이고 화면은 짓지 않는다.
1. 카드 고르기: 만들 수 없는 카드는 막고 서버 까닭을 보인다 · 카드가 없으면 안내. (TC-PCD-01)
2. 요청 문자열: 빈 칸 · 숫자가 아닌 칸은 보내지 않는다(서버 기본값 · 경고를 그대로 받음). (TC-PCD-02)
3. 설정 표: 초기 자본 · 수수료 · 슬리피지 · 피라미딩 · 체결 시점 · 주기 — 값이 없으면 줄표 · 같은 종가 체결은 「현실에서는 불가한 가정」. (TC-PCD-03)
4. 결과: strategy() 안내 · 판 지문 · 경고 · 코드는 이스케이프 · 파일 이름에 카드 · 판 · 종목 · 지문. (TC-PCD-04)
5. 화면 연결: 칸 ids · 핸들러 · 로드 시점 · 서버 길 이름. (TC-PCD-05)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PC = ROOT / "public" / "js" / "pinecard.js"

ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')

RES = {"card_id": "ma_cross_20_60", "version": 2, "fingerprint": "ab12cd34ef56", "symbol": "005930", "pine_version": 6,
       "code": "//@version=6\nstrategy(\"x\", overlap=true)\nif a < b\n    strategy.close(\"L\")\n// <script>alert(1)</script>",
       "warnings": ["price_basis = adj_base — 수정주가 설정을 같게 두세요"], "note": "코드는 저장하지 않습니다.",
       "properties": {"initial_capital": 10000000, "commission_type": "percent", "commission_value": "0.105",
                      "commission_round_trip_pct": "0.21", "slippage_ticks": 1, "slippage_effective_bp": 14.2857,
                      "pyramiding": 0, "process_orders_on_close": False, "timeframe": "1d"}}


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as pc from "{PC.resolve().as_uri()}";\n{ESC}\nconst RES = {json.dumps(RES, ensure_ascii=False)};\n'
                      f"const out = {{}};\n{body}\nprocess.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_card_options_block_ungeneratable(tmp_path):
    """TC-PCD-01"""
    out = _run(tmp_path, """
      out.opts = pc.cardOptions({cards: [{id: "strategy-card-a-v1", card_id: "a", version: 1, universe: ["005930"], generatable: true, reason: ""},
                                         {id: "strategy-card-b-v1", card_id: "b", version: 1, universe: [], generatable: false, reason: "lightgbm 점수는 옮길 수 없다"}]}, esc);
      out.none = pc.cardOptions({cards: []}, esc); out.nul = pc.cardOptions(null, esc);
    """)
    first, second = out["opts"].split("</option>")[:2]
    assert "disabled" not in first and "selected" in first and "a 판 1" in first
    assert "disabled" in second and "만들 수 없음: lightgbm 점수는 옮길 수 없다" in second and "selected" not in second
    assert "카드 파일을 찾지 못했습니다" in out["none"] and "카드 파일을 찾지 못했습니다" in out["nul"]


def test_query_skips_empty_and_non_numeric(tmp_path):
    """TC-PCD-02"""
    out = _run(tmp_path, """
      out.full = pc.pineQuery({symbol: " 005930 ", refPrice: "70000", mintick: "100", slippageBp: "10", capital: "10000000"});
      out.empty = pc.pineQuery({}); out.blank = pc.pineQuery({symbol: "", refPrice: "", mintick: null});
      out.junk = pc.pineQuery({refPrice: "abc", mintick: "Infinity"});
    """)
    assert out["full"] == "?symbol=005930&ref_price=70000&mintick=100&slippage_bp=10&capital=10000000"
    assert out["empty"] == "" and out["blank"] == "" and out["junk"] == ""


def test_properties_table(tmp_path):
    """TC-PCD-03"""
    out = _run(tmp_path, """
      out.t = pc.propertiesTable(RES.properties, esc);
      out.close = pc.propertiesTable({...RES.properties, process_orders_on_close: true, slippage_ticks: 0}, esc);
      out.empty = pc.propertiesTable(null, esc);
    """)
    t = out["t"]
    assert "10,000,000원" in t and "0.105%" in t and "왕복 0.21%" in t and "1틱" in t and "약 14.3bp" in t
    assert "다음 봉 시가에 체결" in t and "일봉(1D)만" in t and "<strong>0</strong>" in t                       # 피라미딩 0
    assert "같은 봉 종가에 체결" in out["close"] and "현실에서는 불가한 가정" in out["close"] and "기준가 · 호가 단위를 넣지 않으면 0" in out["close"]
    assert out["empty"].count("—") >= 4                                                                         # 값이 없으면 줄표


def test_render_result_and_file_name(tmp_path):
    """TC-PCD-04"""
    out = _run(tmp_path, """
      out.html = pc.renderPine(RES, esc); out.none = pc.renderPine(null, esc);
      out.names = [pc.fileName(RES), pc.fileName({card_id: "a/b", version: 1, symbol: "../x", fingerprint: ""}), pc.fileName(null)];
      out.fail = [pc.failText({message: "종목이 2개다 — symbol 로 고른다"}), pc.failText({status: 401}), pc.failText(null)];
    """)
    h = out["html"]
    assert "data-pine-strategy" in h and "<strong>strategy()</strong>" in h and "Properties" in h
    assert "카드 ma_cross_20_60 · 판 2 · 종목 005930 · 판 지문 <code>ab12cd34ef56</code> · Pine v6" in h
    assert "수정주가 설정을 같게 두세요" in h and "코드는 저장하지 않습니다." in h
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in h and "<script>" not in h                                  # 코드는 이스케이프
    assert out["none"] == '<div class="text-sm">코드를 받지 못했습니다.</div>'
    assert out["names"][0] == "ma_cross_20_60_v2_005930_ab12cd34ef56.pine"
    assert out["names"][1] == "a-b_v1_x_x.pine" and out["names"][2] == "x_vx_x_x.pine"                          # 경로 글자는 파일 이름에 못 들어간다
    assert out["fail"] == ["종목이 2개다 — symbol 로 고른다", "로그인이 풀렸습니다. 다시 로그인해 주세요.", "코드를 만들지 못했습니다."]


def test_wired_into_tradingview_screen():
    """TC-PCD-05"""
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    js = (ROOT / "public" / "js" / "tradingview.js").read_text(encoding="utf-8")
    for ident in ('id="pc-card"', 'id="pc-symbol"', 'id="pc-ref"', 'id="pc-tick"', 'id="pc-run"', 'id="pc-copy"', 'id="pc-download"', 'id="pc-result"', "data-pine-download"):
        assert html.count(ident) == 1, ident
    assert html.index("data-pine-download") < html.index('id="tvc-ticker"')                                     # 대사보다 위 — 코드 → 리포트 → 대사 순서
    assert 'from "/js/pinecard.js"' in js and '"/api/strategy-cards"' in js and "/api/strategy-cards/${encodeURIComponent(id)}/pine${q}" in js
    assert 'on("pc-run", "click", runPine)' in js and "loadPineCards();" in js
    assert "「지표」 화면의 Pine 코드는 차트 표시용(indicator)이라 대사에 쓸 수 없습니다" in re.sub(r"\s+", " ", html)
