"""실제 리밸런싱 HTML/JS의 국면 연결·편집 충돌·이력 흐름. API는 고정 응답."""
import json
from pathlib import Path
import re

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = re.sub(r"<script\b[^>]*>.*?</script>", "", (ROOT / "public/app.html").read_text(), flags=re.S)
COMMON = """
export * from '/js/common-actual.js';
export const api = async (url, opts={}) => {
  window.calls.push({url,...opts});
  if(url.includes('/allocation/latest')) return window.saved;
  if(url==='/api/rebalance/status') return {plan:window.plan,snapshot:null};
  if(url==='/api/rebalance/target-changes') return {changes:window.changes};
  if(url==='/api/rebalance/plan') {
    if(opts.body.expected_updated_at!==window.plan.updated_at) throw Error('다른 화면이나 자동 점검에서 플랜을 변경했습니다.');
    window.plan={...window.plan,...opts.body,updated_at:'2026-11-03T07:01:00Z'};
    return window.plan;
  }
  if(url.includes('/runs')) return {runs:[]};
  if(url.includes('/cashflows')) return {events:[]};
  throw Error('예상하지 않은 요청: '+url);
};
export const setToast = s => window.toasts.push(s);
export const escHtml = s => String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;');
export const fmt = s => String(s??0);
export const fmtPct = fmt;
"""


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        def route(r):
            path = r.request.url.removeprefix("http://qurious.test")
            if path == "/":
                r.fulfill(body=HTML, content_type="text/html")
            elif path == "/js/common.js":
                r.fulfill(body=COMMON, content_type="text/javascript")
            elif path == "/js/common-actual.js":
                r.fulfill(body=(ROOT / "public/js/common.js").read_text(), content_type="text/javascript")
            elif path.startswith("/js/") and (ROOT / "public" / path.lstrip("/")).is_file():
                r.fulfill(body=(ROOT / "public" / path.lstrip("/")).read_text(), content_type="text/javascript")
            else:
                r.abort()
        page.route("**/*", route)
        page.goto("http://qurious.test")
        page.evaluate("""() => {
          window.calls=[]; window.toasts=[]; window.changes=[];
          window.plan={targets:[{symbol:'005930.KS',name:'기존',weight_pct:60}],auto_execute:false,
            updated_at:'2026-11-03T07:00:00Z',drift_threshold_pct:5,cashflow_min_amount:100000,
            min_order_amount:10000,regime_auto:{enabled:false}};
          window.saved={id:'b68c8c9b-e417-40e5-b055-f19420a9dd2c',saved_at:'2026-11-03T06:00:00Z',
            result:{allocation_model:'regime'},
            handoff:{targets:[{symbol:'005930.KS',name:'삼성전자',weight_pct:22.5}],domestic_weight_pct:22.5,
              cash_weight_pct:77.5,unapplied_allocations:{해외주식:18.7,국내채권:39.6,대체자산:10},message:'국내주식만 적용'}};
        }""")
        page.evaluate("""async () => {
          const rb=await import('/js/rebalance.js'); rb.initRebalanceView();
          rb.onRebalanceViewActivated('robo-rebalance');
        }""")
        page.wait_for_function("document.querySelector('.rb-w')?.value==='60'")
        click = lambda s: page.locator(s).evaluate("e=>e.click()")
        assert page.locator("#rb-regime-auto").is_disabled()
        page.once("dialog", lambda d: d.accept())
        click("#rb-import-allocation")
        page.wait_for_function("document.querySelector('.rb-w')?.value==='22.5'")
        assert not page.locator("#rb-regime-auto").is_disabled()
        assert not page.locator("#rb-regime-auto").is_checked()
        assert not page.evaluate("calls.some(c=>c.method)")
        click("#rb-regime-auto")
        click("#rb-refresh")
        page.wait_for_timeout(100)
        assert page.locator("#rb-regime-auto").is_checked()
        assert page.locator(".rb-w").input_value() == "22.5"
        click("#rb-save")
        page.wait_for_function("calls.some(c=>c.method==='PUT')")
        page.wait_for_timeout(100)
        body = page.evaluate("calls.find(c=>c.method==='PUT').body")
        assert body["expected_updated_at"] == "2026-11-03T07:00:00Z"
        assert body["regime_auto"]["allocation_id"] == page.evaluate("saved.id")
        assert body["regime_auto"]["enabled"] and not body["auto_execute"]
        # 직접 편집은 자동 변경을 끄며, 서버 갱신 후에는 오래된 편집 저장을 거부한다.
        page.locator(".rb-w").evaluate("e=>{e.value='19';e.dispatchEvent(new Event('input',{bubbles:true}));}")
        assert not page.locator("#rb-regime-auto").is_checked()
        assert page.locator("#rb-regime-auto").is_disabled()
        page.evaluate("""() => {window.plan.updated_at='2026-11-03T07:02:00Z';
          window.plan.targets[0].weight_pct=17; window.plan.regime_auto={enabled:true};}""")
        click("#rb-refresh")
        page.wait_for_timeout(100)
        assert page.locator(".rb-w").input_value() == "19"
        click("#rb-save")
        page.wait_for_function("toasts.some(t=>t.includes('다른 화면이나 자동 점검'))")
        assert page.locator(".rb-w").input_value() == "19"
        page.once("dialog", lambda d: d.accept())
        click("#rb-discard")
        page.wait_for_function("document.querySelector('.rb-w')?.value==='17'")
        assert page.locator("#rb-regime-auto").is_checked()
        page.evaluate("""window.changes=[{id:'x',data_as_of:'2026-11-02',created_at:'2026-11-03T07:00:00Z',
          before_targets:[{symbol:'005930.KS',name:'<검증>',weight_pct:33}],
          after_targets:[{symbol:'005930.KS',name:'<검증>',weight_pct:22.5}],
          evidence:{from_regime:'up_low',to_regime:'down_low',regime:{rule:'추세·변동성'}}}]""")
        page.locator("#rb-regime-history-load").evaluate("e=>e.closest('details').querySelector('summary').click()")
        click("#rb-regime-history-load")
        page.wait_for_function("document.getElementById('rb-regime-history').textContent.includes('77.50%')")
        assert "상승·저변동 → 하락·저변동" in page.locator("#rb-regime-history").inner_text()
        assert page.locator("#rb-regime-history 검증").count() == 0
        click("#rb-regime-auto")
        click("#rb-save")
        page.wait_for_function("calls.filter(c=>c.method==='PUT').length===3")
        assert page.evaluate("calls.filter(c=>c.method==='PUT').at(-1).body.regime_auto.enabled") is False
        assert not page.evaluate("calls.some(c=>c.method==='POST')")
        assert not errors, errors
        browser.close()
    print(json.dumps({"browser": "chromium", "flows": 8, "status": "passed"}))


if __name__ == "__main__":
    main()
