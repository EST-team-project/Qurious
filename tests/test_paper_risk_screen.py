import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_sizing_handoff_clears_old_quantity_and_ignores_late_response(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 필요")
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / "screen.mjs"
    script.write_text('import {mountPaperRisk} from ' + json.dumps((root / 'public/js/paper-risk.js').as_uri()) + ';\n' + r'''
import assert from 'node:assert/strict';
const nodes = {};
const values = {'ps-symbol':'005930', 'ps-qty':'999', 'ps-risk-pct':'1', 'ps-risk-budget':'1000000',
 'ps-risk-cap':'30', 'ps-risk-kind':'pct', 'ps-risk-stop':'1', 'ps-risk-atr':'2', 'ps-risk-slippage':'10',
 'ps-risk-result':'', 'ps-risk-calc':''};
for(const [id,value] of Object.entries(values)) nodes[id]={value,handlers:{},addEventListener(k,f){this.handlers[k]=f;}};
let resolve; const requests=[];
mountPaperRisk({doc:{getElementById:id=>nodes[id]},api:async (url,opts)=>{
 requests.push(opts.body); return await new Promise(r=>{resolve=r;});
}});
const result={quantity:3,equity:1000000,cash:900000,price:10000,stop_price:9900,estimated_loss:300,
 binding_limits:['budget'],basis:{},note:'스탑 자동 등록 없음'};
const one=nodes['ps-risk-calc'].handlers.click();
assert.equal(nodes['ps-qty'].value,'');
nodes['ps-symbol'].value='000660'; nodes['ps-symbol'].handlers.input();
resolve(result);await one;assert.equal(nodes['ps-qty'].value,'');
const two=nodes['ps-risk-calc'].handlers.click();
nodes['ps-symbol'].value='000660.KS'; // 정규화만 된 응답은 적용
resolve(result);await two;assert.equal(nodes['ps-qty'].value,'3');
assert.ok(nodes['ps-risk-result'].textContent.includes('스탑 자동 등록 없음'));
const three=nodes['ps-risk-calc'].handlers.click();
nodes['ps-qty'].value='7';nodes['ps-qty'].handlers.input();
resolve(result);await three;assert.equal(nodes['ps-qty'].value,'7');
assert.equal(requests[0].symbol,'005930');assert.equal(requests[1].symbol,'000660');
''')
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
