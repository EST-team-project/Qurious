"""화면 사용법 창 점검 (2026-10-16 결정 안 A · TC-HT 의 손 몫) — pytest 밖 · 앱을 띄운 뒤 손으로 돌린다.

    python tests/e2e/howto_dialog.py                 # 점검 계정(로컬 관리자 · scripts/personal/check.ps1 과 같은 계정)
    python tests/e2e/howto_dialog.py --slow          # 데이터 관제 30초 새로 그림 뒤에도 단추가 남는지(33초 더)

폭 넷(390 · 768 · 1280 · 1920)에서 사용법 창의 약속을 본다 — 읽기만(서버에 쓰는 요청 없음):
  ① 윗줄이 화면의 첫 자식 · 하나뿐 · 상품 안내 탭을 바꿔도 남는다 · 두 단 화면(거시경제 지표)에서도 두 단 밖
  ② 「사용법」 → 맨 위 층 창(:modal) · 폭 = 화면마다 정한 크기(작게 560 · 보통 680 · 크게 840 · 화면 − 32 를 넘지 않음) ·
     760 아래는 화면 전체 · 문서 가로 넘침 0
  ③ Tab 열두 번 — 초점이 창 밖으로 나가지 않는다(브라우저가 가둠)
  ④ 용어 칩 → 창 안 용어 카드 · Esc → 사용법으로(창은 열림) · Esc → 닫힘 · 초점이 「사용법」 단추로
  ⑤ 덮개를 누르면 닫힘(760 위) · 「용어사전에서 더 찾기」 → 창을 닫고 용어사전 화면으로
실패가 하나라도 있으면 끝에 목록을 찍고 종료코드 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("BASE_URL", "http://localhost:8966")
EMAIL = os.environ.get("E2E_EMAIL", "smoke-check@example.com")
PASSWORD = os.environ.get("E2E_PASSWORD", "smoke-check-1234")
WIDTHS = [390, 768, 1280, 1920]
SIZE_PX = {"s": 560, "m": 680, "l": 840}       # js/howtoview.js SIZE_PX 와 같은 값
CASES = [("agent-products", "l"), ("robo-screening", "m"), ("fin-topic-funds", "s")]
#: 깨 보기 전용 — {"path": "/js/howto.js", "old": …, "new": …} 를 주면 이 브라우저가 받는 그 파일만 한 곳 바꿔 받는다(작업 트리 그대로)
BREAK = json.loads(os.environ.get("HOWTO_BREAK") or "null")

DIALOG_JS = r"""
() => {
  const d = document.getElementById('q-howto-dialog');
  if (!d) return null;
  const r = d.getBoundingClientRect();
  return { open: d.open, modal: d.matches(':modal'), cls: d.className, w: Math.round(r.width), h: Math.round(r.height),
           left: Math.round(r.left), top: Math.round(r.top), docW: document.documentElement.scrollWidth, vw: innerWidth, vh: innerHeight };
}
"""
FOCUS_JS = r"""
() => {
  const a = document.activeElement;
  if (!a || a === document.body || a === document.documentElement) return 'chrome';
  return a.closest('#q-howto-dialog') ? 'in' : `${a.tagName}.${a.className}`;
}
"""
ROW_JS = r"""
(view) => {
  const v = document.querySelector(`.view[data-view="${view}"]`);
  return { rows: v.querySelectorAll('.q-howto-top').length, first: v.firstElementChild?.className || '',
           inMain: !!v.querySelector('.q-main .q-howto-top') };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slow", action="store_true", help="데이터 관제를 33초 두고 단추가 남는지도 본다")
    ap.add_argument("--widths", default=",".join(map(str, WIDTHS)), help="볼 폭(쉼표) — 기본 390,768,1280,1920")
    args = ap.parse_args()
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("  ✔ " if ok else "  ✘ ") + what)
        if not ok:
            fails.append(what)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        res = ctx.request.post(f"{BASE}/api/auth/login", data={"email": EMAIL, "password": PASSWORD})
        if res.status != 200:
            print(f"로그인 실패 {res.status} — 앱이 켜져 있는지 · 계정(E2E_EMAIL)을 확인하세요")
            return 2
        if BREAK:
            def _break(route):
                resp = route.fetch()
                body = resp.text()
                if body.count(BREAK["old"]) != 1:
                    print(f"깨기 닻 {body.count(BREAK['old'])}곳 — {BREAK['path']}")
                route.fulfill(response=resp, body=body.replace(BREAK["old"], BREAK["new"], 1))
            ctx.route(f"**{BREAK['path']}", _break)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        def go(width: int, view: str) -> None:
            page.set_viewport_size({"width": width, "height": 800 if width > 760 else 844})
            page.goto("about:blank")
            page.goto(f"{BASE}/app.html#{view}")
            page.wait_for_selector(f'.view[data-view="{view}"] > .q-howto-top [data-howto-open="guide"]', timeout=15000)

        for width in [int(w) for w in args.widths.split(",") if w.strip()]:
            print(f"== {width}")
            for view, size in CASES:
                go(width, view)
                row = page.evaluate(ROW_JS, view)
                check(row["rows"] == 1 and row["first"] == "q-howto-top", f"{width} {view} 윗줄 하나 · 첫 자식")
                btn = page.locator(f'.view[data-view="{view}"] > .q-howto-top [data-howto-open="guide"]')
                btn.click()
                d = page.evaluate(DIALOG_JS)
                check(bool(d and d["open"] and d["modal"]), f"{width} {view} 창이 맨 위 층으로 열림")
                if not d:
                    continue
                check(f"q-howto-dialog--{size}" in d["cls"], f"{width} {view} 크기 {size} ({d['cls']})")
                if width <= 760:
                    check((d["left"], d["top"], d["w"], d["h"]) == (0, 0, d["vw"], d["vh"]), f"{width} {view} 화면 전체 {d}")
                else:
                    check(d["w"] == min(SIZE_PX[size], width - 32), f"{width} {view} 폭 {d['w']}")
                check(d["docW"] <= d["vw"], f"{width} {view} 가로 넘침 0 ({d['docW']} / {d['vw']})")
                # 브라우저 모달은 마지막 칸 다음 Tab 에 초점을 브라우저 쪽(주소창 · 머리 없는 브라우저에선 body)으로 넘겼다가
                # 다음 Tab 에 창 첫 칸으로 돌린다 — 지킬 것은 「뒤 화면의 요소로는 한 번도 가지 않는다」 · 「창 안에 머문다」
                where = []
                for _ in range(12):
                    page.keyboard.press("Tab")
                    where.append(page.evaluate(FOCUS_JS))
                behind = [w for w in where if w not in ("in", "chrome")]
                check(not behind and "in" in where, f"{width} {view} Tab 열두 번 — 뒤 화면으로 0 ({behind[:2]})")
                chip = page.locator("#q-howto-dialog .q-howto-term").first
                if chip.count():
                    chip.click()
                    page.wait_for_selector("#q-howto-dialog .q-howto-termview .q-term-title", timeout=10000)
                    page.keyboard.press("Escape")
                    st = page.evaluate("() => { const d = document.getElementById('q-howto-dialog'); return { open: d.open, guide: !d.querySelector('.q-howto-guide').hidden }; }")
                    check(st["open"] and st["guide"], f"{width} {view} Esc 하나 — 창 안 용어에서 사용법으로")
                page.keyboard.press("Escape")
                st = page.evaluate("() => ({ open: document.getElementById('q-howto-dialog').open, onBtn: !!document.activeElement?.matches('.q-howto-top [data-howto-open=\"guide\"]') })")
                check(not st["open"] and st["onBtn"], f"{width} {view} Esc 로 닫힘 · 초점이 「사용법」 단추로")

            go(width, "agent-products")
            page.wait_for_selector('.view[data-view="agent-products"] [data-tab]', timeout=20000)
            page.locator('.view[data-view="agent-products"] [data-tab]').nth(1).click()
            page.wait_for_timeout(600)
            row = page.evaluate(ROW_JS, "agent-products")
            check(row["rows"] == 1 and row["first"] == "q-howto-top", f"{width} 상품 안내 탭을 바꿔도 윗줄이 남음")
            if width > 760:
                page.locator('.view[data-view="agent-products"] > .q-howto-top [data-howto-open="guide"]').click()
                page.mouse.click(8, 790)
                check(not page.evaluate("() => document.getElementById('q-howto-dialog').open"), f"{width} 덮개를 누르면 닫힘")
            page.locator('.view[data-view="agent-products"] > .q-howto-top [data-howto-open="guide"]').click()
            page.locator('#q-howto-dialog a[href="#fin-glossary"]').click()
            page.wait_for_timeout(1200)
            st = page.evaluate("() => ({ open: document.getElementById('q-howto-dialog').open, view: document.querySelector('.view.active')?.dataset.view })")
            check(not st["open"] and st["view"] == "fin-glossary", f"{width} 「용어사전에서 더 찾기」 → 닫고 용어사전으로 {st}")

            go(width, "macro-dashboard")
            page.wait_for_timeout(1500)
            row = page.evaluate(ROW_JS, "macro-dashboard")
            check(row["rows"] == 1 and row["first"] == "q-howto-top" and not row["inMain"], f"{width} 두 단 화면에서 윗줄이 두 단 밖")

        if args.slow:
            print("== 데이터 관제 33초")
            go(1280, "data-status")
            page.wait_for_timeout(33000)
            row = page.evaluate(ROW_JS, "data-status")
            check(row["rows"] == 1 and row["first"] == "q-howto-top", "데이터 관제가 새로 그린 뒤에도 윗줄 하나")

        check(not errors, f"페이지 오류 0 ({errors[:3]})")
        browser.close()

    print(f"== 결과: {'모두 통과' if not fails else f'실패 {len(fails)}'}")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
