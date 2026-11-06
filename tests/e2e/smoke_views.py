"""브라우저 E2E 스모크: 로그인 후 app.html 의 모든 뷰를 열어 활성화 여부·JS 오류를 점검한다.

pytest 수집 대상이 아니며(파일명이 test_* 가 아님) 서버가 떠 있을 때 수동/CI 후속 단계에서 실행한다.
    pip install playwright && playwright install chromium
    BASE_URL=http://localhost:8966 E2E_EMAIL=... E2E_PASSWORD=... python tests/e2e/smoke_views.py
종료 코드 0 = 문제 없음, 1 = 비활성 뷰 또는 pageerror 존재.
"""
import asyncio, os, re, sys

from playwright.async_api import async_playwright

BASE = os.environ.get("BASE_URL", "http://localhost:8966")
EMAIL = os.environ.get("E2E_EMAIL", "rbtest@example.com")
PASSWORD = os.environ.get("E2E_PASSWORD", "Test1234!")
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


async def main() -> int:
    html = open(os.path.join(ROOT, "public", "app.html"), encoding="utf-8").read()
    views = re.findall(r'class="view" data-view="([a-z-]+)"', html)
    # 마이페이지로 옮겨진 화면(설정 · 알림 설정 · 외부 API)은 app.html 에 빈 껍데기 .view 만 남고 주소(#settings 등)는 마이페이지가 받는다
    # — 껍데기가 활성인지가 아니라 마이페이지가 활성인지를 본다(viewalias.js 의 MYPAGE_HOSTED 를 그대로 읽어 목록이 어긋나지 않게).
    alias_src = open(os.path.join(ROOT, "public", "js", "viewalias.js"), encoding="utf-8").read()
    hosted_block = re.search(r"MYPAGE_HOSTED\s*=\s*Object\.freeze\(\{(.*?)\}\)", alias_src, re.S)
    hosted = set(re.findall(r'"([a-z-]+)"\s*:', hosted_block.group(1))) if hosted_block else set()
    async with async_playwright() as p:
        br = await p.chromium.launch()
        pg = await br.new_page(viewport={"width": 1400, "height": 1000})
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(f"pageerror {e}"))
        await pg.goto(f"{BASE}/login.html")
        await pg.fill("input[name=email]", EMAIL); await pg.fill("input[name=password]", PASSWORD)
        await pg.click("button[type=submit]"); await pg.wait_for_timeout(2500)
        problems = []
        for v in views:
            n0 = len(errors)
            await pg.goto(f"{BASE}/app.html?v={v}#{v}"); await pg.wait_for_timeout(900)
            shown = "mypage" if v in hosted else v
            active = await pg.evaluate(f"document.querySelector('.view[data-view=\"{shown}\"]')?.classList.contains('active')")
            if not active or len(errors) > n0:
                problems.append((v, active, errors[n0:n0 + 2]))
        await br.close()
    print(f"views={len(views)} problems={len(problems)} pageerrors={len(errors)}")
    for pr in problems:
        print("  ", pr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
