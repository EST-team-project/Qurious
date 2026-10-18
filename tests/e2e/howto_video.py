"""사용법 영상 칸 점검 (D132 첫 단계 · 2026-10-18 · TC-HT 의 손 몫) — pytest 밖 · 앱을 띄우고 영상 폴더를 채운 뒤 손으로 돌린다.

    python tools/demo/help_videos.py build      # 먼저 — 녹화한 PC(다른 PC 는 pull)
    python tests/e2e/howto_video.py             # 점검 계정(로컬 관리자 · scripts/personal/check.ps1 과 같은 계정)

읽기만 한다(서버에 쓰는 요청 없음). 영상 표(/help/videos.json)에서 화면 둘을 고른다 — 그 화면에서 시작하는 영상 하나 ·
여러 화면에 걸쳐 중간 장부터 트는 영상 하나(차트 패턴 = 신호로 종목 살피기 장 2).
  ① 윗줄 「▶ 영상 m:ss」 · 창 안 「영상으로 보기」 칸 · 창 크기 「크게」
  ② 「▶ 영상」 → 창이 열리며 바로 재생 · 그 화면이 나오는 장부터 · 장 표시 「② / 3」 · 지금 장 단추에 aria-current
  ③ 장 단추 ① → 처음으로 · 지금 장 표시가 ① 로 · Tab 으로 장 단추에 닿는다
  ④ 영상 Range 요청은 206 · 로그인 없는 요청은 401
  ⑤ 창을 닫으면 영상이 멈춘다 · 좁은 화면(390)은 장 단추가 한 줄에 하나
  ⑥ 영상 표가 빈 표(영상을 받지 않은 PC — 서버가 200 으로 줌)거나 못 받으면(404) 「▶ 영상」 · 영상 칸이 없다 ·
     영상이 없는 화면도 없다(결정 ⑥)
  ⑦ 창 안 글에 편 번호 · 파일 이름 · 「장면」 · 「HF」 가 없다 · 페이지 오류 0 · 콘솔 오류 0(404 를 일부러 낸 칸 밖)
실패가 하나라도 있으면 끝에 목록을 찍고 종료코드 1.
"""
from __future__ import annotations

import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("BASE_URL", "http://localhost:8966")
EMAIL = os.environ.get("E2E_EMAIL", "smoke-check@example.com")
PASSWORD = os.environ.get("E2E_PASSWORD", "smoke-check-1234")
WIDTHS = [1280, 390]
#: 영상이 없는 화면 후보 — 영상 표에 줄이 없는 첫 화면을 쓴다(녹화가 늘면 바뀐다 · 10-18 밤 F03 이 「펀드와 ETF」 에 붙었다)
NO_VIDEO_CANDIDATES = ("settings", "fin-topic-futures", "fin-topic-bonds", "mypage")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"
#: 화면 글에 나오면 안 되는 것 — 편 번호 · 파일 이름 · 작업 낱말
FORBIDDEN = re.compile(r"(?<![A-Za-z0-9])[VF]\d{2}(?![0-9])|\.webm|\.vtt|장면|HF")
#: 깨 보기 전용 — {"path": "/js/howto.js", "old": …, "new": …} 를 주면 이 브라우저가 받는 그 파일만 한 곳 바꿔 받는다(작업 트리 그대로)
BREAK = json.loads(os.environ.get("HOWTO_BREAK") or "null")

STATE_JS = r"""
() => {
  const d = document.getElementById('q-howto-dialog');
  const v = d && d.querySelector('video');
  const cur = d ? [...d.querySelectorAll('[data-howto-chap]')].findIndex(b => b.getAttribute('aria-current') === 'true') : -1;
  const chaps = d ? d.querySelector('.q-howto-chaps') : null;
  return { open: !!(d && d.open), cls: d ? d.className : '', hasVideo: !!v, t: v ? v.currentTime : -1, paused: v ? v.paused : null,
           ready: v ? v.readyState : -1, err: v && v.error ? v.error.code : 0, badge: d?.querySelector('.q-howto-chapbadge')?.textContent || '',
           cur, n: d ? d.querySelectorAll('[data-howto-chap]').length : 0,
           dir: chaps ? getComputedStyle(chaps).flexDirection : '', text: d ? d.innerText : '' };
}
"""


