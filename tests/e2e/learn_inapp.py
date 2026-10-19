"""개념 학습 앱 안 화면 손 시험 (2026-10-19 · 사용자 「학습을 금융필수지식 + 개념학습으로 하기로 했는데 분리되어 있는 오류」)
— pytest 밖 · 앱을 띄운 뒤 · 읽기만(서버에 쓰는 요청 없음).

    python tests/e2e/learn_inapp.py                       # 이 PC 로컬 시연 계정(tools/demo/record_demo.py 기본값)
    E2E_EMAIL=... E2E_PASSWORD=... python tests/e2e/learn_inapp.py --shots .playwright-mcp/learn

보는 약속:
  ① 왼쪽 트리의 개념 학습 묶음에 「새 화면」 꼬리표 · 바깥 링크가 없다(항목 = 전체 목차 · 장 읽기)
  ② 전체 목차 · 장 읽기 모두 위 탭 「학습」 이 켜진다 · 목차에 부 카드와 장 줄이 그려진다
  ③ 장 읽기 — 차례 · 알림 상자 · 그림(오류 0) · 차례를 눌러도 주소는 #learn-page 그대로
  ④ 다음 장 → 뒤로 가기는 앞 장 → 한 번 더 뒤로는 전체 목차
  ⑤ 주소 #learn/<장> 으로 바로 열기 → 그 장 · 주소는 #learn-page
  ⑥ 390 폭 — 장 · 목차 모두 본문 칸 가로 넘침 0
  ⑦ 콘솔 오류 0
실패가 하나라도 있으면 끝에 목록을 찍고 종료코드 1. 비밀번호는 찍지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "demo"))
import record_demo as rd  # noqa: E402 — 로그인 함수 · 로컬 시연 계정 기본값
from playwright.async_api import async_playwright  # noqa: E402

TITLE = "#cl-page .fl-topic-head h2"
MAIN_OVERFLOW = "(() => { const e = document.getElementById('main-content'); return e.scrollWidth - e.clientWidth; })()"


async def run(base: str, email: str, password: str, shots: Path | None) -> list[str]:
  fails: list[str] = []
  errors: list[str] = []

  def check(ok: bool, what: str) -> None:
    print(("통과 " if ok else "실패 ") + what)
    if not ok:
      fails.append(what)

  async with async_playwright() as p:
    b = await p.chromium.launch()
    ctx = await b.new_context(viewport={"width": 1600, "height": 1000}, locale="ko-KR")
    await rd.login(ctx, base, email, password, False)
    page = await ctx.new_page()
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    await page.goto(f"{base}/app.html#fin-lectures")
    await page.wait_for_selector("#finlearn-hub .fl-card", timeout=30000)
    grp = page.locator('details[data-lnb-group="learn"]')
    check(await grp.locator(".lnb-tag").count() == 0 and await grp.locator("a[data-menu-href]").count() == 0, "① 트리 개념 학습 — 「새 화면」 꼬리표 · 바깥 링크 없음")
    await grp.locator("summary").click()
    items = [t.strip() for t in await grp.locator(".lnb-item").all_inner_texts()]
    check(items == ["전체 목차", "장 읽기"], f"① 트리 항목 {items}")
    check(await page.locator("#finlearn-hub a[href='#learn-home']").count() == 1, "② 강의실 맨 아래 개념 학습 입구")

    await grp.locator('button[data-view="learn-home"]').click()
    await page.wait_for_selector("#cl-home .cl-part", timeout=30000)
    check((await page.locator("[data-gnb].active").all_inner_texts()) == ["학습"], "② 목차에서 위 탭 「학습」")
    check(await page.locator("#cl-home .cl-part").count() > 0 and await page.locator("#cl-home .cl-list li").count() > 0, "② 목차 부 카드 · 장 줄")
    if shots:
      await page.screenshot(path=str(shots / "01-home.png"))

    first = page.locator("#cl-home .cl-list li:has(.cl-st-ready) a").first
    await first.click()
    await page.wait_for_selector("#cl-page .cl-prose h2", timeout=30000)
    await page.wait_for_timeout(2500)   # 그림(Mermaid) · 색칠
    t1 = (await page.locator(TITLE).inner_text()).strip()
    check((await page.locator("[data-gnb].active").all_inner_texts()) == ["학습"], "② 장 읽기에서 위 탭 「학습」")
    check(await page.locator("#cl-page .fl-toc-list a").count() > 1, "③ 이 장의 차례")
    check(await page.locator("#cl-page .cl-mermaid-error").count() == 0, "③ 그림 오류 0")
    await page.locator("#cl-page .fl-toc-list a").nth(1).click()
    await page.wait_for_timeout(600)
    check(await page.evaluate("location.hash") == "#learn-page", "③ 차례를 눌러도 주소는 #learn-page")
    if shots:
      await page.screenshot(path=str(shots / "02-page.png"))

    await page.locator("#cl-page .cl-pager a").last.click()
    await page.wait_for_function("t => (document.querySelector('#cl-page .fl-topic-head h2')||{}).textContent?.trim() !== t", arg=t1, timeout=30000)
    await page.go_back()
    try:
      await page.wait_for_function("t => (document.querySelector('#cl-page .fl-topic-head h2')||{}).textContent?.trim() === t", arg=t1, timeout=15000)
      check(True, "④ 뒤로 가기 → 앞 장")
    except Exception:  # noqa: BLE001
      check(False, "④ 뒤로 가기 → 앞 장")
    await page.go_back()
    await page.wait_for_timeout(1200)
    check(await page.locator('.view[data-view="learn-home"].active').count() == 1, "④ 한 번 더 뒤로 → 전체 목차")

    p2 = await ctx.new_page()
    p2.on("console", lambda m: errors.append("바로 열기: " + m.text) if m.type == "error" else None)
    await p2.goto(f"{base}/app.html#learn/rag-basics")
    await p2.wait_for_selector("#cl-page .cl-prose h2", timeout=30000)
    check(await p2.evaluate("location.hash") == "#learn-page" and await p2.locator('.view[data-view="learn-page"].active').count() == 1, "⑤ #learn/<장> 바로 열기")

    m = await b.new_context(viewport={"width": 390, "height": 844}, locale="ko-KR")
    await rd.login(m, base, email, password, False)
    mp = await m.new_page()
    await mp.goto(f"{base}/app.html#learn/rag-basics")
    await mp.wait_for_selector("#cl-page .cl-prose h2", timeout=30000)
    await mp.wait_for_timeout(1500)
    check(await mp.evaluate(MAIN_OVERFLOW) == 0, "⑥ 390 장 읽기 가로 넘침 0")
    if shots:
      await mp.screenshot(path=str(shots / "03-m390-page.png"))
    await mp.goto(f"{base}/app.html#learn-home")
    await mp.wait_for_selector("#cl-home .cl-part", timeout=30000)
    check(await mp.evaluate(MAIN_OVERFLOW) == 0, "⑥ 390 목차 가로 넘침 0")
    await b.close()
  check(errors == [], f"⑦ 콘솔 오류 {len(errors)}" + (f" — {errors[:3]}" if errors else ""))
  return fails


def main() -> int:
  ap = argparse.ArgumentParser(description="개념 학습 앱 안 화면 손 시험")
  ap.add_argument("--base", default="http://127.0.0.1:8966")
  ap.add_argument("--shots", default="", help="그림을 남길 폴더(.playwright-mcp/… 권장)")
  a = ap.parse_args()
  shots = Path(a.shots) if a.shots else None
  if shots:
    shots.mkdir(parents=True, exist_ok=True)
  email = os.environ.get("E2E_EMAIL", rd.DEFAULT_EMAIL)
  password = os.environ.get("E2E_PASSWORD", rd.DEFAULT_PASSWORD)
  fails = asyncio.run(run(a.base, email, password, shots))
  if fails:
    print("\n실패 목록:\n  " + "\n  ".join(fails))
    return 1
  print("\n모두 통과")
  return 0


if __name__ == "__main__":
  sys.exit(main())
