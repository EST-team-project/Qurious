"""#212 화면의 상태·요청 수량·실제 체결 수량을 JS 렌더러로 검증한다."""
import base64
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NODE = os.environ.get("QURIOUS_NODE_EXECUTABLE") or shutil.which("node")


@unittest.skipUnless(NODE, "Node.js 필요 (QURIOUS_NODE_EXECUTABLE로 지정 가능)")
class TradeStatusScreenTest(unittest.TestCase):
    def test_emergency_cancel_notice_distinguishes_pending_and_unknown(self):
        source = (ROOT / 'public/js/quant.js').read_text(encoding='utf-8')
        handler = source.split('document.getElementById("risk-kill-on").addEventListener', 1)[1]
        handler = 'document.getElementById("risk-kill-on").addEventListener' + handler.split(
            'document.getElementById("risk-kill-off")', 1)[0]
        script = r'''
import assert from 'node:assert/strict';
let click, confirmation, response, toast, refreshes=0;
const calls=[];
const document={getElementById:()=>({addEventListener:(event,fn)=>{click=fn;}})};
const confirm=text=>{confirmation=text;return true;};
const api=async (path,options)=>{calls.push({path,options});return response;};
const setToast=(text,level)=>{toast={text,level};};
const loadAutoTradeStatus=()=>{refreshes++;};
''' + handler + r'''
response={cancellation:{requested:1,pending:2,unknown:0,failed:0,skipped:0}};
await click();
assert.match(confirmation,/KIS 직접 모의 주문/);
assert.equal(calls[0].path,'/api/quant/risk/kill-switch');
assert.equal(calls[0].options.body.enabled,true);
assert.match(toast.text,/취소 요청 1건/);
assert.match(toast.text,/기존 취소 확인 대기 2건/);
assert.match(toast.text,/취소 확정 전에는 체결될 수 있습니다/);
assert.equal(toast.level,'ok');
response={cancellation:{requested:0,pending:0,unknown:1,failed:0,skipped:0}};
await click();
assert.equal(toast.level,'error');
assert.match(toast.text,/결과 미확인 1건/);
assert.match(toast.text,/증권사에서 확인/);
assert.equal(calls.length,2);assert.equal(refreshes,2);
'''
        done = subprocess.run([NODE, '--input-type=module', '-'], input=script, text=True,
                              encoding='utf-8', capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_failure_pending_fill_and_html_escaping(self):
        source = (ROOT / 'public/js/trade-status.js').read_bytes()
        url = 'data:text/javascript;base64,' + base64.b64encode(source).decode()
        script = 'import assert from "node:assert/strict";\n'
        script += f'const {{renderTradeExecution: render}} = await import({json.dumps(url)});\n'
        script += r'''
const esc = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const trade = {action: 'buy', name: '<script>bad()</script>', quantity: 3, price: 217500};
const fail = render({...trade, execution: {label: '증권사 주문 실패', level: 'error', virtual_status: 'not_recorded', ledger: '가상 장부 미반영'}}, esc, String);
assert.match(fail, /증권사 주문 실패/);
assert.match(fail, /var\(--red\)/);
assert.match(fail, /주문 요청 3주/);
assert.doesNotMatch(fail, /<script>|🟢|가상 기록 3주/);
const pending = render({...trade, execution: {label: '증권사 접수·체결 미확인', level: 'warning'}}, esc, String);
assert.match(pending, /체결 미확인/);
assert.doesNotMatch(pending, /var\(--green\)/);
const partial = render({...trade, execution: {label: '증권사 일부 체결', level: 'warning', filled_quantity: 1, avg_filled_price: 217400}}, esc, String);
assert.match(partial, /주문 요청 3주 @217500/);
assert.match(partial, /증권사 확인 1주 @217400/);
const sized = render({...trade, price_basis: {sizing: {binding_limits: ['budget'], estimated_loss: 100, stop_price: 900}, stop: {origin: 'transition', stop_kind: 'atr', stop_price: 900}}}, esc, String);
assert.match(sized, /수량 제한: 1회 예산/);
assert.match(sized, /전환 시 고정 손절 900원/);
const legacy = render({...trade, execution: {label: '증권사 주문 실패', level: 'error', virtual_status: 'filled', ledger: '가상 장부에만 기록됨'}}, esc, String);
assert.match(legacy, /가상 기록 3주/);
assert.match(legacy, /가상 장부에만 기록됨/);
const etf = render({...trade, symbol: '360750.KS', price_basis: {instrument: {is_etf: true, warnings: ['LP <경고>'], close_nav_premium_pct: .5, premium_as_of: '2026-10-30'}}}, esc, String);
assert.match(etf, /data-hub-open="360750"/);
assert.match(etf, /LP &lt;경고&gt;/);
assert.match(etf, /2026-10-30/);
assert.match(etf, /장중 iNAV 아님/);
'''
        subprocess.run([NODE, '--input-type=module', '-'], input=script, text=True, encoding="utf-8", check=True, capture_output=True)


@unittest.skipUnless(NODE, "Node.js 필요 (QURIOUS_NODE_EXECUTABLE로 지정 가능)")
class RiskDisplayEscapingTest(unittest.TestCase):
    """P02-⑤-2/3: 실제 회차·위험관리 렌더러가 저장 기록을 HTML로 실행하지 않는다."""

    def run_renderer(self, body):
        quant = (ROOT / 'public/js/quant.js').read_text(encoding='utf-8')
        common = (ROOT / 'public/js/common.js').read_text(encoding='utf-8')
        functions = [re.search(r'export (function escHtml\(s\) \{.*?\n\})', common, re.S).group(1)]
        for name in ('autoCycleHtml', 'loadRiskStatus'):
            functions.append(re.search(r'(?:async )?function ' + name + r'\([^\n]*\) \{.*?\n\}', quant, re.S).group())
        script = 'import assert from "node:assert/strict";\n' + '\n'.join(functions) + r'''
const elements = new Map();
const document = {getElementById(id) { if (!elements.has(id)) elements.set(id, {}); return elements.get(id); }};
const fmt = String, kstTime = String;
const payload = '<img src=x onerror="globalThis.injected=1">';
''' + body
        done = subprocess.run([NODE, '--input-type=module', '-'], input=script, text=True, encoding="utf-8",
                              capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_cycle_risk_numbers_are_text_and_zero_is_preserved(self):
        self.run_renderer(r'''
for (const key of ['day_pnl_pct', 'orders_today']) {
  const html = autoCycleHtml({risk: {day_pnl_pct: 0, orders_today: 0, [key]: payload}});
  assert.doesNotMatch(html, /<img/);
  assert.ok(html.includes(escHtml(payload)));
}
const normal = autoCycleHtml({risk: {day_pnl_pct: -1.25, orders_today: 0}});
assert.match(normal, /당일 -1.25%/); assert.match(normal, /주문 0건/);
assert.match(autoCycleHtml({risk: {}}), /당일 -%/);
''')

    def test_risk_kpis_escape_values_and_keep_existing_labels(self):
        self.run_renderer(r'''
let response;
const api = async () => response;
for (const key of ['day_pnl_pct', 'orders_today', 'daily_loss_limit_pct', 'max_orders_per_day', 'max_position_pct', 'cooldown_min']) {
  response = {day_pnl_pct: 0, orders_today: 0, limits: {}, [key]: payload}; response.limits[key] = payload;
  await loadRiskStatus();
  const html = elements.get('risk-kpis').innerHTML;
  assert.doesNotMatch(html, /<img/); assert.ok(html.includes(escHtml(payload)), key);
}
response = {day_pnl_pct: 1.25, orders_today: 0, limits: {daily_loss_limit_pct: 3, max_orders_per_day: 20, max_position_pct: 30, cooldown_min: 0}};
await loadRiskStatus();
const normal = elements.get('risk-kpis').innerHTML;
for (const text of ['+1.25%', '0건', '한도 -3%', '최대 20', '30%', '0분', 'OFF']) assert.ok(normal.includes(text), text);
response = {day_pnl_pct: null, limits: {}}; await loadRiskStatus();
assert.ok(elements.get('risk-kpis').innerHTML.includes('∞'));
''')


if __name__ == '__main__':
    unittest.main()
