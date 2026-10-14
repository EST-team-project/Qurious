"""실제 설정 HTML/JS + 고정 API 응답으로 선택 기능 저장·복원 확인."""
import json
from pathlib import Path
import re

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", (ROOT / "public/app.html").read_text(), flags=re.S)
    common = """
export const api = async (url, opts={}) => {
 window.calls.push({url,...opts});
 if(url==='/api/quant/settings') {
   if(opts.method) {window.cfg={...window.cfg,...opts.body}; return {ok:true};}
   return window.cfg;
 }
 return {};
};
export const getMe=()=>null; export const setToast=s=>window.toasts.push(s);
export const escHtml=s=>String(s??''); export const fmt=s=>String(s??0);
export const fmtPct=fmt; export const colorPct=()=>'';
"""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        def serve(route):
            path = route.request.url.removeprefix("http://qurious.test")
            if path == "/": route.fulfill(body=html, content_type="text/html")
            elif path == "/js/common.js": route.fulfill(body=common, content_type="text/javascript")
            elif path == "/js/settings.js":
                route.fulfill(body=(ROOT / "public/js/settings.js").read_text(), content_type="text/javascript")
            else: route.abort()
        page.route("**/*", serve)
        page.goto("http://qurious.test")
        page.evaluate("""() => {window.calls=[]; window.toasts=[]; window.cfg={mode:'paper',broker:'mock',
          execution_capabilities:{retry_note:'현재 연결에서는 실행하지 않습니다.',stop_note:'상주 감시 미연결'}};}""")
        page.evaluate("async () => {window.s=await import('/js/settings.js'); await s.loadSettings();}")
        assert page.locator("#quant-size-kind").input_value() == "fixed_budget"
        assert not page.locator("#quant-retry-enabled").is_checked()
        assert "현재 연결에서는 실행하지 않습니다" in page.locator("#quant-execution-capabilities").text_content()
        page.evaluate("""() => {
          document.getElementById('quant-size-kind').value='risk_pct';
          document.getElementById('quant-risk-pct').value='0.5';
          document.getElementById('quant-retry-enabled').checked=true;
          document.getElementById('quant-retry-window').value='60';
          document.getElementById('broker-save').click();
        }""")
        page.wait_for_function("toasts.length > 0")
        body = page.evaluate("calls.find(c=>c.method==='POST').body.execution_policy")
        assert body["size_kind"] == "risk_pct" and body["risk_pct"] == .5
        assert body["retry_enabled"] and body["retry_window_min"] == 60
        page.evaluate("async () => {document.getElementById('quant-risk-pct').value='5'; await s.loadSettings();}")
        assert page.locator("#quant-risk-pct").input_value() == "0.5"
        assert page.locator("#quant-retry-enabled").is_checked()
        assert not errors, errors
        browser.close()
        print(json.dumps({"browser": "chromium", "flows": 3, "status": "passed"}))


if __name__ == "__main__":
    main()