def main() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("  ✔ " if ok else "  ✘ ") + what)
        if not ok:
            fails.append(what)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        anon = browser.new_context()
        r = anon.request.get(f"{BASE}/help/videos.json")
        check(r.status == 401, f"로그인 없는 영상 표 요청은 401 ({r.status})")
        anon.close()

        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        res = ctx.request.post(f"{BASE}/api/auth/login", data={"email": EMAIL, "password": PASSWORD})
        if res.status != 200:
            print(f"로그인 실패 {res.status} — 앱이 켜져 있는지 · 계정(E2E_EMAIL)을 확인하세요")
            return 2
        m = ctx.request.get(f"{BASE}/help/videos.json")
        if m.status != 200:
            print(f"영상 표가 없습니다({m.status}) — 먼저 python tools/demo/help_videos.py build(녹화한 PC) 또는 pull")
            return 2
        man = m.json()
        views = man.get("views", {})
        start_view = next((k for k, v in views.items() if v["chapter"] == 0), None)
        mid_view = next((k for k, v in views.items() if v["chapter"] > 0), None)
        no_video = next((k for k in NO_VIDEO_CANDIDATES if k not in views), None)
        check(bool(start_view and mid_view and no_video), f"영상 표에서 고른 화면 — 처음부터 {start_view} · 중간 장부터 {mid_view} · 영상 없음 {no_video}")
        if not (start_view and mid_view and no_video):
            return 1

        # ④ Range — 장 단추 · 건너뛰기가 되려면 영상 요청에 206
        any_video = man["videos"][views[mid_view]["video"]]
        rr = ctx.request.get(f"{BASE}{any_video['src']}", headers={"Range": "bytes=0-99"})
        check(rr.status == 206 and len(rr.body()) == 100, f"영상 Range 요청 206 · 100바이트 ({rr.status})")

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
        console: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("console", lambda msg: console.append(msg.text[:120]) if msg.type == "error" else None)

        def go(width: int, view: str) -> None:
            page.set_viewport_size({"width": width, "height": 800 if width > 760 else 844})
            page.goto("about:blank")
            page.goto(f"{BASE}/app.html#{view}")
            page.wait_for_selector(f'.view[data-view="{view}"] > .q-howto-top [data-howto-open="guide"]', timeout=15000)

        for width in WIDTHS:
            print(f"== {width}")
            for view in (start_view, mid_view):
                ref = views[view]
                vid = man["videos"][ref["video"]]
                chs = vid["chapters"]
                k, n = ref["chapter"], len(chs)
                go(width, view)
                vbtn = page.locator(f'.view[data-view="{view}"] > .q-howto-top [data-howto-open="video"]')
                try:
                    vbtn.wait_for(timeout=8000)                    # 영상 표는 첫 화면을 그린 뒤에 온다
                except Exception:
                    pass
                check(vbtn.count() == 1, f"{width} {view} 윗줄 「▶ 영상」")
                if not vbtn.count():
                    continue
                check(re.search(r"영상 \d+:\d{2}", vbtn.inner_text() or "") is not None, f"{width} {view} 단추에 길이 ({vbtn.inner_text()!r})")
                vbtn.click()
                page.wait_for_selector("#q-howto-dialog video", timeout=10000)
                page.wait_for_function("() => { const v = document.querySelector('#q-howto-dialog video'); return v && v.readyState >= 2 && v.currentTime > 0; }", timeout=20000)
                st = page.evaluate(STATE_JS)
                check(st["open"] and "q-howto-dialog--l" in st["cls"], f"{width} {view} 창이 「크게」 로 열림 ({st['cls']})")
                check(not st["paused"] and st["err"] == 0, f"{width} {view} 바로 재생 (멈춤 {st['paused']} · 오류 {st['err']})")
                want = chs[k]["start"]
                check(want - 0.6 <= st["t"] <= want + 8, f"{width} {view} 장 {k + 1} 의 시각({want:.1f}초)부터 ({st['t']:.1f}초)")
                check(st["n"] == n and st["cur"] == k, f"{width} {view} 장 단추 {n} · 지금 장 {k + 1} (단추 {st['n']} · 지금 {st['cur'] + 1})")
                check(st["badge"] == f"{CIRCLED[k]} / {n}", f"{width} {view} 장 표시 {CIRCLED[k]} / {n} ({st['badge']!r})")
                bad = FORBIDDEN.findall(st["text"])
                check(not bad, f"{width} {view} 창 안 글에 편 번호 · 파일 이름 · 작업 낱말 0 ({bad[:3]})")
                if width <= 760:
                    check(st["dir"] == "column", f"{width} {view} 좁은 화면은 장 단추가 한 줄에 하나 ({st['dir']})")
                if k > 0:
                    page.locator('#q-howto-dialog [data-howto-chap="0"]').click()
                    page.wait_for_function("() => { const v = document.querySelector('#q-howto-dialog video'); return v && v.currentTime < %f; }" % chs[1]["start"], timeout=8000)
                    page.wait_for_timeout(400)
                    st = page.evaluate(STATE_JS)
                    check(st["cur"] == 0 and st["badge"] == f"{CIRCLED[0]} / {n}", f"{width} {view} 장 ① 단추 → 처음 · 지금 장 ① ({st['cur'] + 1} · {st['badge']!r})")
                seen = []
                for _ in range(14):
                    page.keyboard.press("Tab")
                    seen.append(page.evaluate("() => document.activeElement?.matches('[data-howto-chap]') || false"))
                check(any(seen), f"{width} {view} Tab 으로 장 단추에 닿음")
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                st = page.evaluate(STATE_JS)
                check(not st["open"] and st["paused"] is True, f"{width} {view} 창을 닫으면 영상이 멈춤 (열림 {st['open']} · 멈춤 {st['paused']})")

            go(width, no_video)
            page.wait_for_timeout(1500)
            check(page.locator(f'.view[data-view="{no_video}"] [data-howto-open="video"]').count() == 0, f"{width} 영상 없는 화면엔 「▶ 영상」 없음")
            page.locator(f'.view[data-view="{no_video}"] > .q-howto-top [data-howto-open="guide"]').click()
            check(page.locator("#q-howto-dialog .q-howto-video").count() == 0, f"{width} 영상 없는 화면의 창엔 영상 칸 없음")
            check(page.locator("#q-howto-dialog .q-howto-note").count() == 1, f"{width} 창 바닥 고지 한 줄")
            page.keyboard.press("Escape")

        check(not console, f"콘솔 오류 0 ({console[:3]})")

        empty = '{"format": 1, "videos": {}, "views": {}, "missing": true}'
        for label, kw in (("빈 표(영상을 받지 않은 PC)", {"status": 200, "content_type": "application/json", "body": empty}),
                          ("못 받음(404)", {"status": 404, "body": ""})):
            print(f"== 영상 표 {label}")
            page.unroute("**/help/videos.json")
            page.route("**/help/videos.json", (lambda kw: (lambda route: route.fulfill(**kw)))(kw))   # 처리기는 route 하나만 받는다
            go(1280, start_view)
            page.wait_for_timeout(2500)
            check(page.locator(f'.view[data-view="{start_view}"] [data-howto-open="video"]').count() == 0, f"{label} — 「▶ 영상」 없음")
            page.locator(f'.view[data-view="{start_view}"] > .q-howto-top [data-howto-open="guide"]').click()
            check(page.locator("#q-howto-dialog .q-howto-video").count() == 0, f"{label} — 창에 영상 칸 없음")
            page.keyboard.press("Escape")

        check(not errors, f"페이지 오류 0 ({errors[:3]})")
        browser.close()

    print(f"== 결과: {'모두 통과' if not fails else f'실패 {len(fails)}'}")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
