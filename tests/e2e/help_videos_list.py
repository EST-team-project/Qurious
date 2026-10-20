"""사용법 영상 목록 점검 (D132 둘째 단계 · 2026-10-20 · TC-HV 의 손 몫) — pytest 밖 · 앱을 띄우고 영상 폴더를 채운 뒤 손으로 돌린다.

    python tools/demo/help_videos.py build      # 먼저 — 녹화한 PC(다른 PC 는 받기)
    python tests/e2e/help_videos_list.py        # 점검 계정(로컬 관리자 · scripts/personal/check.ps1 과 같은 계정)

읽기만 한다(서버에 쓰는 요청 없음). 폭 1280 · 390 에서:
  ① 메뉴 「개념 학습 › 사용법 영상」 줄이 보이고, 차례의 편 수 = 영상 표의 편 수(여정 · 기능 두 묶음)
  ② 처음 편은 여정 1편(이 브라우저에 ✓ 기록이 없을 때) · 지금 편에 aria-current · 장 단추 수 = 그 편의 장 수
  ③ 차례의 다른 편을 누르면 왼쪽이 그 편으로 · 「다음 →」 은 목록 차례의 다음 편
  ④ 장 단추 ② → 영상 시각이 그 장 시작으로
  ⑤ 「이 화면 열기 →」 → 그 화면으로 옮기고 사용법 창이 열린다 · 목록을 떠나면 영상이 멈춘다
  ⑥ 영상 표가 빈 표(영상을 받지 않은 PC — 서버가 200 { missing })면 메뉴 줄이 숨고 화면은 「없습니다」 한 줄
  ⑦ 화면 글에 편 번호 · 파일 이름 · 「장면」 · 「HF」 가 없다 · 가로 넘침 0 · 페이지 오류 0 · 콘솔 오류 0
그림은 .playwright-mcp/help-videos-<폭>.png. 실패가 하나라도 있으면 끝에 목록을 찍고 종료코드 1.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("BASE_URL", "http://localhost:8966")
EMAIL = os.environ.get("E2E_EMAIL", "smoke-check@example.com")
PASSWORD = os.environ.get("E2E_PASSWORD", "smoke-check-1234")
OUT = Path(__file__).resolve().parents[2] / ".playwright-mcp"
FORBIDDEN = re.compile(r"(?<![A-Za-z0-9])[VF]\d{2}(?![0-9])|\.webm|\.vtt|장면|HF")

STATE_JS = r"""
() => {
  const root = document.getElementById('hv-root');
  const v = root && root.querySelector('video');
  const cur = root ? root.querySelector('.hv-item[aria-current="true"]') : null;
  const chapCur = root ? [...root.querySelectorAll('[data-howto-chap]')].findIndex(b => b.getAttribute('aria-current') === 'true') : -1;
  const menu = document.querySelector('#lnb-nav button[data-view="learn-videos"]');
  return { items: root ? root.querySelectorAll('.hv-item').length : 0,
           groups: root ? root.querySelectorAll('.hv-group').length : 0,
           cur: cur ? cur.dataset.hvId : '', chaps: root ? root.querySelectorAll('[data-howto-chap]').length : 0, chapCur,
           t: v ? v.currentTime : -1, paused: v ? v.paused : null,
           next: root?.querySelector('[data-hv-next]')?.dataset.hvNext || '',
           open: root?.querySelector('[data-hv-open]')?.dataset.hvOpen || '',
           menuShown: !!(menu && getComputedStyle(menu).display !== 'none'),
           overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
           text: root ? root.innerText : '' };
}
"""


def main() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("  ✔ " if ok else "  ✘ ") + what)
        if not ok:
            fails.append(what)

    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        res = ctx.request.post(f"{BASE}/api/auth/login", data={"email": EMAIL, "password": PASSWORD})
        if res.status != 200:
            print(f"로그인 실패 {res.status} — 앱이 켜져 있는지 · 계정(E2E_EMAIL)을 확인하세요")
            return 2
        m = ctx.request.get(f"{BASE}/help/videos.json")
        man = m.json() if m.status == 200 else {}
        ids = sorted(k for k in (man.get("videos") or {}) if re.match(r"^[VF]\d{2}-", k))
        if not ids:
            print(f"영상 표에 편이 없습니다({m.status}) — 먼저 python tools/demo/help_videos.py build")
            return 2
        first = next((k for k in ids if k.startswith("V")), ids[0])
        page = ctx.new_page()
        errors: list[str] = []
        console: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("console", lambda msg: console.append(msg.text[:120]) if msg.type == "error" else None)

        def go(width: int) -> dict:
            page.set_viewport_size({"width": width, "height": 800 if width > 760 else 844})
            page.goto("about:blank")
            page.goto(f"{BASE}/app.html#learn-videos")
            page.evaluate("() => { try { localStorage.removeItem('q-help-videos-watched'); } catch (e) {} }")
            page.reload()
            page.wait_for_selector("#hv-root .hv-item", timeout=15000)
            return page.evaluate(STATE_JS)

        for width in (1280, 390):
            print(f"== {width}")
            st = go(width)
            check(st["menuShown"] or width < 760, f"메뉴 줄 「사용법 영상」 보임({st['menuShown']})")
            check(st["items"] == len(ids), f"차례 편 수 {st['items']} = 표 {len(ids)}")
            check(st["groups"] == len({k[0] for k in ids}), f"묶음 수 {st['groups']}")
            check(st["cur"] == first, f"처음 편 {st['cur']} = {first}")
            check(st["chaps"] == len(man["videos"][first]["chapters"]) and st["chapCur"] == 0, f"장 단추 {st['chaps']} · 지금 장 {st['chapCur']}")
            check(st["overflow"] <= 0, f"가로 넘침 {st['overflow']}px")
            check(not FORBIDDEN.search(st["text"]), "화면 글에 편 번호 · 파일 이름 · 작업 낱말 없음")
            page.screenshot(path=str(OUT / f"help-videos-{width}.png"), full_page=True)
            # ③ 다른 편 · 다음
            other = ids[1] if len(ids) > 1 else ids[0]
            page.click(f'#hv-root .hv-item[data-hv-id="{other}"]')
            st = page.evaluate(STATE_JS)
            check(st["cur"] == other, f"차례에서 고른 편 {st['cur']} = {other}")
            if st["next"]:
                nxt = st["next"]
                page.click("#hv-root [data-hv-next]")
                st = page.evaluate(STATE_JS)
                check(st["cur"] == nxt, f"「다음 →」 {st['cur']} = {nxt}")
            # ④ 장 단추 ②
            if st["chaps"] >= 2:
                cur_vid = man["videos"][st["cur"]]
                page.click('#hv-root [data-howto-chap="1"]')
                page.wait_for_timeout(700)
                st2 = page.evaluate(STATE_JS)
                start = cur_vid["chapters"][1]["start"]
                check(abs(st2["t"] - start) < 1.5, f"장 ② 시각 {st2['t']:.1f} ≈ {start:.1f}")
            # ⑤ 이 화면 열기 → 사용법 창 · 목록을 떠나면 멈춤
            st = page.evaluate(STATE_JS)
            if st["open"]:
                target = st["open"]
                page.click("#hv-root [data-hv-open]")
                page.wait_for_timeout(600)
                here = page.evaluate("() => location.hash")
                dlg = page.evaluate("() => !!document.getElementById('q-howto-dialog')?.open")
                check(here == f"#{target}" and dlg, f"「이 화면 열기」 → {here} · 사용법 창 {dlg}")
                paused = page.evaluate("() => { const v = document.querySelector('#hv-root video'); return v ? v.paused : true; }")
                check(paused, "목록을 떠나면 영상 멈춤")
                page.keyboard.press("Escape")

        # ⑥ 빈 표 — 메뉴 줄 숨김 · 「없습니다」
        print("== 빈 표")
        page.route("**/help/videos.json", lambda route: route.fulfill(status=200, content_type="application/json", body='{"format": 1, "missing": true}'))
        page.set_viewport_size({"width": 1280, "height": 800})
        page.goto("about:blank")
        page.goto(f"{BASE}/app.html#learn-videos")
        page.wait_for_timeout(2500)
        st = page.evaluate(STATE_JS)
        check(not st["menuShown"], f"빈 표면 메뉴 줄 숨김({st['menuShown']})")
        check("없습니다" in st["text"] and st["items"] == 0, f"빈 표면 「없습니다」 한 줄 · 차례 {st['items']}")
        page.unroute("**/help/videos.json")

        check(not errors, f"페이지 오류 {errors[:3]}")
        check(not console, f"콘솔 오류 {console[:3]}")
        browser.close()

    print(f"\n끝 — 실패 {len(fails)}")
    for f in fails:
        print("  ✘ " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
