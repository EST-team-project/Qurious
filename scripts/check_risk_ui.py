"""선택 실행: Playwright Chromium으로 #162 위험 안내/비상 정지 화면 검증.

실제 HTML/JS를 사용하고 API는 고정 응답으로 대체한다. 주문 서버에 접속하지 않는다.
"""
import json
from pathlib import Path
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.risk_execution import execution_guidance  # noqa: E402


def main():
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", (ROOT / "public/app.html").read_text(), flags=re.S)
    common = """
export const api = async (url, opts={}) => {
 window.calls.push({url,...opts});
 if(url==='/api/quant/risk/status') return window.risk;
 if(url==='/api/auto-trade/status') return {running:false,log:[]};
 if(url==='/api/quant/risk/kill-switch') return {cancellation:{requested:0,failed:1,skipped:0}};
 throw Error('Unexpected API '+url);
};
export const getMe=()=>null;
export const setToast=(s)=>window.toasts.push(s);
export const escHtml=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;');
export const fmt=s=>String(s??0); export const fmtPct=fmt; export const colorPct=()=>'';
"""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        def serve(route):
            path = route.request.url.removeprefix("http://qurious.test")
            if path == "/":
                route.fulfill(body=html, content_type="text/html")
            elif path == "/js/common.js":
                route.fulfill(body=common, content_type="text/javascript")
            elif path == "/js/core.js":
                route.fulfill(body="export const compareTrayAdd=()=>{}; export const renderCompareTrayAll=()=>{};", content_type="text/javascript")
            elif path == "/js/quant.js":
                route.fulfill(body=(ROOT / "public/js/quant.js").read_text(), content_type="text/javascript")
            else:
                route.abort()
        page.route("**/*", serve)
        page.goto("http://qurious.test")
        page.evaluate("g => {window.calls=[]; window.toasts=[]; window.risk={limits:{},execution_guidance:g};}", execution_guidance())
        page.evaluate("async () => {const q=await import('/js/quant.js'); await q.loadAutoTradeStatus();}")
        page.wait_for_function("document.getElementById('risk-execution-detail').textContent.includes('초 간격')")
        guidance = page.locator("#risk-execution-detail").text_content()
        assert "상주 감시 주문이 아니며" in guidance
        cost_text = page.locator("#risk-cost-example").text_content()
        assert "편도 슬리피지 0bp" in cost_text and "편도 슬리피지 10bp" in cost_text
        assert "실제 승률 예측이 아닙니다" in cost_text
        page.once("dialog", lambda d: d.dismiss())
        page.locator("#risk-kill-on").evaluate("el => el.click()")
        assert not page.evaluate("calls.some(c=>c.method)")
        def accept(dialog):
            assert "자동 청산하지 않습니다" in dialog.message
            dialog.accept()
        page.once("dialog", accept)
        page.locator("#risk-kill-on").evaluate("el => el.click()")
        page.wait_for_function("toasts.some(s=>s.includes('취소 실패'))")
        writes = page.evaluate("calls.filter(c=>c.method)")
        assert len(writes) == 1 and writes[0]["body"]["enabled"] is True
        assert not errors, errors
        browser.close()
        print(json.dumps({"browser": "chromium", "flows": 3, "status": "passed"}))


if __name__ == "__main__":
    main()
