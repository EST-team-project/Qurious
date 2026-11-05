"""실제 JS 함수로 ETF 가져오기 취소/실패/저장 전 차단과 허브 종목 전달을 검사한다."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = os.environ.get("QURIOUS_NODE_EXECUTABLE") or shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="Node.js 필요")


def plain_module(path):
    """브라우저 ES 모듈 글을 vm 스크립트로 돌리도록 import 문 · export 를 뗀다(2026-11-05 · rebalance.js 가 필터 칩 모듈을 가져오게 되어 함께 싣는다)."""
    text = (ROOT / path).read_text(encoding="utf-8")
    text = re.sub(r'^import \{[^}]*\} from "[^"]+";[^\n]*\n', "", text, flags=re.M)
    return re.sub(r"^export ", "", text, flags=re.M)


def run_js(script):
    result = subprocess.run([NODE, "--input-type=module", "-"], input=script, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_etf_import_cancel_error_confirm_and_saved_plan_are_separate():
    source = "\n".join(plain_module(f"public/js/{name}.js") for name in ("listbar", "paperlists", "screenlists", "rebalance"))
    script = r'''
import assert from 'node:assert/strict';
import vm from 'node:vm';
const elements = new Map();
const el = id => {
  if (!elements.has(id)) elements.set(id, {value: '', checked: false, disabled: false, textContent: '', innerHTML: '', querySelectorAll: () => []});
  return elements.get(id);
};
let confirmation = false, fail = false;
const calls = [], messages = [];
const draft = {targets: [{symbol: '360750.KS', name: 'ETF <이름>', weight_pct: 25}], domestic_weight_pct: 0,
  cash_weight_pct: 75, etf_weight_pct: 25, unapplied_allocations: {국내채권: 30},
  selected_etfs: [{asset_class: '해외주식', name: 'ETF <이름>', as_of: '2026-10-30', reason: '유동성 기준'}], message: '일부 후보 없음'};
const context = vm.createContext({console, document: {getElementById: el},
  confirm: text => {messages.push(text); return confirmation;},
  setToast: (...args) => messages.push(args.join(' ')),
  escHtml: text => String(text).replaceAll('<', '&lt;').replaceAll('>', '&gt;'), fmt: String,
  api: async (path, options) => {calls.push({path, options}); if(fail) throw Error('오래된 ETF 자료');
    return {handoff: draft, saved_at: '2026-10-30T16:00:00+09:00'};}});
'''
    script += "vm.runInContext(" + json.dumps(source) + ", context);\n"
    script += r'''
vm.runInContext("targetRows = [{symbol: '005930.KS', name: '기존 목표', weight_pct: 60}]; lastProposal={orders:[1]};", context);
el('rb-auto').checked = true;
el('rb-import-etfs').checked = true;
await vm.runInContext('importAllocation()', context);
assert.equal(calls[0].path, '/api/ml/robo/allocation/latest?include_etfs=true');
assert.equal(vm.runInContext('targetRows[0].symbol', context), '005930.KS');
assert.equal(el('rb-auto').checked, true);
assert.equal(vm.runInContext('lastProposal.orders.length', context), 1);
confirmation = true;
fail = true;
await vm.runInContext('importAllocation()', context);
assert.equal(vm.runInContext('targetRows[0].symbol', context), '005930.KS');
assert.equal(el('rb-import-allocation').disabled, false);
fail = false;
await vm.runInContext('importAllocation()', context);
assert.equal(el('rb-auto').checked, false);
assert.equal(el('rb-execute').disabled, true);
assert.equal(vm.runInContext('lastProposal', context), null);
assert.match(el('rb-targets-body').innerHTML, /ETF &lt;이름&gt;/);
assert.match(el('rb-allocation-note').textContent, /국내 상장 ETF 25%/);
assert.match(el('rb-allocation-note').textContent, /2026-10-30 기준/);
assert.match(el('rb-allocation-note').textContent, /기존 플랜·예약은 유지/);
const count = calls.length;
await vm.runInContext('previewRebalance()', context);
await vm.runInContext('executeRebalance()', context);
assert.equal(calls.length, count);
assert(calls.every(x => !x.options)); // GET만; 서버 플랜/예약/주문 변경 없음
el('rb-import-etfs').checked = false;
confirmation = false;
await vm.runInContext('importAllocation()', context);
assert.equal(calls.at(-1).path, '/api/ml/robo/allocation/latest');
'''
    run_js(script)


def test_hub_handoff_prefills_symbol_and_clears_weight_without_click_or_save():
    uri = (ROOT / "public/js/stockdrawer.js").as_uri()
    run_js(f"import * as drawer from {json.dumps(uri)};\n" + r'''
import assert from 'node:assert/strict';
const fields = {'rb-add-symbol': {value: 'old'}, 'rb-add-weight': {value: '80', focus() {this.focused = true;}}};
const visited = [];
const doc = {getElementById: id => fields[id]};
drawer.openViewForSymbol('robo-rebalance', '360750', 'ETF', {navigate: v => visited.push(v), doc});
assert.equal(fields['rb-add-symbol'].value, '360750');
assert.equal(fields['rb-add-weight'].value, '');
assert(fields['rb-add-weight'].focused);
assert.deepEqual(visited, ['robo-rebalance']);
drawer.openViewForSymbol('robo-rebalance', '<bad>', 'bad', {navigate() {}, doc});
assert.equal(fields['rb-add-symbol'].value, '360750');
const html = drawer.stockDrawerHtml({symbol: '360750', sections: {}});
assert.match(html, /data-hub-go="robo-rebalance"/);
assert.match(html, /종목코드만 전달/);
''')


def test_same_cycle_record_keeps_strategy_score_and_provenance_across_views():
    from app.services.decision_signal_view import signal_view
    record = signal_view({"symbol": "005930.KS", "action": "매수", "score": 2,
                         "basis": {"as_of": "2026-10-30", "interval": "1d"}},
                        {"aggressive": False}, "2026-11-02T01:00:00Z")
    source = (ROOT / "public/js/decision-signals.js").as_uri()
    script = f"import {{latestCycleSignals, renderDecisionBasis}} from {json.dumps(source)};\n"
    script += "const record = " + json.dumps(record, ensure_ascii=False) + ";\n"
    script += r'''
import assert from 'node:assert/strict';
const old = {...record, cycle_at: '2026-10-30T01:00:00Z', score: -9,
  decision: {...record.decision, score_text: '다른 전략 점수 -9'}};
const own = {...record, source: 'me'};
const batch = {...record, source: 'batch', score: -3, decision: {...record.decision, score_text: '시스템 전략 점수 -3'}};
const latest = latestCycleSignals([old, own, {...own}, batch]);
assert.equal(latest.length, 2); // 같은 회차라도 내 전략과 시스템 배치를 합치지 않는다.
const quant = renderDecisionBasis(own, String, String);
const robo = renderDecisionBasis(latest.find(s => s.source === 'me'), String, String);
assert.equal(quant, robo);
assert.match(quant, /기본 일봉/);
assert.match(quant, /2026-10-30/);
assert.match(quant, /2026-11-02T01:00:00Z/);
assert.doesNotMatch(quant, /다른 전략 점수|시스템 전략 점수/);
assert.match(renderDecisionBasis(batch, String, String), /시스템 배치/);
'''
    run_js(script)
    for view in ("quant.js", "robo.js"):
        assert 'from "/js/decision-signals.js"' in (ROOT / "public/js" / view).read_text()
