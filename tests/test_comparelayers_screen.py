"""TC-CLY — TradingView ↔ LEAN 대사 결과의 층별 표시(public/js/comparelayers.js · tradingview.js) · 2026-10-29 · 화면 벤치마킹 S5 · S6

옛 화면은 서버 verdict(수익률 · MDD 차이 3%p / 10%p)를 맨 위 배지 하나로 보였다. 사용자 결정(10-29): 층별 판정만 배지, 성과는 참고 표시.
서버(강민석 님 코드)는 안 바꾸고 응답의 signal_comparison · fill_comparison · performance_comparison 을 화면이 읽는다.
1. 신호 층은 정확 일치 — 어긋난 날이 0 이고 한쪽에만 있는 날도 0 이면 「일치」, 어긋난 날이 있으면 「불일치」, 한쪽에만 있는 날만 있으면
   「겹친 날만 일치」 · 숫자는 응답 값 그대로. (TC-CLY-01)
2. 체결 층: 날짜 · 방향이 모두 100% 이고 짝 없는 체결이 0 이면 「일치」, 아니면 「불일치」 · 체결가 차이는 참고(기준 미정)로만. (TC-CLY-02)
3. 성과는 배지 「참고」 뿐 — 색 기준(3%p / 10%p)과 총평 배지가 화면 코드에 없다. (TC-CLY-03)
4. 비교하지 않은 층은 서버 까닭을 보이고(비교 안 함 / 비교 불가) · LEAN 이 안 돌았으면 맨 위에 「비교 불가」. (TC-CLY-04)
5. 화면이 새 모듈을 부르고 옛 판정 문구 · 색이 없다 · 이력 표의 옛 verdict 는 「성과 차이 판정(참고)」 중립 글씨. (TC-CLY-05)
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CL = ROOT / "public" / "js" / "comparelayers.js"
TVJS = ROOT / "public" / "js" / "tradingview.js"

ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')

SIG_OK = {"status": "compared", "tradingview_signal_count": 40, "lean_signal_count": 40, "matched_date_count": 37,
          "tradingview_only_date_count": 0, "lean_only_date_count": 0, "entry_match_count": 37, "entry_compared_count": 37,
          "entry_match_rate_pct": 100.0, "exit_match_count": 37, "exit_compared_count": 37, "exit_match_rate_pct": 100.0,
          "mismatch_date_count": 0, "mismatch_dates": [], "alignment_method": "거래일 기준 날짜별 상태 비교"}
FILL_OK = {"status": "compared", "paired_event_count": 2, "date_match_rate_pct": 100.0, "side_match_rate_pct": 100.0,
           "avg_abs_price_diff_bps": 331.7, "unmatched_tradingview_events": [], "unmatched_lean_events": []}


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as cl from "{CL.resolve().as_uri()}";\n{ESC}\n'
                      f"const SIG_OK = {json.dumps(SIG_OK, ensure_ascii=False)}, FILL_OK = {json.dumps(FILL_OK, ensure_ascii=False)};\n"
                      f"const out = {{}};\n{body}\nprocess.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_signal_layer_is_exact_match(tmp_path):
    """TC-CLY-01"""
    out = _run(tmp_path, """
      out.ok = cl.signalLayer(SIG_OK);
      out.bad = cl.signalLayer({...SIG_OK, mismatch_date_count: 2, mismatch_dates: ["2026-09-29", "2026-10-23"], entry_match_count: 35, entry_match_rate_pct: 94.6});
      out.only = cl.signalLayer({...SIG_OK, tradingview_only_date_count: 3});
      out.cls = [cl.badgeClass("일치"), cl.badgeClass("불일치"), cl.badgeClass("겹친 날만 일치"), cl.badgeClass("비교 안 함"), cl.badgeClass("참고")];
    """)
    assert out["ok"]["badge"] == "일치" and "겹친 날짜 37일 · 어긋난 날 0일" in out["ok"]["lines"][0]
    assert "진입 상태 일치 37 / 37 (100%)" in out["ok"]["lines"][1] and out["ok"]["limit"] == "거래일 기준 날짜별 상태 비교"
    assert out["bad"]["badge"] == "불일치" and any("2026-09-29 · 2026-10-23" in t for t in out["bad"]["lines"])
    assert "진입 상태 일치 35 / 37 (94.6%)" in out["bad"]["lines"][1]
    assert out["only"]["badge"] == "겹친 날만 일치" and any("TradingView 3일" in t for t in out["only"]["lines"])
    assert out["cls"] == ["badge-buy", "badge-sell", "badge-hold", "badge-hold", "badge-hold"]    # 색은 일치 · 불일치만


def test_fill_layer_exact_date_side_price_is_reference(tmp_path):
    """TC-CLY-02"""
    out = _run(tmp_path, """
      out.ok = cl.fillLayer(FILL_OK);
      out.side = cl.fillLayer({...FILL_OK, side_match_rate_pct: 50.0});
      out.unm = cl.fillLayer({...FILL_OK, unmatched_lean_events: [{}]});
    """)
    assert out["ok"]["badge"] == "일치"                                               # 체결가 331.7bp 차이가 있어도 날짜 · 방향이 맞으면 일치
    assert any("331.7bp" in t and "참고" in t and "기준 미정" in t for t in out["ok"]["lines"])
    assert "허용 오차는 아직 정해지지 않았습니다" in out["ok"]["limit"]
    assert out["side"]["badge"] == "불일치" and out["unm"]["badge"] == "불일치"


def test_performance_is_reference_without_color_or_total_badge(tmp_path):
    """TC-CLY-03"""
    out = _run(tmp_path, """
      out.perf = cl.performanceLayer({status: "compared", verdict: "일치"});
      out.html = cl.renderLayers({signal_comparison: SIG_OK, fill_comparison: FILL_OK, performance_comparison: {status: "compared", verdict: "일치"}, lean: {lean_ok: true}}, esc);
    """)
    assert out["perf"]["badge"] == "참고" and "비슷하다는 이유만으로 통과로 보지 않으며" in out["perf"]["limit"]
    html = out["html"]
    assert html.count('data-layer="') == 3 and "검증 통과" not in html
    assert html.index('data-layer="signal"') < html.index('data-layer="fill"') < html.index('data-layer="performance"')
    assert "부분 일치" not in html                                                       # 옛 성과 판정 낱말을 층 카드에 쓰지 않는다


def test_uncompared_layers_show_server_reason_and_lean_fallback_banner(tmp_path):
    """TC-CLY-04"""
    out = _run(tmp_path, """
      out.none = cl.layersOf({signal_comparison: {status: "not_requested", reason: "신호 CSV가 제공되지 않아 신호 비교를 수행하지 않았습니다."},
                              fill_comparison: {status: "unavailable", reason: "두 엔진의 체결 날짜가 겹치지 않습니다."},
                              performance_comparison: {status: "not_requested", reason: "성과 입력이 없어 성과 비교를 수행하지 않았습니다."}, lean: {lean_ok: true}});
      out.pandas = cl.renderLayers({signal_comparison: SIG_OK, fill_comparison: FILL_OK, performance_comparison: {status: "compared"}, lean: {lean_ok: false}}, esc);
      out.empty = cl.renderLayers({}, esc);
    """)
    sig, fill, perf = out["none"]["layers"]
    assert sig["badge"] == "비교 안 함" and sig["lines"] == ["신호 CSV가 제공되지 않아 신호 비교를 수행하지 않았습니다."]
    assert fill["badge"] == "비교 불가" and fill["lines"] == ["두 엔진의 체결 날짜가 겹치지 않습니다."]
    assert perf["badge"] == "비교 안 함" and out["none"]["banner"] is None
    assert out["pandas"].index("pandas 대체 계산") < out["pandas"].index('data-layer="signal"')   # 맨 위
    assert "LEAN 엔진이 실행되지 않아" in out["pandas"] and "비교 불가" in out["pandas"].split('data-layer="signal"')[0]
    assert out["empty"].count('data-layer="') == 3                                       # 응답이 비어도 깨지지 않는다


def test_screen_uses_layers_and_has_no_old_verdict_rules():
    """TC-CLY-05"""
    js = TVJS.read_text(encoding="utf-8")
    assert 'from "/js/comparelayers.js"' in js and "renderLayers(r, escHtml)" in js and "PERF_NOTE" in js
    assert "VERDICT_CLS" not in js and "3%p 이하" not in js and "text-emerald-600" not in js and "text-amber-500" not in js
    assert "<th>성과 차이 판정(참고)</th>" in js
    assert 'class="text-xs">${escHtml(c.verdict)}</span>' in js                          # 이력의 옛 verdict 는 중립 글씨
