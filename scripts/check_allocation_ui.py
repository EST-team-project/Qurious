"""선택 실행: playwright + Chromium으로 실제 HTML/JS의 배분 전달을 확인한다.

python scripts/check_allocation_ui.py
API만 고정 응답으로 대체한다. 실서버·계정·주문에는 접속하지 않는다.
"""
import json
from pathlib import Path
import re

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = re.sub(r"<script\b[^>]*>.*?</script>", "", (ROOT / "public/app.html").read_text(), flags=re.S)
COMMON = """
export const api = async (url, opts={}) => {
  window.calls.push({url, ...opts});
  if (url.includes('/allocation/latest')) { if(window.missing) throw Error('저장된 배분 결과가 없습니다.'); return window.saved; }
  if (url === '/api/ml/robo/allocation') return {...window.saved.result, saved: window.saved};
  if (url === '/api/rebalance/plan') {window.plan = {...window.plan, ...opts.body}; return {};}
  if (url === '/api/rebalance/status') return {plan: window.plan, snapshot: null};
  if (url.includes('/runs')) return {runs:[]};
  if (url.includes('/cashflows')) return {events:[]};
  throw Error('Unexpected API: '+url);
};
export const setToast = (s) => window.toasts.push(s);
export const getMe = () => null;
export const escHtml = s => String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;');
export const fmt = s => String(s??0);
export const fmtPct = fmt;
export const colorPct = () => '';
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
            elif path == "/js/core.js":
                r.fulfill(body="export const tt = s => s;", content_type="text/javascript")
            elif path in ("/js/rebalance.js", "/js/robo.js"):
                r.fulfill(body=(ROOT / "public" / path.lstrip("/")).read_text(), content_type="text/javascript")
            else:
                r.abort()
        page.route("**/*", route)
        page.goto("http://qurious.test")
        page.evaluate("""() => {
          window.calls=[]; window.toasts=[];
          window.plan={targets:[{symbol:'000660.KS',name:'기존',weight_pct:60}],auto_execute:true,
            drift_threshold_pct:5,cashflow_min_amount:100000,min_order_amount:10000};
          window.saved={id:'test',saved_at:'2026-10-14T00:00:00Z',result:{risk_profile:'moderate',horizon_years:3,
            amount_manwon:5000,allocations:{국내주식:30,해외주식:25,국내채권:30,대체자산:10,현금:5},
            stock_picks:[{name:'삼성전자',code:'005930.KS',weight:30}],projections:[],optimization:{}},
            handoff:{targets:[{symbol:'005930.KS',name:'삼성전자',weight_pct:30}],domestic_weight_pct:30,
            cash_weight_pct:70,unapplied_allocations:{해외주식:25,국내채권:30,대체자산:10},message:'국내주식만 적용'}};
        }""")
        page.evaluate("""async () => {
          const rb=await import('/js/rebalance.js'); rb.initRebalanceView();
          rb.onRebalanceViewActivated('robo-rebalance'); await import('/js/robo.js');
        }""")
        page.wait_for_function("document.querySelector('.rb-w')?.value === '60'")
        click = lambda selector: page.locator(selector).evaluate("el => el.click()")
        # 취소: 기존 편집값과 자동 실행 설정을 유지한다.
        page.once("dialog", lambda d: d.dismiss())
        click("#rb-import-allocation")
        page.wait_for_function("!document.getElementById('rb-import-allocation').disabled")
        assert page.locator(".rb-w").input_value() == "60"
        assert page.locator("#rb-auto").is_checked()
        # 확인: 편집안만 변경. 미리보기/조건 점검도 저장 전에는 서버 요청하지 않는다.
        page.once("dialog", lambda d: d.accept())
        click("#rb-import-allocation")
        page.wait_for_function("document.querySelector('.rb-w')?.value === '30'")
        assert not page.locator("#rb-auto").is_checked()
        click("#rb-preview")
        click("#rb-check")
        click("#rb-refresh")
        page.wait_for_function("window.toasts.length >= 3")
        assert page.locator(".rb-w").input_value() == "30"
        assert not page.evaluate("calls.some(c => c.method)")
        # 명시적 저장 때만 PUT, 새 목표와 자동 실행 꺼짐을 함께 보낸다.
        click("#rb-save")
        page.wait_for_function("calls.some(c => c.method === 'PUT')")
        writes = page.evaluate("calls.filter(c => c.method)")
        assert len(writes) == 1 and writes[0]["body"]["auto_execute"] is False
        assert writes[0]["body"]["targets"][0]["symbol"] == "005930.KS"
        # 저장본 복원 + 다시 계산한 결과 렌더링.
        click("#robo-load-allocation")
        page.wait_for_function("document.getElementById('robo-allocation-saved').textContent.includes('저장됨')")
        assert "30%" in page.locator("#robo-stock-picks").inner_text()
        click("#robo-optimize-btn")
        page.wait_for_function("calls.some(c => c.url === '/api/ml/robo/allocation')")
        page.wait_for_function("!document.getElementById('robo-optimize-btn').disabled")
        # 저장본 없음: 기존 목표 유지 + 오류 표시.
        page.evaluate("window.missing=true")
        click("#rb-import-allocation")
        page.wait_for_function("toasts.some(s => s.includes('저장된 배분 결과가 없습니다'))")
        assert page.locator(".rb-w").input_value() == "30"
        assert errors == [], errors
        assert not page.evaluate("calls.some(c => c.url.includes('/execute'))")
        browser.close()
        print(json.dumps({"browser": "chromium", "flows": 7, "status": "passed"}))


if __name__ == "__main__":
    main()
