"""TC-VR · 커스텀 지표 판 · 계산(P02-②-3 · P02-②-1) — 무엇을 계산했는지와 비용이 그대로 들어가는지.

- 저장한 지표를 연 뒤 식을 고치고 「계산 실행」 을 누르면, 저장본이 아니라 고친 식(미리보기)을 계산한다.
  고치지 않았으면 저장본 경로(판 · 결과 이력)로 계산한다 — #243(넣을지 물은 셋 가운데 2) · 강사님 lumina-invest `5b6fc9a`.
- 함수 카드의 「이 예시로 바꾸기」 는 고른 입력칸만 바꾼다 — #243(넣을지 물은 셋 가운데 1).
- 커스텀 경로(`/api/quant/pipeline` strategy=custom)와 자유 산식 경로가 비용 인자를 받아 수익률에서 뗀다 —
  요구 대장 `P02-②-1` 「막는 것」(09-29 적음)이 다시 생기지 않게 지킨다(10-23 재현되지 않음).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.routes import formula as formula_route
from app.routes import stocks
from tests.conftest import make_candles

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js"

SAVED = {"id": "A", "name": "평균 대비", "description": "", "indicator_expr": "zscore(close, n)",
         "buy_expr": "zscore(close, n) < -2", "sell_expr": "zscore(close, n) > 0", "params": {"n": 20.0},
         "current_version": 3, "checksum": "x"}

# formula.js 를 Node 에서 그대로 돌린다 — /js/ 가져오기는 임시 폴더의 가짜 모듈로, DOM 은 id 로 찾는 가짜 요소로 바꾼다
NODE_FLOW = r"""
const SAVED = __SAVED__;
const calls = [];
const els = {}, found = {};
function fake(id) {
  return { id, value: "", textContent: "", innerHTML: "", checked: false, hidden: false, disabled: false, dataset: {}, on: {},
    classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); }, toggle(c) { this.s.has(c) ? this.s.delete(c) : this.s.add(c); }, contains(c) { return this.s.has(c); } },
    addEventListener(t, f) { (this.on[t] ??= []).push(f); }, focus() {}, after() {},
    querySelectorAll(sel) {  // innerHTML 에서 그 class 를 가진 태그를 찾아 data-* 를 dataset 으로
      const cls = sel.slice(1), out = [];
      for (const m of this.innerHTML.matchAll(/<\w+\s[^>]*>/g)) {
        const c = /class="([^"]*)"/.exec(m[0]);
        if (!c || !c[1].split(/\s+/).includes(cls)) continue;
        const e = fake(""); for (const d of m[0].matchAll(/data-([\w-]+)="([^"]*)"/g)) e.dataset[d[1]] = d[2]; out.push(e);
        (found[cls] ??= []).push(e);
      }
      return out;
    } };
}
const el = id => (els[id] ??= fake(id));
globalThis.document = { getElementById: el, documentElement: { dataset: {} } };
globalThis.window = {};
globalThis.__api = async (url, opt = {}) => {
  calls.push({ url, method: opt.method || "GET", body: opt.body || null });
  if (url === "/api/formula-indicators/reference") return { templates: [], rules: [], functions: [
    { signature: "rsi(x, n=14)", description: "RSI", example: "rsi(close, 14)" },
    { signature: "abs, log, sqrt, sign, clip(x,lo,hi)", description: "수학", example: "clip(zscore(close,20), -3, 3)" },
    { signature: "변수", description: "params", example: "close / sma(close, n) - 1" }] };
  if (url === "/api/formula-indicators") return { indicators: [{ ...SAVED }] };
  if (url === "/api/formula-indicators/A") return { ...SAVED };
  if (url.endsWith("/versions")) return { versions: [], current_version: SAVED.current_version };
  if (url.includes("/results")) return { results: [] };
  if (url.endsWith("/compute")) return { version: SAVED.current_version, as_of: "2026-10-22", rows: 300, latest_value: 1, latest_signal: "HOLD", payload: { series: null, backtest: {}, indicator_stats: {} } };
  throw new Error("모르는 주소 " + url);
};
const tick = () => new Promise(r => setTimeout(r, 0));
const fire = async (id, t) => { for (const f of el(id).on[t] || []) await f(); await tick(); };
el("fx-period").value = "2y"; el("fx-symbol").value = "005930.KS";
globalThis.Event = class { constructor(type) { this.type = type; } };
for (const id of ["fx-indicator", "fx-buy", "fx-sell", "fx-params"]) el(id).dispatchEvent = function (e) { (this.on[e.type] || []).forEach(f => f()); };

