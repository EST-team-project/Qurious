"""#212 화면의 상태·요청 수량·실제 체결 수량을 JS 렌더러로 검증한다."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NODE = os.environ.get("QURIOUS_NODE_EXECUTABLE") or shutil.which("node")


@unittest.skipUnless(NODE, "Node.js 필요 (QURIOUS_NODE_EXECUTABLE로 지정 가능)")
class TradeStatusScreenTest(unittest.TestCase):
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
        subprocess.run([NODE, '--input-type=module', '-'], input=script, text=True, check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