const { initFormulaView, onFormulaViewActivated } = await import("__FORMULA__");
initFormulaView();
onFormulaViewActivated("indicator-formula");
for (let i = 0; i < 5; i++) await tick();
// 목록을 그릴 때 「열기」 단추에 붙은 처리기를 누른다
await found["fx-open"][0].on.click[0](); for (let i = 0; i < 5; i++) await tick();

const out = { openedCurrent: el("fx-current").textContent };
const mark = () => calls.length;
let k = mark(); await fire("fx-compute", "click");
out.unchanged = calls.slice(k).filter(c => c.url.endsWith("/compute"));
out.unchangedMeta = el("fx-result-meta").innerHTML;

el("fx-buy").value = "zscore(close, n) < -1"; await fire("fx-buy", "input");
out.dirty = { current: el("fx-current").textContent, resultHidden: el("fx-result").classList.contains("hidden"), validate: el("fx-validate-result").textContent };
k = mark(); await fire("fx-compute", "click");
out.edited = calls.slice(k).filter(c => c.url.endsWith("/compute"));
out.editedMeta = el("fx-result-meta").innerHTML;

el("fx-buy").value = SAVED.buy_expr; el("fx-params").value = '{"n": 20}';
k = mark(); await fire("fx-compute", "click");
out.back = calls.slice(k).filter(c => c.url.endsWith("/compute"));
// 함수 카드 — 「이 예시로 바꾸기」 는 고른 칸 전체를 바꾸고, 「변수」 처럼 식이 아닌 카드에는 단추가 없다
el("fx-ref-target").value = "fx-sell";
const cards = found["fx-fn"] || [];
out.cardButtons = cards.map(c => c.dataset.i);
await cards[0].on.click[0](); await tick();
out.card = { sell: el("fx-sell").value, buy: el("fx-buy").value, current: el("fx-current").textContent };
out.functionsHtml = el("fx-functions").innerHTML;
process.stdout.write(JSON.stringify(out));
"""

STUB_COMMON = """export const api = (...a) => globalThis.__api(...a);
export const setToast = () => {};
export const escHtml = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmt = v => String(v);
"""


@pytest.fixture(scope="module")
def flow(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 모듈을 돌릴 수 없다")
    d = tmp_path_factory.mktemp("fx")
    (d / "common.js").write_text(STUB_COMMON, encoding="utf-8")
    (d / "formula-guide.js").write_text("export function initFormulaGuide() {}\n"
                                        "export const functionHelp = { rsi: ['상승 하락 강도', 'RSI 예시'], abs: ['크기 다듬기', 'clip 예시'] };\n",
                                        encoding="utf-8")
    (d / "formula-chart-help.js").write_text("export function renderFormulaChartHelp() {}\n", encoding="utf-8")
    src = (JS / "formula.js").read_text(encoding="utf-8").replace('from "/js/', 'from "./')
    (d / "formula.js").write_text(src, encoding="utf-8")
    script = d / "flow.mjs"
    script.write_text(NODE_FLOW.replace("__SAVED__", json.dumps(SAVED, ensure_ascii=False))
                      .replace("__FORMULA__", (d / "formula.js").as_uri()), encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_연_지표를_고치지_않으면_저장본_경로로_계산한다(flow):
    assert flow["openedCurrent"] == "평균 대비 · 저장된 v3"
    assert [c["url"] for c in flow["unchanged"]] == ["/api/formula-indicators/A/compute"]
    assert "indicator_expr" not in flow["unchanged"][0]["body"]  # 저장본 경로는 식을 보내지 않는다 — 서버가 판을 읽는다
    assert "v3" in flow["unchangedMeta"]


def test_연_지표의_식을_고치면_저장본이_아니라_고친_식을_미리보기로_계산한다(flow):
    assert [c["url"] for c in flow["edited"]] == ["/api/formula-indicators/compute"]
    body = flow["edited"][0]["body"]
    assert body["buy_expr"] == "zscore(close, n) < -1" and body["indicator_expr"] == SAVED["indicator_expr"]
    assert "미리보기 · 결과 미저장" in flow["editedMeta"]
    assert flow["dirty"] == {"current": "평균 대비 · v3에서 수정 중 · 계산은 입력값 미리보기", "resultHidden": True,
                             "validate": "입력이 바뀌었습니다. 산식을 다시 확인하세요."}


def test_고친_식을_저장본과_같게_되돌리면_다시_저장본_경로다(flow):
    # 숫자 설정 20 과 서버의 20.0 은 같은 값으로 본다
    assert [c["url"] for c in flow["back"]] == ["/api/formula-indicators/A/compute"]


def test_함수_카드는_고른_입력칸만_예시로_바꾸고_식이_아닌_카드에는_단추가_없다(flow):
    assert flow["cardButtons"] == ["0", "1"]  # 「변수」 카드(2)에는 단추가 없다
    assert flow["card"]["sell"] == "rsi(close, 14)"
    assert flow["card"]["buy"] == SAVED["buy_expr"]  # 고르지 않은 칸은 그대로
    assert flow["card"]["current"] == "평균 대비 · v3에서 수정 중 · 계산은 입력값 미리보기"  # 바꾸면 수정 중으로
    assert "상승 하락 강도" in flow["functionsHtml"] and "크기 다듬기" in flow["functionsHtml"]  # abs, … 줄도 뜻을 찾는다


# ── 비용 인자 — 커스텀 · 자유 산식 두 경로 ─────────────────────────────────
def _pipeline_custom(monkeypatch, **cost):
    async def fake_candles(symbol, period, interval):
        return {"candles": make_candles(400)}

    monkeypatch.setattr(stocks, "get_candles", fake_candles)
    args = dict(cost_bps=None, cost_model=None, slippage_bps=None)
    args.update(cost)
    return asyncio.run(stocks.quant_pipeline_indicator_backtest(
        symbol="005930.KS", period="10y", base="macd_bb", short=5, mid=20, rsi=14, buy_th=35.0,
        strategy="custom", market=None, stop_loss_pct=None, take_profit_pct=None, _user=None,
        entry_mode="close", exit_mode="close", **args,
    ))


def test_커스텀_경로는_화면의_비용_입력을_수익률에서_뗀다(monkeypatch):
    free = _pipeline_custom(monkeypatch, cost_bps=0.0, slippage_bps=0.0)
    paid = _pipeline_custom(monkeypatch, cost_bps=50.0, slippage_bps=0.0)
    assert paid["trade_count"] == free["trade_count"] > 0
    assert paid["cost"]["model"] == "flat" and paid["costs"]["commission_bps"] == 50.0
    assert paid["return_total"] < free["return_total"]
    assert paid["return_gross"] == free["return_gross"]  # 비용 전 수익률은 같다 — 다른 것은 비용뿐


def test_자유_산식_경로는_비용_인자를_수익률에서_뗀다(monkeypatch):
    async def fake_candles(symbol, period, interval):
        return {"candles": make_candles(400)}

    monkeypatch.setattr(formula_route, "get_candles", fake_candles)
    defn = {"indicator_expr": "rsi(close, 14)", "buy_expr": "rsi(close, 14) < 45", "sell_expr": "rsi(close, 14) > 55", "params": {}}
    run = lambda **c: asyncio.run(formula_route._run(defn, formula_route.ComputeBody(**c)))["backtest"]
    free, paid = run(), run(commission_bps=50.0, slippage_bps=10.0)
    assert paid["trade_count"] == free["trade_count"] > 0
    assert paid["cost_pct"] > 0 == free["cost_pct"]
    assert paid["total_return_pct"] < free["total_return_pct"]
